"""Route-level probes for ariadne--qe6 — stats endpoint collections invariant.

Pre-fix: ``GET /api/stats`` reported ``total_collections = len(_collections)``
(registered-only) and ``collections`` = doc-bearing map. These two sets
diverge in either direction, so ``total_collections`` disagreed with
``len(stats.collections)`` AND with ``GET /api/collections`` (which already
took the union at routes.py:1087).

Post-fix (routes.py:1199-1218): ``collection_stats`` is padded with
``setdefault(name, 0)`` for every name in ``_collections`` and
``total_collections`` is reported as ``len(collection_stats)``. The
load-bearing invariant is::

    body["total_collections"] == len(body["collections"])

…and the cross-endpoint invariant is::

    GET /api/stats: total_collections  ==  GET /api/collections: len(collections)

Probes:
  - Probe 1 — Registered-empty collection appears in stats with 0 count.
  - Probe 2 — Doc-bearing-but-not-registered collection appears in stats.
  - Probe 3 — Mixed registered-empty + doc-bearing produces correct union
    (registered-AND-doc-bearing not double-counted).
  - Probe 4 — Stats ``total_collections`` matches ``GET /api/collections``'s union.
  - Probe 5 — Falsification distinguishability (static-source guard for the
    ``setdefault(name, 0)`` pad — same shape as ariadne--tol probe 6).

Helpers (_install_clean_state, _build_app_with_real_router, _seed_doc) are
copy-shape from sibling verification modules (ariadne--ucw, ariadne--tol)
and the existing test_api_delete_collection.py — the dir name
``ariadne--qe6`` is not a valid Python module identifier (double dash) so
cross-import is awkward; copy-shape is the convention.

Run with ``PYTHONPATH=src python -m pytest tests/verification/ariadne--qe6/``
from the worktree root, or ``cd src && python -m pytest
../tests/verification/ariadne--qe6/``.
"""

from __future__ import annotations

