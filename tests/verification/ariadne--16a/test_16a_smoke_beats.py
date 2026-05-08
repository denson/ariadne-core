"""VERA verification probes for ariadne--16a (Batch G / che + io5).

Independent post-build verification of ADA's commit a3bd4a8. These probes
do NOT replace ADA's tests/test_ingest_config_plumbing.py — they cover
the load-bearing beats VERA's brief calls out the seat to independently
re-verify, plus the integration / cross-batch beats (5, 6) that ADA's
unit tests deliberately leave to the broader suite.

The seat is asking three falsifying questions:

  Q1 — Does the §F2 422 contract hold *at the HTTP layer*? ADA's beat 7
       tests verify the error-dict shape inside _process_single_document;
       this seat constructs a TestClient probe that POSTs an
       ``ingest_config`` with a bogus key against the live route and
       asserts the wire-level response is 422 (NOT 500 — which is what
       the pre-r2 ARGUS-flagged shape would have produced via the global
       Exception handler at app.py:136-157).

  Q2 — Is the URL single-fetch invariant true *at the route layer*?
       ADA's beat 3 mocks urlopen + urlretrieve and asserts call counts
       on services._process_single_document. This seat re-verifies the
       same invariant but driven through the REAL POST /api/documents
       route, so a regression that fetches in routes.py (or any future
       middleware seam) would also be caught.

  Q3 — Does extract_from_bytes structurally avoid re-fetching? Static
       check on markitdown.py: extract_from_bytes must NOT reference
       _resolve_uri, _download_to_temp, or urlretrieve in its body.
       Belt-and-braces against a future refactor that adds a "smart
       fallback" re-fetch inside the bytes seam.

Also covers Beat 5 (backward compat: local PDF + URL ingest still work),
Beat 6 (pipeline regression: dedup hit + warnings_count + Batch F YAML
chunking config still active), and a forward-pin on the cap-misconfig
guard (configure_ingest rejects max_source_bytes <= 0).

Plus a regression gate for the Batch F ``chunking_config`` 422 contract
fixed in ariadne--ucw — encoded as
``TestChunkingConfig422Contract::test_bogus_chunking_config_key_returns_422``
in this file, and re-asserted at the route layer by
``tests/verification/ariadne--ucw/test_ucw_chunking_422.py``. Keeping the
gate here ensures any future regression of the chunking_config 422
contract trips both the 16a integration suite and the ucw probe.

Run with ``PYTHONPATH=src python -m pytest tests/verification/ariadne--16a/``.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.app import app as production_app
from pipeline.api.routes import router
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import (
    ExtractionResult,
    MarkItDownExtractor,
)
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# __file__ is .../tests/verification/ariadne--16a/test_smoke_beats.py
# parents[0] = ariadne--16a, parents[1] = verification, parents[2] = tests
_FIXTURE_TXT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "sample.txt"
)


# ── Local helpers ───────────────────────────────────────────────────────────


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


def _fake_extraction_result(source_file: str, markdown: str = "# fake\n\nhello world\n") -> ExtractionResult:
    return ExtractionResult(
        document_id="00000000-0000-0000-0000-000000000000",
        source_file=source_file,
        markdown=markdown,
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

    def _fake_extract_from_bytes(content, source_file):
        return _fake_extraction_result(source_file)

    mock.extract_from_bytes.side_effect = _fake_extract_from_bytes
    return mock


def _install_clean_state(monkeypatch) -> MagicMock:
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    monkeypatch.setattr(services, "_ingest_config", IngestConfig())
    extractor = _make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", extractor)
    return extractor


def _build_app_with_real_router() -> FastAPI:
    """Fresh FastAPI mounting the production router + the production
    global Exception handler. Reuses production handlers off the real
    app, so a regression that swaps either follows automatically."""
    app = FastAPI()
    handler = production_app.exception_handlers[Exception]
    app.add_exception_handler(Exception, handler)
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


# ── Q1 — §F2 422 contract at the HTTP layer ─────────────────────────────────


class TestF2_422_HTTPContract:
    """Wire-level verification that beat 7's invariant holds end-to-end.

    The pre-r2 ARGUS finding: the local try/except in
    services._process_single_document for unknown ingest_config keys
    converts ValueError → error-dict → routes.py:282 → HTTP 422. WITHOUT
    that local catch, the bare ValueError propagates to app.py's global
    Exception handler at app.py:136-157 and surfaces as HTTP 500. These
    probes drive the route via TestClient and assert the status code
    on the wire."""

    def test_bogus_ingest_config_key_returns_422_not_500(self, monkeypatch):
        _install_clean_state(monkeypatch)
        client = TestClient(_build_app_with_real_router())

        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_F2_bogus",
                "ingest_config": {"bogus_key_owned_by_typo": 1},
            },
        )

        assert resp.status_code == 422, (
            f"§F2 broken: bogus key surfaces as {resp.status_code}, not 422. "
            f"Body: {resp.text}"
        )
        body = resp.json()
        # routes.py wraps the message under detail
        detail = body.get("detail", body)
        message = detail.get("message", "")
        assert "Invalid ingest config" in message, body
        assert "bogus_key_owned_by_typo" in message, body

    def test_oversize_source_returns_413_confirmation_required(
        self, monkeypatch, tmp_path
    ):
        """m5e migration of the legacy 422-on-oversize semantic.

        Per-request ``max_source_bytes=1024`` against a 4 KB local file
        must surface as **HTTP 413** with ``code: "confirmation_required"``
        and a token in the body. Pre-m5e this was 422 ``Source read
        failed``; post-m5e the soft cap triggers the confirmation flow
        (default deployment with ``require_confirmation_above_soft=True``).

        Defense-in-depth: the request must NOT surface as 500 (raw
        SourceTooLargeError leak through global handler). The cap-aware
        error-dict at services._process_single_document is the load-
        bearing converter; this probe pins the route-layer status code
        and wire shape.
        """
        _install_clean_state(monkeypatch)

        big = tmp_path / "oversize.txt"
        big.write_bytes(b"x" * 4096)

        client = TestClient(_build_app_with_real_router())
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(big),
                "collection": "vera_16a_F2_oversize",
                "ingest_config": {"max_source_bytes": 1024},
            },
        )

        assert resp.status_code == 413, (
            f"oversize source must surface as 413 confirmation_required "
            f"(m5e); got {resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        detail = body.get("detail", body)
        assert detail.get("code") == "confirmation_required", body
        assert detail.get("reported_size") == 4096, body
        assert detail.get("soft_cap") == 1024, body
        assert detail.get("confirmation_token"), body  # non-empty string

    def test_above_hard_cap_returns_422_exceeds_hard_limit(
        self, monkeypatch, tmp_path
    ):
        """m5e: per-request ``max_source_bytes_hard`` override below the
        file size must surface as 422 ``exceeds_hard_limit`` (no token).
        The hard cap is the memory-safety floor that the confirmation
        flow does NOT bypass (per design §11.B.4 / probe (f))."""
        _install_clean_state(monkeypatch)

        big = tmp_path / "huge.txt"
        big.write_bytes(b"x" * 4096)

        client = TestClient(_build_app_with_real_router())
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(big),
                "collection": "vera_16a_F2_hard",
                "ingest_config": {
                    "max_source_bytes": 512,
                    "max_source_bytes_hard": 1024,
                },
            },
        )

        assert resp.status_code == 422, resp.text
        body = resp.json()
        detail = body.get("detail", body)
        assert detail.get("code") == "exceeds_hard_limit", body
        assert detail.get("hard_cap") == 1024, body
        assert "confirmation_token" not in detail, body

    def test_no_override_succeeds_with_yaml_default(self, monkeypatch):
        """ingest_config absent (=> None) must use the YAML/dataclass
        default (200 MB) and the small fixture must succeed."""
        _install_clean_state(monkeypatch)

        client = TestClient(_build_app_with_real_router())
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_F2_default",
                # ingest_config deliberately absent
            },
        )

        assert resp.status_code == 200, (
            f"YAML default path failed: {resp.status_code}; body: {resp.text}"
        )
        assert resp.json().get("error") is not True


# ── Q2 — URL single-fetch at the route layer ────────────────────────────────


class TestURLSingleFetchAtRoute:
    """Re-verify beat 3 via the REAL POST /api/documents route.

    ADA's unit test at tests/test_ingest_config_plumbing.py::
    test_beat_3_url_fetched_exactly_once_per_ingest mocks urlopen +
    urlretrieve at the helper level. This seat drives the route end-to-end
    so a future fetch added inside routes.py or middleware would also
    trip the assertion."""

    def test_url_fetch_count_eq_1_via_route(self, monkeypatch):
        """m5e migration: HEAD probe + GET = 2 urlopen calls per ingest.
        The "single body fetch" invariant lives at the urlretrieve assertion
        (extractor must not re-fetch); the urlopen count is now 2 because
        the size probe runs HEAD before the GET."""
        _install_clean_state(monkeypatch)

        body = b"# vera independent route probe\n"
        reads = iter([body, b""])
        fake_resp = MagicMock()
        fake_resp.headers = {"Content-Length": str(len(body))}
        fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        client = TestClient(_build_app_with_real_router())

        with patch(
            "pipeline.services.urlopen", return_value=fake_resp
        ) as urlopen_mock, patch(
            "pipeline.extraction.markitdown.urlretrieve"
        ) as urlretrieve_mock:
            resp = client.post(
                "/api/documents",
                json={
                    "uri": "https://example.com/vera-route-probe.txt",
                    "collection": "vera_16a_route_single_fetch",
                },
            )

        assert resp.status_code == 200, resp.text
        assert urlopen_mock.call_count == 2, (
            f"m5e: URL must be HEAD-probed once + GET-fetched once via "
            f"the route; got {urlopen_mock.call_count} urlopen calls"
        )
        assert urlretrieve_mock.call_count == 0, (
            f"urlretrieve must NOT be called from the canonical route flow; "
            f"got {urlretrieve_mock.call_count}"
        )


# ── Q3 — Static check: extract_from_bytes never re-fetches ──────────────────


class TestExtractFromBytesStructural:
    """Static check on markitdown.py to lock the structural property:
    extract_from_bytes must not call _resolve_uri, _download_to_temp,
    or urlretrieve. Fast belt-and-braces against a future refactor that
    adds a 'smart fallback' re-fetch inside the bytes seam."""

    def test_extract_from_bytes_does_not_reference_fetch_helpers(self):
        import inspect
        src = inspect.getsource(MarkItDownExtractor.extract_from_bytes)
        forbidden = [
            "_resolve_uri",
            "_download_to_temp",
            "urlretrieve",
            "urlopen",
        ]
        offenders = [tok for tok in forbidden if tok in src]
        assert offenders == [], (
            f"extract_from_bytes must not reference fetch helpers; "
            f"found: {offenders}\n\nSource:\n{src}"
        )

    def test_extract_from_bytes_uses_convert_stream(self):
        """Affirmative: confirm the seam routes through convert_stream
        (not convert(local_path)) — i.e., the bytes really do flow
        through the no-fetch path."""
        import inspect
        src = inspect.getsource(MarkItDownExtractor.extract_from_bytes)
        assert "convert_stream" in src, (
            f"extract_from_bytes must call MarkItDown.convert_stream; "
            f"source:\n{src}"
        )
        assert "BytesIO" in src, (
            f"extract_from_bytes must wrap content in BytesIO; source:\n{src}"
        )


# ── Beat 5 — backward compat ───────────────────────────────────────────────


class TestBackwardCompat:
    """Local file + URL ingest pathways still work post-Batch-G; the
    canonical happy paths are not regressed by the bytes-only seam swap."""

    def test_local_text_file_still_ingests(self, monkeypatch):
        _install_clean_state(monkeypatch)
        client = TestClient(_build_app_with_real_router())
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_compat_local",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("error") is not True, body
        assert body.get("document_id"), body
        assert body.get("source_file") == "sample.txt", body
        # Batch B: warnings_count surfaces
        assert "warnings_count" in body, body
        assert isinstance(body["warnings_count"], int), body

    def test_url_ingest_still_works(self, monkeypatch):
        _install_clean_state(monkeypatch)

        body_bytes = b"# fake URL doc\n\nbody\n"
        reads = iter([body_bytes, b""])
        fake_resp = MagicMock()
        fake_resp.headers = {"Content-Length": str(len(body_bytes))}
        fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        client = TestClient(_build_app_with_real_router())
        with patch("pipeline.services.urlopen", return_value=fake_resp):
            resp = client.post(
                "/api/documents",
                json={
                    "uri": "https://example.com/compat-probe.txt",
                    "collection": "vera_16a_compat_url",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("error") is not True, body
        assert body.get("document_id"), body


# ── Beat 6 — pipeline regression spot checks ────────────────────────────────


class TestPipelineRegression:
    """Cross-batch contracts that must survive Batch G's seam swap:
       Batch D — fingerprint stable across re-ingest of identical bytes;
                 was_dedup_skip=True on the second ingest.
       Batch B — warnings_count surfaces in the response."""

    def test_dedup_hit_on_reingest_preserves_was_dedup_skip(self, monkeypatch):
        _install_clean_state(monkeypatch)

        client = TestClient(_build_app_with_real_router())

        first = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_dedup",
            },
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body.get("was_dedup_skip") is False, first_body

        second = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_dedup",
            },
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body.get("was_dedup_skip") is True, second_body
        # Same fingerprint surface (Batch D contract: byte-stable)
        assert (
            second_body.get("content_fingerprint")
            == first_body.get("content_fingerprint")
        ), (first_body, second_body)


# ── configure_ingest cap-misconfig guard ────────────────────────────────────


class TestConfigureIngestGuard:
    """Independent re-verification of ADA's
    test_configure_ingest_rejects_nonpositive_cap. Brief specifies this
    as a load-bearing guard: misconfigured deployments must fail at
    lifespan-load, not at first byte read."""

    def test_zero_cap_rejected_loudly(self):
        with pytest.raises(ValueError) as excinfo:
            services.configure_ingest(IngestConfig(max_source_bytes=0))
        assert "must be > 0" in str(excinfo.value)

    def test_negative_cap_rejected_loudly(self):
        with pytest.raises(ValueError):
            services.configure_ingest(IngestConfig(max_source_bytes=-100))


# ── Regression gate: chunking_config 422 contract (parallel of F2) ─────────


class TestChunkingConfig422Contract:
    """Regression gate for the 422 contract on chunking_config — fix landed
    in ariadne--ucw. Parallel to the ingest_config 422 contract Batch G F2
    established (services.py:268-291); the chunking_config block at
    services.py:529 now has the same local try/except → error-dict shape,
    so an unknown chunking_config key surfaces as HTTP 422 (not 500)."""

    def test_bogus_chunking_config_key_returns_422(self, monkeypatch):
        """Asserts POST /api/documents with bogus chunking_config key
        returns HTTP 422 with ``Invalid chunking config: Unknown chunking
        config keys`` message — the same 422 contract Batch G F2
        established for ingest_config."""
        _install_clean_state(monkeypatch)
        client = TestClient(_build_app_with_real_router())
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_chunk_422_contract",
                "chunking_config": {"bogus_chunk_key": 1},
            },
        )
        assert resp.status_code == 422, (
            f"chunking_config bogus key should surface as 422; got "
            f"{resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        # routes.py wraps the message under detail (mirror F2 access pattern)
        detail = body.get("detail", body)
        message = detail.get("message", "")
        assert "Invalid chunking config" in message, body
        assert "Unknown chunking config keys" in message, body
        assert "bogus_chunk_key" in message, body
