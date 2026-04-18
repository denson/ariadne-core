"""FastAPI application setup.

Creates the FastAPI app with CORS, lifespan, and route mounting.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pipeline.api.auth import get_key_store, set_require_auth
from pipeline.api.routes import router
from pipeline.config import load_config
from pipeline.embedding.embedder import EmbeddingConfig
from pipeline.services import configure_embedding, configure_image_enrichment, configure_stores
from pipeline.stores import create_stores, close_pool

logger = logging.getLogger("ariadne.app")


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

    # Auth enforcement
    api_key = os.environ.get("ARIADNE_API_KEY")
    if api_key:
        get_key_store().create_key("default", api_key)
        set_require_auth(True)
        logger.info("API key authentication is REQUIRED (key seeded from env)")
    elif config.api.require_auth:
        logger.info("API key authentication is REQUIRED")
        set_require_auth(True)
    else:
        set_require_auth(False)

    yield
    # Shutdown: close connections
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
    return JSONResponse(
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
