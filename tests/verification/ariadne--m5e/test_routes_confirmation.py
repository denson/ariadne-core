"""Server-side route probes for ariadne--m5e.

Maps to design-rev3.1 §4 probes (a)-(l):

  (a) Below soft cap → 200 (happy path; not regressed by m5e).
  (b) Between soft and hard, no token → 413 with structured body.
  (c) Re-submit with valid token within TTL → proceeds (200).
  (d) Tampered / mismatched / expired token → 413 with fresh token.
  (e) Multi-shot within TTL: same token re-used → both succeed.
  (f) Above hard cap → 422 with ``exceeds_hard_limit``.
  (g) HEAD failure / Content-Length missing → falls through; chunked-read
      accumulator-overrun produces 413 with ``size_precise=False`` token.
  (h) Strict-mode soft-cap breach → 422 with ``exceeds_soft_cap_strict``.
  (i) Token size-binding dropped: growth / shrinkage / hard-cap-still-fires.
  (j) Last-Modified RFC 7231 normalization to ISO-8601 UTC.
  (k) HEAD timeout default = 10s.
  (l) Legacy error-dict back-compat shape (no ``code`` key on legacy paths).

All probes use TestClient + override_auth.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api import confirmation
from pipeline.api.app import app as production_app
from pipeline.api.routes import router
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import ExtractionResult, MarkItDownExtractor
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# ── Fixtures + helpers ─────────────────────────────────────────────────────


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
        markdown="# fake\n\nhello world\n",
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


def _decode_token_payload(token: str) -> dict:
    payload_part, _ = token.split(".", 1)
    pad = "=" * ((4 - len(payload_part) % 4) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_part + pad)
    return json.loads(payload_bytes.decode("utf-8"))


# ── (a) Below soft cap → 200 ────────────────────────────────────────────────


def test_a_below_soft_cap_returns_200(monkeypatch):
    """Below soft cap, the happy path is unchanged from pre-m5e: 200,
    parsed Document body, no error fields."""
    _install_clean_state(monkeypatch)
    client = TestClient(_build_app())
    resp = client.post(
        "/api/documents",
        json={"uri": str(_FIXTURE_TXT), "collection": "m5e_a"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("error") is not True
    assert body.get("document_id")
    assert "code" not in body  # legacy success path has no code field


# ── (b) Soft cap breach → 413 with structured body ─────────────────────────


def test_b_soft_breach_returns_413_with_full_body(monkeypatch, tmp_path):
    """Synthetic 4 KB local file with per-request soft cap = 1024.
    Asserts every field in §2.6's response shape."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "soft_breach.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    resp = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_b",
            "ingest_config": {"max_source_bytes": 1024},
        },
    )
    assert resp.status_code == 413, resp.text
    detail = resp.json()["detail"]
    expected_fields = {
        "code",
        "message",
        "soft_cap",
        "hard_cap",
        "reported_size",
        "source",
        "content_type",
        "last_modified",
        "confirmation_token",
        "ttl_seconds",
    }
    assert expected_fields.issubset(detail.keys()), (
        f"missing fields: {expected_fields - set(detail.keys())}; "
        f"got keys: {sorted(detail.keys())}"
    )
    assert detail["code"] == "confirmation_required"
    assert detail["soft_cap"] == 1024
    assert detail["reported_size"] == 4096
    assert detail["confirmation_token"]
    assert isinstance(detail["ttl_seconds"], int) and detail["ttl_seconds"] > 0
    # Local file mime guess: sample fixture for .txt → "text/plain".
    assert detail["content_type"] == "text/plain"
    # Last-modified for a local file → ISO-8601 UTC.
    assert detail["last_modified"]
    assert "T" in detail["last_modified"]


# ── (c) Re-submit with valid token within TTL → 200 ────────────────────────


def test_c_token_resubmit_proceeds(monkeypatch, tmp_path):
    _install_clean_state(monkeypatch)
    big = tmp_path / "resubmit.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_c",
            "ingest_config": {"max_source_bytes": 1024},
        },
    )
    assert first.status_code == 413
    token = first.json()["detail"]["confirmation_token"]

    second = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_c",
            "ingest_config": {"max_source_bytes": 1024},
            "confirmation_token": token,
        },
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body.get("error") is not True
    assert body.get("document_id")
    assert "code" not in body  # no m5e error code on success


# ── (d) Tampered / URI-mismatch / expired tokens → 413 with fresh token ────


