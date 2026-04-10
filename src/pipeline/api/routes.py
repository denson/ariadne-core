"""REST API routes — mirrors MCP tool functionality.

All POST endpoints accept caller metadata (agent_id, agent_type, model,
initiated_by). GET /api/health requires no auth. All other endpoints
use optional auth in Phase 1 (require_auth=false by default).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from pipeline.api.auth import APIKey, check_api_key
import pipeline.mcp_server as _mcp

router = APIRouter()


# ── Request/Response models ──────────────────────────────────────────────────


class CallerMetadata(BaseModel):
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    model: Optional[str] = None
    initiated_by: Optional[str] = None
    agent_notes: Optional[str] = None
    agent_metadata: Optional[dict] = None


class DocumentRequest(CallerMetadata):
    uri: str
    store: bool = True
    collection: str = "default"
    tags: list[str] = Field(default_factory=list)
    force: bool = False
    chunking_config: Optional[dict] = None


class SearchRequest(CallerMetadata):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    collection: Optional[str] = None
    filters: Optional[dict] = None


class IngestRequest(CallerMetadata):
    path: str
    collection: str = "default"
    recursive: bool = True
    file_types: Optional[list[str]] = None
    force: bool = False
    tags: list[str] = Field(default_factory=list)


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None


class CollectionResponse(BaseModel):
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None


# ── In-memory collection store (Phase 1) ─────────────────────────────────────

_collections: dict[str, CollectionResponse] = {
    "default": CollectionResponse(name="default", description="Default collection"),
}


# ── Helper to resolve agent_id from API key ──────────────────────────────────


def _resolve_agent_id(
    metadata: CallerMetadata, api_key: APIKey | None
) -> str | None:
    """Use explicit agent_id if provided, else infer from API key name."""
    if metadata.agent_id:
        return metadata.agent_id
    if api_key:
        return f"api-key:{api_key.name}"
    return None


# ── Upload endpoint ─────────────────────────────────────────────────────────


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    api_key: APIKey | None = Depends(check_api_key),
):
    """Upload a file to the server for processing.

    Returns the server-side path, which can then be passed to
    convert_document or used with ingest.
    """
    import os
    from pathlib import Path as _Path

    upload_dir = _Path(os.environ.get("ARIADNE_UPLOAD_DIR", "./data/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = _Path(file.filename).name if file.filename else "upload"
    dest = upload_dir / safe_name

    # Avoid overwrites by appending a counter
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = upload_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    content = await file.read()
    dest.write_bytes(content)

    return {
        "path": str(dest),
        "filename": safe_name,
        "size_bytes": len(content),
    }


# ── Health check (no auth) ───────────────────────────────────────────────────


@router.get("/health")
async def health():
    """Health check — no authentication required."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "engine": "markitdown",
        "embedding_enabled": _mcp._embedding_client.enabled,
    }


# ── Document endpoints ───────────────────────────────────────────────────────