import inspect
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api import routes
from pipeline.api.app import app as production_app
from pipeline.api.routes import CollectionResponse, router
from pipeline.dedup import (
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# ── Local helpers ───────────────────────────────────────────────────────────


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


def _install_clean_state(monkeypatch) -> InMemoryDedupStore:
    """Reset every piece of state that the stats endpoint reads.

    Critically, this includes ``routes._collections`` — the in-memory
    registered-collection dict. Without this reset, prior test mutations
    (e.g., a leftover ``POST /api/collections`` from another test) leak
    in and corrupt the invariant assertions. We swap to a fresh dict
    seeded with the production "default" entry to mirror the module's
    initial state at routes.py:93-95.
    """
    dedup = InMemoryDedupStore()
    vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_dedup_store", dedup)
    monkeypatch.setattr(services, "_vector_store", vector)
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    # Mirror the production module-level seed at routes.py:93-95 so the
    # "default" collection's behavior is unchanged across the reset.
    monkeypatch.setattr(
        routes,
        "_collections",
        {
            "default": CollectionResponse(
                name="default", description="Default collection"
            ),
        },
    )
    return dedup


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


def _seed_doc(store: InMemoryDedupStore, collection: str, content: bytes) -> str:
    """Seed a document into the dedup store directly. Copy-shape from
    test_api_delete_collection.py:_seed_doc — bypasses the ingest pipeline
    so probes don't need extraction fixtures or the markitdown extractor."""
    fp = compute_fingerprint(content)
    doc_id = str(uuid.uuid4())
    doc = StoredDocument(
        document_id=doc_id,
        collection_id=collection,
        source_file="seed.txt",
        content_fingerprint=fp,
        file_type="txt",
        engine="markitdown",
        markdown=content.decode("utf-8", errors="replace"),
        title="seed",
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[{"step": "extraction", "tool": "markitdown"}],
        tags=[],
    )
    store.store_document(doc)
    return doc_id


# ── Probe 1 — Registered-empty collection appears with 0 doc count ─────────


def test_probe_1_registered_empty_appears_in_stats_with_zero(monkeypatch):
    """``POST /api/collections`` with no document ingest must surface in
    ``GET /api/stats``'s ``collections`` map with a 0 doc count, and the
    invariant ``total_collections == len(collections)`` must hold.

    Pre-fix: the registered-empty name was counted by ``total_collections``
    (=len(_collections)) but absent from ``collections`` (built solely
    from documents) — divergence.
    """
    _install_clean_state(monkeypatch)
    client = TestClient(_build_app_with_real_router())

    # Register an empty collection (no docs).
    resp = client.post(
        "/api/collections",
        json={"name": "qe6_registered_empty"},
    )
    assert resp.status_code == 201, resp.text

    stats = client.get("/api/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()

    assert body["total_collections"] >= 1, body
    assert "qe6_registered_empty" in body["collections"], body
    assert body["collections"]["qe6_registered_empty"] == 0, body
    # Load-bearing invariant.
    assert body["total_collections"] == len(body["collections"]), body


# ── Probe 2 — Doc-bearing-but-not-registered appears in stats ──────────────


def test_probe_2_doc_bearing_unregistered_appears_in_stats(monkeypatch):
    """A collection that has documents but was never explicitly registered
    via ``POST /api/collections`` must appear in stats with its real doc
    count, and the invariant must hold.

    Pre-fix this side already worked (collections came from documents) —
    but the invariant did NOT hold, because ``total_collections`` was
    ``len(_collections)`` (registered) which excluded this name.
    """
    dedup = _install_clean_state(monkeypatch)
    _seed_doc(dedup, "qe6_implicit", b"hello world")

    client = TestClient(_build_app_with_real_router())
    stats = client.get("/api/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()

    assert "qe6_implicit" in body["collections"], body
    assert body["collections"]["qe6_implicit"] >= 1, body
    # Load-bearing invariant.
    assert body["total_collections"] == len(body["collections"]), body


# ── Probe 3 — Mixed state, registered-AND-doc-bearing not double-counted ───


def test_probe_3_mixed_union_no_double_count(monkeypatch):
    """When a collection is BOTH registered AND has documents, it must
    appear exactly once in the stats map (not double-counted in the union).
    The doc count, not 0, must win — registered-empty pad uses
    ``setdefault`` precisely so it does not overwrite a real count.
    """
    dedup = _install_clean_state(monkeypatch)
    client = TestClient(_build_app_with_real_router())

    # Two registered-empty.
    for name in ("qe6_registered_a", "qe6_registered_b"):
        resp = client.post("/api/collections", json={"name": name})
        assert resp.status_code == 201, resp.text

    # One implicit (doc-bearing only).
    _seed_doc(dedup, "qe6_implicit_c", b"hello c")

    # qe6_registered_a is now BOTH registered AND doc-bearing.
    _seed_doc(dedup, "qe6_registered_a", b"hello a1")
    _seed_doc(dedup, "qe6_registered_a", b"hello a2")

    stats = client.get("/api/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    collections = body["collections"]

    assert "qe6_registered_a" in collections, body
    assert "qe6_registered_b" in collections, body
    assert "qe6_implicit_c" in collections, body
    # Doc count wins for registered-AND-doc-bearing (no overwrite by 0).
    assert collections["qe6_registered_a"] == 2, body
    # Registered-empty stays 0.
    assert collections["qe6_registered_b"] == 0, body
    assert collections["qe6_implicit_c"] >= 1, body
    # Load-bearing invariant — the union is counted once, not twice.
    assert body["total_collections"] == len(collections), body
    # Sanity-check the literal count: default + 2 registered + 1 implicit = 4.
    assert body["total_collections"] == 4, body


# ── Probe 4 — Cross-endpoint consistency with /api/collections ─────────────


def test_probe_4_stats_matches_list_collections_union(monkeypatch):
    """``GET /api/stats``'s ``total_collections`` and ``GET /api/collections``'s
    response length must agree — both endpoints walk the same union
    (registered ∪ doc-bearing). Without this guarantee, a client checking
    one endpoint's count gets a different answer than another.
    """
    dedup = _install_clean_state(monkeypatch)
    client = TestClient(_build_app_with_real_router())

    # Mixed state mirroring probe 3.
    for name in ("qe6_registered_a", "qe6_registered_b"):
        resp = client.post("/api/collections", json={"name": name})
        assert resp.status_code == 201, resp.text
    _seed_doc(dedup, "qe6_implicit_c", b"hello c")
    _seed_doc(dedup, "qe6_registered_a", b"hello a")

    stats_resp = client.get("/api/stats")
    list_resp = client.get("/api/collections")
    assert stats_resp.status_code == 200, stats_resp.text
    assert list_resp.status_code == 200, list_resp.text

    stats_total = stats_resp.json()["total_collections"]
    coll_count = len(list_resp.json()["collections"])

    assert stats_total == coll_count, (
        f"GET /api/stats total_collections={stats_total} disagrees with "
        f"GET /api/collections length={coll_count}. The two endpoints "
        f"must walk the same union."
    )


# ── Probe 5 — Static-source falsification guard ────────────────────────────


def test_probe_5_setdefault_pad_present_in_get_stats_source():
    """Static guard against silent removal of the registered-empty pad.

    The fix's load-bearing line is ``collection_stats.setdefault(name, 0)``
    inside ``get_stats``. If a future "cleanup" deletes that line without
    updating these probes, the runtime probes 1/3/4 would still pass
    on the path they exercise (and might miss edge cases under different
    state), but the invariant disappears for the registered-empty case
    that is not also exercised by a doc seed. This static probe pins the
    code shape — same discipline as ariadne--tol probe 6.

    The probe inspects the function's source code only (not its docstring),
    because the docstring legitimately mentions "setdefault" while
    explaining the design intent.
    """
    func = routes.get_stats
    src = inspect.getsource(func)
    if func.__doc__:
        src_no_doc = src.replace(func.__doc__, "")
    else:  # pragma: no cover — docstring is present
        src_no_doc = src

    assert "setdefault(name, 0)" in src_no_doc, (
        "get_stats must pad collection_stats with "
        "setdefault(name, 0) over _collections — the load-bearing line "
        "for the ariadne--qe6 invariant total_collections == "
        "len(collections). Source (docstring stripped):\n" + src_no_doc
    )
    # The pad is meaningless if total_collections is still
    # len(_collections); pin that we report len(collection_stats).
    assert "len(collection_stats)" in src_no_doc, (
        "get_stats must report total_collections as len(collection_stats), "
        "not len(_collections). The pad alone is insufficient — both "
        "halves of the fix are load-bearing. Source (docstring stripped):\n"
        + src_no_doc
    )
