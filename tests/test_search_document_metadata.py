"""Tests for POST /api/search surfacing ``documents.metadata`` per result.

Covers the ariadne--uuo.3 surface: the search route now returns a
``metadata`` object on every result entry, carrying the *owning
document's* structured metadata (``documents.metadata`` in Pg /
``InMemoryDedupStore._doc_metadata`` in the in-memory backend) — the
dict folded in at ingest via ``store_document(agent_metadata=...)``.

This is distinct from the existing ``metadata`` *filter*
(test_search_metadata_filter.py), which resolves against the latest
*interaction's* ``agent_metadata``. Here we assert the document-level
metadata is *returned in the result shape*, and that the Pg and
in-memory backends return the same shape.

The InMemoryVectorStore path is exercised end-to-end via TestClient.
The PgVectorStore path is exercised only when a local Postgres is
reachable; otherwise the Pg test gracefully skips.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.routes import router
from pipeline.chunking.chunker import Chunk
from pipeline.dedup import (
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


# ── Fixtures and helpers ─────────────────────────────────────────────────────


class _StubEmbedQueryClient:
    """Minimal embedding client returning a constant query vector."""

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


class _InMemoryFixture:
    """Fresh in-memory stores + mounted FastAPI + TestClient + stub embed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app)
        self.dedup = InMemoryDedupStore()
        self.vector = InMemoryVectorStore()
        services.configure_stores(self.dedup, self.vector)
        monkeypatch.setattr(services, "_embedding_client", _StubEmbedQueryClient())
        self.collection = f"t_{uuid.uuid4().hex[:8]}"

    def seed(
        self,
        source_file: str,
        document_metadata: dict[str, Any] | None,
    ) -> StoredDocument:
        """Store a document + one chunk. ``document_metadata`` is folded
        into ``documents.metadata`` via ``store_document(agent_metadata=)``
        — exactly the path bw ingest uses. Returns the StoredDocument so
        the caller can correlate IDs.
        """
        content = f"body of {source_file}"
        doc = _make_doc(self.collection, source_file, content)
        self.dedup.store_document(doc, agent_metadata=document_metadata)
        self.vector.insert([_make_chunk(doc)])
        return doc

    def search(self) -> dict[str, Any]:
        resp = self.client.post(
            "/api/search",
            json={
                "query": "anything",
                "top_k": 20,
                "collection": self.collection,
            },
        )
        return {"status": resp.status_code, "body": resp.json()}


# ── End-to-end InMemory backend tests ────────────────────────────────────────


def test_search_result_includes_document_metadata(monkeypatch):
    """A bw-style ingested doc surfaces its full ``documents.metadata``
    object (ticket_id / bw_status / source_type) on the search result.
    """
    f = _InMemoryFixture(monkeypatch)
    seeded_meta = {
        "ticket_id": "ariadne--uuo",
        "bw_status": "open",
        "source_type": "bw_ticket",
    }
    doc = f.seed("ariadne--uuo.md", seeded_meta)

    r = f.search()
    assert r["status"] == 200, r["body"]
    results = r["body"]["results"]
    assert len(results) == 1, r["body"]

    res = results[0]
    assert res["document_id"] == doc.document_id
    # The key is present...
    assert "metadata" in res, res
    # ...and matches the doc's seeded metadata exactly.
    assert res["metadata"] == seeded_meta


def test_search_result_metadata_is_empty_dict_when_unseeded(monkeypatch):
    """A doc ingested with no structured metadata still gets a ``metadata``
    key — an empty object, never missing and never ``None``. Keeps the
    result shape uniform for clients (uuo-4 CLI degrades gracefully on {}).
    """
    f = _InMemoryFixture(monkeypatch)
    doc = f.seed("plain.txt", None)

    r = f.search()
    assert r["status"] == 200, r["body"]
    results = r["body"]["results"]
    assert len(results) == 1, r["body"]

    res = results[0]
    assert res["document_id"] == doc.document_id
    assert res["metadata"] == {}


