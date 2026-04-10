"""Entry point: ariadne-core serve

Subcommands:
    serve — Start the MCP server and REST API
    api   — Alias for serve
"""

from __future__ import annotations

import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if command in ("serve", "api"):
        _run_serve()
    else:
        print(f"Unknown command: {command}")
        print("Usage: ariadne-core serve")
        sys.exit(1)


def _run_serve() -> None:
    """Start the MCP server and REST API.

    If api.port and api.mcp_port are the same (e.g., Railway where only one
    port is available), mounts the MCP handler inside the FastAPI app and
    runs a single uvicorn server.

    If they differ (local dev default: 8000 + 8081), runs two separate
    uvicorn servers concurrently.
    """
    import asyncio
    import logging

    import uvicorn

    from pipeline.config import load_config

    config = load_config()

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("ariadne")

    api_port = int(config.api.port) if isinstance(config.api.port, str) else config.api.port
    mcp_port = int(config.api.mcp_port) if isinstance(config.api.mcp_port, str) else config.api.mcp_port

    if api_port == mcp_port:
        # Single-port mode: add MCP route to the FastAPI app and manage
        # the MCP session lifecycle inside FastAPI's lifespan.
        logger.info("Single-port mode: REST API + MCP on :%d", api_port)

        from pipeline.api.app import app as fastapi_app, lifespan as original_lifespan
        from pipeline.mcp_server import app as mcp_app

        # Build the MCP Starlette sub-app (has its own lifespan for session manager)
        mcp_starlette = mcp_app.streamable_http_app()

        # Wrap FastAPI's lifespan to also run the MCP session manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def combined_lifespan(app):
            async with original_lifespan(app):
                async with mcp_app.session_manager.run():
                    yield

        fastapi_app.router.lifespan_context = combined_lifespan

        # Mount the MCP Starlette app (its lifespan won't run since we
        # manage the session manager above)
        fastapi_app.mount("", mcp_starlette)

        server_config = uvicorn.Config(
            fastapi_app,
            host=config.api.host,
            port=api_port,
            log_level=config.logging.level,
        )
        server = uvicorn.Server(server_config)
        asyncio.run(server.serve())
    else:
        # Dual-port mode: separate servers (local dev)
        async def _serve() -> None:
            rest_config = uvicorn.Config(
                "pipeline.api.app:app",
                host=config.api.host,
                port=api_port,
                log_level=config.logging.level,
            )
            rest_server = uvicorn.Server(rest_config)

            from pipeline.mcp_server import app as mcp_app

            mcp_starlette = mcp_app.streamable_http_app()
            mcp_config = uvicorn.Config(
                mcp_starlette,
                host=config.api.host,
                port=mcp_port,
                log_level=config.logging.level,
            )
            mcp_server = uvicorn.Server(mcp_config)

            logger.info(
                "Starting REST API on :%d and MCP server on :%d",
                api_port,
                mcp_port,
            )

            await asyncio.gather(
                rest_server.serve(),
                mcp_server.serve(),
            )

        asyncio.run(_serve())


if __name__ == "__main__":
    main()
