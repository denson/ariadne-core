"""FastAPI application setup.

Creates the FastAPI app with CORS, lifespan, and route mounting.
The app uses the same shared services (dedup store, vector store,
embedding client) as the MCP server.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pipeline.api.auth import get_key_store, set_require_auth
from pipeline.api.routes import router
from pipeline.config import load_config
from pipeline.embedding.embedder import EmbeddingConfig
from pipeline.mcp_server import configure_embedding, configure_stores
from pipeline.stores import create_stores, close_pool

logger = logging.getLogger("ariadne.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    config = load_config()
    dimensions = config.embedding.dimensions

    logger.info(
        "Starting with embedding model=%s dimensions=%d endpoint=%s [v2-gemini-fix]",
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


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Gate /mcp requests with the same API key auth as REST endpoints."""

    async def dispatch(self, request, call_next):
        from pipeline.api.auth import _require_auth, hash_api_key, _key_store

        if _require_auth and request.url.path.startswith("/mcp"):
            api_key = request.headers.get("x-api-key")
            if not api_key:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Missing API key. Provide X-API-Key header."},
                )
            stored = _key_store.find_by_hash(hash_api_key(api_key))
            if stored is None:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Invalid or revoked API key."},
                )
        return await call_next(request)


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

app.add_middleware(MCPAuthMiddleware)
app.include_router(router, prefix="/api")
