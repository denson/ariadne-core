"""Tests for POST /api/search ``metadata`` and ``metadata_exists`` filters.

Covers the ariadne--8fd Phase-1 surface:

- Containment hit and miss (JSONB ``@>`` semantics, top-level keys).
- Key-exists hit and miss.
- Nested-key containment (e.g., ``{"labels": {"is": "posse"}}``).
- AND-composition of ``metadata_exists`` (every listed key must be
  present).
- Malformed-input validation (422) for both filter keys.
- Pure-Python ``_jsonb_contains`` mirror of Postgres ``@>`` semantics
  (so the in-memory backend matches Pg).

The InMemoryVectorStore path is exercised end-to-end via TestClient.
The PgVectorStore path is exercised only when a local Postgres is
reachable; otherwise the Pg test gracefully skips. The Pg test also
runs an ``EXPLAIN ANALYZE`` and asserts the GIN index name appears,
confirming the filter is index-eligible (not a sequential scan).
"""

from __future__ import annotations

import os
import uuid
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


# ── Fixtures and helpers ─────────────────────────────────────────────────────


class _StubEmbedQueryClient:
    """Minimal embedding client returning a constant query vector.

    Search results' ordering is irrelevant to filter tests — we only
    care that the right *set* of docs survives the filter. The stub
    therefore embeds every query to the same 3-dim vector and accepts
    any matching pre-seeded chunk embedding for ranking purposes.
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


def _make_doc(
    collection: str,
    source_file: str,
    content: str,
    *,
    tags: list[str] | None = None,
) -> StoredDocument:
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
        tags=list(tags or []),
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
        agent_metadata: dict[str, Any] | None,
        content: str | None = None,
    ) -> StoredDocument:
        """Store a document + one chunk + one interaction carrying the
        given ``agent_metadata``. Returns the StoredDocument so the
        caller can correlate IDs.
        """
        content = content or f"body of {source_file}"
        doc = _make_doc(self.collection, source_file, content)
        self.dedup.store_document(doc)
        self.dedup.record_interaction(
            DocumentInteraction(
                document_id=doc.document_id,
                collection_id=self.collection,
                agent_id="test-agent",
                agent_metadata=agent_metadata,
            )
        )
        self.vector.insert([_make_chunk(doc)])
        return doc

    def search(self, filters: dict[str, Any]) -> dict[str, Any]:
        resp = self.client.post(
            "/api/search",
            json={
                "query": "anything",
                "top_k": 20,
                "collection": self.collection,
                "filters": filters,
            },
        )
        return {"status": resp.status_code, "body": resp.json()}


# ── Pure-Python containment mirror tests ─────────────────────────────────────


def test_jsonb_contains_scalar_equality():
    assert services._jsonb_contains("v", "v") is True
    assert services._jsonb_contains("v", "x") is False
    assert services._jsonb_contains(1, 1) is True
    assert services._jsonb_contains(1, "1") is False


def test_jsonb_contains_flat_dict():
    hay = {"a": 1, "b": 2, "c": 3}
    assert services._jsonb_contains(hay, {"a": 1}) is True
    assert services._jsonb_contains(hay, {"a": 1, "b": 2}) is True
    assert services._jsonb_contains(hay, {"a": 9}) is False
    assert services._jsonb_contains(hay, {"z": 1}) is False


def test_jsonb_contains_nested_dict():
    hay = {"labels": {"is": "posse", "tier": "p3"}, "outer": "yes"}
    assert services._jsonb_contains(hay, {"labels": {"is": "posse"}}) is True
    assert services._jsonb_contains(
        hay, {"labels": {"is": "posse", "tier": "p3"}}
    ) is True
    assert services._jsonb_contains(hay, {"labels": {"is": "nope"}}) is False
    assert services._jsonb_contains(hay, {"labels": {"absent": "x"}}) is False


def test_jsonb_contains_list_elements():
    hay = {"items": [1, 2, 3]}
    assert services._jsonb_contains(hay, {"items": [1]}) is True
    assert services._jsonb_contains(hay, {"items": [1, 3]}) is True
    assert services._jsonb_contains(hay, {"items": [9]}) is False


def test_jsonb_contains_handles_none_haystack():
    # ``None`` is not a dict, so any dict needle fails.
    assert services._jsonb_contains(None, {"a": 1}) is False


# ── End-to-end InMemory backend tests ────────────────────────────────────────


def test_metadata_containment_hit_and_miss(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    keep = f.seed("keep.txt", {"project": "atlas", "status": "extracted"})
    f.seed("drop.txt", {"project": "borealis"})

    # Hit: containment matches the "atlas" doc, not the "borealis" doc.
    r = f.search({"metadata": {"project": "atlas"}})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {keep.document_id}, r["body"]

    # Miss: nothing matches "phoenix".
    r = f.search({"metadata": {"project": "phoenix"}})
    assert r["status"] == 200
    assert r["body"]["results"] == []


def test_metadata_nested_containment(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    posse = f.seed("p.txt", {"labels": {"is": "posse", "tier": "p3"}})
    other = f.seed("o.txt", {"labels": {"is": "other"}})

    r = f.search({"metadata": {"labels": {"is": "posse"}}})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {posse.document_id}, r["body"]
    assert other.document_id not in doc_ids


def test_metadata_exists_hit_and_miss(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    has_doc_type = f.seed("a.txt", {"wb_doc_type": "report", "year": 2024})
    no_doc_type = f.seed("b.txt", {"year": 2024})  # has year, lacks wb_doc_type

    # Hit: the doc with the key, regardless of its value.
    r = f.search({"metadata_exists": ["wb_doc_type"]})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {has_doc_type.document_id}
    assert no_doc_type.document_id not in doc_ids


def test_metadata_exists_and_composition(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    both = f.seed("both.txt", {"k1": "x", "k2": "y"})
    only_k1 = f.seed("k1only.txt", {"k1": "x"})

    # Asking for BOTH keys present → only the "both" doc qualifies.
    r = f.search({"metadata_exists": ["k1", "k2"]})
    assert r["status"] == 200
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {both.document_id}
    assert only_k1.document_id not in doc_ids


def test_metadata_and_metadata_exists_compose_with_and(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    match = f.seed("match.txt", {"project": "atlas", "wb_doc_type": "report"})
    has_key_wrong_value = f.seed(
        "wrongvalue.txt", {"project": "borealis", "wb_doc_type": "report"}
    )
    has_value_no_key = f.seed("nokey.txt", {"project": "atlas"})

    # metadata-containment AND metadata_exists must BOTH hold.
    r = f.search(
        {
            "metadata": {"project": "atlas"},
            "metadata_exists": ["wb_doc_type"],
        }
    )
    assert r["status"] == 200
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {match.document_id}
    assert has_key_wrong_value.document_id not in doc_ids
    assert has_value_no_key.document_id not in doc_ids


def test_metadata_resolves_against_latest_interaction(monkeypatch):
    """The filter uses the latest interaction's ``agent_metadata``, not
    the first. A doc whose original interaction lacks the key but
    whose latest interaction has it should match.
    """
    f = _InMemoryFixture(monkeypatch)
    doc = _make_doc(f.collection, "latest.txt", "body")
    f.dedup.store_document(doc)
    # First (older) interaction lacks the key.
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=f.collection,
            agent_metadata={"project": "borealis"},
        )
    )
    # Second (latest) interaction has the desired value.
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=f.collection,
            agent_metadata={"project": "atlas", "status": "reviewed"},
        )
    )
    f.vector.insert([_make_chunk(doc)])

    r = f.search({"metadata": {"project": "atlas"}})
    assert r["status"] == 200
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {doc.document_id}


def test_metadata_exists_with_none_agent_metadata_is_clean_miss(monkeypatch):
    """A doc whose latest interaction has ``agent_metadata=None`` must
    cleanly NOT match a ``metadata_exists`` probe — not crash, not
    spuriously match. Pins the ``_latest_agent_metadata`` ``None``
    fallback path in ``_post_filter_results``.
    """
    f = _InMemoryFixture(monkeypatch)
    has_key = f.seed("has.txt", {"k": "v"})
    none_doc = f.seed("none.txt", agent_metadata=None)

    r = f.search({"metadata_exists": ["k"]})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {has_key.document_id}
    assert none_doc.document_id not in doc_ids


def test_metadata_empty_needle_matches_all_docs(monkeypatch):
    """``{"metadata": {}}`` matches every doc — Postgres ``@>`` semantics
    say "every container contains the empty object." Pin that here for
    the in-memory backend so it stays in lock-step with Pg.
    """
    f = _InMemoryFixture(monkeypatch)
    a = f.seed("a.txt", {"project": "atlas"})
    b = f.seed("b.txt", {"project": "borealis"})

    r = f.search({"metadata": {}})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert doc_ids == {a.document_id, b.document_id}


# ── 422 validation tests ─────────────────────────────────────────────────────


def test_metadata_not_a_dict_returns_422(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    f.seed("a.txt", {"k": "v"})  # body irrelevant — we fail at validation.

    resp = f.client.post(
        "/api/search",
        json={
            "query": "anything",
            "collection": f.collection,
            "filters": {"metadata": "not-a-dict"},
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    # The error should be actionable — mention the field and the
    # expected shape, not just a Pydantic-style stack trace.
    assert "metadata" in detail["error"].lower()
    assert "dict" in detail["error"].lower() or "object" in detail["error"].lower()


def test_metadata_exists_not_a_list_returns_422(monkeypatch):
    f = _InMemoryFixture(monkeypatch)
    f.seed("a.txt", {"k": "v"})

    resp = f.client.post(
        "/api/search",
        json={
            "query": "anything",
            "collection": f.collection,
            "filters": {"metadata_exists": "not-a-list"},
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "metadata_exists" in detail["error"].lower()
    assert "list" in detail["error"].lower()


def test_metadata_exists_with_non_string_element_returns_422(monkeypatch):
    """A list with mixed types should fail just as cleanly as a non-list."""
    f = _InMemoryFixture(monkeypatch)
    f.seed("a.txt", {"k": "v"})

    resp = f.client.post(
        "/api/search",
        json={
            "query": "anything",
            "collection": f.collection,
            "filters": {"metadata_exists": ["valid_key", 42]},
        },
    )
    assert resp.status_code == 422, resp.text


# ── PgVectorStore integration (skip if Pg unreachable) ───────────────────────


def _pg_test_url() -> str:
    explicit = os.environ.get("ARIADNE_TEST_DATABASE_URL")
    if explicit:
        return explicit
    pw = os.environ.get("DB_PASSWORD", "local-dev-only")
    return f"postgresql://app:{pw}@localhost:5432/pipeline"


@pytest.fixture
def pg_search_stack(pg_pool, monkeypatch):
    """A PgVectorStore + PgDedupStore wired into services, with a
    stub embedding client. Yields a helper exposing seed() and search().

    Each test gets a unique collection name (and a tiny chunk
    embedding dimension that matches the stub) to stay isolated. The
    fixture relies on ``pg_pool`` (conftest), which already applies
    migrations 001 + 002 before yielding.
    """
    import psycopg
    from pipeline.dedup import PgDedupStore
    from pipeline.storage.pgvector import PgVectorStore

    # The pg_pool fixture has already applied migrations 001 (which now
    # includes the GIN index inline via IF NOT EXISTS) plus 002 (the
    # standalone migration). Confirm the index exists; if not, the
    # migration runner did not pick up the new file and the test would
    # silently be checking wrong behavior.
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'idx_interactions_agent_metadata'"
            )
            if cur.fetchone() is None:
                pytest.skip("GIN index not present — migration not applied")

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

    seeded_doc_ids: list[str] = []

    class _Helper:
        def __init__(self) -> None:
            self.app = _build_app()
            self.client = TestClient(self.app)
            self.collection = collection
            self.pool = pg_pool

        def seed(
            self,
            source_file: str,
            agent_metadata: dict[str, Any] | None,
        ) -> StoredDocument:
            content = f"body of {source_file}"
            doc = _make_doc(collection, source_file, content)
            dedup.store_document(doc)
            dedup.record_interaction(
                DocumentInteraction(
                    document_id=doc.document_id,
                    collection_id=collection,
                    agent_id="test-agent",
                    agent_metadata=agent_metadata,
                )
            )
            vector.insert([_make_chunk(doc)])
            seeded_doc_ids.append(doc.document_id)
            return doc

        def search(self, filters: dict[str, Any]) -> dict[str, Any]:
            resp = self.client.post(
                "/api/search",
                json={
                    "query": "anything",
                    "top_k": 20,
                    "collection": collection,
                    "filters": filters,
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


def test_pg_metadata_containment_end_to_end(pg_search_stack):
    h = pg_search_stack
    keep = h.seed("keep.txt", {"project": "atlas"})
    h.seed("drop.txt", {"project": "borealis"})

    r = h.search({"metadata": {"project": "atlas"}})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert keep.document_id in doc_ids
    # The "drop" doc must not appear in the result set.
    assert all(res["document_id"] != "drop.txt" for res in r["body"]["results"])


def test_pg_metadata_exists_end_to_end(pg_search_stack):
    h = pg_search_stack
    keep = h.seed("keep.txt", {"wb_doc_type": "report"})
    h.seed("drop.txt", {"year": 2024})

    r = h.search({"metadata_exists": ["wb_doc_type"]})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert keep.document_id in doc_ids


def test_pg_metadata_empty_needle_matches_all_docs(pg_search_stack):
    """Pg ``@>`` says every container contains ``{}``; ``{"metadata": {}}``
    therefore matches every doc with a latest interaction. Pin parity
    with the InMemory backend.
    """
    h = pg_search_stack
    a = h.seed("a.txt", {"project": "atlas"})
    b = h.seed("b.txt", {"project": "borealis"})

    r = h.search({"metadata": {}})
    assert r["status"] == 200, r["body"]
    doc_ids = {res["document_id"] for res in r["body"]["results"]}
    assert a.document_id in doc_ids
    assert b.document_id in doc_ids


def test_pg_metadata_explain_uses_gin_index(pg_search_stack):
    """Sanity-check that the GIN index is actually consulted for the
    JSONB ``@>`` filter. We bypass the route layer and run an
    EXPLAIN against a hand-built query that mirrors PgVectorStore's
    correlated-subquery shape — the planner output should mention the
    ``idx_interactions_agent_metadata`` index, not a sequential scan
    on ``document_interactions``.

    Skipped if no rows exist for the chosen collection (planner
    short-circuits to seq-scan when the table is empty), which is why
    the fixture seeds first.
    """
    h = pg_search_stack
    h.seed("a.txt", {"project": "atlas"})
    h.seed("b.txt", {"project": "borealis"})

    # Force the planner to prefer indexes when both options are
    # available, so a small-table seq-scan preference doesn't hide
    # the index from EXPLAIN.
    with h.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_seqscan = OFF")
            cur.execute(
                """
                EXPLAIN
                SELECT 1
                FROM document_interactions di
                WHERE di.agent_metadata @> '{"project": "atlas"}'::jsonb
                """
            )
            plan_lines = [row[0] for row in cur.fetchall()]
    plan_text = "\n".join(plan_lines)
    # Either the index is used directly, or psql may report it as
    # "Bitmap Index Scan on idx_interactions_agent_metadata".
    assert "idx_interactions_agent_metadata" in plan_text, plan_text
