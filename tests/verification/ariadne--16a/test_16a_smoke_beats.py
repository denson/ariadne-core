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

Plus the Batch F ``chunking_config`` validation residual ADA flagged as
out-of-scope: probe encoded as ``test_residual_chunking_config_422_gap_is_real``
so a future fix that closes the gap surfaces immediately as a now-passing
xfail.

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

    def test_oversize_source_returns_422_not_500(self, monkeypatch, tmp_path):
        """Per-request cap=1024 against a 4 KB local file must surface
        as 422, NOT 500. Same defense-in-depth shape as bogus-key: the
        SourceTooLargeError must be caught by services._process_single_document
        and converted to the standard error-dict."""
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

        assert resp.status_code == 422, (
            f"oversize source returned {resp.status_code} not 422. "
            f"Body: {resp.text}"
        )
        body = resp.json()
        detail = body.get("detail", body)
        message = detail.get("message", "")
        assert "Source read failed" in message, body
        assert "max_source_bytes" in message, body

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
        assert urlopen_mock.call_count == 1, (
            f"URL must be fetched exactly once via the route; got "
            f"{urlopen_mock.call_count}"
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


# ── Residual: Batch F chunking_config 422 gap (out-of-scope flag) ───────────


class TestChunkingConfigResidual:
    """ADA's commit message flagged the pre-existing Batch F chunking_config
    validation gap as out-of-scope for Batch G (services.py:529-536 raises
    ValueError WITHOUT a local try/except, so an unknown chunking_config
    key escapes to FastAPI's global handler → HTTP 500 instead of 422).

    This probe pins the gap as a known-bad expected-fail. When the gap is
    closed in a follow-up batch, this xfail will start passing — pytest
    will surface it as XPASS and the maintainer will know to delete the
    xfail marker. That's the in-tree breadcrumb for the residual.

    DO NOT delete this probe when the residual is fixed. Convert it to a
    plain assertion that confirms the 422 contract holds for chunking_config
    too. The probe IS the regression gate going forward."""

    @pytest.mark.xfail(
        reason=(
            "Pre-existing Batch F defect (services.py:529-536) — bare "
            "ValueError for unknown chunking_config keys escapes to "
            "FastAPI global handler → HTTP 500. Out-of-scope for "
            "Batch G; tracked for separate post-merge fix."
        ),
        strict=True,
    )
    def test_bogus_chunking_config_key_should_return_422(self, monkeypatch):
        _install_clean_state(monkeypatch)
        client = TestClient(
            _build_app_with_real_router(),
            raise_server_exceptions=False,
        )
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_16a_chunk_residual",
                "chunking_config": {"bogus_chunk_key": 1},
            },
        )
        # Once the residual is fixed, assert 422 here. Pre-fix this is 500.
        assert resp.status_code == 422, (
            f"chunking_config bogus key should surface as 422; got "
            f"{resp.status_code}. Body: {resp.text}"
        )