@router.post("/documents")
async def submit_document(
    req: DocumentRequest,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Submit a single document for extraction and processing."""
    from pipeline.mcp_server import _process_single_document

    agent_id = _resolve_agent_id(req, api_key)

    result = _process_single_document(
        uri=req.uri,
        store=req.store,
        collection=req.collection,
        tags=req.tags,
        force=req.force,
        agent_id=agent_id,
        agent_type=req.agent_type,
        model=req.model,
        initiated_by=req.initiated_by,
        agent_notes=req.agent_notes,
        agent_metadata=req.agent_metadata,
        chunking_config=req.chunking_config,
    )

    if result.get("error"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": result.get("message"),
                "document_id": result.get("document_id"),
                "source_file": result.get("source_file"),
            },
        )

    return result


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    include_chunks: bool = Query(True),
    include_interactions: bool = Query(True),
    api_key: APIKey | None = Depends(check_api_key),
):
    """Retrieve the full processed document by ID."""
    doc = _mcp._find_document_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    response: dict[str, Any] = {
        "document_id": doc.document_id,
        "source_file": doc.source_file,
        "title": doc.title,
        "file_type": doc.file_type,
        "engine": doc.engine,
        "processing_time_ms": doc.processing_time_ms,
        "output_tokens_estimate": doc.output_tokens_estimate,
        "token_savings_ratio": doc.token_savings_ratio,
        "content_fingerprint": doc.content_fingerprint,
        "collection": doc.collection_id,
        "tags": doc.tags,
        "processing_chain": doc.processing_chain,
        "content_markdown": doc.markdown,
    }

    if include_chunks:
        doc_chunks = _mcp._get_chunks_for_document(doc.document_id)
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
        interactions = _mcp._dedup_store.get_interactions(doc.document_id)
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

    return response


@router.get("/documents")
async def list_documents(
    collection: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    api_key: APIKey | None = Depends(check_api_key),
):
    """List all documents, optionally filtered by collection or file type."""
    from pipeline.dedup import PgDedupStore

    start = (page - 1) * per_page

    if isinstance(_mcp._dedup_store, PgDedupStore):
        page_docs, total = _mcp._dedup_store.list_documents(
            collection=collection, file_type=file_type,
            limit=per_page, offset=start,
        )
    else:
        docs = list(_mcp._dedup_store._documents.values())
        if collection:
            docs = [d for d in docs if d.collection_id == collection]
        if file_type:
            ft = file_type.lstrip(".")
            docs = [d for d in docs if d.file_type == ft]
        total = len(docs)
        page_docs = docs[start:start + per_page]

    return {
        "documents": [
            {
                "document_id": d.document_id,
                "source_file": d.source_file,
                "title": d.title,
                "file_type": d.file_type,
                "collection": d.collection_id,
                "content_fingerprint": d.content_fingerprint,
                "chunk_count": _mcp._count_chunks_for_document(d.document_id),
                "interaction_count": len(
                    _mcp._dedup_store.get_interactions(d.document_id)
                ),
                "created_at": d.created_at,
            }
            for d in page_docs
        ],
        "total_count": total,
        "page": page,
        "per_page": per_page,
    }


# ── Search endpoint ──────────────────────────────────────────────────────────


@router.post("/search")
async def search_documents(
    req: SearchRequest,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Semantic search over the document knowledge store."""
    if not _mcp._embedding_client.enabled:
        raise HTTPException(
            status_code=503,
            detail="Search is not available: no embedding API key configured.",
        )

    try:
        query_embedding = _mcp._embedding_client.embed_query(req.query)
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to embed query: {e}",
        )

    search_filters: dict[str, Any] = {}
    if req.collection:
        search_filters["collection"] = req.collection
    if req.filters:
        search_filters.update(req.filters)

    results = _mcp._vector_store.search(
        query_embedding=query_embedding,
        top_k=req.top_k,
        filters=search_filters if search_filters else None,
    )

    # Post-filter for source_file, file_type, tags when using in-memory store
    from pipeline.storage.base import InMemoryVectorStore
    if isinstance(_mcp._vector_store, InMemoryVectorStore) and search_filters:
        results = _mcp._post_filter_results(results, search_filters)

    response_results = []
    for r in results:
        interactions = _mcp._dedup_store.get_interactions(r.document_id)
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
    from pipeline.dedup import SearchLogEntry
    agent_id = _resolve_agent_id(req, api_key)
    _mcp._dedup_store.record_search(
        SearchLogEntry(
            query=req.query,
            collection=req.collection,
            filters=search_filters if search_filters else None,
            top_k=req.top_k,
            results_count=len(response_results),
            result_document_ids=[r["document_id"] for r in response_results],
            agent_id=agent_id,
            agent_type=req.agent_type,
            model=req.model,
            initiated_by=req.initiated_by,
            agent_notes=req.agent_notes,
            agent_metadata=req.agent_metadata,
        )
    )

    return {
        "query": req.query,
        "top_k": req.top_k,
        "collection": req.collection,
        "results_count": len(response_results),
        "results": response_results,
    }


# ── Ingest endpoint ──────────────────────────────────────────────────────────


