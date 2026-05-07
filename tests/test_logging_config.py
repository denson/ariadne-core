"""Probes for ``pipeline.__main__._configure_logging`` and the
``log_config=None`` knob the helper depends on.

These pin the stdout/stderr split that landed in ariadne--90e: INFO+DEBUG
records go to stdout, WARNING+ records go to stderr. The split matches
Railway's stream-based severity classification, so application INFO logs
do not drown real errors in severity-filtered dashboards.

Probe 4 is a static-source AST guard against silent removal of
``force=True`` on the ``logging.basicConfig`` call. The earlier
substring-only shape of this probe was decorative -- the helper's
docstring discussed ``force=True`` enough times that the substring
check passed even when the actual kwarg was deleted from the call.
The AST walk pins the actual kwarg on the actual call.

Probes 5 and 6 pin the ``log_config=None`` companion knob in
``_run_serve``: under ``log_config=None``, uvicorn's three loggers
(``uvicorn``, ``uvicorn.access``, ``uvicorn.error``) keep Python
defaults (no own handler, ``propagate=True``) and inherit the root
split. Probe 6 additionally pins that the design space for the
post-Batch-H healthcheck-noise follow-up is preserved -- specifically,
that adding a record-level filter to ``uvicorn.access`` still
suppresses lines as expected under ``log_config=None``.
"""

from __future__ import annotations

import ast
import inspect
import logging
import sys

import pytest
import uvicorn

