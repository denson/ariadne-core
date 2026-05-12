"""ariadne--5f2 — documents.metadata is seeded at store_document time.

Before ariadne--5f2, ``store_document`` left ``documents.metadata`` NULL
and only ``update_document_metadata`` could populate it. The bw → Ariadne
ingest helpers had to call ``update_document_metadata`` immediately after
``_process_single_document`` to seed the column so subsequent body-doc
lookups via ``documents.metadata @> {...}`` could find the row.

After ariadne--5f2, ``store_document`` accepts an optional
``agent_metadata`` kwarg and folds it into ``documents.metadata`` at
INSERT time (or shallow-merges on UPSERT). These tests assert the
parity invariant: after one call to ``store_document(agent_metadata=...)``,
the metadata is visible on the document — no follow-up PATCH-meta needed.

Covers both backends:
  • InMemoryDedupStore: ``_doc_metadata[doc_id]`` is populated.
  • PgDedupStore: ``documents.metadata`` JSONB column is populated (the
    test skips when Postgres is unreachable, per conftest.pg_pool).
"""

from __future__ import annotations

import uuid

from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)


def _make_doc(
    collection: str,
    source_file: str = "a.txt",
    content: str = "alpha",
) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint(
            (content + source_file).encode("utf-8")
        ),
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


# ── InMemoryDedupStore ──────────────────────────────────────────────────────


def test_inmemory_seeds_metadata_at_ingest_time():
    """Parity: after store_document(agent_metadata=...), _doc_metadata is set.

    Equivalent to documents.metadata being non-NULL on the Pg path.
    This is what lets _resolve_body_doc_id find the doc by JSONB
    containment immediately after ingest.
    """
    store = InMemoryDedupStore()
    doc = _make_doc("myproj")
    meta = {
        "ticket_id": "bw-test-a3f",
        "source_type": "body",
        "project": "myproj",
        "labels": {"kind": "person"},
    }
    store.store_document(doc, agent_metadata=meta)

    stored_meta = store._doc_metadata.get(doc.document_id, {})
    assert stored_meta == meta, f"expected metadata seeded, got {stored_meta!r}"


def test_inmemory_default_none_leaves_metadata_empty():
    """Backward compatibility: legacy callers (no agent_metadata kwarg) work.

    Default-None must NOT populate _doc_metadata — the normal ingest
    path from POST /api/ingest passes agent_metadata explicitly only
    when the caller supplied it; absent metadata stays absent.
    """
    store = InMemoryDedupStore()
    doc = _make_doc("myproj")
    store.store_document(doc)  # no agent_metadata kwarg
    assert store._doc_metadata.get(doc.document_id) is None


def test_inmemory_seed_then_update_merges_shallow():
    """Shallow-merge: a follow-up update_document_metadata extends seeded keys.

    Mirrors documents.metadata's JSONB ``COALESCE(metadata, '{}') ||
    EXCLUDED.metadata`` semantics. Existing keys not present in the
    update are preserved; overlapping keys are overwritten.
    """
    store = InMemoryDedupStore()
    doc = _make_doc("myproj")
    seed = {"ticket_id": "bw-1", "source_type": "body", "labels": {"k": "v1"}}
    store.store_document(doc, agent_metadata=seed)

    store.update_document_metadata(
        document_id=doc.document_id,
        agent_metadata={"labels": {"k": "v2"}, "new_key": "new_value"},
    )

    stored_meta = store._doc_metadata.get(doc.document_id, {})
    # ticket_id and source_type are preserved from the seed.
    assert stored_meta["ticket_id"] == "bw-1"
    assert stored_meta["source_type"] == "body"
    # labels is overwritten (shallow merge).
    assert stored_meta["labels"] == {"k": "v2"}
    # new_key is added.
    assert stored_meta["new_key"] == "new_value"


def test_inmemory_resolve_body_doc_finds_seeded_doc():
    """End-to-end: bw_ingest._resolve_body_doc_id finds the doc by metadata.

    This is the load-bearing acceptance: without seed-at-INSERT, the
    body-doc lookup returned None. With seed-at-INSERT (and the inline
    update_document_metadata call removed), the lookup must still succeed.
    """
    from pipeline import services
    from pipeline.api.bw_ingest import _resolve_body_doc_id

    services._dedup_store = InMemoryDedupStore()
    doc = _make_doc("myproj")
    meta = {
        "ticket_id": "bw-test-a3f",
        "source_type": "body",
        "project": "myproj",
    }
    services._dedup_store.store_document(doc, agent_metadata=meta)

    found = _resolve_body_doc_id(slug="myproj", ticket_id="bw-test-a3f")
    assert found == doc.document_id


