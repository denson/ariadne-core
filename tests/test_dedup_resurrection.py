"""Regression tests for the Phase 8 ghost-write bug.

The bug: PgDedupStore.store_document's ON CONFLICT clause updated the
row's content columns but did not clear deleted_at / deletion_scheduled_at.
A re-ingest of a soft-deleted fingerprint returned store_status="stored"
with the prior UUID, while the row stayed invisible to every default
query. Phase 8 hit it on all 558 "successful" ingests.

These tests lock in:
  1. A fresh re-ingest after soft-delete resurrects the row and makes it
     visible to find_by_fingerprint again.
  2. The returned was_resurrected flag is True in that case and False on
     a plain fresh insert.
  3. The underlying SQL row has deleted_at IS NULL after resurrection.
  4. The parallel InMemoryDedupStore contract matches.
"""

from __future__ import annotations

import pytest

from pipeline.dedup import (
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)


def _make_stored_doc(
    collection: str,
    content: bytes,
    *,
    document_id: str | None = None,
) -> StoredDocument:
    import uuid
    fp = compute_fingerprint(content.decode("utf-8", errors="replace"))
    return StoredDocument(
        document_id=document_id or str(uuid.uuid4()),
        collection_id=collection,
        source_file="test_resurrection.txt",
        content_fingerprint=fp,
        file_type="txt",
        engine="markitdown",
        markdown=content.decode("utf-8", errors="replace"),
        title="Resurrection test",
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[{"step": "extraction", "tool": "markitdown"}],
        tags=[],
    )


# ── InMemoryDedupStore parity tests (run without Pg) ─────────────────────────


class TestInMemoryResurrection:
    """Mirror of the Pg tests below. Locks the contract on the InMemory
    backend too so developers without Postgres still get coverage."""

    def test_fresh_insert_returns_false(self):
        store = InMemoryDedupStore()
        doc = _make_stored_doc("coll_a", b"hello world")
        was_resurrected = store.store_document(doc)
        assert was_resurrected is False
        assert store.find_by_fingerprint("coll_a", doc.content_fingerprint) is not None

    def test_upsert_of_non_deleted_doc_returns_false(self):
        store = InMemoryDedupStore()
        doc = _make_stored_doc("coll_a", b"hello world")
        store.store_document(doc)
        doc2 = _make_stored_doc("coll_a", b"hello world")
        was_resurrected = store.store_document(doc2)
        assert was_resurrected is False

    def test_reingest_after_soft_delete_resurrects(self):
        store = InMemoryDedupStore()
        doc = _make_stored_doc("coll_a", b"hello world")
        store.store_document(doc)
        fp = doc.content_fingerprint

        # Soft-delete via collection-level delete
        marked = store.soft_delete_collection("coll_a")
        assert marked == 1
        assert store.find_by_fingerprint("coll_a", fp) is None
        assert store.find_by_fingerprint("coll_a", fp, include_deleted=True) is not None

        # Re-ingest identical content — was_resurrected must be True
        doc2 = _make_stored_doc("coll_a", b"hello world")
        was_resurrected = store.store_document(doc2)
        assert was_resurrected is True

        # Default query must find it again
        found = store.find_by_fingerprint("coll_a", fp)
        assert found is not None, "Re-ingest after soft-delete must resurrect the row"


# ── Pg integration tests (skipped if Postgres unreachable) ────────────────────


class TestPgResurrection:
    """Integration tests against a real Postgres. Require a running Pg
    (docker compose up -d postgres) OR ARIADNE_TEST_DATABASE_URL set.
    Otherwise the `pg_dedup_store` fixture skips cleanly."""

    def test_re_ingest_after_soft_delete_resurrects_row(
        self, pg_dedup_store, unique_collection
    ):
        """Phase 8 regression: identical content re-ingested after a
        collection soft-delete must be visible again."""
        content = b"resurrection test content " + unique_collection.encode()
        doc = _make_stored_doc(unique_collection, content)

        was_new = pg_dedup_store.store_document(doc)
        assert was_new is False, "first insert is not a resurrection"

        fp = doc.content_fingerprint
        found = pg_dedup_store.find_by_fingerprint(unique_collection, fp)
        assert found is not None
        original_doc_id = found.document_id

        marked = pg_dedup_store.soft_delete_collection(unique_collection)
        assert marked == 1
        assert pg_dedup_store.find_by_fingerprint(unique_collection, fp) is None
        assert (
            pg_dedup_store.find_by_fingerprint(
                unique_collection, fp, include_deleted=True
            )
            is not None
        )

        doc2 = _make_stored_doc(unique_collection, content)
        was_resurrected = pg_dedup_store.store_document(doc2)
        assert was_resurrected is True, (
            "Re-ingest after soft-delete must report was_resurrected=True"
        )

        found2 = pg_dedup_store.find_by_fingerprint(unique_collection, fp)
        assert found2 is not None, (
            "Re-ingest after soft-delete must resurrect the row "
            "(Phase 8 regression)"
        )
        assert found2.document_id == original_doc_id, (
            "Resurrected row must keep the original UUID (ON CONFLICT "
            "preserves id)"
        )

    def test_deleted_at_is_null_after_resurrection(
        self, pg_dedup_store, unique_collection, pg_pool
    ):
        """Direct SQL check: the row's deleted_at column must be NULL
        after an upsert over a soft-deleted row."""
        content = b"sql-level resurrection check " + unique_collection.encode()
        doc = _make_stored_doc(unique_collection, content)
        pg_dedup_store.store_document(doc)

        pg_dedup_store.soft_delete_collection(unique_collection)

        doc2 = _make_stored_doc(unique_collection, content)
        pg_dedup_store.store_document(doc2)

        # Peek at the raw row.
        with pg_pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.deleted_at, d.deletion_scheduled_at
                FROM documents d
                JOIN collections col ON d.collection_id = col.id
                WHERE col.name = %(c)s
                  AND d.content_fingerprint = %(fp)s
                """,
                {"c": unique_collection, "fp": doc.content_fingerprint},
            )
            row = cur.fetchone()

        assert row is not None
        deleted_at, deletion_scheduled_at = row
        assert deleted_at is None, (
            "deleted_at must be NULL after resurrection; ON CONFLICT "
            "DO UPDATE must include `deleted_at = NULL`"
        )
        assert deletion_scheduled_at is None, (
            "deletion_scheduled_at must be NULL after resurrection"
        )

    def test_purge_deleted_with_zero_hours_clears_just_marked_rows(
        self, pg_dedup_store, unique_collection
    ):
        """?purge=true route relies on purge_deleted(0) actually deleting
        rows that were soft-deleted moments ago. Verify the 0-hour cutoff
        matches rows with deletion_scheduled_at = now()."""
        doc = _make_stored_doc(unique_collection, b"purge-zero-hours probe")
        pg_dedup_store.store_document(doc)

        marked = pg_dedup_store.soft_delete_collection(unique_collection)
        assert marked == 1

        purged = pg_dedup_store.purge_deleted(older_than_hours=0)
        assert purged >= 1, (
            "purge_deleted(older_than_hours=0) must delete rows that were "
            "just soft-deleted (used by DELETE /api/collections?purge=true)"
        )

        # After a hard purge, a fresh ingest must produce a brand-new row
        # — NOT a resurrection.
        doc2 = _make_stored_doc(unique_collection, b"purge-zero-hours probe")
        was_resurrected = pg_dedup_store.store_document(doc2)
        assert was_resurrected is False, (
            "After a hard-purge there is no prior row to resurrect"
        )
