"""Probes for ariadne--cw2 — config.logging.format=json is honored.

Pre-cw2 the YAML field was declared but the ``_configure_logging`` helper
hardcoded the text format string, so flipping the YAML to ``"json"``
silently no-op'd. These probes pin both:

  A) Default / ``"text"`` path keeps the pre-cw2 format string. No
     surprise behavior change for deployments that didn't set the
     field or set it to ``text``.
  B) ``"json"`` flips both handlers to a JSON-emitting formatter; an
     INFO log line is parseable as JSON with a fixed schema.
  C) Stream-split contract from ariadne--90e is preserved under JSON:
     INFO -> stdout, WARNING -> stderr.
  D) ``extra={...}`` kwargs surface as top-level keys in the JSON payload.

The 90e contract probes (test_logging_config.py) continue to assert
the structural split independent of format choice.
"""
from __future__ import annotations

import io
import json
import logging
import sys

import pytest

from pipeline.__main__ import _configure_logging, _JsonLogFormatter


@pytest.fixture(autouse=True)
def _reset_root_logger():
    saved_root_handlers = logging.root.handlers[:]
    saved_root_level = logging.root.level
    try:
        yield
    finally:
        logging.root.handlers[:] = saved_root_handlers
        logging.root.setLevel(saved_root_level)


def test_default_text_format_is_unchanged(capsys):
    """Probe A — default/text format: handlers carry the pre-cw2 format
    string. Pinned so a future refactor that flips the default to JSON
    doesn't ship as a silent breaking change for log scrapers that
    expect the human-readable shape.
    """
    _configure_logging("info")
    log = logging.getLogger("test.cw2.text_default")
    log.propagate = True
    log.setLevel(logging.DEBUG)
    log.info("CW2_TEXT_PROBE")

    for h in logging.root.handlers:
        h.flush()
    captured = capsys.readouterr()
    assert "CW2_TEXT_PROBE" in captured.out
    # The text format prefixes ``asctime name levelname`` so the line
    # is NOT parseable as JSON — pin that explicitly so a future format
    # flip surfaces here.
    line = next(
        line for line in captured.out.splitlines() if "CW2_TEXT_PROBE" in line
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_json_format_emits_parseable_json(capsys):
    """Probe B — under format='json', each emitted record is a single
    JSON object on one line with the documented schema."""
    _configure_logging("info", "json")
    log = logging.getLogger("test.cw2.json_basic")
    log.propagate = True
    log.setLevel(logging.DEBUG)
    log.info("CW2_JSON_PROBE_BASIC")

    for h in logging.root.handlers:
        h.flush()
    captured = capsys.readouterr()
    candidates = [
        line for line in captured.out.splitlines() if "CW2_JSON_PROBE_BASIC" in line
    ]
    assert candidates, f"INFO line missing from stdout: {captured.out!r}"
    payload = json.loads(candidates[0])
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.cw2.json_basic"
    assert payload["message"] == "CW2_JSON_PROBE_BASIC"
    assert "timestamp" in payload


def test_json_format_preserves_stream_split(capsys):
    """Probe C — ariadne--90e's INFO->stdout / WARNING->stderr split
    is orthogonal to format choice. Without this pin, a future refactor
    of the JSON path could regress the split (e.g. by attaching the
    JSON formatter only to one handler)."""
    _configure_logging("info", "json")
    log = logging.getLogger("test.cw2.json_split")
    log.propagate = True
    log.setLevel(logging.DEBUG)
    log.info("CW2_JSON_INFO_LINE")
    log.error("CW2_JSON_ERROR_LINE")

    for h in logging.root.handlers:
        h.flush()
    captured = capsys.readouterr()
    assert "CW2_JSON_INFO_LINE" in captured.out
    assert "CW2_JSON_INFO_LINE" not in captured.err
    assert "CW2_JSON_ERROR_LINE" in captured.err
    assert "CW2_JSON_ERROR_LINE" not in captured.out

    # Both lines parse as JSON.
    info_line = next(
        line for line in captured.out.splitlines() if "CW2_JSON_INFO_LINE" in line
    )
    error_line = next(
        line for line in captured.err.splitlines() if "CW2_JSON_ERROR_LINE" in line
    )
    assert json.loads(info_line)["level"] == "INFO"
    assert json.loads(error_line)["level"] == "ERROR"


def test_json_format_surfaces_extra_kwargs(capsys):
    """Probe D — application code uses ``extra={...}`` to attach
    structured fields (e.g. dedup-miss-store telemetry). Those keys
    must surface as top-level fields in the JSON payload, not be
    swallowed by the formatter."""
    _configure_logging("info", "json")
    log = logging.getLogger("test.cw2.json_extra")
    log.propagate = True
    log.setLevel(logging.DEBUG)
    log.info(
        "extra-payload-marker",
        extra={"document_id": "doc-abc-123", "fingerprint_prefix": "deadbeef"},
    )

    for h in logging.root.handlers:
        h.flush()
    captured = capsys.readouterr()
    line = next(
        line for line in captured.out.splitlines() if "extra-payload-marker" in line
    )
    payload = json.loads(line)
    assert payload["document_id"] == "doc-abc-123"
    assert payload["fingerprint_prefix"] == "deadbeef"


def test_json_formatter_strips_unjson_safe_values():
    """Probe E — non-JSON-serializable extras are repr'd, not crashed.
    Pinned because a logger.info(..., extra={"obj": some_class_instance})
    call site must not blow up the entire log handler."""
    formatter = _JsonLogFormatter()
    record = logging.LogRecord(
        name="probe", level=logging.INFO, pathname=__file__, lineno=1,
        msg="x", args=(), exc_info=None,
    )

    class _NonSerializable:
        def __repr__(self) -> str:
            return "<sentinel-repr-value>"

    record.weird = _NonSerializable()  # type: ignore[attr-defined]
    out = formatter.format(record)
    payload = json.loads(out)
    assert payload["weird"] == "<sentinel-repr-value>"
