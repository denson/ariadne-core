"""Shared scaffolding for ``tests/verification/`` probe directories.

Hoisted from per-ticket copies that had drifted into duplication
between ``ariadne--m5e/`` and ``ariadne--rv0/`` (and now
``ariadne--rxn/`` / ``ariadne--cw2/``). Per ariadne--nud §4: hoist real
duplication, leave per-ticket-specific helpers in their own dirs.

What lives here
---------------
* ``FIXTURE_TXT`` — repo-root ``tests/fixtures/sample.txt`` path. Same
  resolution every probe dir was doing inline (``parents[2]`` walk).
* ``DisabledEmbeddingClient`` — sentinel class assignable to
  ``services._embedding_client`` so the embedding path stays out of
  the probe.
* ``fake_extraction_result`` — minimal ``ExtractionResult`` to bypass
  MarkItDown for routes that just need the pipeline to flow.
* ``make_extractor_mock`` — ``MagicMock`` that maps
  ``extract_from_bytes(content, source_file)`` to
  ``fake_extraction_result(source_file)``.
* ``install_clean_state`` — monkeypatches the four ``services`` module-
  globals (``_dedup_store``, ``_vector_store``, ``_embedding_client``,
  ``_ingest_config``, ``_extractor``) to in-memory / mock equivalents.
* ``build_app`` — fresh ``FastAPI`` with the production exception
  handler + auth override + the production router included at
  ``/api``.

What does NOT live here
-----------------------
* Per-probe-suite-specific helpers (e.g.
  ``_decode_token_payload`` for m5e). Those stay where they are; this
  module is only for the genuinely-duplicated scaffolding.
* Fixtures. The hoisted helpers are pure functions / classes with no
  side effects beyond the monkeypatch invocation. ``install_clean_state``
  takes the test's ``monkeypatch`` and applies it inline; making it a
  pytest fixture would force every caller into a particular
  scope-and-yield contract. Per nud §3: pure helpers → imports;
  side-effect-bearing helpers → fixtures. ``install_clean_state`` IS
  side-effecting via monkeypatch but the side-effects are bound to
  the caller's monkeypatch object (test-scoped) — keeping it as an
  import lets each probe drive monkeypatch in its own way (e.g.
  patching additional symbols in the same call site).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI

from pipeline import services
from pipeline.api.app import app as production_app
from pipeline.api.routes import router
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# Repo-root ``tests/fixtures/sample.txt`` — every probe dir under
# ``tests/verification/<ticket>/`` resolves this via ``parents[2]``.
FIXTURE_TXT: Path = Path(__file__).resolve().parent.parent / "fixtures" / "sample.txt"


class DisabledEmbeddingClient:
    """Sentinel embedding-client whose ``enabled=False`` keeps the
    embedding path unwalked. Probe suites that DO want to exercise the
    embedding path should install their own mock instead.
    """

    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover — assertion path
        raise AssertionError(
            "DisabledEmbeddingClient.embed_texts called — probe suite "
            "expected the embedding path to be skipped."
        )


def fake_extraction_result(source_file: str) -> ExtractionResult:
    """Minimal ``ExtractionResult`` that lets the rest of the pipeline
    flow without hitting MarkItDown."""
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


def make_extractor_mock() -> MagicMock:
    """A ``MagicMock`` whose ``extract_from_bytes(content, source_file)``
    returns a deterministic ``ExtractionResult``."""
    mock = MagicMock()
    mock.extract_from_bytes.side_effect = (
        lambda content, source_file: fake_extraction_result(source_file)
    )
    return mock


def install_clean_state(monkeypatch) -> MagicMock:
    """Replace the five ``services`` module-globals with in-memory /
    mocked equivalents. Returns the extractor mock so probes that need
    to assert on its call history can inspect it.
    """
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", DisabledEmbeddingClient())
    monkeypatch.setattr(services, "_ingest_config", IngestConfig())
    extractor = make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", extractor)
    return extractor


def build_app() -> FastAPI:
    """A fresh ``FastAPI`` configured the way every route-tier probe
    needs: production exception handler attached, auth dependency
    overridden, production router mounted at ``/api``.
    """
    app = FastAPI()
    handler = production_app.exception_handlers[Exception]
    app.add_exception_handler(Exception, handler)
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app
