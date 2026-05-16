"""Tests for search_log.collections first-class column (ariadne--2cf).

Promotes the multi-collection scope from JSONB-only (recoverable from
``filters['collection_in']``) to a dedicated TEXT[] column with a GIN
index. Three persistence cases:

  • Multi-collection search → ``collections`` populated.
  • Single-collection search → ``collections IS NULL``.
  • No-collection search → ``collections IS NULL``.

In-memory store behavior is unchanged — the dataclass field has carried
the list since ariadne--wgi; the schema-shape concern is Pg-only.

Pg fixture is skipped automatically when no live Postgres is reachable
(same gating dependency as the rest of the suite's Pg tests).
"""

from __future__ import annotations

import uuid

import pytest

from pipeline.dedup import SearchLogEntry


# ── In-memory parity check — dataclass field unchanged ───────────────────


def test_in_memory_search_log_carries_collections():
    """The InMemoryDedupStore appends SearchLogEntry verbatim — collections
    field is observable on the appended entry. This is the wgi-era
    contract and 2cf does not regress it."""
    from pipeline.dedup import InMemoryDedupStore

    store = InMemoryDedupStore()
    entry = SearchLogEntry(
        query="q",
        collection=None,
        collections=["alpha", "beta"],
        filters={"collection_in": ["alpha", "beta"]},
        top_k=5,
        results_count=0,
        result_document_ids=[],
    )
    store.record_search(entry)
    assert len(store._search_log) == 1
    assert store._search_log[-1].collections == ["alpha", "beta"]


# ── Pg gated — column populated for multi-collection searches ─────────────


@pytest.fixture
def fresh_collection_slug():
    return f"vis2cf-{uuid.uuid4().hex[:8]}"


def _read_back(pool, entry_id: str) -> dict:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT collection, collections, filters
                FROM search_log
                WHERE id = %(id)s::uuid
                """,
                {"id": entry_id},
            )
            row = cur.fetchone()
    assert row is not None, f"search_log row {entry_id} not found"
    return {"collection": row[0], "collections": row[1], "filters": row[2]}


def test_pg_record_search_writes_collections_column_for_multi_scope(
    pg_dedup_store, pg_pool, fresh_collection_slug
):
    """Multi-collection search → ``collections`` populated as a real TEXT[]
    column (not just JSONB)."""
    slug_a = fresh_collection_slug
    slug_b = f"{fresh_collection_slug}-b"
    entry = SearchLogEntry(
        query="multi",
        collection=None,
        collections=[slug_a, slug_b],
        filters={"collection_in": [slug_a, slug_b]},
        top_k=10,
        results_count=0,
        result_document_ids=[],
    )
    pg_dedup_store.record_search(entry)
    got = _read_back(pg_pool, entry.id)
    assert got["collection"] is None
    assert got["collections"] == [slug_a, slug_b]
    # JSONB still carries the scope (we did not remove the filter mechanism)
    assert got["filters"] is not None
    assert got["filters"].get("collection_in") == [slug_a, slug_b]


def test_pg_record_search_collections_null_for_single_scope(
    pg_dedup_store, pg_pool, fresh_collection_slug
):
    """Single-collection search → ``collections IS NULL`` (the single-scope
    column remains the dispatch surface)."""
    entry = SearchLogEntry(
        query="single",
        collection=fresh_collection_slug,
        collections=None,
        filters=None,
        top_k=5,
        results_count=0,
        result_document_ids=[],
    )
    pg_dedup_store.record_search(entry)
    got = _read_back(pg_pool, entry.id)
    assert got["collection"] == fresh_collection_slug
    assert got["collections"] is None


def test_pg_record_search_collections_null_for_no_scope(
    pg_dedup_store, pg_pool
):
    """No-collection search → both columns NULL."""
    entry = SearchLogEntry(
        query="any",
        collection=None,
        collections=None,
        filters=None,
        top_k=5,
        results_count=0,
        result_document_ids=[],
    )
    pg_dedup_store.record_search(entry)
    got = _read_back(pg_pool, entry.id)
    assert got["collection"] is None
    assert got["collections"] is None


def test_pg_search_log_collections_gin_index_present(pg_pool):
    """Verify the GIN index exists after migration. Without it the
    ``'X' = ANY(collections)`` query in the analytics surface would
    fall back to a sequential scan; the index is the whole point of
    promoting the column."""
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'search_log'
                  AND indexname = 'idx_search_log_collections'
                """
            )
            row = cur.fetchone()
    assert row is not None, (
        "idx_search_log_collections GIN index missing — migration 004 "
        "(or its 001 fold-forward) did not apply"
    )


def test_pg_collections_any_query_returns_seeded_rows(
    pg_dedup_store, pg_pool, fresh_collection_slug
):
    """Round-trip: insert a multi-collection row, then query for it via
    the ``ANY(collections)`` shape that drives the analytics SQL in
    SPEC.md § Search Log."""
    target = f"target-{fresh_collection_slug}"
    other = f"other-{fresh_collection_slug}"
    entry = SearchLogEntry(
        query="analytics-probe",
        collection=None,
        collections=[target, other],
        filters={"collection_in": [target, other]},
        top_k=5,
        results_count=0,
        result_document_ids=[],
    )
    pg_dedup_store.record_search(entry)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM search_log
                WHERE %(target)s = ANY(collections)
                  AND id = %(id)s::uuid
                """,
                {"target": target, "id": entry.id},
            )
            count = cur.fetchone()[0]
    assert count == 1, (
        f"ANY(collections) lookup did not find the seeded row "
        f"(slug={target}, id={entry.id})"
    )
