"""Route-level probes for ariadne--b1q — `chunk_count` field-name consistency.

Pre-fix, the API used two different keys for the same concept:
- ``POST /api/documents`` returned ``chunks_count`` (with the trailing ``s``)
  on every response path (success/store, store=false, dedup-skip,
  embedding-failure).
- ``GET /api/documents`` (list) and ``GET /api/documents/{id}`` (with
  ``include_chunks=true``) returned ``chunk_count`` (no ``s``).

The drift forced the client package to carry both fields with a fallback,
forced ``scripts/bulk_ingest.py`` to carry a compat shim, and produced a
SPEC vs. wire mismatch that surprised every new caller.

Post-fix (PRINCIPAL Option A — hard rename): every load-bearing surface
returns ``chunk_count`` (no ``s``), aligning with the sibling
``interaction_count`` already on GET list rows. ``chunks_count`` MUST
NOT appear in any current API response.

Probes:
  - Probe 1 — POST /api/documents (store=true success) returns
    ``chunk_count`` and NOT ``chunks_count``.
  - Probe 2 — POST /api/documents with store=false returns ``chunk_count``
    (== 0) and NOT ``chunks_count``.
  - Probe 3 — GET /api/documents (list) rows carry ``chunk_count`` and
    NOT ``chunks_count``; GET /api/documents/{id} with include_chunks=true
    carries ``chunk_count`` and NOT ``chunks_count``.
  - Probe 4 — Static-source falsification guard: the load-bearing
    handlers (``services._process_single_document``, ``routes.list_documents``,
    ``routes.get_document``) must not contain the substring ``"chunks_count"``
    anywhere except inside docstrings (which legitimately discuss the
    historical key in design context). Same shape as ariadne--tol probe 6
    and ariadne--qe6 probe 5.

Helpers (_install_clean_state, _build_app_with_real_router) are
copy-shape from sibling verification modules (ariadne--qe6,
ariadne--ucw) — the dir name ``ariadne--b1q`` is not a valid Python
module identifier (double dash), so cross-import is awkward; copy-shape
is the convention used across this tree.

Run with ``PYTHONPATH=src python -m pytest tests/verification/ariadne--b1q/``
from the worktree root, or ``cd src && python -m pytest
../tests/verification/ariadne--b1q/``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api import routes
from pipeline.api.app import app as production_app
from pipeline.api.routes import router
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# __file__ is .../tests/verification/ariadne--b1q/test_b1q_chunk_count_consistency.py
# parents[0] = ariadne--b1q, parents[1] = verification, parents[2] = tests
_FIXTURE_TXT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "sample.txt"
)


# ── Local helpers (copy-shape from ariadne--ucw / ariadne--qe6 modules) ─────


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


class _StubEmbedResult:
    """Stand-in for EmbeddingResult returned by embed_texts on success.

    Copy-shape from tests/test_services.py:_StubEmbedResult — the real
    EmbeddingResult dataclass has ``embeddings`` (list of vectors) and
    ``processing_chain_entry`` (dict). Only those two are read on the
    happy path in services.py:572-575."""

    def __init__(self, count: int, dims: int = 3) -> None:
        self.embeddings = [[0.1] * dims for _ in range(count)]
        self.processing_chain_entry = {
            "step": "embedding",
            "tool": "stub:b1q",
            "ts": "2026-05-06T00:00:00Z",
            "ms": 1,
        }


class _SuccessEmbeddingClient:
    """Returns deterministic fake embeddings (one per input text) so the
    success path produces ``chunk_count > 0`` without a real provider."""

    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_texts(self, texts):
        return _StubEmbedResult(count=len(texts))


def _fake_extraction_result(
    source_file: str, markdown: str = "# fake\n\nhello world\n"
) -> ExtractionResult:
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


def _install_clean_state(monkeypatch, *, embedding="success") -> MagicMock:
    """Reset the services module's stores and embedding client.

    ``embedding`` selects between the success embedder (chunk_count > 0
    on store=true) and disabled (chunk_count == 0 on store=false control).
    """
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    if embedding == "success":
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
    else:
        monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    monkeypatch.setattr(services, "_ingest_config", IngestConfig())
    extractor = _make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", extractor)
    return extractor


def _build_app_with_real_router() -> FastAPI:
    """Fresh FastAPI mounting the production router + production global
    Exception handler. Reuses production handlers off the real app, so a
    regression that swaps either follows automatically."""
    app = FastAPI()
    handler = production_app.exception_handlers[Exception]
    app.add_exception_handler(Exception, handler)
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


# ── Probe 1 — POST /api/documents store=true returns `chunk_count` ─────────


def test_probe_1_post_documents_store_true_uses_chunk_count(monkeypatch):
    """``POST /api/documents`` with ``store=true`` (the default) must
    return ``chunk_count`` (no ``s``) on the success path. The legacy
    ``chunks_count`` key MUST NOT appear in the response body.

    Pre-fix this path returned ``chunks_count``; post-fix it must
    return ``chunk_count``.
    """
    _install_clean_state(monkeypatch, embedding="success")
    client = TestClient(_build_app_with_real_router())

    resp = client.post(
        "/api/documents",
        json={
            "uri": str(_FIXTURE_TXT),
            "collection": "b1q_post_store_true",
            # store defaults to true
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "chunk_count" in body, (
        f"POST /api/documents (store=true) must return `chunk_count` — "
        f"got body keys: {sorted(body.keys())}"
    )
    assert "chunks_count" not in body, (
        f"POST /api/documents (store=true) MUST NOT return the legacy "
        f"`chunks_count` key — got body keys: {sorted(body.keys())}"
    )
    assert isinstance(body["chunk_count"], int), body
    assert body["chunk_count"] >= 1, body
    assert body["store_status"] == "stored", body


# ── Probe 2 — POST /api/documents store=false returns `chunk_count` == 0 ───


def test_probe_2_post_documents_store_false_uses_chunk_count(monkeypatch):
    """``POST /api/documents`` with ``store=false`` must still return
    ``chunk_count`` (set to ``0`` because nothing is chunked or stored)
    and MUST NOT return the legacy ``chunks_count`` key.

    Pre-fix this path also returned ``chunks_count: 0``; post-fix it
    must use the new key name.
    """
    _install_clean_state(monkeypatch, embedding="disabled")
    client = TestClient(_build_app_with_real_router())

    resp = client.post(
        "/api/documents",
        json={
            "uri": str(_FIXTURE_TXT),
            "collection": "b1q_post_store_false",
            "store": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "chunk_count" in body, (
        f"POST /api/documents (store=false) must return `chunk_count` — "
        f"got body keys: {sorted(body.keys())}"
    )
    assert "chunks_count" not in body, (
        f"POST /api/documents (store=false) MUST NOT return the legacy "
        f"`chunks_count` key — got body keys: {sorted(body.keys())}"
    )
    assert body["chunk_count"] == 0, body
    assert body["store_status"] == "not_stored", body


# ── Probe 3 — GET /api/documents (list) + GET /api/documents/{id} (detail) ──


def test_probe_3_get_documents_list_and_detail_use_chunk_count(monkeypatch):
    """Both ``GET /api/documents`` (list) row and
    ``GET /api/documents/{id}?include_chunks=true`` (detail) must carry
    ``chunk_count`` (no ``s``) and MUST NOT carry the legacy
    ``chunks_count`` key.

    The GET endpoints already used ``chunk_count`` pre-fix — this probe
    is a regression guard: someone could "harmonize" the two GET
    handlers back to ``chunks_count`` thinking they're aligning to the
    POST shape, undoing the b1q fix.
    """
    _install_clean_state(monkeypatch, embedding="success")
    client = TestClient(_build_app_with_real_router())

    # Seed one document via the public POST so the dedup store + vector
    # store both hold real shapes (avoids surprises a direct seed would
    # paper over).
    post = client.post(
        "/api/documents",
        json={
            "uri": str(_FIXTURE_TXT),
            "collection": "b1q_get_list_and_detail",
        },
    )
    assert post.status_code == 200, post.text
    post_body = post.json()
    document_id = post_body["document_id"]

    # GET /api/documents list — single-row body filtered by collection.
    list_resp = client.get(
        "/api/documents",
        params={"collection": "b1q_get_list_and_detail"},
    )
    assert list_resp.status_code == 200, list_resp.text
    list_body = list_resp.json()
    rows = list_body["documents"]
    assert len(rows) >= 1, list_body
    for row in rows:
        assert "chunk_count" in row, (
            f"GET /api/documents row must carry `chunk_count` — "
            f"got row keys: {sorted(row.keys())}"
        )
        assert "chunks_count" not in row, (
            f"GET /api/documents row MUST NOT carry the legacy "
            f"`chunks_count` key — got row keys: {sorted(row.keys())}"
        )
        assert isinstance(row["chunk_count"], int), row

    # GET /api/documents/{id} with include_chunks=true (the default).
    detail = client.get(f"/api/documents/{document_id}")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert "chunk_count" in detail_body, (
        f"GET /api/documents/{{id}} must carry `chunk_count` when "
        f"include_chunks=true — got body keys: {sorted(detail_body.keys())}"
    )
    assert "chunks_count" not in detail_body, (
        f"GET /api/documents/{{id}} MUST NOT carry the legacy "
        f"`chunks_count` key — got body keys: "
        f"{sorted(detail_body.keys())}"
    )
    assert isinstance(detail_body["chunk_count"], int), detail_body
    assert detail_body["chunk_count"] >= 1, detail_body


# ── Probe 4 — Static-source falsification guard ─────────────────────────────


def test_probe_4_no_chunks_count_in_load_bearing_handler_source():
    """Static guard against silent reintroduction of the legacy
    ``chunks_count`` key in the three load-bearing response builders:

    - ``services._process_single_document`` — emits the POST response
      dict on every code path (dedup-skip, store=false, embedding-fail,
      success).
    - ``routes.list_documents`` — emits the GET list rows.
    - ``routes.get_document`` — emits the GET detail body (chunk_count
      under ``include_chunks=true``).

    Pre-fix services.py contained five literal ``"chunks_count"``
    occurrences; post-fix it contains zero. Pre-fix the GET handlers
    already used ``chunk_count`` (they were the right side of the
    drift), so they must continue to. This probe pins all three code
    shapes — same discipline as ariadne--tol probe 6 and ariadne--qe6
    probe 5.

    The probe inspects each function's CODE only (docstrings stripped),
    because a docstring may legitimately mention the historical key in
    a backward-context note (e.g., "pre-rename, this returned
    chunks_count").
    """
    targets = (
        services._process_single_document,
        routes.list_documents,
        routes.get_document,
    )
    for func in targets:
        src = inspect.getsource(func)
        if func.__doc__:
            src_no_doc = src.replace(func.__doc__, "")
        else:
            src_no_doc = src
        assert "chunks_count" not in src_no_doc, (
            f"{func.__module__}.{func.__name__} contains the legacy "
            f"`chunks_count` substring after the ariadne--b1q rename. "
            f"Every API response surface must use `chunk_count` "
            f"(no trailing `s`). Source (docstring stripped):\n"
            + src_no_doc
        )
