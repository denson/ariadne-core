"""Ariadne Core service layer — shared state and document processing logic.

This module contains all the business logic for document extraction, storage,
search, and lifecycle management. The REST API routes and any future interfaces
import from here.
"""

import asyncio
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

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

logger = logging.getLogger(__name__)

# Shared services
_extractor = MarkItDownExtractor(enable_plugins=True)
_dedup_store = InMemoryDedupStore()
_vector_store = InMemoryVectorStore()
_embedding_client = EmbeddingClient()  # Disabled by default (no API key)

# Image enrichment — disabled by default, configured at startup via configure_image_enrichment()
_image_enricher = ImageEnricher(None)


def configure_embedding(config: EmbeddingConfig) -> None:
    """Configure the embedding client. Call before using store/search."""
    global _embedding_client
    _embedding_client = EmbeddingClient(config)


def configure_image_enrichment(api_key: str, model: str, base_url: str) -> None:
    """Configure the image enrichment client. Call at startup from app.py."""
    global _image_enricher
    if api_key:
        _image_enricher = ImageEnricher(VisionConfig(
            api_key=api_key,
            model=model,
            base_url=base_url,
        ))
    else:
        _image_enricher = ImageEnricher(None)


def configure_stores(dedup_store, vector_store) -> None:
    """Replace the default in-memory stores with the given implementations."""
    global _dedup_store, _vector_store
    _dedup_store = dedup_store
    _vector_store = vector_store


# File extensions that should be treated as standalone images when
# MarkItDown produces no extractable text. These trigger a direct
# vision-model call in _process_single_document.
_STANDALONE_IMAGE_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "svg",
}


# Supported file extensions for ingestion
SUPPORTED_EXTENSIONS = {
    "pdf", "docx", "pptx", "xlsx", "xls", "csv", "tsv",
    "html", "htm", "txt", "md", "json", "xml", "rtf",
    "epub", "eml", "msg", "zip", "ipynb", "rst", "org",
    "wav", "mp3", "m4a", "jpg", "jpeg", "png", "gif",
}


def _read_source_bytes(uri: str) -> bytes:
    """Return raw bytes for a uri (file://, http(s)://, or local path).

    URL path: deliberately uses the same default urllib semantics as the
    extractor's ``_download_to_temp`` (stdlib ``urlretrieve`` at
    ``extraction/markitdown.py:267``). No ``Accept-Encoding`` header is
    sent; no decompression is performed. If a server unilaterally returns
    ``Content-Encoding: gzip`` (rare but legal), BOTH the fingerprint path
    and the extraction path receive identical compressed bytes — so
    fingerprint-vs-extraction can never diverge on the same fetch.
    """
    if uri.startswith("file://"):
        path = urlparse(uri).path
        return Path(path).read_bytes()
    if uri.startswith(("http://", "https://")):
        # Match urlretrieve default: no extra headers, follow redirects.
        with urlopen(uri) as resp:
            return resp.read()
    return Path(uri).read_bytes()