def test_d_tampered_token_returns_413_with_fresh(monkeypatch, tmp_path):
    _install_clean_state(monkeypatch)
    big = tmp_path / "tampered.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_d_tamp",
            "ingest_config": {"max_source_bytes": 1024},
        },
    )
    token = first.json()["detail"]["confirmation_token"]
    # Mutate one byte of the signature suffix.
    payload, sig = token.rsplit(".", 1)
    bad_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    tampered = f"{payload}.{bad_sig}"

    second = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_d_tamp",
            "ingest_config": {"max_source_bytes": 1024},
            "confirmation_token": tampered,
        },
    )
    assert second.status_code == 413
    fresh_token = second.json()["detail"]["confirmation_token"]
    assert fresh_token != tampered
    # The fresh token should validate (round-trip), unlike the tampered one.
    assert (
        confirmation.validate_token(fresh_token, source_uri=str(big))
        == confirmation.ValidationResult.VALID
    )
    # And the tampered one must NOT validate.
    assert (
        confirmation.validate_token(tampered, source_uri=str(big))
        == confirmation.ValidationResult.TAMPERED
    )


def test_d_uri_mismatch_returns_413_with_fresh(monkeypatch, tmp_path):
    _install_clean_state(monkeypatch)
    big_a = tmp_path / "uri_a.txt"
    big_a.write_bytes(b"x" * 4096)
    big_b = tmp_path / "uri_b.txt"
    big_b.write_bytes(b"y" * 4096)

    client = TestClient(_build_app())
    first = client.post(
        "/api/documents",
        json={
            "uri": str(big_a),
            "collection": "m5e_d_uri",
            "ingest_config": {"max_source_bytes": 1024},
        },
    )
    token_for_a = first.json()["detail"]["confirmation_token"]

    # Submit token issued for A against URI B.
    second = client.post(
        "/api/documents",
        json={
            "uri": str(big_b),
            "collection": "m5e_d_uri",
            "ingest_config": {"max_source_bytes": 1024},
            "confirmation_token": token_for_a,
        },
    )
    assert second.status_code == 413
    fresh = second.json()["detail"]["confirmation_token"]
    # Fresh token is for URI B (its payload should sign B).
    payload = _decode_token_payload(fresh)
    assert payload["uri"] == str(big_b)


def test_d_expired_token_returns_413_with_fresh(monkeypatch, tmp_path):
    _install_clean_state(monkeypatch)
    # Per design §2.3, ``confirmation_token_ttl_seconds`` is a server-
    # policy knob, not a per-request override. To exercise the expired-
    # token path, mutate the active singleton's TTL field directly;
    # monkeypatch auto-restores the original value at test teardown.
    # ``_install_clean_state`` already installed a fresh ``IngestConfig()``
    # on services._ingest_config, so this rebinds a field on that fresh
    # singleton and does not leak across tests.
    monkeypatch.setattr(
        services._ingest_config, "confirmation_token_ttl_seconds", 1
    )
    big = tmp_path / "expired.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_d_exp",
            "ingest_config": {"max_source_bytes": 1024},
        },
    )
    token = first.json()["detail"]["confirmation_token"]
    payload = _decode_token_payload(token)
    # Advance the confirmation module's clock past exp.
    monkeypatch.setattr(
        confirmation.time, "time", lambda: payload["exp"] + 1
    )

    second = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_d_exp",
            "ingest_config": {"max_source_bytes": 1024},
            "confirmation_token": token,
        },
    )
    assert second.status_code == 413
    fresh = second.json()["detail"]["confirmation_token"]
    assert fresh != token


# ── (e) Multi-shot within TTL ──────────────────────────────────────────────


