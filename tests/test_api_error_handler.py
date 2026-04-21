"""Tests for BL-21 — global exception handler shape.

The Phase 8 V2 run surfaced 11 × naked `HTTP 500 Internal Server Error` with
no body, forcing a Railway log pull to diagnose NUL-byte errors. The fix is
a global `@app.exception_handler(Exception)` in `pipeline.api.app` that
returns `{"detail": {"error_type", "message", "path", "method"}}` so the
client can see what actually broke.

These tests build a minimal FastAPI, attach the real handler registered on
the production app, and drive it with two routes: one that raises a generic
exception and one that raises HTTPException. The HTTPException path must be
unaffected — FastAPI's HTTPException handler runs before the generic one.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pipeline.api.app import app as real_app


def _build_app_with_real_handler() -> FastAPI:
    """Fresh FastAPI that reuses the production Exception handler.

    Pulling the handler off the real app tests the actual code in app.py,
    not a copy — if someone swaps the handler in app.py, these tests follow.
    """
    handler = real_app.exception_handlers[Exception]
    app = FastAPI()
    app.add_exception_handler(Exception, handler)

    @app.get("/boom")
    def _boom():
        raise ValueError("bang — pretend this is a psycopg.DataError about NUL bytes")

    @app.get("/http-error")
    def _http_error():
        raise HTTPException(status_code=422, detail="validation failed")

    return app


def test_unhandled_exception_returns_structured_500():
    """A route raising a non-HTTPException returns detail.{error_type, message, path, method}."""
    app = _build_app_with_real_handler()
    # raise_server_exceptions=False so TestClient returns the handler's response
    # instead of re-raising the underlying ValueError.
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/boom")

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert "detail" in body, body
    detail = body["detail"]
    assert detail["error_type"] == "ValueError", detail
    assert "bang" in detail["message"], detail
    assert "NUL bytes" in detail["message"], detail
    assert detail["path"] == "/boom", detail
    assert detail["method"] == "GET", detail


def test_exception_message_is_truncated_at_2000_chars():
    """Massive error messages (e.g. pg psycopg bodies) are truncated to 2000 chars."""
    handler = real_app.exception_handlers[Exception]
    app = FastAPI()
    app.add_exception_handler(Exception, handler)

    huge = "x" * 5000

    @app.get("/huge")
    def _huge():
        raise RuntimeError(huge)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/huge")

    assert resp.status_code == 500
    msg = resp.json()["detail"]["message"]
    assert len(msg) == 2000, f"expected 2000 chars, got {len(msg)}"


def test_http_exception_is_not_affected_by_global_handler():
    """HTTPException raised in a route uses FastAPI's own handler, not the generic Exception one.

    If the generic handler clobbered HTTPException, existing routes that raise
    422/404/410/etc. would all turn into shape-changed 500s.
    """
    app = _build_app_with_real_handler()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/http-error")

    assert resp.status_code == 422, resp.text
    body = resp.json()
    # FastAPI's HTTPException handler returns {"detail": "validation failed"} — a string.
    # The generic handler would have returned a dict with error_type/message/path/method.
    assert body == {"detail": "validation failed"}, body


def test_existing_http_exception_routes_still_work_through_real_router():
    """End-to-end sanity: an existing route that raises HTTPException (auth required)
    still returns its pre-BL-21 shape via the real router, proving the generic handler
    didn't steal HTTPException responses from the production app."""
    from fastapi import FastAPI as _FastAPI
    from pipeline.api.routes import router

    # Build a fresh app that mirrors production — router + the same Exception handler.
    # Routes unconditionally require an Auth0 Bearer token (OAuth Pass 2); no toggle
    # needed — a request without a token must return 401.
    handler = real_app.exception_handlers[Exception]
    app = _FastAPI()
    app.add_exception_handler(Exception, handler)
    app.include_router(router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)

    # No Authorization header → require_user raises HTTPException(401). That must
    # NOT get reshaped into the generic handler's dict.
    resp = client.get("/api/documents")
    assert resp.status_code == 401, resp.text
    body = resp.json()
    # The auth error shape is a string detail ("missing_token"), not our generic dict.
    assert isinstance(body.get("detail"), str), body
