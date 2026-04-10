"""Ariadne Core MCP server — document extraction tools.

Served via Streamable HTTP by `ariadne-core serve`.
Import `app` for programmatic use.
"""

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from mcp.server import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from pipeline.chunking.chunker import Chunk, ChunkingConfig, chunk_document
from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    PgDedupStore,
    SearchLogEntry,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig
from pipeline.enrichment.images import ImageEnricher
from pipeline.enrichment.vision import VisionConfig
from pipeline.extraction.markitdown import MarkItDownExtractor
from pipeline.storage.base import InMemoryVectorStore
from pipeline.storage.pgvector import PgVectorStore

def _build_security_settings() -> TransportSecuritySettings:
    """Build transport security settings from environment."""
    allowed = os.environ.get("MCP_ALLOWED_HOSTS", "")
    hosts = [h.strip() for h in allowed.split(",") if h.strip()] if allowed else []
    # In production (Railway etc), DNS rebinding protection needs the hostname
    # to be allowed. If no hosts are configured, disable protection entirely
    # since the server is meant to be publicly accessible.
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


app = FastMCP(
    "ariadne-core",
    transport_security=_build_security_settings(),
    instructions="""\
Ariadne Core is a document extraction and retrieval pipeline. It converts \
documents (over 20 supported formats) into clean Markdown and stores them as \
searchable vector embeddings.

AVAILABLE TOOLS:

- convert_document — Extract a single document to Markdown. Chunks, embeds, and \
stores it by default. Use for any individual file.
- search — Semantic search over stored documents. Supports filters for collection, \
source_file, file_type, tags, and document_id.
- get_document — Retrieve the full Markdown content and chunks for a document by ID.
- list_documents — Browse stored documents by collection or file type.
- list_collections — See all collections with document counts. Call this before \
choosing a collection for ingestion or search scoping.
- ingest — Batch-ingest a directory of documents. Use for processing multiple files \
at once.

WHEN TO USE THESE TOOLS:

- When the user uploads or references a document, use convert_document to extract it. \
The extracted Markdown is clean, structured, and far more token-efficient than raw files.

- When the user says "process this folder" or "ingest everything", use ingest for \
batch directory operations.

- When the user asks a question that could be answered by their documents, use \
search first. Search returns the most relevant chunks with relevance scores.

- Call list_collections before choosing a collection for ingestion or search scoping.

HOW TO USE EFFECTIVELY:

- Always set store=true (the default) so documents are available for future search. \
Only set store=false for one-time extraction without persistence.

- Always pass agent_type (e.g., "claude-cowork", "claude-code", "ob1") and \
initiated_by (e.g., "user:denson") for provenance tracking. Every interaction is \
recorded — even on dedup skips.

- Use collections to organize documents by purpose. Call list_collections first to \
see what exists.

- Dedup is automatic. If a document was already processed, the system skips the \
expensive work and returns the existing record. Use force=true only if the user \
says the document content has changed.

- Search results include interaction history — which agents have previously \
touched each document.
""",
)

# Shared services
_extractor = MarkItDownExtractor(enable_plugins=True)
_dedup_store = InMemoryDedupStore()
_vector_store = InMemoryVectorStore()
_embedding_client = EmbeddingClient()  # Disabled by default (no API key)

# Image enrichment — enabled only when VISION_API_KEY is set
_vision_config = VisionConfig(
    api_key=os.environ.get("VISION_API_KEY", ""),
    model=os.environ.get("VISION_MODEL", "gpt-4o-mini"),
    base_url=os.environ.get("VISION_BASE_URL", "https://api.openai.com/v1"),
)
_image_enricher = ImageEnricher(_vision_config if _vision_config.api_key else None)


def configure_embedding(config: EmbeddingConfig) -> None:
    """Configure the embedding client. Call before using store/search."""
    global _embedding_client
    _embedding_client = EmbeddingClient(config)


def configure_stores(dedup_store, vector_store) -> None:
    """Replace the default in-memory stores with the given implementations."""
    global _dedup_store, _vector_store
    _dedup_store = dedup_store
    _vector_store = vector_store


