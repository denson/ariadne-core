"""Tests for BL-24 — JSON responses must declare charset=utf-8.

Windows clients (PowerShell Invoke-WebRequest etc.) default to cp1252 when
the server omits the charset, producing mojibake from correct-UTF-8 bytes.
See dave_and_bob_communication/BL24_SCHEMA_MOJIBAKE_ROOT_CAUSE.md.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api.app import app


def test_health_response_declares_utf8_charset():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text
    assert "charset=utf-8" in resp.headers["content-type"]