def test_e_multi_shot_token_within_ttl(monkeypatch, tmp_path):
    """Token can be reused multiple times within TTL: nothing is
    invalidated on success."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "multi.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_e",
            "ingest_config": {"max_source_bytes": 1024},
        },
    )
    token = first.json()["detail"]["confirmation_token"]

    base_body = {
        "uri": str(big),
        "collection": "m5e_e",
        "ingest_config": {"max_source_bytes": 1024},
        "confirmation_token": token,
    }
    r1 = client.post("/api/documents", json=base_body)
    r2 = client.post("/api/documents", json={**base_body, "force": True})
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text


# ── (f) Above hard cap → 422 ───────────────────────────────────────────────


def test_f_above_hard_cap_returns_422_no_token(monkeypatch, tmp_path):
    _install_clean_state(monkeypatch)
    big = tmp_path / "hard.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    resp = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_f",
            "ingest_config": {
                "max_source_bytes": 512,
                "max_source_bytes_hard": 1024,
            },
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "exceeds_hard_limit"
    assert "confirmation_token" not in detail
    # exceeds_hard_limit shape: no soft_cap field per §2.6 distinguishability.
    assert "soft_cap" not in detail
    assert detail["reported_size"] == 4096
    assert detail["hard_cap"] == 1024


# ── (g) HEAD failure / no Content-Length → fall through; chunked overrun ──


def _http_resp_with_body(body: bytes, *, content_length=True):
    chunks = iter([body, b""])
    fake = MagicMock()
    fake.headers = (
        {"Content-Length": str(len(body))} if content_length else {}
    )
    fake.read = MagicMock(side_effect=lambda n: next(chunks))
    fake.__enter__ = MagicMock(return_value=fake)
    fake.__exit__ = MagicMock(return_value=False)
    return fake


def test_g_head_405_falls_through_then_chunked_overrun_yields_413(
    monkeypatch, tmp_path
):
    """HEAD raises HTTPError(405); fall through to GET; chunked-read
    accumulator overrun produces 413 with ``size_precise=False`` token."""
    _install_clean_state(monkeypatch)

    body = b"x" * (services._READ_CHUNK + 100)  # > soft cap of 1024
    chunks_iter = iter([body[: services._READ_CHUNK], body[services._READ_CHUNK:], b""])

    fake_get = MagicMock()
    fake_get.headers = {}  # no Content-Length on GET either
    fake_get.read = MagicMock(side_effect=lambda n: next(chunks_iter))
    fake_get.__enter__ = MagicMock(return_value=fake_get)
    fake_get.__exit__ = MagicMock(return_value=False)

    from urllib.error import HTTPError

    def _urlopen(req_or_uri, *args, **kwargs):
        # HEAD probe gets a Request object with method=HEAD; raise 405.
        # GET path gets a bare URI string; return the body-streaming mock.
        if hasattr(req_or_uri, "get_method") and req_or_uri.get_method() == "HEAD":
            raise HTTPError(
                url="https://example.org/x", code=405,
                msg="Method Not Allowed", hdrs=None, fp=None,
            )
        return fake_get

    with patch("pipeline.services.urlopen", side_effect=_urlopen):
        resp_dict = services._process_single_document(
            uri="https://example.org/big.bin",
            store=True,
            collection="m5e_g",
            tags=[],
            force=False,
            agent_id="test",
            agent_type="test",
            model=None,
            initiated_by=None,
            agent_notes=None,
            agent_metadata=None,
            chunking_config=None,
            ingest_config={"max_source_bytes": 1024},
        )

    assert resp_dict.get("error") is True, resp_dict
    assert resp_dict.get("code") == "confirmation_required", resp_dict
    token = resp_dict["confirmation_token"]
    payload = _decode_token_payload(token)
    # rev3 §11.B.3 risk-3 pick 3b: fall-through tokens carry
    # size_precise=False so future size-correlation logging knows the
    # comparison is meaningless.
    assert payload.get("size_precise") is False, payload
    assert payload.get("size") >= 1024


def test_g_head_no_content_length_falls_through(monkeypatch, tmp_path):
    """HEAD returns 200 but headers lack Content-Length; probe.size = None;
    fall through to GET; chunked-read overrun yields 413 with
    size_precise=False."""
    _install_clean_state(monkeypatch)

    body = b"x" * (services._READ_CHUNK + 50)
    chunks_iter = iter([body[: services._READ_CHUNK], body[services._READ_CHUNK:], b""])

    head_resp = MagicMock()
    head_resp.headers = {}
    head_resp.__enter__ = MagicMock(return_value=head_resp)
    head_resp.__exit__ = MagicMock(return_value=False)

    get_resp = MagicMock()
    get_resp.headers = {}
    get_resp.read = MagicMock(side_effect=lambda n: next(chunks_iter))
    get_resp.__enter__ = MagicMock(return_value=get_resp)
    get_resp.__exit__ = MagicMock(return_value=False)

    def _urlopen(req_or_uri, *args, **kwargs):
        if hasattr(req_or_uri, "get_method") and req_or_uri.get_method() == "HEAD":
            return head_resp
        return get_resp

    with patch("pipeline.services.urlopen", side_effect=_urlopen):
        resp_dict = services._process_single_document(
            uri="https://example.org/no-cl.bin",
            store=True,
            collection="m5e_g_nocl",
            tags=[],
            force=False,
            agent_id="test",
            agent_type="test",
            model=None,
            initiated_by=None,
            agent_notes=None,
            agent_metadata=None,
            chunking_config=None,
            ingest_config={"max_source_bytes": 1024},
        )

    assert resp_dict.get("code") == "confirmation_required", resp_dict
    payload = _decode_token_payload(resp_dict["confirmation_token"])
    assert payload.get("size_precise") is False


# ── (h) Strict-mode soft-cap breach → 422 ──────────────────────────────────


def test_h_strict_mode_soft_breach_returns_422(monkeypatch, tmp_path):
    """``require_confirmation_above_soft=False`` → 422 ``exceeds_soft_cap_strict``,
    with ``soft_cap`` field (distinguishing from ``exceeds_hard_limit``)."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "strict.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    resp = client.post(
        "/api/documents",
        json={
            "uri": str(big),
            "collection": "m5e_h",
            "ingest_config": {
                "max_source_bytes": 1024,
                "require_confirmation_above_soft": False,
            },
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "exceeds_soft_cap_strict"
    assert detail["soft_cap"] == 1024
    assert "hard_cap" in detail
    assert "confirmation_token" not in detail
    assert "ttl_seconds" not in detail


def test_h_three_422_codes_are_distinguishable(monkeypatch, tmp_path):
    """``exceeds_hard_limit`` (no soft_cap), ``exceeds_soft_cap_strict``
    (soft_cap present), legacy errors (no code) — three sentinel shapes
    that must remain distinguishable on the wire (per §11.B.4 / probe l)."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "distinct.txt"
    big.write_bytes(b"x" * 4096)
    client = TestClient(_build_app())

    # exceeds_hard_limit
    r_hard = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_h_hard",
        "ingest_config": {"max_source_bytes_hard": 1024},
    })
    assert r_hard.status_code == 422
    d_hard = r_hard.json()["detail"]
    assert d_hard["code"] == "exceeds_hard_limit"
    assert "soft_cap" not in d_hard

    # exceeds_soft_cap_strict
    r_strict = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_h_strict",
        "ingest_config": {
            "max_source_bytes": 1024,
            "require_confirmation_above_soft": False,
        },
    })
    assert r_strict.status_code == 422
    d_strict = r_strict.json()["detail"]
    assert d_strict["code"] == "exceeds_soft_cap_strict"
    assert "soft_cap" in d_strict
    assert d_strict["hard_cap"] != d_strict["soft_cap"]


# ── (i) Token size-binding dropped — three sub-cases ───────────────────────


def test_i_token_validates_with_size_growth(monkeypatch, tmp_path):
    """Issue token for size N; re-submit with file grown to N+1MB still
    below hard cap → proceeds (200). Pin: no SIZE_MISMATCH path."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "growth.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_i_grow",
        "ingest_config": {"max_source_bytes": 1024},
    })
    token = first.json()["detail"]["confirmation_token"]

    # Grow the file between probe and re-submit.
    big.write_bytes(b"x" * 8192)

    second = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_i_grow",
        "ingest_config": {"max_source_bytes": 1024},
        "confirmation_token": token,
    })
    assert second.status_code == 200, second.text