@app.tool()
async def convert_document(
    uri: str,
    store: bool = True,
    collection: str = "default",
    tags: list[str] = [],
    force: bool = False,
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    model: Optional[str] = None,
    initiated_by: Optional[str] = None,
    agent_notes: Optional[str] = None,
    agent_metadata: Optional[dict] = None,
    chunking_config: Optional[dict] = None,
) -> str:
    """Convert a document to clean Markdown optimized for LLM consumption.

    Supports over 20 formats including PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, and more.

    Args:
        uri: file://, http://, https://, or local file path
        store: If true, also chunk, embed, and store in vector DB
        collection: Collection to store in (default: "default")
        tags: Tags to apply to the document
        force: If true, re-process even if fingerprint matches existing document
        agent_id: Caller's identity (e.g., "cowork-session-abc", "ob1-agent-daily")
        agent_type: Client type: "claude-cowork", "claude-code", "ob1", "api", etc.
        model: The LLM model the caller is running (e.g., "claude-sonnet-4-6")
        initiated_by: Human or system identity (e.g., "user:denson")
        agent_notes: Free-text description of context (e.g., "Eval run: testing PDF extraction")
        agent_metadata: Structured JSON metadata from the caller (e.g., eval run details)
        chunking_config: Optional override for chunking parameters (strategy, max_characters, etc.)

    Returns:
        JSON string with extracted Markdown content plus metadata.
    """
    response = _process_single_document(
        uri=uri,
        store=store,
        collection=collection,
        tags=tags,
        force=force,
        agent_id=agent_id,
        agent_type=agent_type,
        model=model,
        initiated_by=initiated_by,
        agent_notes=agent_notes,
        agent_metadata=agent_metadata,
        chunking_config=chunking_config,
        action="convert",
    )
    return json.dumps(response, indent=2)


@app.tool()
async def search(
    query: str,
    top_k: int = 5,
    collection: Optional[str] = None,
    filters: Optional[dict] = None,
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    model: Optional[str] = None,
    initiated_by: Optional[str] = None,
    agent_notes: Optional[str] = None,
    agent_metadata: Optional[dict] = None,
) -> str:
    """Semantic search over the document knowledge store.

    Args:
        query: Natural language query.
        top_k: Number of results (default 5, max 20).
        collection: Limit search to a collection (default: search all).
        filters: Optional filters (source_file, file_type, etc.).
        agent_id: Caller's identity.
        agent_type: Client type.
        model: The LLM model the caller is running.
        initiated_by: Human or system identity.
        agent_notes: Free-text description of context.
        agent_metadata: Structured JSON metadata from the caller.

    Returns:
        JSON with top-level keys: query, top_k, collection, results_count, results.

        Each result object contains:
        - chunk_id: Unique chunk identifier
        - document_id: Source document ID
        - collection: Collection the chunk belongs to
        - text: Chunk text content
        - section: Section heading (may be null)
        - page: Page number (may be null)
        - token_count: Token count of the chunk
        - relevance_score: Cosine similarity score (0-1, 4 decimal places)
        - embedding_model: Model used to generate the embedding
        - interactions: Array of all agent interactions with the source document,
          each containing agent_id, agent_type, model, initiated_by, agent_notes,
          agent_metadata, action, was_dedup_skip, created_at
    """
    top_k = min(top_k, 20)

    if not _embedding_client.enabled:
        return json.dumps(
            {
                "error": True,
                "message": "Search is not available: no embedding API key configured.",
            },
            indent=2,
        )

    # Embed the query
    try:
        query_embedding = _embedding_client.embed_query(query)
    except RuntimeError as e:
        return json.dumps(
            {"error": True, "message": f"Failed to embed query: {e}"},
            indent=2,
        )

    # Build search filters
    search_filters: dict[str, Any] = {}
    if collection:
        search_filters["collection"] = collection
    if filters:
        search_filters.update(filters)

    results = _vector_store.search(
        query_embedding=query_embedding,
        top_k=top_k,
        filters=search_filters if search_filters else None,
    )

    # Post-filter for source_file, file_type, tags when using in-memory store
    if isinstance(_vector_store, InMemoryVectorStore) and search_filters:
        results = _post_filter_results(results, search_filters)

    # Build response with document interactions
    response_results = []
    for r in results:
        # Get interactions for this document
        interactions = _dedup_store.get_interactions(r.document_id)

        response_results.append(
            {
                "chunk_id": r.chunk.chunk_id,
                "document_id": r.document_id,
                "collection": r.collection_id,
                "text": r.chunk.text,
                "section": r.chunk.section,
                "page": r.chunk.page_start,
                "token_count": r.chunk.token_count,
                "relevance_score": round(r.score, 4),
                "embedding_model": r.chunk.embedding_model,
                "interactions": [
                    {
                        "agent_id": i.agent_id,
                        "agent_type": i.agent_type,
                        "model": i.model,
                        "initiated_by": i.initiated_by,
                        "agent_notes": i.agent_notes,
                        "agent_metadata": i.agent_metadata,
                        "action": i.action,
                        "was_dedup_skip": i.was_dedup_skip,
                        "created_at": i.created_at,
                    }
                    for i in interactions
                ],
            }
        )

    # Record search in search_log (non-blocking — failures are logged, not raised)
    _dedup_store.record_search(
        SearchLogEntry(
            query=query,
            collection=collection,
            filters=search_filters if search_filters else None,
            top_k=top_k,
            results_count=len(response_results),
            result_document_ids=[r["document_id"] for r in response_results],
            agent_id=agent_id,
            agent_type=agent_type,
            model=model,
            initiated_by=initiated_by,
            agent_notes=agent_notes,
            agent_metadata=agent_metadata,
        )
    )

    return json.dumps(
        {
            "query": query,
            "top_k": top_k,
            "collection": collection,
            "results_count": len(response_results),
            "results": response_results,
        },
        indent=2,
    )


