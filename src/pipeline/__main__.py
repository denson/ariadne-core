"""Entry point: ariadne-core serve

Subcommands:
    serve — Start the REST API
    api   — Alias for serve
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


# Records emitted by the stdlib have a stable set of attributes; everything
# else on the LogRecord (handler-internal cruft) is excluded from JSON
# output to keep payloads predictable for log-aggregator schemas.
_LOG_RECORD_BUILTIN_ATTRS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class _JsonLogFormatter(logging.Formatter):
    """Minimal JSON line formatter — one record per line, stdlib-only.

    Output schema is intentionally narrow:

        {"timestamp": "ISO-8601 UTC", "level": "INFO", "logger": "<name>",
         "message": "<rendered message>", ...extras}

    ``...extras`` are the keys passed via ``logger.info(..., extra={...})``;
    the call sites already use ``extra=`` for structured fields (e.g.
    services.py 'dedup-miss-store'). Reserved record attributes (the
    stdlib's stable set) are stripped so a future stdlib addition does
    not leak into the schema.

    Custom Formatter rather than ``python-json-logger`` because the dep
    is not in pyproject.toml and the schema is small enough that adding
    a transitive dep is more cost than benefit (``rule clarity over rule
    sprawl`` — the rule for adding a dep is "the lib does something we
    can't quickly reproduce in stdlib"; that bar isn't met here).
    """

    def format(self, record: logging.LogRecord) -> str:
        # ISO-8601 UTC with microsecond precision. ``time.strftime`` is
        # not portable for ``%f`` on every libc (Windows in particular
        # rejects the format string), so build the string from a UTC
        # ``datetime`` directly.
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict[str, object] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        # Surface ``extra={...}`` kwargs and any other non-builtin
        # attribute the application attached to the record.
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_BUILTIN_ATTRS or key in payload:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


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


def _configure_logging(level: str, log_format: str = "text") -> None:
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

    ``log_format`` selects the formatter applied to BOTH handlers:

      * ``"json"`` -> :class:`_JsonLogFormatter`. One JSON object per
        line; ``timestamp`` / ``level`` / ``logger`` / ``message`` plus
        any ``extra={...}`` keys. Useful for Railway, Datadog, Loggly,
        ELK pipelines that consume structured records.
      * ``"text"`` (default) -> the human-readable
        ``%(asctime)s %(name)s %(levelname)s %(message)s`` shape used
        before ariadne--cw2.

    Format choice is orthogonal to the stream-split contract — both
    handlers always receive the same Formatter instance.
    """
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    formatter: logging.Formatter
    if log_format == "json":
        formatter = _JsonLogFormatter()
    else:
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

    _configure_logging(config.logging.level, config.logging.format)
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