@router.post("/ingest")
async def ingest_directory(
    req: IngestRequest,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Batch-ingest a directory of documents."""
    from pipeline.mcp_server import SUPPORTED_EXTENSIONS, _process_single_document
    from pathlib import Path as _Path
    import os as _os

    agent_id = _resolve_agent_id(req, api_key)
    dir_path = _Path(req.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {req.path}")

    allowed_exts = SUPPORTED_EXTENSIONS
    if req.file_types:
        allowed_exts = {ft.lstrip(".").lower() for ft in req.file_types} & SUPPORTED_EXTENSIONS

    files: list[_Path] = []
    if req.recursive:
        for root, _dirs, filenames in _os.walk(dir_path):
            for fn in filenames:
                fp = _Path(root) / fn
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
    files_processed = 0
    files_skipped = 0
    files_errored = 0
    results_list = []

    for fp in files:
        try:
            doc_result = _process_single_document(
                uri=str(fp),
                store=True,
                collection=req.collection,
                tags=req.tags,
                force=req.force,
                agent_id=agent_id,
                agent_type=req.agent_type,
                model=req.model,
                initiated_by=req.initiated_by,
                agent_notes=req.agent_notes,
                agent_metadata=req.agent_metadata,
                chunking_config=None,
            )

            if doc_result.get("error"):
                files_errored += 1
                results_list.append({
                    "source_file": fp.name,
                    "document_id": doc_result.get("document_id"),
                    "was_dedup_skip": False,
                    "error": doc_result.get("message"),
                })
            elif doc_result.get("was_dedup_skip"):
                files_skipped += 1
                results_list.append({
                    "source_file": fp.name,
                    "document_id": doc_result["document_id"],
                    "was_dedup_skip": True,
                    "error": None,
                })
            else:
                files_processed += 1
                results_list.append({
                    "source_file": fp.name,
                    "document_id": doc_result["document_id"],
                    "was_dedup_skip": False,
                    "error": None,
                })
        except Exception as e:
            files_errored += 1
            results_list.append({
                "source_file": fp.name,
                "document_id": None,
                "was_dedup_skip": False,
                "error": str(e),
            })

    return {
        "files_found": files_found,
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "files_errored": files_errored,
        "results": results_list,
    }


# ── Collection endpoints ─────────────────────────────────────────────────────


@router.get("/collections")
async def list_collections(
    api_key: APIKey | None = Depends(check_api_key),
):
    """List all collections with document counts."""
    from pipeline.dedup import PgDedupStore

    # Count documents per collection
    collection_counts: dict[str, int] = {}
    if isinstance(_mcp._dedup_store, PgDedupStore):
        all_docs, _ = _mcp._dedup_store.list_documents(limit=100000)
        for d in all_docs:
            collection_counts[d.collection_id] = (
                collection_counts.get(d.collection_id, 0) + 1
            )
    else:
        for (coll, _fp), _doc in _mcp._dedup_store._documents.items():
            collection_counts[coll] = collection_counts.get(coll, 0) + 1

    # Merge registered collections with those that have documents
    all_names = set(collection_counts.keys()) | set(_collections.keys())
    result = []
    for name in sorted(all_names):
        desc = None
        if name in _collections:
            desc = _collections[name].description
        result.append({
            "name": name,
            "description": desc,
            "document_count": collection_counts.get(name, 0),
        })

    return {"collections": result}


@router.post("/collections", status_code=201)
async def create_collection(
    req: CollectionCreate,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Create a new collection."""
    if req.name in _collections:
        raise HTTPException(
            status_code=409,
            detail=f"Collection '{req.name}' already exists.",
        )

    _collections[req.name] = CollectionResponse(
        name=req.name,
        description=req.description,
        created_by=req.created_by,
    )
    return {"name": req.name, "description": req.description, "status": "created"}


# ── Stats endpoint ───────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    api_key: APIKey | None = Depends(check_api_key),
):
    """System statistics."""
    from pipeline.dedup import PgDedupStore

    if isinstance(_mcp._dedup_store, PgDedupStore):
        all_docs, total_docs = _mcp._dedup_store.list_documents(limit=10000)
    else:
        all_docs = list(_mcp._dedup_store._documents.values())
        total_docs = len(all_docs)

    # Per-collection counts
    collection_stats: dict[str, int] = {}
    for d in all_docs:
        collection_stats[d.collection_id] = collection_stats.get(d.collection_id, 0) + 1

    return {
        "total_documents": total_docs,
        "total_chunks": _mcp._vector_store.count(),
        "total_collections": len(_collections),
        "embedding_enabled": _mcp._embedding_client.enabled,
        "collections": collection_stats,
    }