def test_i_token_validates_with_size_shrinkage(monkeypatch, tmp_path):
    _install_clean_state(monkeypatch)
    big = tmp_path / "shrink.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_i_shrink",
        "ingest_config": {"max_source_bytes": 1024},
    })
    token = first.json()["detail"]["confirmation_token"]

    # Shrink the file (still above soft).
    big.write_bytes(b"x" * 2048)

    second = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_i_shrink",
        "ingest_config": {"max_source_bytes": 1024},
        "confirmation_token": token,
    })
    assert second.status_code == 200, second.text


def test_i_hard_cap_still_enforces_after_token_validate(monkeypatch, tmp_path):
    """Issue token for N (between soft and hard); re-submit with file
    grown above hard cap → 422 ``exceeds_hard_limit``. The chunked-read
    accumulator at effective_hard catches the overrun on the actual
    fetch; token-validity does NOT bypass effective_hard."""
    _install_clean_state(monkeypatch)
    big = tmp_path / "hard_after.txt"
    big.write_bytes(b"x" * 4096)

    client = TestClient(_build_app())
    first = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_i_hard",
        "ingest_config": {
            "max_source_bytes": 1024,
            "max_source_bytes_hard": 8192,
        },
    })
    assert first.status_code == 413
    token = first.json()["detail"]["confirmation_token"]

    # Grow the file above hard cap.
    big.write_bytes(b"x" * 16_384)

    second = client.post("/api/documents", json={
        "uri": str(big),
        "collection": "m5e_i_hard",
        "ingest_config": {
            "max_source_bytes": 1024,
            "max_source_bytes_hard": 8192,
        },
        "confirmation_token": token,
    })
    assert second.status_code == 422, second.text
    assert second.json()["detail"]["code"] == "exceeds_hard_limit"


