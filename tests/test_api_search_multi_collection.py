"""Tests for ``POST /api/search`` multi-collection support (ariadne--wgi).

Adds the ``collections`` top-level field (list of slugs) alongside the
existing ``collection`` (single string). Mutually exclusive at the
request layer; both rejected with 422 when set together. Empty list
rejected; per-element slug allow-list enforced.

Backend coverage:
  • In-memory store via ``_apply_filters['collection_in']`` is exercised
    end-to-end with TestClient.
  • Pg backend ``WHERE col.name = ANY(%(...)s)`` is exercised inline
    when a live Postgres is reachable; skipped otherwise.

Search-log persistence:
  • ``SearchLogEntry`` gains a ``collections`` field; the in-memory
    store appends as-is so the entry is observable for assertions.
"""

from __future__ import annotations

import uuid
import os
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.routes import router
from pipeline.chunking.chunker import Chunk
from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# ── Fixtures ────────────────────────────────────────────────────────────────


class _StubEmbedQueryClient:
    """Constant query vector — collection filtering is orthogonal to
    similarity ranking, so a stub is sufficient.
    """

    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_query(self, _q: str) -> list[float]:
        return [0.1, 0.2, 0.3]


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


def _make_doc(collection: str, source_file: str, content: str) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint(content.encode("utf-8")),
        file_type="txt",
        engine="markitdown",
        markdown=content,
        title=source_file,
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[],
        tags=[],
        warnings=[],
    )


def _make_chunk(doc: StoredDocument, idx: int = 0) -> Chunk:
    return Chunk(
        chunk_id=f"{doc.document_id}-chunk-{idx:04d}",
        document_id=doc.document_id,
        collection_id=doc.collection_id,
        chunk_index=idx,
        text=doc.markdown,
        section=None,
        page_start=None,
        page_end=None,
        token_count=10,
        embedding_model="stub-model",
        embedding=[0.1, 0.2, 0.3],
        metadata={},
    )


@pytest.fixture
def stub_in_memory(monkeypatch):
    """Fresh in-memory stores + a stub embed client, exposed as a small
    namespace object for use by the multi-collection tests.

    Seeds three collections (``coll-a``, ``coll-b``, ``coll-c``) with one
    chunk each so the multi-collection filter is observably narrowing
    the candidate set.
    """
    app = _build_app()
    client = TestClient(app)
    dedup = InMemoryDedupStore()
    vector = InMemoryVectorStore()
    services.configure_stores(dedup, vector)
    monkeypatch.setattr(services, "_embedding_client", _StubEmbedQueryClient())

    # Suffix collection names with a uuid hash so reruns / parallel
    # workers don't collide if the in-memory stores ever become shared.
    suffix = uuid.uuid4().hex[:6]
    colls = {
        "a": f"coll-a-{suffix}",
        "b": f"coll-b-{suffix}",
        "c": f"coll-c-{suffix}",
    }

    docs: dict[str, StoredDocument] = {}
    for key, coll in colls.items():
        doc = _make_doc(coll, f"file-{key}.txt", f"body of {key}")
        dedup.store_document(doc)
        dedup.record_interaction(
            DocumentInteraction(
                document_id=doc.document_id,
                collection_id=coll,
                agent_id="test-agent",
            )
        )
        vector.insert([_make_chunk(doc)])
        docs[key] = doc

    class _Stub:
        pass

    s = _Stub()
    s.app = app
    s.client = client
    s.dedup = dedup
    s.vector = vector
    s.colls = colls
    s.docs = docs
    return s


# ── Happy path — multi-collection narrows the result set ──────────────────