# ── PgDedupStore ────────────────────────────────────────────────────────────


def _metadata_in_db(pg_pool, document_id: str) -> dict | None:
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT metadata FROM documents WHERE id = %(id)s::uuid",
                {"id": document_id},
            )
            row = cur.fetchone()
            return row[0] if row else None


def test_pg_seeds_metadata_at_ingest_time(
    pg_dedup_store, pg_pool, unique_collection
):
    """Parity probe on Pg: documents.metadata is non-empty after store_document.

    Pre-5f2 this row had metadata = '{}' (the schema default) and the
    bw bridge had to PATCH it. Post-5f2 store_document writes the
    agent_metadata kwarg directly into the column.
    """
    doc = _make_doc(unique_collection)
    meta = {
        "ticket_id": "bw-test-a3f",
        "source_type": "body",
        "project": unique_collection,
    }
    pg_dedup_store.store_document(doc, agent_metadata=meta)

    db_meta = _metadata_in_db(pg_pool, doc.document_id)
    assert db_meta is not None, "documents.metadata row missing"
    assert db_meta.get("ticket_id") == "bw-test-a3f"
    assert db_meta.get("source_type") == "body"
    assert db_meta.get("project") == unique_collection


def test_pg_default_none_yields_empty_object(
    pg_dedup_store, pg_pool, unique_collection
):
    """Backward compatibility on Pg: omitting agent_metadata → '{}'::jsonb.

    Matches the column's DEFAULT '{}' and the legacy pre-5f2 behavior
    (the row existed, the column was the empty JSONB object).
    """
    doc = _make_doc(unique_collection)
    pg_dedup_store.store_document(doc)  # no agent_metadata kwarg

    db_meta = _metadata_in_db(pg_pool, doc.document_id)
    assert db_meta == {}, f"expected empty dict, got {db_meta!r}"


def test_pg_upsert_shallow_merges_metadata(
    pg_dedup_store, pg_pool, unique_collection
):
    """Re-ingest with new agent_metadata: existing keys merged, overlap overwrites.

    Same content_fingerprint hits the ON CONFLICT path; the metadata
    column updates via COALESCE(documents.metadata, '{}') || EXCLUDED.
    """
    doc1 = _make_doc(unique_collection, source_file="a.txt", content="alpha")
    pg_dedup_store.store_document(
        doc1,
        agent_metadata={"ticket_id": "bw-1", "labels": {"k": "v1"}},
    )

    # Re-ingest the same content (same fingerprint) → ON CONFLICT path.
    doc2 = _make_doc(unique_collection, source_file="a.txt", content="alpha")
    doc2.content_fingerprint = doc1.content_fingerprint  # force collision
    pg_dedup_store.store_document(
        doc2,
        agent_metadata={"labels": {"k": "v2"}, "new_key": "x"},
    )

    db_meta = _metadata_in_db(pg_pool, doc1.document_id)
    assert db_meta is not None
    # ticket_id is preserved from the first ingest.
    assert db_meta.get("ticket_id") == "bw-1"
    # labels.k is overwritten by the second ingest.
    assert db_meta.get("labels") == {"k": "v2"}
    # new_key is added.
    assert db_meta.get("new_key") == "x"


def test_pg_seed_then_record_interaction_keeps_metadata(
    pg_dedup_store, pg_pool, unique_collection
):
    """Sanity: record_interaction (which writes to documents.source_reference)
    does NOT clobber documents.metadata. The two columns are independent.
    """
    doc = _make_doc(unique_collection)
    pg_dedup_store.store_document(
        doc,
        agent_metadata={"ticket_id": "bw-1", "source_reference": "doi:10.1/x"},
    )

    pg_dedup_store.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=unique_collection,
            agent_metadata={"source_reference": "doi:10.1/x"},
        )
    )

    db_meta = _metadata_in_db(pg_pool, doc.document_id)
    assert db_meta is not None
    assert db_meta.get("ticket_id") == "bw-1"
