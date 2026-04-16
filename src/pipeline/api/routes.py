"""REST API routes for document extraction and retrieval.

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
from pipeline.api.signing import mark_signature_used, verify_signature
import pipeline.services as _svc

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
    include_deleted: bool = False


class UpdateDocumentRequest(CallerMetadata):
    tags: Optional[list[str]] = None
    collection: Optional[str] = None


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


# ── Signed upload endpoint (no API key header; HMAC-signed query params) ────


@router.post("/upload/signed")
async def upload_file_signed(
    file: UploadFile = File(...),
    filename: str = Query(...),
    expires: int = Query(...),
    max_size: int = Query(...),
    signature: str = Query(...),
):
    """Upload a file using a presigned URL. No X-API-Key header required.

    The signature must have been generated server-side via
    `pipeline.api.signing.generate_presigned_url` using the server's
    ARIADNE_API_KEY as the secret. Each signature is single-use.
    """
    import os
    from pathlib import Path as _Path

    secret_key = os.environ.get("ARIADNE_API_KEY")
    if not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Signed uploads are not available: no server API key configured.",
        )

    if not verify_signature(filename, expires, max_size, signature, secret_key):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired upload signature.",
        )

    uploaded_name = _Path(file.filename).name if file.filename else "upload"
    if uploaded_name != filename:
        raise HTTPException(
            status_code=400,
            detail="Uploaded filename does not match signed filename.",
        )

    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds max_size of {max_size} bytes.",
        )

    if not mark_signature_used(signature, expires):
        raise HTTPException(
            status_code=409,
            detail="Upload signature has already been consumed.",
        )

    upload_dir = _Path(os.environ.get("ARIADNE_UPLOAD_DIR", "./data/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _Path(filename).name
    dest = upload_dir / safe_name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = upload_dir / f"{stem}_{counter}{suffix}"
            counter += 1

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
        "embedding_enabled": _svc._embedding_client.enabled,
    }


# ── Document endpoints ───────────────────────────────────────────────────────


@router.post("/documents")
async def submit_document(
    req: DocumentRequest,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Submit a single document for extraction and processing."""
    from pipeline.services import _process_single_document

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
    doc = _svc._find_document_by_id(document_id)
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
        doc_chunks = _svc._get_chunks_for_document(doc.document_id)
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
        interactions = _svc._dedup_store.get_interactions(doc.document_id)
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    api_key: APIKey | None = Depends(check_api_key),
):
    """List all documents, optionally filtered by collection or file type."""
    from pipeline.dedup import PgDedupStore

    if isinstance(_svc._dedup_store, PgDedupStore):
        page_docs, total = _svc._dedup_store.list_documents(
            collection=collection, file_type=file_type,
            limit=limit, offset=offset,
            include_deleted=include_deleted,
        )
    else:
        docs = list(_svc._dedup_store._documents.values())
        if not include_deleted:
            docs = [
                d for d in docs
                if d.document_id not in _svc._dedup_store._deletions
            ]
        if collection:
            docs = [d for d in docs if d.collection_id == collection]
        if file_type:
            ft = file_type.lstrip(".")
            docs = [d for d in docs if d.file_type == ft]
        total = len(docs)
        page_docs = docs[offset:offset + limit]

    return {
        "documents": [
            {
                "document_id": d.document_id,
                "source_file": d.source_file,
                "title": d.title,
                "file_type": d.file_type,
                "collection": d.collection_id,
                "content_fingerprint": d.content_fingerprint,
                "chunk_count": _svc._count_chunks_for_document(d.document_id),
                "interaction_count": len(
                    _svc._dedup_store.get_interactions(d.document_id)
                ),
                "created_at": d.created_at,
            }
            for d in page_docs
        ],
        "total_count": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    req: UpdateDocumentRequest,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Patch a stored document's metadata.

    `tags` REPLACES the full tag list. `agent_metadata` is shallow-merged
    into the existing metadata. `collection` moves the document.
    """
    from pipeline.dedup import DocumentInteraction

    updated_fields: list[str] = []
    if req.tags is not None:
        updated_fields.append("tags")
    if req.agent_metadata is not None:
        updated_fields.append("agent_metadata")
    if req.collection is not None:
        updated_fields.append("collection")

    if not updated_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "No fields to update. Provide at least one of: "
                "tags, agent_metadata, collection."
            ),
        )

    try:
        updated = _svc._dedup_store.update_document_metadata(
            document_id=document_id,
            tags=req.tags,
            agent_metadata=req.agent_metadata,
            collection=req.collection,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    agent_id = _resolve_agent_id(req, api_key)
    _svc._dedup_store.record_interaction(
        DocumentInteraction(
            document_id=document_id,
            collection_id=updated.get("collection") or "",
            agent_id=agent_id,
            agent_type=req.agent_type,
            model=req.model,
            initiated_by=req.initiated_by,
            agent_notes=req.agent_notes,
            agent_metadata=req.agent_metadata,
            action="update",
            was_dedup_skip=False,
        )
    )

    return {
        "document_id": updated["document_id"],
        "collection": updated.get("collection"),
        "tags": updated.get("tags", []),
        "agent_metadata": updated.get("agent_metadata", {}),
        "updated_fields": updated_fields,
    }


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    req: Optional[CallerMetadata] = None,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Soft-delete a document. Hidden immediately, purged after 48 hours."""
    from datetime import datetime, timezone
    from pipeline.dedup import DocumentInteraction

    req = req or CallerMetadata()
    doc = _svc._find_document_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    _svc._dedup_store.soft_delete_document(document_id)
    scheduled_at = datetime.now(timezone.utc).isoformat()

    agent_id = _resolve_agent_id(req, api_key)
    _svc._dedup_store.record_interaction(
        DocumentInteraction(
            document_id=document_id,
            collection_id=doc.collection_id,
            agent_id=agent_id,
            agent_type=req.agent_type,
            model=req.model,
            initiated_by=req.initiated_by,
            agent_notes=req.agent_notes,
            agent_metadata=req.agent_metadata,
            action="delete",
            was_dedup_skip=False,
        )
    )

    return {
        "document_id": document_id,
        "status": "scheduled_for_deletion",
        "deletion_scheduled_at": scheduled_at,
        "message": "Will be purged after 48 hours.",
    }


@router.post("/documents/{document_id}/restore")
async def restore_document(
    document_id: str,
    req: Optional[CallerMetadata] = None,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Undo a soft-delete within the 48-hour grace window."""
    from pipeline.dedup import DocumentInteraction, PgDedupStore

    req = req or CallerMetadata()
    doc = None
    if isinstance(_svc._dedup_store, PgDedupStore):
        doc = _svc._dedup_store.get_document_by_id(
            document_id, include_deleted=True
        )
    else:
        for (_coll, _fp), candidate in _svc._dedup_store._documents.items():
            if candidate.document_id == document_id:
                doc = candidate
                break
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        _svc._dedup_store.restore_document(document_id)
    except ValueError as e:
        msg = str(e)
        if "48h" in msg or "48 h" in msg or "outside" in msg:
            raise HTTPException(status_code=410, detail=msg)
        raise HTTPException(status_code=404, detail=msg)

    agent_id = _resolve_agent_id(req, api_key)
    _svc._dedup_store.record_interaction(
        DocumentInteraction(
            document_id=document_id,
            collection_id=doc.collection_id,
            agent_id=agent_id,
            agent_type=req.agent_type,
            model=req.model,
            initiated_by=req.initiated_by,
            agent_notes=req.agent_notes,
            agent_metadata=req.agent_metadata,
            action="restore",
            was_dedup_skip=False,
        )
    )

    return {"document_id": document_id, "status": "restored"}


# ── Search endpoint ──────────────────────────────────────────────────────────


@router.post("/search")
async def search_documents(
    req: SearchRequest,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Semantic search over the document knowledge store."""
    if not _svc._embedding_client.enabled:
        raise HTTPException(
            status_code=503,
            detail="Search is not available: no embedding API key configured.",
        )

    try:
        query_embedding = _svc._embedding_client.embed_query(req.query)
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

    results = _svc._vector_store.search(
        query_embedding=query_embedding,
        top_k=req.top_k,
        filters=search_filters if search_filters else None,
        include_deleted=req.include_deleted,
    )

    # Post-filter for source_file, file_type, tags when using in-memory store
    from pipeline.storage.base import InMemoryVectorStore
    if isinstance(_svc._vector_store, InMemoryVectorStore) and search_filters:
        results = _svc._post_filter_results(results, search_filters)

    response_results = []
    for r in results:
        interactions = _svc._dedup_store.get_interactions(r.document_id)
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
    _svc._dedup_store.record_search(
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
    from pipeline.services import SUPPORTED_EXTENSIONS, _process_single_document
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

    def _process_file_safe(fp: _Path) -> dict:
        """Process a single file, catching exceptions."""
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

    # Process files concurrently, up to 4 at a time
    import asyncio as _asyncio
    semaphore = _asyncio.Semaphore(4)
    loop = _asyncio.get_event_loop()

    async def _run_one(fp: _Path) -> dict:
        async with semaphore:
            return await loop.run_in_executor(None, _process_file_safe, fp)

    results_list = await _asyncio.gather(*[_run_one(fp) for fp in files])

    files_processed = sum(1 for r in results_list if not r.get("error") and not r.get("was_dedup_skip"))
    files_skipped = sum(1 for r in results_list if r.get("was_dedup_skip"))
    files_errored = sum(1 for r in results_list if r.get("error"))

    return {
        "files_found": files_found,
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "files_errored": files_errored,
        "results": list(results_list),
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
    if isinstance(_svc._dedup_store, PgDedupStore):
        all_docs, _ = _svc._dedup_store.list_documents(limit=100000)
        for d in all_docs:
            collection_counts[d.collection_id] = (
                collection_counts.get(d.collection_id, 0) + 1
            )
    else:
        for (coll, _fp), _doc in _svc._dedup_store._documents.items():
            if _doc.document_id in _svc._dedup_store._deletions:
                continue
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


@router.delete("/collections/{collection_name}")
async def delete_collection(
    collection_name: str,
    req: Optional[CallerMetadata] = None,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Soft-delete every document in a collection.

    Each document keeps its own 48-hour restore clock — documents that were
    individually deleted earlier retain their original deletion time. The
    collection record itself is preserved.
    """
    _ = req or CallerMetadata()
    marked = _svc._dedup_store.soft_delete_collection(collection_name)
    return {
        "collection": collection_name,
        "documents_marked": marked,
        "message": (
            f"{marked} document(s) scheduled for deletion. "
            "Each will be purged after its own 48-hour window expires. "
            "Use POST /api/documents/{document_id}/restore on individual "
            "documents to undo."
        ),
    }


@router.post("/collections/{collection_name}/restore")
async def restore_collection(
    collection_name: str,
    req: Optional[CallerMetadata] = None,
    api_key: APIKey | None = Depends(check_api_key),
):
    """Restore soft-deleted documents in a collection within the 48h window."""
    _ = req or CallerMetadata()
    restored = _svc._dedup_store.restore_collection(collection_name)
    return {
        "collection": collection_name,
        "documents_restored": restored,
    }


# ── Stats endpoint ───────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    api_key: APIKey | None = Depends(check_api_key),
):
    """System statistics."""
    from pipeline.dedup import PgDedupStore

    if isinstance(_svc._dedup_store, PgDedupStore):
        all_docs, total_docs = _svc._dedup_store.list_documents(limit=10000)
    else:
        all_docs = [
            d for d in _svc._dedup_store._documents.values()
            if d.document_id not in _svc._dedup_store._deletions
        ]
        total_docs = len(all_docs)

    # Per-collection counts
    collection_stats: dict[str, int] = {}
    for d in all_docs:
        collection_stats[d.collection_id] = collection_stats.get(d.collection_id, 0) + 1

    return {
        "total_documents": total_docs,
        "total_chunks": _svc._vector_store.count(),
        "total_collections": len(_collections),
        "embedding_enabled": _svc._embedding_client.enabled,
        "collections": collection_stats,
    }