# ── (j) Last-Modified normalization ────────────────────────────────────────


def test_j_http_last_modified_normalized_to_iso8601(monkeypatch):
    """Mock HEAD response with RFC 7231 Last-Modified; assert the wire
    body's last_modified field is ISO-8601 UTC."""
    _install_clean_state(monkeypatch)

    head_resp = MagicMock()
    head_resp.headers = {
        "Content-Length": "300000000",
        "Content-Type": "application/pdf",
        "Last-Modified": "Wed, 15 Apr 2026 12:00:00 GMT",
    }
    head_resp.__enter__ = MagicMock(return_value=head_resp)
    head_resp.__exit__ = MagicMock(return_value=False)

    def _urlopen(req_or_uri, *args, **kwargs):
        if hasattr(req_or_uri, "get_method") and req_or_uri.get_method() == "HEAD":
            return head_resp
        raise AssertionError("body fetch should not happen — 413 short-circuits")

    with patch("pipeline.services.urlopen", side_effect=_urlopen):
        result = services._process_single_document(
            uri="https://example.org/big.pdf",
            store=True,
            collection="m5e_j",
            tags=[],
            force=False,
            agent_id="test",
            agent_type="test",
            model=None,
            initiated_by=None,
            agent_notes=None,
            agent_metadata=None,
            chunking_config=None,
        )

    assert result.get("code") == "confirmation_required", result
    assert result["last_modified"] == "2026-04-15T12:00:00+00:00", result
    assert result["content_type"] == "application/pdf", result


def test_j_malformed_last_modified_falls_to_null(monkeypatch):
    _install_clean_state(monkeypatch)

    head_resp = MagicMock()
    head_resp.headers = {
        "Content-Length": "300000000",
        "Last-Modified": "not-a-date",
    }
    head_resp.__enter__ = MagicMock(return_value=head_resp)
    head_resp.__exit__ = MagicMock(return_value=False)

    def _urlopen(req_or_uri, *args, **kwargs):
        if hasattr(req_or_uri, "get_method") and req_or_uri.get_method() == "HEAD":
            return head_resp
        raise AssertionError("no body fetch expected")

    with patch("pipeline.services.urlopen", side_effect=_urlopen):
        result = services._process_single_document(
            uri="https://example.org/malformed.pdf",
            store=True,
            collection="m5e_j_bad",
            tags=[],
            force=False,
            agent_id="test",
            agent_type="test",
            model=None,
            initiated_by=None,
            agent_notes=None,
            agent_metadata=None,
            chunking_config=None,
        )

    assert result.get("code") == "confirmation_required"
    assert result["last_modified"] is None


# ── (k) HEAD timeout default = 10s ─────────────────────────────────────────


def test_k_head_timeout_default_is_10_seconds(monkeypatch):
    """Pin the HEAD-probe default timeout at 10s. A future regression that
    drops it to 5s would shorten the patience window for slow servers."""
    captured = {}

    def _spy(req, timeout=None, **kwargs):  # noqa: ARG001
        captured["timeout"] = timeout
        # Return a HEAD response shape — empty headers so probe size=None
        # and fall-through. Caller will hit GET and raise; that's fine,
        # we only care about the timeout the spy saw.
        resp = MagicMock()
        resp.headers = {}
        resp.read = MagicMock(return_value=b"")
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("pipeline.services.urlopen", side_effect=_spy):
        # Just call _probe_size directly — that is the public surface
        # that owns the timeout default.
        services._probe_size("https://example.org/x")

    assert captured["timeout"] == 10.0, (
        f"_probe_size HEAD-probe timeout default must be 10.0s; got {captured['timeout']}"
    )


# ── (l) Legacy error-dict back-compat shape ────────────────────────────────


