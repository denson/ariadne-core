"""Route-level smoke probes for ariadne--ucw — chunking_config 422 contract.

Parallel to tests/verification/ariadne--16a/test_16a_smoke_beats.py
``TestF2_422_HTTPContract`` for ingest_config. Pre-fix, an unknown
``chunking_config`` key escaped services._process_single_document as a
raw ValueError → FastAPI global handler → HTTP 500. Post-fix, the
ValueError is caught locally and converted to the standard error-dict
shape that routes.py:287 turns into HTTP 422.

Probes:
  - ``test_bogus_chunking_config_key_returns_422_via_route`` — wire-level
    assertion that bogus key surfaces as HTTP 422 with the
    ``Invalid chunking config: Unknown chunking config keys`` message.
  - ``test_no_override_succeeds_with_yaml_default_chunking`` — control
    that the absent-chunking_config happy path still returns 200, so the
    new try/except did not narrow successful responses.

Helpers (_install_clean_state, _build_app_with_real_router, _FIXTURE_TXT)
are copy-shaped from the sibling ariadne--16a probe module — the dir
name ``ariadne--16a`` is not a valid Python module identifier (double
dash), so cross-import is awkward; copy-shape is the convention used
across other verification dirs in this tree.

Run with ``PYTHONPATH=src python -m pytest tests/verification/ariadne--ucw/``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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


# __file__ is .../tests/verification/ariadne--ucw/test_ucw_chunking_422.py
# parents[0] = ariadne--ucw, parents[1] = verification, parents[2] = tests
_FIXTURE_TXT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "sample.txt"
)


# ── Local helpers (copy-shape from ariadne--16a probe module) ───────────────


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


# ── chunking_config 422 contract at the HTTP layer ──────────────────────────


class TestChunkingConfig_422_HTTPContract:
    """Wire-level verification that the ariadne--ucw fix holds end-to-end.

    Pre-fix: services.py:529 raised ValueError without a local try/except,
    so the bare exception escaped to app.py's global Exception handler at
    app.py:125-137 and surfaced as HTTP 500. Post-fix: the local try/except
    converts ValueError → error-dict → routes.py:287 → HTTP 422. These
    probes drive the route via TestClient and assert the wire-level status."""

    def test_bogus_chunking_config_key_returns_422_via_route(self, monkeypatch):
        _install_clean_state(monkeypatch)
        client = TestClient(_build_app_with_real_router())

        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_ucw_chunk_bogus",
                "chunking_config": {"bogus_chunk_key": 1},
            },
        )

        assert resp.status_code == 422, (
            f"chunking_config bogus key surfaces as {resp.status_code}, "
            f"not 422. Body: {resp.text}"
        )
        body = resp.json()
        # routes.py wraps the message under detail
        detail = body.get("detail", body)
        message = detail.get("message", "")
        assert "Invalid chunking config" in message, body
        assert "Unknown chunking config keys" in message, body
        assert "bogus_chunk_key" in message, body

    def test_no_override_succeeds_with_yaml_default_chunking(self, monkeypatch):
        """chunking_config absent (=> None) must use the YAML/dataclass
        defaults and the small fixture must succeed. Control case proves
        the new try/except didn't narrow the happy path."""
        _install_clean_state(monkeypatch)

        client = TestClient(_build_app_with_real_router())
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(_FIXTURE_TXT),
                "collection": "vera_ucw_chunk_default",
                # chunking_config deliberately absent
            },
        )

        assert resp.status_code == 200, (
            f"YAML default chunking path failed: {resp.status_code}; "
            f"body: {resp.text}"
        )
        assert resp.json().get("error") is not True