def _source_file_from_uri(uri: str) -> str:
    """Derive a display-name source_file from a URI without touching disk."""
    return Path(urlparse(uri).path).name if "://" in uri else Path(uri).name


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
    # Read source bytes for fingerprinting BEFORE extraction. URL sources are
    # fetched here using the same urlretrieve-equivalent semantics the
    # extractor uses on cache miss; this guarantees fingerprint-bytes ==
    # extraction-bytes within a single ingest. See dedup.py and
    # _read_source_bytes for the byte-stream invariant rationale.
    try:
        raw_bytes = _read_source_bytes(uri)
    except Exception as e:
        return {
            "error": True,
            "message": f"Source read failed: {e}",
            "document_id": None,
            "source_file": _source_file_from_uri(uri),
        }

    fingerprint = compute_fingerprint(raw_bytes)

    if not force:
        existing = _dedup_store.find_by_fingerprint(collection, fingerprint)
        if existing is not None:
            logger.info(
                "dedup-skip",
                extra={
                    "collection": collection,
                    "fingerprint_prefix": fingerprint[:8],
                    "source_file": _source_file_from_uri(uri),
                    "algorithm": "raw-bytes",
                },
            )
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
                "warnings_count": len(existing.warnings or []),
                "markdown": existing.markdown,
            }

    # Cache miss (or force=True): now do the expensive extraction.
    result = _extractor.extract(uri)

    if result.errors:
        return {
            "error": True,
            "message": f"Extraction failed: {'; '.join(result.errors)}",
            "document_id": result.document_id,
            "source_file": result.source_file,
        }

    if not result.markdown or not result.markdown.strip():
        ext = (result.file_type or "").lower().lstrip(".")
        is_image = ext in _STANDALONE_IMAGE_EXTENSIONS

        if is_image and _image_enricher.enabled:
            # Standalone image: MarkItDown produced no text, so call the
            # vision model directly on the image file. The resulting
            # description becomes the document's markdown content.
            local_path = uri
            if uri.startswith("file://"):
                local_path = uri[len("file://"):]
            vision_start = time.perf_counter()
            try:
                description = _image_enricher.describe_image(local_path)
            except Exception as e:
                return {
                    "error": True,
                    "message": (
                        f"Vision extraction failed for {result.source_file}: {e}"
                    ),
                    "document_id": result.document_id,
                    "source_file": result.source_file,
                }
            vision_ms = int((time.perf_counter() - vision_start) * 1000)
            result.markdown = f"# Image: {result.source_file}\n\n{description}"
            result.file_type = ext
            result.output_tokens_estimate = max(1, len(result.markdown) // 4)
            result.processing_chain.append({
                "step": "vision_extraction",
                "tool": "image_enricher",
                "ts": datetime.now(timezone.utc).isoformat(),
                "ms": vision_ms,
            })
        else:
            return {
                "error": True,
                "message": f"Extraction produced empty output for {result.source_file}. "
                           "Image files require vision API configuration. "
                           "Check ARIADNE_IMAGE_ENRICHMENT_API_KEY.",
                "document_id": result.document_id,
                "source_file": result.source_file,
            }

    # Fingerprint already computed before extraction — do NOT recompute from
    # result.markdown.
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
        image_count = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))
        if image_count > 0:
            warnings.append(
                f"Document contains {image_count} image(s) but no VISION_API_KEY "
                "is configured — image descriptions were not generated"
            )

    # Merge encoding/language tags from extraction into the document's tag list
    if hasattr(result, 'suggested_tags') and result.suggested_tags:
        tags = list(tags or []) + result.suggested_tags

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

    # BL-19 transactional ingest: chunk + embed BEFORE any Postgres write.
    # On embed failure we bail here — no documents row, no chunks, no
    # vectors, no interaction are written.
    chunks: list[Chunk] = []
    if store:
        chunk_cfg = None
        if chunking_config:
            chunk_cfg = ChunkingConfig(**chunking_config)

        chunks = chunk_document(
            markdown=markdown,
            document_id=result.document_id,
            collection_id=collection,
            file_type=result.file_type,
            config=chunk_cfg,
        )

        if _embedding_client.enabled and chunks:
            try:
                texts = [c.text for c in chunks]
                embed_result = _embedding_client.embed_texts(texts)
                for chunk, embedding in zip(chunks, embed_result.embeddings):
                    chunk.embedding = embedding
                    chunk.embedding_model = _embedding_client.model
                processing_chain.append(embed_result.processing_chain_entry)
            except RuntimeError as e:
                failure_warnings = warnings + [f"Embedding failed: {e}"]
                return {
                    "error": True,
                    "message": f"Embedding failed: {e}",
                    "document_id": None,
                    "source_file": result.source_file,
                    "collection": collection,
                    "store_status": "error",
                    "chunks_count": 0,
                    "warnings": failure_warnings,
                    "warnings_count": len(failure_warnings),
                }

    if store:
        # Probe-then-store: detect would-be resurrection BEFORE storing so the
        # resurrection warning can be appended to `warnings` alongside the
        # metadata-hygiene warnings below — all of which must land in the list
        # BEFORE store_document is called. PgDedupStore.store_document
        # snapshots `doc.warnings or []` into the SQL parameter dict and
        # commits before returning (dedup.py:294-300), so any append after
        # the call never reaches Postgres. The two probe calls answer the
        # probe-time question; the function's own internal SELECT-in-
        # transaction remains the race-correct signal for its bool return,
        # which we don't second-guess from here.
        existing_visible = _dedup_store.find_by_fingerprint(
            collection, fingerprint, include_deleted=False
        )
        existing_any = _dedup_store.find_by_fingerprint(
            collection, fingerprint, include_deleted=True
        )
        would_resurrect = (existing_visible is None) and (existing_any is not None)
        if would_resurrect:
            warnings.append(
                "This document was previously soft-deleted and has been "
                "resurrected by re-ingest. Its deletion_scheduled_at has "
                "been cleared."
            )

    # Warn when key metadata conventions aren't followed
    if collection == "default":
        warnings.append(
            "Document stored in 'default' collection. Consider using a named "
            "collection (project, topic, or task) for better searchability."
        )
    if not agent_notes:
        warnings.append(
            "No agent_notes provided. Future agents won't know why this "
            "document was processed."
        )
    if not agent_metadata or (
        "source_url" not in agent_metadata
        and "source_reference" not in agent_metadata
    ):
        warnings.append(
            "No source_url or source_reference in agent_metadata. "
            "Future agents won't know where this document came from. "
            "See SPEC.md Metadata Conventions for provenance guidelines."
        )

    if store:
        # All warnings must be appended BEFORE store_document — PgDedupStore
        # snapshots warnings into the SQL params at call time and commits
        # before returning (dedup.py:294-300). Return value (was_resurrected)
        # ignored here; would_resurrect above drove the user-facing warning
        # using probe-time state.
        _dedup_store.store_document(stored_doc)
        logger.info(
            "dedup-miss-store",
            extra={
                "collection": collection,
                "fingerprint_prefix": fingerprint[:8],
                "source_file": _source_file_from_uri(uri),
                "algorithm": "raw-bytes",
            },
        )
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
        "warnings_count": len(warnings),
    }

    # When the document is being stored, the full markdown is already
    # persisted and retrievable via get_document / search — returning it
    # inline blows up the LLM context window (a 110-chunk PDF is ~160K
    # chars). Send a short preview instead. When store=false, the caller
    # has nowhere else to get the content, so we return the full text.
    if store:
        if len(markdown) > 500:
            response["markdown"] = (
                markdown[:500]
                + "... [truncated, use get_document for full content]"
            )
            response["markdown_truncated"] = True
        else:
            response["markdown"] = markdown
            response["markdown_truncated"] = False
    else:
        response["markdown"] = markdown

    if store:
        if force:
            _vector_store.delete_by_document(doc_id)
        _vector_store.insert(chunks)
        response["chunks_count"] = len(chunks)
        response["embedding_model"] = (
            _embedding_client.model if _embedding_client.enabled else None
        )
        response["store_status"] = "stored"

        # Record interaction AFTER all processing (SPEC pipeline step 7).
        # Under BL-19 transactional ingest this only runs on the success
        # path — store=False and embed-fail both skip the interaction row.
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
    else:
        response["store_status"] = "not_stored"
        response["chunks_count"] = 0

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


def _count_chunks_for_document(document_id: str) -> int:
    """Count chunks for a specific document."""
    if isinstance(_vector_store, PgVectorStore):
        return _vector_store.count_by_document(document_id)
    # In-memory fallback
    return sum(
        1 for c in _vector_store._chunks.values()
        if c.document_id == document_id
    )


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
