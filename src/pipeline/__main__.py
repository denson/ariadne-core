"""Entry point: ariadne-core serve

Subcommands:
    serve — Start the REST API
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
    """Start the REST API."""
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

    logger.info("Starting REST API on :%d", api_port)

    server_config = uvicorn.Config(
        "pipeline.api.app:app",
        host=config.api.host,
        port=api_port,
        log_level=config.logging.level,
    )
    server = uvicorn.Server(server_config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
