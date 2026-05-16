"""FastAPI application setup.

Creates the FastAPI app with CORS, lifespan, and route mounting.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pipeline.api.bw_ingest import _bw_retry_worker
from pipeline.api.bw_routes import (
    projects_router as bw_projects_router,
    router as bw_router,
)
from pipeline.api.confirmation import configure_confirmation
from pipeline.api.discovery import router as discovery_router
from pipeline.api.routes import router
from pipeline.config import load_config
from pipeline.embedding.embedder import EmbeddingConfig
from pipeline.services import (
    configure_chunking,
    configure_embedding,
    configure_image_enrichment,
    configure_ingest,
    configure_stores,
)
from pipeline.stores import create_stores, close_pool

logger = logging.getLogger("ariadne.app")


def _ensure_bw_repos_root() -> None:
    """Phase 5 (ariadne--8fd.9): ``makedirs`` BW_REPOS_ROOT on startup.

    On Railway, the persistent volume is mounted before the container
    process starts — but a freshly-provisioned volume is empty, and a
    local-dev / docker-compose run typically does not pre-create the
    path. ``makedirs(exist_ok=True)`` is idempotent and cheap; if the
    directory exists (mount provisioned, prior run created it), this
    is a no-op. If creation fails (permissions / mount unavailable),
    log a WARNING and continue — the bw HTTP surface will return clear
    404 ``bw_project_uninitialized`` errors per slug, and other Ariadne
    functionality (search, documents) keeps working independent of bw.

    Reads ``BW_REPOS_ROOT`` from the ``bw_routes`` module live (not
    via ``os.environ`` directly) so tests that monkey-patch the module
    constant see the override take effect here too.
    """
    from pipeline.api import bw_routes as _bw_routes
    bw_root = _bw_routes.BW_REPOS_ROOT
    try:
        os.makedirs(bw_root, exist_ok=True)
        logger.info(
            "bw repos root ready: path=%s (BW_REPOS_ROOT)",
            bw_root,
        )
    except OSError as e:
        logger.warning(
            "bw repos root not creatable: path=%s error=%s "
            "(bw HTTP surface will return 404 per slug; other "
            "endpoints unaffected)",
            bw_root, e,
        )


class UTF8JSONResponse(JSONResponse):
    """JSONResponse subclass that declares charset=utf-8 in Content-Type.

    Windows clients (PowerShell Invoke-WebRequest, older curl, some HTTP
    libs) default to cp1252 when the server omits the charset — the bytes
    on the wire are correct UTF-8 but the client decodes them as cp1252,
    producing mojibake like \\u00e2\\u20ac\\u201d for an em-dash. See
    dave_and_bob_communication/BL24_SCHEMA_MOJIBAKE_ROOT_CAUSE.md.
    """

    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    config = load_config()
    dimensions = config.embedding.dimensions

    logger.info(
        "Starting with embedding model=%s dimensions=%d endpoint=%s",
        config.embedding.model,
        dimensions,
        config.embedding.base_url,
    )

    # Initialize stores (Postgres or in-memory based on config)
    dedup_store, vector_store = create_stores(config)
    configure_stores(dedup_store, vector_store)
    logger.info("Stores initialized (backend=%s)", config.vector_store.backend)

    # Install YAML-loaded chunking defaults (ariadne--lpf / Batch F).
    # Per-request overrides still win at call time. Position: after
    # configure_stores (chunking has no dependency on embedding/vision)
    # so operator-visible startup errors fail loud here, before any
    # network-touching configure_* runs.
    configure_chunking(config.chunking)
    logger.info(
        "Chunking defaults loaded (strategy=%s, min_tokens=%d)",
        config.chunking.strategy,
        config.chunking.min_chunk_tokens,
    )

    # Install YAML-loaded ingest defaults (ariadne--16a / Batch G).
    # Per-request overrides still win at call time. configure_ingest
    # validates the cap-coherence + TTL invariants and raises ValueError
    # loudly here if the YAML value is misconfigured (no silent zero-cap,
    # no silent hard < soft, no silent zero-TTL).
    configure_ingest(config.ingest)
    logger.info(
        "Ingest defaults loaded (max_source_bytes=%d, "
        "max_source_bytes_hard=%d, "
        "require_confirmation_above_soft=%s, "
        "confirmation_token_ttl_seconds=%d)",
        config.ingest.max_source_bytes,
        config.ingest.max_source_bytes_hard,
        config.ingest.require_confirmation_above_soft,
        config.ingest.confirmation_token_ttl_seconds,
    )

    # m5e: install the per-process HMAC secret used by the source-size
    # confirmation flow (api/confirmation.py). secret=None regenerates
    # 32 bytes via secrets.token_bytes; tokens issued before a container
    # restart are invalidated by the restart and the caller path is
    # identical to EXPIRED (re-submit gets a fresh 413 with a new token).
    configure_confirmation()

    # Configure the shared embedding client from ariadne.yaml
    if config.embedding.api_key:
        logger.info("Embedding API key found, enabling embeddings")
        configure_embedding(
            EmbeddingConfig(
                model=config.embedding.model,
                dimensions=config.embedding.dimensions,
                provider=config.embedding.provider,
                base_url=config.embedding.base_url,
                api_key=config.embedding.api_key,
            )
        )
    else:
        logger.info("No embedding API key — search disabled")

    # Configure image enrichment from config (reads ARIADNE_IMAGE_ENRICHMENT_* env vars)
    if config.image_enrichment.api_key:
        configure_image_enrichment(
            api_key=config.image_enrichment.api_key,
            model=config.image_enrichment.model,
            base_url=config.image_enrichment.base_url,
        )
        logger.info("Image enrichment enabled (model=%s)", config.image_enrichment.model)
    else:
        logger.info("No image enrichment API key — image descriptions disabled")

    # Auth: every protected route uses Depends(require_user) which
    # validates an Auth0 Bearer JWT against the JWKS on each request.
    # No lifespan setup is needed — `pipeline.auth_oauth` reads
    # AUTH0_DOMAIN / AUTH0_AUDIENCE lazily on first use. The discovery
    # endpoint (`/.well-known/ariadne-config`) additionally needs
    # AUTH0_CLIENT_ID. A deploy that forgot any of them surfaces as a
    # 500 with detail="auth_misconfigured" on the first request that
    # hits that path.
    logger.info("OAuth Bearer JWT authentication is REQUIRED (Auth0)")

    # Phase 5 (ariadne--8fd.9): ensure BW_REPOS_ROOT exists on startup.
    # See ``_ensure_bw_repos_root`` for the rationale; extracted as a
    # module-level helper so tests can drive it without spinning up
    # the full lifespan (DB / embedding / etc.).
    _ensure_bw_repos_root()

    # Phase 3 (ariadne--8fd.5): start the bw → Ariadne ingest retry
    # worker. Drains the bw_ingest_retry_queue + JSONL file fallback
    # on a poll interval so failed ingests are recovered without a
    # restart. The task is canceled on shutdown so it doesn't keep
    # the process alive past the lifespan.
    bw_retry_task = asyncio.create_task(_bw_retry_worker())
    logger.info("bw_retry_worker started (Phase 3 / ariadne--8fd.5)")

    yield
    # Shutdown: cancel the retry worker, then close connections.
    bw_retry_task.cancel()
    try:
        await bw_retry_task
    except asyncio.CancelledError:
        pass
    close_pool()


app = FastAPI(
    title="Ariadne Core",
    description=(
        "Open source document extraction and retrieval pipeline. "
        "Converts documents (PDF, DOCX, PPTX, XLSX, HTML, over 20 formats) "
        "into clean Markdown and vector embeddings for semantic search."
    ),
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return structured error bodies for uncaught exceptions.

    FastAPI's default 500 handler returns a bare "Internal Server Error"
    that gives agents no signal. Surface the exception type and message
    so the client can see what actually broke. HTTPException has its own
    handler and is NOT affected by this — this only catches exceptions
    that would otherwise bubble up as naked 500s.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return UTF8JSONResponse(
        status_code=500,
        content={
            "detail": {
                "error_type": type(exc).__name__,
                "message": str(exc)[:2000],
                "path": request.url.path,
                "method": request.method,
            }
        },
    )


app.include_router(router, prefix="/api")
# bw HTTP surface (ariadne--8fd.2 / Phase 2). bw_router already carries
# its own ``/bw/projects/{slug}`` prefix, so mounting under ``/api`` gives
# the full path ``/api/bw/projects/{slug}/...`` — matches the Phase 2
# plan's locked path-prefix-per-project convention.
app.include_router(bw_router, prefix="/api")
# bw project bootstrap (ariadne--9e7). ``POST /api/bw/projects`` initializes
# a new on-disk bw project (mkdir + git init + bw init) under the per-slug
# lock, replacing the prior SSH-required operator step. The router has no
# ``{slug}`` in its prefix (the slug arrives in the request body), so it
# cannot share ``bw_router``'s prefix and is mounted separately.
app.include_router(bw_projects_router, prefix="/api")
# `/.well-known/ariadne-config` lives at the app root, not under /api.
# Unauthenticated by construction — a client that can't auth yet must
# be able to read how to auth.
app.include_router(discovery_router)