from pipeline.__main__ import _configure_logging


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Each probe needs a clean root-handlers slate, plus restoration of
    the three uvicorn loggers' state.

    Logging state is process-global; without this fixture, probes leak
    handlers and propagate flags into each other and into the rest of
    the suite.
    """
    saved_root_handlers = logging.root.handlers[:]
    saved_root_level = logging.root.level

    uvicorn_logger_names = ("uvicorn", "uvicorn.access", "uvicorn.error")
    saved_uvicorn = {}
    for name in uvicorn_logger_names:
        lg = logging.getLogger(name)
        saved_uvicorn[name] = (
            lg.handlers[:],
            lg.propagate,
            lg.level,
            lg.filters[:],
        )

    try:
        yield
    finally:
        logging.root.handlers[:] = saved_root_handlers
        logging.root.setLevel(saved_root_level)
        for name, (handlers, propagate, level, filters) in saved_uvicorn.items():
            lg = logging.getLogger(name)
            lg.handlers[:] = handlers
            lg.propagate = propagate
            lg.setLevel(level)
            lg.filters[:] = filters


def test_configure_logging_installs_two_handlers_split_by_stream():
    """Probe 1 -- happy path: exactly two handlers, one per stream, with
    the stderr handler gated to WARNING and the stdout handler carrying
    a level-based filter."""
    _configure_logging("info")

    handlers = logging.root.handlers
    assert len(handlers) == 2, (
        f"expected exactly 2 handlers; got {len(handlers)}: {handlers!r}"
    )

    streams = [getattr(h, "stream", None) for h in handlers]
    assert streams.count(sys.stdout) == 1, (
        f"expected exactly one stdout handler; streams={streams!r}"
    )
    assert streams.count(sys.stderr) == 1, (
        f"expected exactly one stderr handler; streams={streams!r}"
    )

    stdout_handler = next(h for h in handlers if h.stream is sys.stdout)
    stderr_handler = next(h for h in handlers if h.stream is sys.stderr)

    assert stderr_handler.level == logging.WARNING, (
        f"stderr handler level should be WARNING; got {stderr_handler.level}"
    )

    # The stdout handler must carry a filter that drops WARNING+ records,
    # otherwise WARNING records double-emit on both streams.
    assert stdout_handler.filters, (
        "stdout handler must carry a filter dropping WARNING+ records"
    )

    # Synthesize a WARNING and an INFO record and confirm the filter
    # accepts INFO and rejects WARNING. ``addFilter`` may be given either
    # a callable (as in this implementation) or an object exposing
    # ``.filter`` -- handle both shapes via ``Handler.filter()`` which
    # delegates correctly.
    warning_record = logging.LogRecord(
        name="probe",
        level=logging.WARNING,
        pathname=__file__,
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    info_record = logging.LogRecord(
        name="probe",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    assert not stdout_handler.filter(warning_record), (
        "stdout handler must REJECT WARNING records"
    )
    assert stdout_handler.filter(info_record), (
        "stdout handler must ACCEPT INFO records"
    )


def test_info_routes_to_stdout_error_routes_to_stderr(capsys):
    """Probe 2 -- behavioral: INFO emits on stdout only; ERROR emits on
    stderr only. ``capsys`` captures the underlying file descriptors,
    which is what ``StreamHandler`` writes through.
    """
    _configure_logging("info")

    log = logging.getLogger("test.probe.routing")
    # Ensure propagation reaches the root handlers (default True, but pin it).
    log.propagate = True
    log.setLevel(logging.DEBUG)

    log.info("INFO_LINE_PROBE2")
    log.error("ERROR_LINE_PROBE2")

    # Force buffered stream handlers to flush before reading capsys.
    for handler in logging.root.handlers:
        handler.flush()

    captured = capsys.readouterr()

    assert "INFO_LINE_PROBE2" in captured.out, (
        f"INFO_LINE_PROBE2 should appear in stdout; out={captured.out!r}"
    )
    assert "INFO_LINE_PROBE2" not in captured.err, (
        f"INFO_LINE_PROBE2 must NOT appear in stderr; err={captured.err!r}"
    )

    assert "ERROR_LINE_PROBE2" in captured.err, (
        f"ERROR_LINE_PROBE2 should appear in stderr; err={captured.err!r}"
    )
    assert "ERROR_LINE_PROBE2" not in captured.out, (
        f"ERROR_LINE_PROBE2 must NOT appear in stdout; out={captured.out!r}"
    )


def test_force_true_defeats_pre_existing_handler():
    """Probe 3 -- ``force=True`` evicts pre-existing handlers. This pins
    the load-bearing claim: without ``force=True``, a handler installed
    by uvicorn (or any import) before ``_run_serve()`` runs would
    survive, ``basicConfig`` would no-op, and the stderr-everything
    regression returns silently.
    """
    sentinel = logging.StreamHandler(sys.stderr)
    logging.root.addHandler(sentinel)
    assert sentinel in logging.root.handlers, "fixture pre-condition broken"

    _configure_logging("info")

    assert sentinel not in logging.root.handlers, (
        "force=True should have evicted the pre-existing handler; "
        f"handlers={logging.root.handlers!r}"
    )
    assert len(logging.root.handlers) == 2, (
        f"expected exactly 2 handlers after force=True reset; "
        f"got {len(logging.root.handlers)}: {logging.root.handlers!r}"
    )


def test_configure_logging_source_pins_force_true_via_ast():
    """Probe 4 -- AST guard: walk ``_configure_logging``'s source for the
    actual ``logging.basicConfig`` Call node and confirm it carries a
    ``force=True`` keyword. Pins the actual call, not docstring mentions.

    The earlier shape of this probe was a substring check
    (``assert "force=True" in inspect.getsource(...)``). VERA flagged it
    decorative: the helper's docstring discussed ``force=True`` three
    times, so the substring check passed even when the kwarg was
    deleted from the actual call. Future readers should NOT replace
    this with a substring check; the AST walk is the correct shape.
    """
    src = inspect.getsource(_configure_logging)
    tree = ast.parse(src)
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef), (
        f"expected the source to start with the def; got {type(fn).__name__}"
    )

    # Find every ``Call`` node whose target resolves to ``basicConfig``
    # (either as ``logging.basicConfig(...)`` or a bare ``basicConfig(...)``).
    matching_calls = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "basicConfig":
            matching_calls.append(node)
        elif isinstance(func, ast.Name) and func.id == "basicConfig":
            matching_calls.append(node)

    assert matching_calls, (
        "_configure_logging must call logging.basicConfig at least once; "
        f"found none in source"
    )

    # At least one of those calls must have ``force=True`` as a kwarg.
    have_force_true = False
    for call in matching_calls:
        for kw in call.keywords:
            if (
                kw.arg == "force"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                have_force_true = True
                break
        if have_force_true:
            break

    assert have_force_true, (
        "_configure_logging's basicConfig call must include force=True as a "
        "keyword argument with the literal value True. Removing it silently "
        "regresses ariadne--90e: a default StreamHandler(sys.stderr) installed "
        "by uvicorn or any other import before _run_serve() runs would survive, "
        "basicConfig would no-op, and the stderr-everything behavior returns. "
        "(See _configure_logging's docstring; this probe replaces the earlier "
        "substring-based shape that VERA flagged decorative.)"
    )


def test_uvicorn_lifecycle_loggers_route_through_root():
    """Probe 5 -- ``log_config=None`` keeps uvicorn's three loggers
    (``uvicorn``, ``uvicorn.access``, ``uvicorn.error``) on Python
    defaults: no own handlers, ``propagate=True``. Without this knob,
    ``uvicorn.Config.__init__`` calls ``self.configure_logging()`` which
    applies ``LOGGING_CONFIG`` and installs uvicorn's own handlers
    (``uvicorn`` -> stderr, ``uvicorn.access`` -> stdout) with
    ``propagate=False`` -- and uvicorn lifecycle INFO banners ride to
    stderr, undoing the stream split.

    Empirical anchor: uvicorn 0.35.0 ``config.py:362``
    (``if self.log_config is not None:``) gates the dictConfig branch.
    """
    _configure_logging("info")

    async def _noop_app(scope, receive, send):
        return None

    server_config = uvicorn.Config(_noop_app, log_config=None)
    assert server_config is not None  # construction triggers configure_logging

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        assert lg.propagate is True, (
            f"{name} should keep propagate=True under log_config=None; "
            f"got propagate={lg.propagate}"
        )
        assert len(lg.handlers) == 0, (
            f"{name} should have no own handlers under log_config=None; "
            f"got handlers={lg.handlers!r}"
        )


def test_uvicorn_lifecycle_loggers_emit_through_root_split(capsys):
    """Probe 5b -- behavioral companion of Probe 5: emit a synthetic INFO
    record on each of the three uvicorn loggers and confirm they land
    on stdout (via the root stdout handler installed by
    ``_configure_logging``), not stderr. This pins that the design
    contract works end-to-end, not just at the propagate/handlers
    metadata level.
    """
    _configure_logging("info")

    async def _noop_app(scope, receive, send):
        return None

    _ = uvicorn.Config(_noop_app, log_config=None)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        # uvicorn.Config sets these to log_level (INFO by default) at
        # config.py:385-392; pin DEBUG here for clarity.
        lg.setLevel(logging.DEBUG)
        lg.info("UVICORN_INFO_PROBE5B_%s", name.replace(".", "_"))

    for handler in logging.root.handlers:
        handler.flush()

    captured = capsys.readouterr()

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        marker = f"UVICORN_INFO_PROBE5B_{name.replace('.', '_')}"
        assert marker in captured.out, (
            f"{name} INFO line should appear on stdout under log_config=None; "
            f"out={captured.out!r}"
        )
        assert marker not in captured.err, (
            f"{name} INFO line must NOT appear on stderr under log_config=None; "
            f"err={captured.err!r}"
        )


def test_uvicorn_access_filter_chain_still_mountable(capsys):
    """Probe 6 -- the post-Batch-H healthcheck-noise follow-up's
    design-space approach (a) is preserved: under ``log_config=None``,
    a record-level filter added to ``logging.getLogger("uvicorn.access")``
    via ``addFilter`` still suppresses access-log records as expected.

    This is the empirical anchor for the comment in ``_run_serve`` that
    says approach (a) survives ``log_config=None``. Without this probe,
    a future maintainer could revert ``log_config=None`` thinking it
    breaks the follow-up, when in fact filter-on-record works
    independently of the LOGGING_CONFIG branch.
    """
    _configure_logging("info")

    async def _noop_app(scope, receive, send):
        return None

    _ = uvicorn.Config(_noop_app, log_config=None)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.DEBUG)

    # Drop-everything filter -- the most aggressive shape of approach (a).
    # A real follow-up would filter on /healthz substring; the principle
    # is the same: addFilter applies at logger level, independent of
    # log_config. ``Filter`` returning False drops the record.
    access_logger.addFilter(lambda record: False)

    # Emit a synthetic access record matching uvicorn's raw access-log
    # call shape (config-time logger, before format string is applied
    # by uvicorn's AccessFormatter -- which is absent under
    # log_config=None).
    access_logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1",
        "GET",
        "/healthz",
        "1.1",
        200,
    )

    for handler in logging.root.handlers:
        handler.flush()

    captured = capsys.readouterr()

    # The drop-everything filter should suppress on both streams.
    assert "/healthz" not in captured.out, (
        "drop-everything filter on uvicorn.access should suppress on stdout; "
        f"out={captured.out!r}"
    )
    assert "/healthz" not in captured.err, (
        "drop-everything filter on uvicorn.access should suppress on stderr; "
        f"err={captured.err!r}"
    )


def test_run_serve_source_pins_log_config_none_via_ast():
    """Probe 7 -- symmetric AST guard for ``log_config=None`` in
    ``_run_serve``'s ``uvicorn.Config(...)`` call. Same shape as Probe 4's
    ``force=True`` guard -- patterns the same lesson onto the companion
    load-bearing knob.

    The substring shape would be decorative: ``__main__.py`` mentions
    ``log_config=None`` in docstrings + comment blocks ~10 times, so a
    substring check survives silent removal of the actual kwarg from the
    call site. AST-walk pins the kwarg in the actual ``Call`` node, not
    in prose.

    If a future change silently removes ``log_config=None`` from the
    ``uvicorn.Config(...)`` call, this probe fails -- preventing the
    uvicorn-internal-INFO-on-stderr regression from re-emerging
    unnoticed.
    """
    from pipeline import __main__ as main_module

    source = inspect.getsource(main_module._run_serve)
    tree = ast.parse(source)

    # Walk for Call nodes whose func resolves to uvicorn.Config (Attribute
    # chain: Attribute(value=Name(id='uvicorn'), attr='Config')).
    config_calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Config"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "uvicorn"
        ):
            config_calls.append(node)

    assert len(config_calls) >= 1, (
        f"_run_serve must contain at least one uvicorn.Config(...) call; "
        f"AST walk found {len(config_calls)}."
    )

    # At least one of those calls must carry log_config=None as a kwarg
    # (literal Constant(None), not Name('None') or any other shape).
    for call in config_calls:
        for kw in call.keywords:
            if (
                kw.arg == "log_config"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is None
            ):
                return  # Pinned.

    raise AssertionError(
        "uvicorn.Config(...) in _run_serve must carry log_config=None as a "
        "kwarg (literal None). AST walk found uvicorn.Config call(s) but no "
        "log_config=None kwarg. This pins the load-bearing knob that "
        "delegates uvicorn-internal loggers to root inheritance -- without "
        "it, uvicorn.Config.__init__ re-applies LOGGING_CONFIG and undoes "
        "the stream split. See the comment block above the uvicorn.Config "
        "call in __main__.py for the full explanation."
    )