def test_search_result_metadata_is_per_document(monkeypatch):
    """Each result carries its *own* document's metadata — no cross-talk
    between documents in a multi-result response.
    """
    f = _InMemoryFixture(monkeypatch)
    a = f.seed("a.md", {"ticket_id": "ariadne--aaa", "bw_status": "open"})
    b = f.seed("b.md", {"ticket_id": "ariadne--bbb", "bw_status": "closed"})

    r = f.search()
    assert r["status"] == 200, r["body"]
    by_id = {res["document_id"]: res["metadata"] for res in r["body"]["results"]}
    assert by_id[a.document_id] == {"ticket_id": "ariadne--aaa", "bw_status": "open"}
    assert by_id[b.document_id] == {
        "ticket_id": "ariadne--bbb",
        "bw_status": "closed",
    }


# ── PgVectorStore integration (skip if Pg unreachable) ───────────────────────


@pytest.fixture
def pg_metadata_stack(pg_pool, monkeypatch):
    """A PgVectorStore + PgDedupStore wired into services with a stub
    embed client. Yields a helper exposing seed() and search(). Mirrors
    the pg_search_stack fixture in test_search_metadata_filter.py.
    """
    from pipeline.dedup import PgDedupStore
    from pipeline.storage.pgvector import PgVectorStore

    dedup = PgDedupStore(pg_pool)
    vector = PgVectorStore(pg_pool)
    services.configure_stores(dedup, vector)
    monkeypatch.setattr(services, "_embedding_client", _StubEmbedQueryClient())

    collection = f"t_{uuid.uuid4().hex[:8]}"

    # Ensure collection row exists for the FK on chunks.collection_id.
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO collections (name) VALUES (%s) "
                "ON CONFLICT (name) DO NOTHING",
                (collection,),
            )
        conn.commit()

    class _Helper:
        def __init__(self) -> None:
            self.app = _build_app()
            self.client = TestClient(self.app)
            self.collection = collection

        def seed(
            self,
            source_file: str,
            document_metadata: dict[str, Any] | None,
        ) -> StoredDocument:
            content = f"body of {source_file}"
            doc = _make_doc(collection, source_file, content)
            dedup.store_document(doc, agent_metadata=document_metadata)
            vector.insert([_make_chunk(doc)])
            return doc

        def search(self) -> dict[str, Any]:
            resp = self.client.post(
                "/api/search",
                json={
                    "query": "anything",
                    "top_k": 20,
                    "collection": collection,
                },
            )
            return {"status": resp.status_code, "body": resp.json()}

    yield _Helper()

    # Teardown: purge the test collection so repeated runs stay clean.
    try:
        dedup.soft_delete_collection(collection)
        dedup.purge_deleted(older_than_hours=0)
    except Exception:
        pass


def test_pg_search_result_includes_document_metadata(pg_metadata_stack):
    """Pg backend surfaces the same ``metadata`` object shape as the
    in-memory backend — the in-SQL ``d.metadata`` path.
    """
    h = pg_metadata_stack
    seeded_meta = {
        "ticket_id": "ariadne--uuo",
        "bw_status": "open",
        "source_type": "bw_ticket",
    }
    doc = h.seed("ariadne--uuo.md", seeded_meta)

    r = h.search()
    assert r["status"] == 200, r["body"]
    match = [
        res for res in r["body"]["results"] if res["document_id"] == doc.document_id
    ]
    assert len(match) == 1, r["body"]
    assert match[0]["metadata"] == seeded_meta


def test_pg_search_result_metadata_empty_when_unseeded(pg_metadata_stack):
    """Pg backend returns ``{}`` (not null, not missing) for a doc
    ingested without structured metadata — parity with in-memory.
    """
    h = pg_metadata_stack
    doc = h.seed("plain.txt", None)

    r = h.search()
    assert r["status"] == 200, r["body"]
    match = [
        res for res in r["body"]["results"] if res["document_id"] == doc.document_id
    ]
    assert len(match) == 1, r["body"]
    assert match[0]["metadata"] == {}