@app.tool()
async def get_document(
    document_id: str,
    include_chunks: bool = True,
    include_interactions: bool = True,
) -> str:
    """Retrieve the full stored document by ID.

    Use this after a search to get the complete Markdown content, all chunks,
    and the full interaction history for a document.

    Args:
        document_id: The document UUID (from search results or list_documents).
        include_chunks: If true, return all chunks with text, section, page info.
        include_interactions: If true, return all interaction records (who touched it).

    Returns:
        JSON string with the full document content and metadata.
    """
    # Find document — use get_document_by_id for Pg, fallback to scan for in-memory
    doc = _find_document_by_id(document_id)

    if doc is None:
        return json.dumps(
            {"error": True, "message": f"Document not found: {document_id}"},
            indent=2,
        )

    response: dict[str, Any] = {
        "document_id": doc.document_id,
        "collection": doc.collection_id,
        "source_file": doc.source_file,
        "title": doc.title,
        "file_type": doc.file_type,
        "engine": doc.engine,
        "content_fingerprint": doc.content_fingerprint,
        "processing_time_ms": doc.processing_time_ms,
        "output_tokens_estimate": doc.output_tokens_estimate,
        "token_savings_ratio": doc.token_savings_ratio,
        "processing_chain": doc.processing_chain,
        "tags": doc.tags,
        "warnings": list(doc.warnings),
        "content_markdown": doc.markdown,
        "created_at": doc.created_at,
    }

    if include_chunks:
        doc_chunks = _get_chunks_for_document(document_id)
        response["chunks"] = [
            {
                "chunk_id": c.chunk_id,
                "text": c.text,
                "section": c.section,
                "page": c.page_start,
                "token_count": c.token_count,
                "embedding_model": c.embedding_model,
            }
            for c in doc_chunks
        ]
        response["chunk_count"] = len(doc_chunks)

    if include_interactions:
        interactions = _dedup_store.get_interactions(doc.document_id)
        response["interactions"] = [
            {
                "agent_id": i.agent_id,
                "agent_type": i.agent_type,
                "model": i.model,
                "initiated_by": i.initiated_by,
                "agent_notes": i.agent_notes,
                "agent_metadata": i.agent_metadata,
                "action": i.action,
                "was_dedup_skip": i.was_dedup_skip,
                "created_at": i.created_at,
            }
            for i in interactions
        ]

    return json.dumps(response, indent=2)


