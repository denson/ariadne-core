"""Pass 4 — source_reference denormalization on documents.source_reference.

These tests exercise the Pg write-path: record_interaction and
update_document_metadata must propagate agent_metadata.source_reference
into the denormalized column, and list_documents(has_source_reference=...)
must read from that column via the Pass 4 SQL filter.

Skips when Postgres is unreachable (see conftest.pg_pool fixture).
"""

from __future__ import annotations

import uuid

from pipeline.dedup import (
    DocumentInteraction,
    StoredDocument,
    compute_fingerprint,
)


def _make_doc(collection: str, source_file: str, content: str) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint(content + source_file),
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


def _source_ref_in_db(pg_pool, document_id: str) -> str | None:
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_reference FROM documents "
                "WHERE id = %(id)s::uuid",
                {"id": document_id},
            )
            row = cur.fetchone()
            return row[0] if row else None


def test_source_reference_written_by_record_interaction(
    pg_dedup_store, pg_pool, unique_collection
):
    doc = _make_doc(unique_collection, "a.txt", "alpha")
    pg_dedup_store.store_document(doc)
    assert _source_ref_in_db(pg_pool, doc.document_id) is None

    pg_dedup_store.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=unique_collection,
            agent_metadata={"source_reference": "doi:10.1234/abc"},
        )
    )

    assert _source_ref_in_db(pg_pool, doc.document_id) == "doi:10.1234/abc"


def test_source_reference_updated_on_subsequent_interaction(
    pg_dedup_store, pg_pool, unique_collection
):
    doc = _make_doc(unique_collection, "a.txt", "alpha")
    pg_dedup_store.store_document(doc)

    pg_dedup_store.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=unique_collection,
            agent_metadata={"source_reference": "doi:first"},
        )
    )
    pg_dedup_store.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=unique_collection,
            agent_metadata={"source_reference": "doi:second"},
        )
    )

    assert _source_ref_in_db(pg_pool, doc.document_id) == "doi:second"


def test_source_reference_unknown_preserved_but_not_matched(
    pg_dedup_store, pg_pool, unique_collection
):
    """'unknown' is stored verbatim for display/audit, but
    has_source_reference=True excludes it and has_source_reference=False
    includes it. The partial index shares this definition."""
    doc = _make_doc(unique_collection, "a.txt", "alpha")
    pg_dedup_store.store_document(doc)
    pg_dedup_store.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=unique_collection,
            agent_metadata={"source_reference": "unknown"},
        )
    )

    assert _source_ref_in_db(pg_pool, doc.document_id) == "unknown"

    rows, total = pg_dedup_store.list_documents(
        collection=unique_collection, has_source_reference=True
    )
    assert total == 0 and rows == []

    rows, total = pg_dedup_store.list_documents(
        collection=unique_collection, has_source_reference=False
    )
    assert total == 1
    assert rows[0].document_id == doc.document_id


def test_source_reference_written_by_update_document_metadata(
    pg_dedup_store, pg_pool, unique_collection
):
    doc = _make_doc(unique_collection, "a.txt", "alpha")
    pg_dedup_store.store_document(doc)

    pg_dedup_store.update_document_metadata(
        document_id=doc.document_id,
        agent_metadata={"source_reference": "https://example.com/paper"},
    )

    assert (
        _source_ref_in_db(pg_pool, doc.document_id)
        == "https://example.com/paper"
    )