def _trigger_legacy(client, monkeypatch, *, raise_factory, json_payload, expected_keys_subset):
    """Helper: monkeypatch an internal stage to raise; assert the wire
    response status is 422 and detail keys form the expected subset
    (with NO ``code``/``bytes_seen``/``cap_kind`` keys in detail)."""
    raise_factory(monkeypatch)
    resp = client.post("/api/documents", json=json_payload)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "code" not in detail, detail
    assert "bytes_seen" not in detail, detail
    assert "cap_kind" not in detail, detail
    for k in expected_keys_subset:
        assert k in detail, (k, detail)
    return detail


def test_l_extraction_failure_legacy_shape(monkeypatch):
    """Extraction failure produces the pre-m5e error-dict shape: no code,
    just ``{message, document_id, source_file}``."""
    _install_clean_state(monkeypatch)

    # Mutate the extractor to return errors=[...] which triggers the
    # services.py:389-395 path.
    failing = MagicMock()
    failing.extract_from_bytes.return_value = ExtractionResult(
        document_id="00000000-0000-0000-0000-000000000000",
        source_file="sample.txt",
        markdown="",
        title=None,
        file_type="txt",
        pages=None,
        engine="markitdown-mock",
        processing_time_ms=1,
        output_tokens_estimate=0,
        token_savings_ratio=None,
        processing_chain=[],
        warnings=[],
        errors=["boom"],
    )
    monkeypatch.setattr(services, "_extractor", failing)

    client = TestClient(_build_app())
    resp = client.post("/api/documents", json={
        "uri": str(_FIXTURE_TXT),
        "collection": "m5e_l_extract",
    })
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "code" not in detail, detail
    assert detail.keys() == {"message", "document_id", "source_file"}, detail
    assert "Extraction failed" in detail["message"]


def test_l_invalid_chunking_config_legacy_shape(monkeypatch):
    """Bogus chunking_config key surfaces with no ``code`` field."""
    _install_clean_state(monkeypatch)
    client = TestClient(_build_app())
    resp = client.post("/api/documents", json={
        "uri": str(_FIXTURE_TXT),
        "collection": "m5e_l_chunk",
        "chunking_config": {"bogus_chunk_key": 1},
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "code" not in detail, detail
    assert detail.keys() == {"message", "document_id", "source_file"}, detail
    assert "Invalid chunking config" in detail["message"]


def test_l_invalid_ingest_config_legacy_shape(monkeypatch):
    """Bogus ingest_config key surfaces with no ``code`` field."""
    _install_clean_state(monkeypatch)
    client = TestClient(_build_app())
    resp = client.post("/api/documents", json={
        "uri": str(_FIXTURE_TXT),
        "collection": "m5e_l_ingest",
        "ingest_config": {"bogus_ingest_key": 1},
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "code" not in detail, detail
    assert detail.keys() == {"message", "document_id", "source_file"}, detail
    assert "Invalid ingest config" in detail["message"]


def test_l_source_read_failed_non_cap_legacy_shape(monkeypatch):
    """Non-cap source-read failure (e.g., file does not exist) surfaces
    with no ``code`` field — the legacy ``Source read failed:`` shape
    is preserved verbatim."""
    _install_clean_state(monkeypatch)
    client = TestClient(_build_app())
    resp = client.post("/api/documents", json={
        "uri": "/does/not/exist.txt",
        "collection": "m5e_l_read",
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "code" not in detail, detail
    assert detail.keys() == {"message", "document_id", "source_file"}, detail
    assert "Source read failed" in detail["message"]


# ── Nit 5 (optional) — issue_token always sets size_precise ────────────────


def test_nit5_every_issue_token_call_carries_size_precise():
    """Optional unit-tier probe (Nit 5): every ``issue_token`` output
    decodes with the ``size_precise`` field present. Pins that a future
    refactor that drops the kwarg surfaces here as a probe failure
    rather than a silent default-permissive absorption at validate time.

    Two flavors:
      * size_precise=True (HEAD-resolved) → token payload has it True.
      * size_precise=False (fall-through) → token payload has it False.
    """
    t1, _ = confirmation.issue_token(
        source_uri="https://example.org/a",
        reported_size=1,
        size_precise=True,
        ttl_seconds=60,
    )
    t2, _ = confirmation.issue_token(
        source_uri="https://example.org/b",
        reported_size=2,
        size_precise=False,
        ttl_seconds=60,
    )
    p1 = _decode_token_payload(t1)
    p2 = _decode_token_payload(t2)
    assert "size_precise" in p1 and p1["size_precise"] is True
    assert "size_precise" in p2 and p2["size_precise"] is False
