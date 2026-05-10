"""REST API routes for document extraction and retrieval.

All POST endpoints accept caller metadata (agent_id, agent_type, model,
initiated_by). Auth model:

- `GET /api/health` is unauthenticated (liveness probe).
- `POST /api/upload/signed` uses a presigned HMAC query-param
  signature and therefore takes no Authorization header (the signing
  secret is a server-side shared secret, not a user credential).
- Every other route requires a valid Auth0 Bearer JWT via
  `Depends(require_user)` from `pipeline.auth_oauth`. A valid JWT
  resolves to a `Principal` whose `user_id` (Auth0 `sub`) is used as
  the fallback agent_id when the request doesn't supply one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel, Field

from pipeline.api.signing import mark_signature_used, verify_signature
from pipeline.auth_oauth import Principal, require_user
import pipeline.services as _svc

router = APIRouter()


# ── Build / commit identification ───────────────────────────────────────────
#
# /api/health surfaces a ``commit`` field so an operator (or PLINY's deploy-
# verification routine) can distinguish "new commit live" from "previous
# deploy still serving" without separately consulting the GitHub Deployments
# API. Resolution order on first read:
#
#   1. ``RAILWAY_GIT_COMMIT_SHA`` — auto-injected by Railway when the deploy
#      originated from a GitHub trigger (Railway docs: Variables Reference,
#      verified 2026-05-09).
#   2. ``GIT_COMMIT`` — generic hosting fallback.
#   3. ``.git/HEAD`` (and any ref it points to) — local dev outside Railway.
#   4. ``"unknown"`` — no signal available; surface honestly rather than
#      pin to a stale value.
#
# Cached at module level: read once on first request, reused thereafter.
# A container restart re-reads (which is the lifecycle event a SHA flip
# corresponds to anyway).

_COMMIT_SHA_CACHE: Optional[str] = None


def _read_commit_from_dot_git(start_dir: Optional[Path] = None) -> Optional[str]:
    """Read the current commit SHA from ``.git/HEAD`` (and the ref it
    points to). Returns the short 7-char SHA, or ``None`` if the repo
    isn't reachable or HEAD is unparseable.

    Handles both layouts:

    1. Regular checkout — ``<start_dir>/.git`` is a directory, HEAD and
       refs both live there.
    2. Linked worktree (Denson's standard pattern) — ``<start_dir>/.git``
       is a *file* containing ``gitdir: <path>`` that points at
       ``<main-repo>/.git/worktrees/<name>/``. The linked dir holds the
       per-worktree HEAD; ``refs/heads/*`` live in the shared *commondir*
       (the main repo's ``.git/``), located via the ``commondir`` file
       inside the linked dir. Without this branch, ``_resolve_commit_sha``
       returns ``"unknown"`` from any worktree, which silently breaks
       PLINY's deploy-verification signal during local development.

    ``start_dir`` defaults to ``Path.cwd()`` (matches prior behavior); a
    test may pass an explicit directory to drive both layouts under
    ``tmp_path`` without ``monkeypatch.chdir``.

    Sentinel-on-fail: any unresolvable case returns ``None`` so the
    caller falls through to ``"unknown"``. We do NOT consult
    ``packed-refs`` — refs that exist only in packed form fall through
    to ``"unknown"`` rather than failing loudly. (Operators in that
    state can use ``GIT_COMMIT`` instead.)
    """
    base = start_dir if start_dir is not None else Path.cwd()
    dot_git = base / ".git"
    if not dot_git.exists():
        return None

    if dot_git.is_dir():
        git_dir = dot_git
        common_dir = dot_git
    else:
        # Worktree layout — ``.git`` is a file with a ``gitdir:`` pointer.
        try:
            pointer = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not pointer.startswith("gitdir:"):
            return None
        gitdir_value = pointer[len("gitdir:"):].strip()
        if not gitdir_value:
            return None
        gitdir_path = Path(gitdir_value)
        if not gitdir_path.is_absolute():
            gitdir_path = (dot_git.parent / gitdir_path).resolve()
        if not gitdir_path.is_dir():
            return None
        git_dir = gitdir_path
        # ``commondir`` inside the linked dir points at the shared
        # ``.git`` (main repo) where ``refs/heads/*`` actually live.
        # If absent, fall back to ``git_dir`` (degenerate but safe —
        # ref-walk will then miss and return None).
        commondir_file = git_dir / "commondir"
        common_dir = git_dir
        if commondir_file.is_file():
            try:
                cd_value = commondir_file.read_text(encoding="utf-8").strip()
            except OSError:
                cd_value = ""
            if cd_value:
                cd_path = Path(cd_value)
                if not cd_path.is_absolute():
                    cd_path = (git_dir / cd_path).resolve()
                if cd_path.is_dir():
                    common_dir = cd_path

    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return None
    try:
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref: "):
        ref_rel = head[len("ref: "):].strip()
        if not ref_rel:
            return None
        ref_path = common_dir / ref_rel
        if not ref_path.is_file():
            return None
        try:
            sha = ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
    else:
        sha = head
    if len(sha) < 7:
        return None
    return sha[:7]


def _resolve_commit_sha() -> str:
    """Memoized resolution of the current deploy's commit SHA."""
    global _COMMIT_SHA_CACHE
    if _COMMIT_SHA_CACHE is not None:
        return _COMMIT_SHA_CACHE
    for var in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT"):
        val = os.environ.get(var)
        if val:
            _COMMIT_SHA_CACHE = val[:7]
            return _COMMIT_SHA_CACHE
    from_git = _read_commit_from_dot_git()
    if from_git:
        _COMMIT_SHA_CACHE = from_git
        return _COMMIT_SHA_CACHE
    _COMMIT_SHA_CACHE = "unknown"
    return _COMMIT_SHA_CACHE


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
    # Per-request ingest knobs (Batch G / ariadne--16a §F2). Accepts any
    # field of pipeline.config.IngestConfig (e.g. ``max_source_bytes``,
    # ``max_source_bytes_hard``, ``require_confirmation_above_soft``);
    # unknown keys raise 422 to surface operator typos. None falls back
    # to YAML defaults from configure_ingest().
    ingest_config: Optional[dict] = None
    # m5e source-size confirmation flow: when the server returns HTTP 413
    # with ``code: "confirmation_required"`` and a ``confirmation_token``,
    # the caller re-submits the same request with the token in this
    # field to bypass the soft-cap friction. The token is HMAC-signed and
    # binds to the request URI; tokens are valid for
    # ``confirmation_token_ttl_seconds`` (default 300) and may be re-used
    # within that window.
    #
    # rv0: max_length=4096 bounds the DoS surface. Legitimate HMAC-signed
    # tokens are well under 1 KB; 4096 leaves comfortable headroom while
    # rejecting megabyte-sized payloads at validation (422) before they
    # reach the HMAC verifier and consume server memory.
    confirmation_token: Optional[str] = Field(default=None, max_length=4096)


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
    metadata: CallerMetadata, principal: Principal | None
) -> str | None:
    """Use explicit agent_id if provided, else derive from the Auth0 principal.

    The fallback shape is `auth0:<sub>`, matching the prior
    `api-key:<name>` shape (prefix:identifier) so the interaction log
    stays grep-parseable across the X-API-Key → OAuth transition. The
    semantic drift from key-name to Auth0 sub is intentional — it is
    the clean-break replacement, not a rename.
    """
    if metadata.agent_id:
        return metadata.agent_id
    if principal:
        return f"auth0:{principal.user_id}"
    return None


# ── Upload endpoint ─────────────────────────────────────────────────────────


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_user),
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
    """Upload a file using a presigned URL. No Authorization header required.

    The signature must have been generated server-side via
    `pipeline.api.signing.generate_presigned_url` using the server's
    ARIADNE_UPLOAD_SIGNING_SECRET. Each signature is single-use.

    Note: this endpoint uses a server-side HMAC shared secret for URL
    signing. It is intentionally separate from the per-user OAuth auth
    that protects the other routes — a presigned URL can be handed to
    an uploader that does NOT hold a user credential. In the OAuth
    world the client already has a short-lived JWT, so this
    value-proposition may be worth revisiting; see ariadne--xft.2
    follow-ups.
    """
    import os
    from pathlib import Path as _Path

    secret_key = os.environ.get("ARIADNE_UPLOAD_SIGNING_SECRET")
    if not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Signed uploads are not available: no upload signing secret configured.",
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
        "commit": _resolve_commit_sha(),
        "engine": "markitdown",
        "embedding_enabled": _svc._embedding_client.enabled,
    }


# ── Document endpoints ───────────────────────────────────────────────────────


@router.post("/documents")
async def submit_document(
    req: DocumentRequest,
    principal: Principal = Depends(require_user),
):
    """Submit a single document for extraction and processing."""
    from pipeline.services import _process_single_document

    agent_id = _resolve_agent_id(req, principal)

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
        ingest_config=req.ingest_config,
        confirmation_token=req.confirmation_token,
    )

    if result.get("error"):
        # m5e dispatch: route the m5e error codes to their wire status.
        # Legacy paths (chunking-config errors, source-read errors,
        # extraction failure, embedding failure, …) do NOT set ``code``;
        # the ``.get(code, 422)`` default preserves the pre-m5e behavior
        # (HTTP 422 with ``{message, document_id, source_file}`` plus
        # any pre-existing extras). Pinned by §4 probe (l).
        code = result.get("code", "")
        status = {
            "confirmation_required": 413,
            "exceeds_hard_limit": 422,
            "exceeds_soft_cap_strict": 422,
        }.get(code, 422)
        # Surface every key in the error-dict (minus the ``error: True``
        # internal flag). For m5e codes that means soft_cap / hard_cap /
        # confirmation_token / etc all flow to the client; for legacy
        # codes the existing message / document_id / source_file shape
        # is preserved verbatim because the legacy dicts only carry
        # those keys.
        detail = {k: v for k, v in result.items() if k != "error"}
        raise HTTPException(status_code=status, detail=detail)

    return result


@router.get("/documents/aggregate")
async def aggregate_documents(
    request: Request,
    group_by: str = Query(
        ...,
        description=(
            "Field to group by. See /api/documents/schema for valid values."
        ),
    ),
    collection: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    has_warnings: Optional[bool] = Query(None),
    has_source_reference: Optional[bool] = Query(None),
    include_deleted: bool = Query(False),
    principal: Principal = Depends(require_user),
):
    """Group-by summary over /documents filters. Returns [{group, count}, ...]."""
    import collections as _py_collections

    _reject_unknown_query_params(
        request, _AGGREGATE_PARAMS, "/api/documents/aggregate"
    )

    if group_by not in _AGGREGATE_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown group_by '{group_by}'.",
                "valid_group_by": sorted(_AGGREGATE_REGISTRY.keys()),
                "see": "/api/documents/schema",
            },
        )

    # list_documents owns filtering on both backends, so a single call
    # returns the post-filter corpus ready for bucketing. The 100000 cap
    # is still a fetch-and-count hack — flagged for replacement by a
    # native SQL GROUP BY query in a future pass.
    all_docs, _ = _svc._dedup_store.list_documents(
        collection=collection,
        file_type=file_type,
        limit=100000,
        offset=0,
        include_deleted=include_deleted,
        tag=tag,
        has_warnings=has_warnings,
        has_source_reference=has_source_reference,
    )

    counter: _py_collections.Counter[str] = _py_collections.Counter()
    if group_by == "collection":
        for d in all_docs:
            counter[d.collection_id] += 1
    elif group_by == "file_type":
        for d in all_docs:
            counter[d.file_type] += 1
    elif group_by == "tags":
        for d in all_docs:
            for t in (d.tags or []):
                counter[t] += 1

    if len(counter) > _CAPS["aggregate_buckets_max"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": (
                    f"Aggregate produced {len(counter)} buckets, "
                    f"exceeds cap of {_CAPS['aggregate_buckets_max']}. "
                    "Narrow with a filter (collection, file_type, etc.)."
                ),
                "cap_applied": _CAPS["aggregate_buckets_max"],
                "see": "/api/documents/schema",
            },
        )

    buckets_sorted = sorted(
        counter.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )

    applied_filters = {
        k: v for k, v in {
            "collection": collection,
            "file_type": file_type,
            "tag": tag,
            "has_warnings": has_warnings,
            "has_source_reference": has_source_reference,
            "include_deleted": include_deleted,
        }.items() if v is not None and v is not False
    }

    return {
        "group_by": group_by,
        "filters": applied_filters,
        "buckets": [{"group": g, "count": c} for g, c in buckets_sorted],
        "total_buckets": len(buckets_sorted),
        "total_documents": (
            sum(counter.values()) if group_by != "tags" else len(all_docs)
        ),
    }


@router.get("/documents/schema")
async def documents_schema(
    principal: Principal = Depends(require_user),
):
    """Return the list/aggregate query surface. Call this first from an agent."""
    return {
        "list_endpoint": "/api/documents",
        "aggregate_endpoint": "/api/documents/aggregate",
        "filters": dict(_FILTER_REGISTRY),
        "includes": dict(_INCLUDE_REGISTRY),
        "aggregatable_fields": dict(_AGGREGATE_REGISTRY),
        "caps": {
            "list_default": _CAPS["list_default"],
            "list_with_markdown": _CAPS["list_with_markdown"],
            "aggregate_buckets_max": _CAPS["aggregate_buckets_max"],
        },
        "brute_force_fallback": (
            "If a question can't be expressed with these filters, "
            "paginate /api/documents with include=[...] covering the "
            "fields you need, then filter client-side."
        ),
        "deferred": {
            "store_status_filter": (
                "BL-19 made store_status vestigial (failed ingests no longer "
                "write rows). Not planned."
            ),
            "agent_metadata_group_by": (
                "Grouping by arbitrary JSON paths in agent_metadata is a "
                "future pass."
            ),
            "date_range_filters": (
                "created_after / created_before are a future pass."
            ),
        },
    }


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    include_chunks: bool = Query(True),
    include_interactions: bool = Query(True),
    principal: Principal = Depends(require_user),
):
    """Retrieve the full processed document by ID."""
    doc = _svc._find_document_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    warnings = list(doc.warnings) if doc.warnings else []
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
        "warnings": warnings,
        "warnings_count": len(warnings),
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


# -- Query API registries (single source of truth for /schema) --------------

_FILTER_REGISTRY: dict[str, str] = {
    "collection": "Exact match on collection name.",
    "file_type": "Exact match (leading dot stripped - 'pdf' and '.pdf' both match).",
    "tag": "Docs whose tag list contains this tag (single-value, OR-semantics across repeated calls).",
    "has_warnings": "true -> only docs with >=1 warning; false -> only clean docs.",
    "has_source_reference": (
        "true -> document has a non-empty 'source_reference' value "
        "(latest-wins from agent_metadata) that is not literally "
        "'unknown'. false -> inverse."
    ),
    "include_deleted": "Include soft-deleted docs (default false).",
}

_INCLUDE_REGISTRY: dict[str, str] = {
    "agent_metadata": "Adds the latest interaction's agent_metadata dict per row.",
    "tags": "Adds the full tag list per row.",
    "last_interaction": "Adds {agent_notes, action, created_at} of the latest interaction.",
    "markdown": "Adds the full markdown body per row (caps limit at 50).",
}

_AGGREGATE_REGISTRY: dict[str, str] = {
    "collection": "One bucket per collection name.",
    "file_type": "One bucket per file type.",
    "tags": "One bucket per distinct tag. Docs with multiple tags contribute to multiple buckets. Docs with no tags contribute to nothing.",
}

_CAPS = {
    "list_default": 500,
    "list_with_markdown": 50,
    "aggregate_buckets_max": 1000,
}

_VALID_INCLUDES = set(_INCLUDE_REGISTRY.keys())

_LIST_DOCUMENTS_PARAMS = (
    set(_FILTER_REGISTRY.keys()) | {"include", "limit", "offset"}
)
_AGGREGATE_PARAMS = (set(_FILTER_REGISTRY.keys()) | {"group_by"}) - {"include"}


def _reject_unknown_query_params(
    request: Request,
    allowed: set[str],
    endpoint_hint: str,
) -> None:
    """Raise 400 if the request has query params not in `allowed`.

    FastAPI's declarative Query params silently drop unknown keys by design.
    For agent-facing endpoints we want a loud failure so an agent that typos
    `collecton=` gets an immediate, specific error instead of a silent
    full-corpus scan.
    """
    got = set(request.query_params.keys())
    unknown = got - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown query param(s): {sorted(unknown)}.",
                "valid_params": sorted(allowed),
                "endpoint": endpoint_hint,
                "see": "/api/documents/schema",
            },
        )


@router.get("/documents")
async def list_documents(
    request: Request,
    collection: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(
        None,
        description="Match docs with this tag in their tag list",
    ),
    has_warnings: Optional[bool] = Query(
        None,
        description="Filter to docs that have (or do not have) any warnings",
    ),
    has_source_reference: Optional[bool] = Query(
        None,
        description=(
            "Filter by presence of a non-empty, non-'unknown' "
            "source_reference on the document "
            "(latest value written from agent_metadata)."
        ),
    ),
    include: list[str] = Query(
        default_factory=list,
        description=(
            "Fields to include in each row. Accepted: "
            "agent_metadata, tags, last_interaction, markdown"
        ),
    ),
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    principal: Principal = Depends(require_user),
):
    """List all documents, optionally filtered by collection or file type."""
    _reject_unknown_query_params(
        request, _LIST_DOCUMENTS_PARAMS, "/api/documents"
    )

    bad_includes = [i for i in include if i not in _VALID_INCLUDES]
    if bad_includes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown include value(s): {bad_includes}.",
                "valid_includes": sorted(_VALID_INCLUDES),
                "see": "SPEC.md § Querying documents",
            },
        )
    include_set = set(include)

    cap = 50 if "markdown" in include_set else 500
    if limit > cap:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"limit={limit} exceeds cap of {cap} for this include set.",
                "cap_applied": cap,
                "cap_rationale": (
                    "50 when 'markdown' is included (full doc body per row); "
                    "500 otherwise"
                ),
                "include_set": sorted(include_set),
            },
        )

    page_docs, total = _svc._dedup_store.list_documents(
        collection=collection,
        file_type=file_type,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        tag=tag,
        has_warnings=has_warnings,
        has_source_reference=has_source_reference,
    )

    def _build_row(d) -> dict[str, Any]:
        row: dict[str, Any] = {
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
            "warnings_count": len(d.warnings) if d.warnings else 0,
        }
        if "tags" in include_set:
            row["tags"] = list(d.tags) if d.tags else []
        if "markdown" in include_set:
            row["markdown"] = d.markdown
        if "agent_metadata" in include_set or "last_interaction" in include_set:
            interactions = _svc._dedup_store.get_interactions(d.document_id)
            latest = interactions[-1] if interactions else None
            if "agent_metadata" in include_set:
                row["agent_metadata"] = latest.agent_metadata if latest else None
            if "last_interaction" in include_set:
                row["last_interaction"] = (
                    {
                        "agent_notes": latest.agent_notes,
                        "action": latest.action,
                        "created_at": latest.created_at,
                    }
                    if latest
                    else None
                )
        return row

    return {
        "documents": [_build_row(d) for d in page_docs],
        "total_count": total,
        "total_is_exact": True,
        "limit": limit,
        "offset": offset,
    }


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    req: UpdateDocumentRequest,
    principal: Principal = Depends(require_user),
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

    agent_id = _resolve_agent_id(req, principal)
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
    principal: Principal = Depends(require_user),
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

    agent_id = _resolve_agent_id(req, principal)
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
    principal: Principal = Depends(require_user),
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

    agent_id = _resolve_agent_id(req, principal)
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
    principal: Principal = Depends(require_user),
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
    agent_id = _resolve_agent_id(req, principal)
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
    principal: Principal = Depends(require_user),
):
    """Batch-ingest a directory of documents."""
    from pipeline.services import SUPPORTED_EXTENSIONS, _process_single_document
    from pathlib import Path as _Path
    import os as _os

    agent_id = _resolve_agent_id(req, principal)
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
    principal: Principal = Depends(require_user),
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
    principal: Principal = Depends(require_user),
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
    purge: bool = Query(
        False,
        description=(
            "Hard-delete immediately instead of soft-delete. "
            "Irreversible — bypasses the 48-hour restore window."
        ),
    ),
    req: Optional[CallerMetadata] = None,
    principal: Principal = Depends(require_user),
):
    """Soft-delete every document in a collection (or hard-delete with ?purge=true).

    Each document keeps its own 48-hour restore clock — documents that were
    individually deleted earlier retain their original deletion time. The
    collection record itself is preserved.

    When ``purge=true``, documents are marked and then immediately
    hard-deleted from the database. Use this to fully reset a collection
    before a fresh ingest (a soft-deleted row with the same fingerprint is
    resurrected by re-ingest — see PgDedupStore.store_document).
    """
    _ = req or CallerMetadata()
    if purge:
        _svc._dedup_store.soft_delete_collection(collection_name)
        purged = _svc._dedup_store.purge_deleted(older_than_hours=0)
        return {
            "collection": collection_name,
            "documents_purged": purged,
            "message": (
                f"Hard-deleted {purged} document(s). Not recoverable."
            ),
        }
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
    principal: Principal = Depends(require_user),
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
    principal: Principal = Depends(require_user),
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

    # Per-collection counts (doc-bearing only)
    collection_stats: dict[str, int] = {}
    for d in all_docs:
        collection_stats[d.collection_id] = collection_stats.get(d.collection_id, 0) + 1

    # ariadne--qe6: pad collection_stats with registered-but-empty collections.
    #
    # Pre-fix, ``total_collections`` was ``len(_collections)`` (registered
    # only) while ``collections`` was the doc-bearing map — the two sets
    # diverged in either direction, so ``total_collections`` did not match
    # ``len(stats.collections)`` and disagreed with ``GET /api/collections``
    # (which already takes the union at routes.py:1087). Padding with
    # ``setdefault(name, 0)`` here makes the response a true union and
    # establishes the invariant ``total_collections == len(collections)``.
    for name in _collections:
        collection_stats.setdefault(name, 0)

    return {
        "total_documents": total_docs,
        "total_chunks": _svc._vector_store.count(),
        "total_collections": len(collection_stats),
        "embedding_enabled": _svc._embedding_client.enabled,
        "collections": collection_stats,
    }


