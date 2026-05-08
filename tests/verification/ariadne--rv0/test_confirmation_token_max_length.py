"""Probes for ariadne--rv0 — DocumentRequest.confirmation_token max_length=4096.

Two probes per the ticket Verification section:

    A) confirmation_token of length 4097 → 422 with validation error naming
       the field + max_length (rejected at validation; never reaches HMAC).
    B) confirmation_token of length 4096 → reaches HMAC validation path
       (which then rejects as INVALID since it's not a real token, but
       the path was reached — i.e. error type is HMAC-related, not
       validation-length-related).

Both probes use TestClient + override_auth (same pattern as
tests/verification/ariadne--m5e/test_routes_confirmation.py).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.app import app as production_app
from pipeline.api.routes import router
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# ── Fixtures + helpers (mirrors m5e test scaffolding) ─────────────────────────


_FIXTURE_TXT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "sample.txt"
)


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


def _fake_extraction_result(source_file: str) -> ExtractionResult:
    return ExtractionResult(
        document_id="00000000-0000-0000-0000-000000000000",
        source_file=source_file,
        markdown="# fake\n\nhello\n",
        title="fake",
        file_type="txt",
        pages=None,
        engine="markitdown-mock",
        processing_time_ms=1,
        output_tokens_estimate=10,
        token_savings_ratio=None,
        processing_chain=[{"step": "extraction", "tool": "markitdown-mock"}],
        warnings=[],
        errors=[],
    )


def _make_extractor_mock() -> MagicMock:
    mock = MagicMock()
    mock.extract_from_bytes.side_effect = (
        lambda content, source_file: _fake_extraction_result(source_file)
    )
    return mock


def _install_clean_state(monkeypatch) -> MagicMock:
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    monkeypatch.setattr(services, "_ingest_config", IngestConfig())
    extractor = _make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", extractor)
    return extractor


def _build_app() -> FastAPI:
    app = FastAPI()
    handler = production_app.exception_handlers[Exception]
    app.add_exception_handler(Exception, handler)
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


# ── Probe A: 4097-char token → 422 validation error naming the field ───────


def test_a_token_above_max_length_returns_422(monkeypatch, tmp_path):
    """A confirmation_token of length 4097 is rejected at Pydantic
    validation (HTTP 422). The error must name the field
    ``confirmation_token`` and indicate the max_length constraint, so a
    caller debugging from the error body can fix the call site without
    reading the SPEC."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "rv0_a.txt"
    big.write_bytes(b"x" * 16)

    over_limit_token = "a" * 4097

    client = TestClient(_build_app())
    resp = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "rv0_a",
            "confirmation_token": over_limit_token,
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # FastAPI wraps Pydantic validation errors in {"detail": [...]}; each
    # entry has a ``loc`` (path to the field) and a ``msg`` describing
    # the failure. We assert the error names confirmation_token and
    # references the length / max_length constraint.
    detail = body.get("detail")
    assert isinstance(detail, list) and detail, body
    matching = [
        e for e in detail
        if "confirmation_token" in (e.get("loc") or [])
    ]
    assert matching, f"no detail entry mentions confirmation_token: {body}"
    # Pydantic v2 error messages for max_length use phrasing like
    # "String should have at most 4096 characters" (type ``string_too_long``).
    err = matching[0]
    err_type = err.get("type", "")
    err_msg = err.get("msg", "").lower()
    assert (
        "too_long" in err_type
        or "max_length" in err_msg
        or "at most 4096" in err_msg
        or "4096" in err_msg
    ), f"error doesn't reference max_length / 4096: {err}"


# ── Probe B: 4096-char token → reaches HMAC path (rejected as INVALID) ─────


def test_b_token_at_max_length_reaches_hmac_path(monkeypatch, tmp_path):
    """A confirmation_token of exactly length 4096 passes Pydantic
    validation and reaches the HMAC verification code path. The token
    is fabricated (not server-signed) so HMAC rejects it — but the
    rejection shape is HMAC-derived (a fresh confirmation_required 413
    with a server-issued token), NOT a Pydantic 422 validation error.

    This is the load-bearing distinction: at length 4097 the request
    dies at validation; at length 4096 it reaches the HMAC verifier.
    The test pins that boundary."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "rv0_b.txt"
    # Force the soft-cap path so the request ENGAGES the confirmation
    # flow (with no valid token, the server falls through to "issue a
    # fresh 413 with a fresh token"). Without exceeding the soft cap,
    # the server would never reach the token-validation logic at all.
    big.write_bytes(b"x" * 4096)

    at_limit_token = "a" * 4096

    client = TestClient(_build_app())
    resp = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "rv0_b",
            "ingest_config": {"max_source_bytes": 1024},
            "confirmation_token": at_limit_token,
        },
    )
    # NOT 422 — Pydantic validation passed. The fabricated token is
    # rejected by the HMAC verifier (treated as missing/invalid), so
    # the server emits a fresh confirmation_required 413.
    assert resp.status_code != 422, (
        f"length-4096 token should not trigger Pydantic validation 422; "
        f"body={resp.text}"
    )
    assert resp.status_code == 413, resp.text
    detail = resp.json().get("detail")
    assert isinstance(detail, dict), detail
    assert detail.get("code") == "confirmation_required"
    # Server issued its own fresh token (HMAC-signed), distinct from the
    # fabricated 4096-char one we sent.
    fresh = detail.get("confirmation_token")
    assert fresh and fresh != at_limit_token