def test_multi_collection_returns_only_listed_collections(stub_in_memory):
    """A search with ``collections: [coll-a, coll-b]`` returns hits from
    coll-a and coll-b but NOT coll-c (three collections seeded; one
    chunk per collection).
    """
    s = stub_in_memory
    resp = s.client.post(
        "/api/search",
        json={
            "query": "anything",
            "top_k": 20,
            "collections": [s.colls["a"], s.colls["b"]],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned = {r["collection"] for r in body["results"]}
    assert s.colls["a"] in returned
    assert s.colls["b"] in returned
    assert s.colls["c"] not in returned
    assert body["results_count"] == 2


def test_multi_collection_response_echoes_collections_field(stub_in_memory):
    """The response includes both ``collection`` (null when ``collections``
    was used) and ``collections`` (the list the caller sent).
    """
    s = stub_in_memory
    payload = {
        "query": "anything",
        "top_k": 5,
        "collections": [s.colls["a"], s.colls["b"]],
    }
    resp = s.client.post("/api/search", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["collection"] is None
    assert body["collections"] == [s.colls["a"], s.colls["b"]]


def test_multi_collection_records_collections_on_search_log(stub_in_memory):
    """The in-memory search log appends a ``SearchLogEntry`` carrying the
    ``collections`` list AND a ``filters['collection_in']`` mirror.
    """
    s = stub_in_memory
    pre = len(s.dedup._search_log)
    resp = s.client.post(
        "/api/search",
        json={
            "query": "anything",
            "collections": [s.colls["a"], s.colls["b"]],
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(s.dedup._search_log) == pre + 1
    entry = s.dedup._search_log[-1]
    assert entry.collection is None
    assert entry.collections == [s.colls["a"], s.colls["b"]]
    # ``collection_in`` flows into the persisted filters dict.
    assert entry.filters is not None
    assert entry.filters.get("collection_in") == [s.colls["a"], s.colls["b"]]


# ── 422 — mutually-exclusive fields ────────────────────────────────────────


def test_both_collection_and_collections_returns_422(stub_in_memory):
    """Setting both ``collection`` and ``collections`` is 422 with the
    documented error code in the detail message.
    """
    s = stub_in_memory
    resp = s.client.post(
        "/api/search",
        json={
            "query": "x",
            "collection": s.colls["a"],
            "collections": [s.colls["b"]],
        },
    )
    assert resp.status_code == 422, resp.text
    # Pydantic v2 surfaces ValueError messages under detail[0].msg or
    # under the structured envelope. Grep the whole response.
    assert "mutually_exclusive_collections" in resp.text


# ── 422 — empty list ───────────────────────────────────────────────────────


def test_empty_collections_list_returns_422(stub_in_memory):
    """An empty ``collections: []`` list is rejected (ambiguous: caller
    meant ``None`` to get the no-filter case).
    """
    s = stub_in_memory
    resp = s.client.post(
        "/api/search",
        json={
            "query": "x",
            "collections": [],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "empty_collections_list" in resp.text


# ── 422 — bad slug in the collections list ────────────────────────────────


@pytest.mark.parametrize(
    "bad_slug",
    [
        "UPPERCASE",
        "foo.bar",          # dots
        "foo/bar",          # slash
        "a" * 65,           # over max length
        "foo@bar",          # @
    ],
)
def test_invalid_slug_in_collections_returns_422(stub_in_memory, bad_slug):
    """Each element of ``collections`` must match the slug allow-list."""
    s = stub_in_memory
    resp = s.client.post(
        "/api/search",
        json={
            "query": "x",
            "collections": [s.colls["a"], bad_slug],
        },
    )
    assert resp.status_code == 422, (
        f"Bad slug {bad_slug!r} in collections list should be 422; "
        f"got {resp.status_code}: {resp.text}"
    )
    assert "invalid_collection_slug" in resp.text


# ── Back-compat — single ``collection`` still works as before ──────────────


def test_single_collection_backwards_compat(stub_in_memory):
    """A request with only ``collection`` (the pre-wgi shape) returns
    the same hits it always did, with ``collection`` echoed and
    ``collections`` null in the response.
    """
    s = stub_in_memory
    resp = s.client.post(
        "/api/search",
        json={
            "query": "anything",
            "collection": s.colls["a"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned = {r["collection"] for r in body["results"]}
    assert returned == {s.colls["a"]}
    assert body["collection"] == s.colls["a"]
    assert body["collections"] is None


def test_single_collection_no_collections_field_returns_collection(
    stub_in_memory,
):
    """Pre-wgi callers send neither field → the route returns all
    collections with both echo fields null.
    """
    s = stub_in_memory
    resp = s.client.post("/api/search", json={"query": "anything"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["collection"] is None
    assert body["collections"] is None
    # All three collections appear.
    returned = {r["collection"] for r in body["results"]}
    assert returned == set(s.colls.values())


# ── Pg backend — opt-in (skipped when no Postgres) ────────────────────────


@pytest.fixture
def pg_search_fixture(monkeypatch, pg_dedup_store, pg_pool):
    """Wire a real PgVectorStore + PgDedupStore into services so the
    multi-collection ``collection_in`` filter is exercised through the
    real ``WHERE col.name = ANY(...)`` SQL path.

    Skips automatically when Postgres is unreachable (the pg_dedup_store
    fixture is the gating dependency).
    """
    from pipeline.storage.pgvector import PgVectorStore

    pg_vector = PgVectorStore(pg_pool)
    services.configure_stores(pg_dedup_store, pg_vector)
    monkeypatch.setattr(services, "_embedding_client", _StubEmbedQueryClient())

    app = _build_app()
    client = TestClient(app)

    # Two collections with a unique-per-test suffix so reruns don't
    # collide with prior search-log rows.
    suffix = uuid.uuid4().hex[:8]
    colls = {
        "a": f"wgi-a-{suffix}",
        "b": f"wgi-b-{suffix}",
        "c": f"wgi-c-{suffix}",
    }

    docs: dict[str, StoredDocument] = {}
    for key, coll in colls.items():
        doc = _make_doc(coll, f"file-{key}.txt", f"body of {key}")
        pg_dedup_store.store_document(doc)
        pg_vector.insert([_make_chunk(doc)])
        docs[key] = doc

    class _PgFixture:
        pass

    f = _PgFixture()
    f.app = app
    f.client = client
    f.colls = colls
    f.docs = docs
    return f


def test_pg_multi_collection_filter_narrows_results(pg_search_fixture):
    """Run the multi-collection search against the Pg backend and confirm
    the ``ANY(...)`` WHERE clause restricts results to the listed
    collections only. Skipped automatically when Pg is unreachable.
    """
    f = pg_search_fixture
    resp = f.client.post(
        "/api/search",
        json={
            "query": "anything",
            "top_k": 20,
            "collections": [f.colls["a"], f.colls["b"]],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned = {r["collection"] for r in body["results"]}
    # coll-c must NOT appear; coll-a and coll-b should.
    assert f.colls["c"] not in returned
    # Both of a and b should be present (one chunk seeded per collection).
    assert f.colls["a"] in returned
    assert f.colls["b"] in returned
