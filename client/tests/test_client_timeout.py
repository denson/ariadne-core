"""Tests for BL-18 — client ingest timeout behavior.

Without a floor, `AriadneClient(timeout=60)` applied 60s to the ingest POST
even though embedding a large doc routinely takes several minutes. The fix
lands a `DEFAULT_INGEST_TIMEOUT = 600` floor in `_create_document`, plus a
per-call `timeout=` kwarg on the three ingest methods.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ariadne_core_client import client as client_module
from ariadne_core_client.client import DEFAULT_INGEST_TIMEOUT, AriadneClient


def _canned_document_response(document_id: str = "doc-1") -> dict:
    return {
        "document_id": document_id,
        "source_file": "test.txt",
        "chunks_count": 1,
        "store_status": "stored",
        "warnings": [],
    }


def _canned_upload_response(path: str = "/tmp/test.txt") -> dict:
    return {"path": path}


def test_default_ingest_timeout_is_six_hundred():
    """The module-level constant is 600s — the floor all ingest POSTs use."""
    assert DEFAULT_INGEST_TIMEOUT == 600


def test_create_document_floors_timeout_at_default(captured_http, tmp_path: Path):
    """Even with a low instance timeout, the ingest POST uses DEFAULT_INGEST_TIMEOUT."""
    captured_http.set_upload_response(_canned_upload_response())
    captured_http.set_json_response(_canned_document_response())

    fp = tmp_path / "hello.txt"
    fp.write_text("hello world")

    c = AriadneClient(
        host="http://localhost",
        timeout=30,  # intentionally low — should be floored up to 600
    )
    c.ingest_file(str(fp), collection="t")

    call = captured_http.last_json_call()
    assert call["timeout"] == DEFAULT_INGEST_TIMEOUT, (
        f"expected POST /api/documents timeout to be floored at "
        f"{DEFAULT_INGEST_TIMEOUT}s, got {call['timeout']}"
    )
    assert call["url"].endswith("/api/documents")


def test_create_document_keeps_timeout_above_floor(captured_http, tmp_path: Path):
    """If instance timeout > DEFAULT_INGEST_TIMEOUT, use the instance value (max-wins)."""
    captured_http.set_upload_response(_canned_upload_response())
    captured_http.set_json_response(_canned_document_response())

    fp = tmp_path / "hello.txt"
    fp.write_text("hello world")

    c = AriadneClient(
        host="http://localhost",
        timeout=900,  # higher than the 600 floor — should win
    )
    c.ingest_file(str(fp), collection="t")

    assert captured_http.last_json_call()["timeout"] == 900


def test_ingest_file_respects_per_call_timeout_override(captured_http, tmp_path: Path):
    """Per-call timeout=N on ingest_file propagates to the POST, overriding the floor."""
    captured_http.set_upload_response(_canned_upload_response())
    captured_http.set_json_response(_canned_document_response())

    fp = tmp_path / "tiny.txt"
    fp.write_text("tiny")

    c = AriadneClient(
        host="http://localhost",
        timeout=60,
    )
    # Agent knows this file is small — dropping the timeout well below the floor.
    c.ingest_file(str(fp), collection="t", timeout=15)

    assert captured_http.last_json_call()["timeout"] == 15


def test_ingest_url_respects_per_call_timeout_override(captured_http):
    """Per-call timeout= on ingest_url overrides the floor the same way."""
    captured_http.set_json_response(_canned_document_response())

    c = AriadneClient(
        host="http://localhost",
        timeout=60,
    )
    c.ingest_url("https://example.com/doc.pdf", collection="t", timeout=1800)

    call = captured_http.last_json_call()
    assert call["timeout"] == 1800
    assert call["url"].endswith("/api/documents")


def test_ingest_bytes_respects_per_call_timeout_override(captured_http):
    """Per-call timeout= on ingest_bytes overrides the floor the same way."""
    captured_http.set_upload_response(_canned_upload_response())
    captured_http.set_json_response(_canned_document_response())

    c = AriadneClient(
        host="http://localhost",
        timeout=60,
    )
    c.ingest_bytes(b"hello", "hello.txt", collection="t", timeout=45)

    assert captured_http.last_json_call()["timeout"] == 45


def test_upload_timeout_floor_unchanged(captured_http, tmp_path: Path):
    """The multipart _upload floor of max(self.timeout, 120) is preserved — out of scope for BL-18."""
    captured_http.set_upload_response(_canned_upload_response())
    captured_http.set_json_response(_canned_document_response())

    fp = tmp_path / "hello.txt"
    fp.write_text("hello world")

    c = AriadneClient(
        host="http://localhost",
        timeout=30,
    )
    c.ingest_file(str(fp), collection="t")

    upload = captured_http.last_upload_call()
    assert upload["timeout"] == 120, (
        "BL-18 must not touch the _upload floor — it stays at max(self.timeout, 120)"
    )
