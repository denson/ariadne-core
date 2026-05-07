"""Entry point: ariadne-core serve

Subcommands:
    serve — Start the REST API
    api   — Alias for serve
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if command in ("--version", "-V"):
        # ariadne--4d1: read distribution version from package metadata
        # (pyproject.toml's [project] version is the source of truth).
        # PackageNotFoundError here would mean the install is broken
        # (e.g. an editable install where metadata never landed); let it
        # propagate so the user sees a real signal instead of a sentinel.
        from importlib.metadata import version as _pkg_version
        print(f"ariadne-core {_pkg_version('ariadne-core')}")
        sys.exit(0)

    if command in ("serve", "api"):
        _run_serve()
    else:
        print(f"Unknown command: {command}")
        print("Usage: ariadne-core serve")
        sys.exit(1)


def _configure_logging(level: str) -> None:
    """Configure root logger with a two-handler split: INFO/DEBUG -> stdout,
    WARNING+ -> stderr. This matches Railway's stream-based severity
    classification (stderr -> severity:'error') so application INFO logs
    don't drown real errors in severity-filtered dashboards.

    The stdout handler carries a level-based filter
    (``record.levelno < logging.WARNING``) so WARNING+ records do not
    double-emit on both streams. The stderr handler uses
    ``setLevel(logging.WARNING)`` instead of a filter -- the threshold
    gate is sufficient there.

    The ``force`` kwarg on ``logging.basicConfig`` is load-bearing:
    uvicorn or other imports may install a default
    ``StreamHandler(sys.stderr)`` before ``_run_serve()`` runs;
    without that kwarg set, ``basicConfig`` becomes a no-op and the
    stderr-everything behavior persists. Removing it is a silent
    regression -- ``tests/test_logging_config.py`` Probe 4 pins it via
    an AST walk on ``_configure_logging``'s source.

    Companion knob: ``_run_serve`` passes ``log_config=None`` to
    ``uvicorn.Config(...)``. Without that, uvicorn's ``__init__`` re-
    applies its own ``LOGGING_CONFIG`` AFTER this helper runs, which
    flips ``uvicorn`` and ``uvicorn.access`` to ``propagate=False`` with
    own handlers (``uvicorn`` -> stderr, ``uvicorn.access`` -> stdout)
    -- and the most user-visible Railway noise (uvicorn lifecycle INFO
    banners) lands on stderr again. ``log_config=None`` keeps the three
    uvicorn loggers on Python defaults so they inherit this root split.
    Pinned by Probe 5 in the same test file. See the comment block above
    the ``uvicorn.Config(...)`` call for the full source-citation.

    Both handlers share a single Formatter; the format string is the
    same one the previous single-stream ``basicConfig`` used. Honoring
    ``config.logging.format = "json"`` is a separate ticket.
    """
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(resolved_level)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    logging.basicConfig(
        level=resolved_level,
        handlers=[stdout_handler, stderr_handler],
        force=True,
    )


def _run_serve() -> None:
    """Start the REST API."""
    import asyncio

    import uvicorn

    from pipeline.config import load_config

    config = load_config()

    _configure_logging(config.logging.level)
    logger = logging.getLogger("ariadne")

    api_port = int(config.api.port) if isinstance(config.api.port, str) else config.api.port

    logger.info("Starting REST API on :%d", api_port)

    # ariadne--90e: ``log_config=None`` is load-bearing for the stream-split
    # contract. ``uvicorn.Config.__init__`` calls ``self.configure_logging()``
    # at construction (uvicorn 0.35.0 ``config.py:275``); when ``log_config`` is
    # any value other than ``None``, that method calls
    # ``logging.config.dictConfig(LOGGING_CONFIG)`` (uvicorn 0.35.0
    # ``config.py:362-367``), which installs uvicorn's own handlers on the
    # ``uvicorn`` and ``uvicorn.access`` loggers and flips them to
    # ``propagate=False``. Those handlers route ``uvicorn``-INFO banners to
    # stderr (uvicorn ``LOGGING_CONFIG``'s ``"default"`` handler binds
    # ``ext://sys.stderr``) — re-introducing the misclassification
    # ``_configure_logging`` exists to fix.
    #
    # Setting ``log_config=None`` short-circuits that branch (uvicorn 0.35.0
    # ``config.py:362``: ``if self.log_config is not None:``); ``uvicorn`` and
    # ``uvicorn.access`` then keep their Python defaults — no own handlers,
    # ``propagate=True`` — and inherit the root split installed by
    # ``_configure_logging`` above. Lifecycle banners ride to stdout via the
    # root stdout handler; access lines do too.
    #
    # Side effect: uvicorn's ``AccessFormatter`` (``"%(client_addr)s - "``
    # ...``%(status_code)s``) is no longer in play; access lines now use the
    # root formatter applied in ``_configure_logging`` and uvicorn's raw
    # access-log call format
    # (``'%s - "%s %s HTTP/%s" %d'``). The status-code colorization and
    # trailing ``OK`` text are gone; the line content is preserved. This is
    # intentional and documented; see the same-named comment block above
    # ``_configure_logging``.
    #
    # Healthcheck-noise follow-up (post-Batch-H, ariadne--<future>): the design
    # space for that fix is preserved — filter-on-record (``addFilter``) on
    # ``logging.getLogger("uvicorn.access")`` works regardless of log_config,
    # and ``access_log=False`` on this Config still works because uvicorn
    # 0.35.0 ``config.py:393-395`` clears access handlers + propagate
    # unconditionally of log_config. A custom LOGGING_CONFIG dict approach
    # would require reverting ``log_config=None`` at that time. Pinned by
    # ``tests/test_logging_config.py`` Probes 5 + 6.
    server_config = uvicorn.Config(
        "pipeline.api.app:app",
        host=config.api.host,
        port=api_port,
        log_level=config.logging.level,
        log_config=None,
    )
    server = uvicorn.Server(server_config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