@app.tool()
async def list_documents(
    collection: Optional[str] = None,
    file_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List documents in the knowledge store.

    Browse stored documents by collection or file type. Returns metadata only —
    call get_document with a document_id to retrieve the full content.

    Args:
        collection: Filter to a specific collection. If null, returns documents from all collections.
        file_type: Filter by file extension (e.g., ".pdf", ".docx").
        limit: Number of documents to return (default 20, max 100).
        offset: Pagination offset (default 0).

    Returns:
        JSON string with document list and total count.
    """
    limit = min(limit, 100)

    # Use Pg-backed list if available, otherwise fall back to in-memory scan
    if isinstance(_dedup_store, PgDedupStore):
        page_docs, total = _dedup_store.list_documents(
            collection=collection, file_type=file_type,
            limit=limit, offset=offset,
        )
    else:
        docs = list(_dedup_store._documents.values())
        if collection:
            docs = [d for d in docs if d.collection_id == collection]
        if file_type:
            ft = file_type.lstrip(".")
            docs = [d for d in docs if d.file_type == ft]
        total = len(docs)
        page_docs = docs[offset:offset + limit]

    return json.dumps(
        {
            "total_count": total,
            "limit": limit,
            "offset": offset,
            "documents": [
                {
                    "document_id": d.document_id,
                    "collection": d.collection_id,
                    "source_file": d.source_file,
                    "file_type": d.file_type,
                    "title": d.title,
                    "content_fingerprint": d.content_fingerprint,
                    "chunk_count": _count_chunks_for_document(d.document_id),
                    "interaction_count": len(
                        _dedup_store.get_interactions(d.document_id)
                    ),
                    "created_at": d.created_at,
                }
                for d in page_docs
            ],
        },
        indent=2,
    )


@app.tool()
async def list_collections() -> str:
    """List all collections with document counts."""
    # Count documents per collection from the dedup store
    collection_counts: dict[str, int] = {}

    if isinstance(_dedup_store, PgDedupStore):
        # Use SQL to count documents grouped by collection
        all_docs, _ = _dedup_store.list_documents(limit=100000)
        for d in all_docs:
            collection_counts[d.collection_id] = (
                collection_counts.get(d.collection_id, 0) + 1
            )
    else:
        for (coll, _fp), _doc in _dedup_store._documents.items():
            collection_counts[coll] = collection_counts.get(coll, 0) + 1

    # Import the routes-level collections store for descriptions
    from pipeline.api.routes import _collections

    collections_list = []
    # Include all collections that have documents or are registered
    all_names = set(collection_counts.keys()) | set(_collections.keys())
    for name in sorted(all_names):
        desc = None
        if name in _collections:
            desc = _collections[name].description
        collections_list.append({
            "name": name,
            "description": desc,
            "document_count": collection_counts.get(name, 0),
        })

    return json.dumps({"collections": collections_list}, indent=2)


@app.tool()
async def ingest(
    path: str,
    collection: str = "default",
    recursive: bool = True,
    file_types: Optional[list[str]] = None,
    force: bool = False,
    tags: list[str] = [],
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    model: Optional[str] = None,
    initiated_by: Optional[str] = None,
    agent_notes: Optional[str] = None,
    agent_metadata: Optional[dict] = None,
) -> str:
    """Batch-ingest a directory of documents. Processes all supported files and returns a summary.

    Args:
        path: Directory path to scan for documents.
        collection: Collection to store all documents in (default: "default").
        recursive: Recurse into subdirectories (default: true).
        file_types: Filter to specific extensions (e.g., ["pdf", "docx"]). If null, process all supported types.
        force: Re-process documents even if they already exist (dedup override).
        tags: Tags to apply to all documents.
        agent_id: Caller's identity.
        agent_type: Client type.
        model: The LLM model the caller is running.
        initiated_by: Human or system identity.
        agent_notes: Free-text description of context.
        agent_metadata: Structured JSON metadata from the caller.

    Returns:
        JSON string with ingestion summary and per-file results.
    """
    dir_path = Path(path)
    if not dir_path.is_dir():
        return json.dumps(
            {"error": True, "message": f"Not a directory: {path}"},
            indent=2,
        )

    # Determine which extensions to accept
    allowed_exts = SUPPORTED_EXTENSIONS
    if file_types:
        allowed_exts = {ft.lstrip(".").lower() for ft in file_types} & SUPPORTED_EXTENSIONS

    # Collect files
    files: list[Path] = []
    if recursive:
        for root, _dirs, filenames in os.walk(dir_path):
            for fn in filenames:
                fp = Path(root) / fn
                ext = fp.suffix.lower().lstrip(".")
                if ext in allowed_exts:
                    files.append(fp)
    else:
        for item in dir_path.iterdir():
            if item.is_file():
                ext = item.suffix.lower().lstrip(".")
                if ext in allowed_exts:
                    files.append(item)

    files_found = len(files)
    results_list: list[dict[str, Any]] = []

    def _process_file_safe(fp: Path) -> dict[str, Any]:
        """Process a single file, catching exceptions."""
        try:
            doc_result = _process_single_document(
                uri=str(fp),
                store=True,
                collection=collection,
                tags=tags,
                force=force,
                agent_id=agent_id,
                agent_type=agent_type,
                model=model,
                initiated_by=initiated_by,
                agent_notes=agent_notes,
                agent_metadata=agent_metadata,
                chunking_config=None,
            )

            if doc_result.get("error"):
                return {
                    "source_file": fp.name,
                    "document_id": doc_result.get("document_id"),
                    "was_dedup_skip": False,
                    "error": doc_result.get("message"),
                }
            elif doc_result.get("was_dedup_skip"):
                return {
                    "source_file": fp.name,
                    "document_id": doc_result["document_id"],
                    "was_dedup_skip": True,
                    "error": None,
                }
            else:
                return {
                    "source_file": fp.name,
                    "document_id": doc_result["document_id"],
                    "was_dedup_skip": False,
                    "error": None,
                }
        except Exception as e:
            return {
                "source_file": fp.name,
                "document_id": None,
                "was_dedup_skip": False,
                "error": str(e),
            }

    # Process files concurrently (up to 4 at a time)
    semaphore = asyncio.Semaphore(4)
    loop = asyncio.get_event_loop()

    async def _run_one(fp: Path) -> dict[str, Any]:
        async with semaphore:
            return await loop.run_in_executor(None, _process_file_safe, fp)

    results_list = await asyncio.gather(*[_run_one(fp) for fp in files])

    files_processed = sum(1 for r in results_list if not r.get("error") and not r.get("was_dedup_skip"))
    files_skipped = sum(1 for r in results_list if r.get("was_dedup_skip"))
    files_errored = sum(1 for r in results_list if r.get("error"))

    return json.dumps(
        {
            "files_found": files_found,
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "files_errored": files_errored,
            "results": results_list,
        },
        indent=2,
    )


# Supported file extensions for ingestion
SUPPORTED_EXTENSIONS = {
    "pdf", "docx", "pptx", "xlsx", "xls", "csv", "tsv",
    "html", "htm", "txt", "md", "json", "xml", "rtf",
    "epub", "eml", "msg", "zip", "ipynb", "rst", "org",
    "wav", "mp3", "m4a", "jpg", "jpeg", "png", "gif",
}


def _process_single_document(
    uri: str,
    store: bool,
    collection: str,
    tags: list[str],
    force: bool,
    agent_id: Optional[str],
    agent_type: Optional[str],
    model: Optional[str],
    initiated_by: Optional[str],
    agent_notes: Optional[str],
    agent_metadata: Optional[dict],
    chunking_config: Optional[dict],
    action: str = "ingest",
) -> dict[str, Any]:
    """Shared pipeline logic for convert_document and ingest.

    Returns a response dict (not JSON string).
    """
    result = _extractor.extract(uri)

    if result.errors:
        return {
            "error": True,
            "message": f"Extraction failed: {'; '.join(result.errors)}",
            "document_id": result.document_id,
            "source_file": result.source_file,
        }

    fingerprint = compute_fingerprint(result.markdown)

    if not force:
        existing = _dedup_store.find_by_fingerprint(collection, fingerprint)
        if existing is not None:
            _dedup_store.record_interaction(
                DocumentInteraction(
                    document_id=existing.document_id,
                    collection_id=collection,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    model=model,
                    initiated_by=initiated_by,
                    agent_notes=agent_notes,
                    agent_metadata=agent_metadata,
                    action=action,
                    was_dedup_skip=True,
                )
            )
            interactions = _dedup_store.get_interactions(existing.document_id)
            chunks_count = _count_chunks_for_document(existing.document_id)
            # Get embedding_model from the first chunk, if any
            doc_chunks = _get_chunks_for_document(existing.document_id)
            embedding_model = doc_chunks[0].embedding_model if doc_chunks else None
            return {
                "document_id": existing.document_id,
                "source_file": existing.source_file,
                "title": existing.title,
                "file_type": existing.file_type,
                "engine": existing.engine,
                "processing_time_ms": existing.processing_time_ms,
                "output_tokens_estimate": existing.output_tokens_estimate,
                "token_savings_ratio": existing.token_savings_ratio,
                "content_fingerprint": existing.content_fingerprint,
                "collection": collection,
                "was_dedup_skip": True,
                "chunks_count": chunks_count,
                "store_status": "skipped",
                "embedding_model": embedding_model,
                "provenance": {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "model": model,
                    "initiated_by": initiated_by,
                    "processing_chain": existing.processing_chain,
                },
                "interactions": [
                    {
                        "agent_id": i.agent_id,
                        "agent_type": i.agent_type,
                        "model": i.model,
                        "initiated_by": i.initiated_by,
                        "agent_notes": i.agent_notes,
                        "agent_metadata": i.agent_metadata,
                        "action": i.action,
                        "was_dedup_skip": i.was_dedup_skip,
                        "created_at": i.created_at,
                    }
                    for i in interactions
                ],
                "warnings": existing.warnings,
                "markdown": existing.markdown,
            }

    processing_chain = list(result.processing_chain)
    markdown = result.markdown
    warnings = list(result.warnings)

    # Image enrichment (SPEC pipeline step 3) — after fingerprint, before chunking
    if _image_enricher.enabled:
        source_dir = str(Path(uri).parent) if not uri.startswith(("http://", "https://")) else None
        try:
            enrich_result = _image_enricher.enrich(markdown, source_dir=source_dir)
            markdown = enrich_result.markdown
            if enrich_result.processing_chain_entry:
                processing_chain.append(enrich_result.processing_chain_entry)
            warnings.extend(enrich_result.errors)
        except Exception as e:
            warnings.append(f"Image enrichment failed: {e}")
    else:
        # Count image references and warn if vision key is missing
        import re as _re
        image_count = len(_re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))
        if image_count > 0:
            warnings.append(
                f"Document contains {image_count} image(s) but no VISION_API_KEY "
                "is configured — image descriptions were not generated"
            )

    stored_doc = StoredDocument(
        document_id=result.document_id,
        collection_id=collection,
        source_file=result.source_file,
        content_fingerprint=fingerprint,
        file_type=result.file_type,
        engine=result.engine,
        markdown=markdown,
        title=result.title,
        processing_time_ms=result.processing_time_ms,
        output_tokens_estimate=result.output_tokens_estimate,
        token_savings_ratio=result.token_savings_ratio,
        processing_chain=processing_chain,
        tags=tags,
        warnings=warnings,
    )
    _dedup_store.store_document(stored_doc)
    doc_id = stored_doc.document_id

    response: dict[str, Any] = {
        "document_id": doc_id,
        "source_file": result.source_file,
        "title": result.title,
        "file_type": result.file_type,
        "engine": result.engine,
        "processing_time_ms": result.processing_time_ms,
        "output_tokens_estimate": result.output_tokens_estimate,
        "token_savings_ratio": result.token_savings_ratio,
        "content_fingerprint": fingerprint,
        "collection": collection,
        "was_dedup_skip": False,
        "provenance": {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "model": model,
            "initiated_by": initiated_by,
            "processing_chain": processing_chain,
        },
        "warnings": warnings,
        "markdown": markdown,
    }

    if store:
        chunk_cfg = None
        if chunking_config:
            chunk_cfg = ChunkingConfig(**chunking_config)

        chunks = chunk_document(
            markdown=markdown,
            document_id=doc_id,
            collection_id=collection,
            file_type=result.file_type,
            config=chunk_cfg,
        )

        response["chunks_count"] = len(chunks)

        if _embedding_client.enabled and chunks:
            try:
                texts = [c.text for c in chunks]
                embed_result = _embedding_client.embed_texts(texts)
                for chunk, embedding in zip(chunks, embed_result.embeddings):
                    chunk.embedding = embedding
                    chunk.embedding_model = _embedding_client.model
                processing_chain.append(embed_result.processing_chain_entry)
                response["embedding_model"] = _embedding_client.model
            except RuntimeError as e:
                response.setdefault("warnings", []).append(
                    f"Embedding failed: {e}"
                )

        if chunks:
            if force:
                _vector_store.delete_by_document(doc_id)
            _vector_store.insert(chunks)

        response["store_status"] = "stored"
        response["provenance"]["processing_chain"] = processing_chain
    else:
        response["store_status"] = "not_stored"
        response["chunks_count"] = 0

    # Record interaction AFTER all processing (SPEC pipeline step 7)
    _dedup_store.record_interaction(
        DocumentInteraction(
            document_id=doc_id,
            collection_id=collection,
            agent_id=agent_id,
            agent_type=agent_type,
            model=model,
            initiated_by=initiated_by,
            agent_notes=agent_notes,
            agent_metadata=agent_metadata,
            action=action,
            was_dedup_skip=False,
        )
    )

    return response


def _find_document_by_id(document_id: str) -> StoredDocument | None:
    """Find a document by ID across all collections."""
    if isinstance(_dedup_store, PgDedupStore):
        return _dedup_store.get_document_by_id(document_id)
    # In-memory fallback: scan all documents
    for (collection, fp), doc in _dedup_store._documents.items():
        if doc.document_id == document_id:
            return doc
    return None


def _get_chunks_for_document(document_id: str) -> list:
    """Get all chunks for a document, ordered by chunk index."""
    if isinstance(_vector_store, PgVectorStore):
        return _vector_store.get_document_chunks(document_id)
    # In-memory fallback
    doc_chunks = [
        c for c in _vector_store._chunks.values()
        if c.document_id == document_id
    ]
    doc_chunks.sort(key=lambda c: c.chunk_id)
    return doc_chunks


def _post_filter_results(
    results: list, filters: dict[str, Any]
) -> list:
    """Post-filter search results for source_file, file_type, tags.

    Used with InMemoryVectorStore which doesn't have access to document
    metadata during search. Looks up the source document from the dedup
    store to apply these filters.
    """
    if not any(k in filters for k in ("source_file", "file_type", "tags")):
        return results

    filtered = []
    for r in results:
        doc = _find_document_by_id(r.document_id)
        if doc is None:
            continue

        if "source_file" in filters:
            if filters["source_file"].lower() not in doc.source_file.lower():
                continue

        if "file_type" in filters:
            ft = filters["file_type"].lstrip(".")
            if doc.file_type != ft:
                continue

        if "tags" in filters:
            filter_tags = set(filters["tags"])
            doc_tags = set(doc.tags) if doc.tags else set()
            if not filter_tags & doc_tags:
                continue

        filtered.append(r)

    return filtered


def _count_chunks_for_document(document_id: str) -> int:
    """Count chunks for a specific document."""
    if isinstance(_vector_store, PgVectorStore):
        return _vector_store.count_by_document(document_id)
    # In-memory fallback
    return sum(
        1 for c in _vector_store._chunks.values()
        if c.document_id == document_id
    )


if __name__ == "__main__":
    app.run(transport="stdio")
