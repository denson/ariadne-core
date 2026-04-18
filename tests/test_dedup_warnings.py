"""BL-22: warnings are persisted on the documents table and round-trip
through find_by_fingerprint and list_documents.

Prior to the 005 migration, warnings were silently dropped on INSERT
and read back as []. The has_warnings filter on /api/documents was a
no-op against Pg. This test pins the fix.
"""
from __future__ import annotations

import uuid

import pytest

from pipeline.dedup import StoredDocument


pytestmark = pytest.mark.usefixtures("pg_dedup_store")


def _doc(collection: str, warnings: list[str]) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=f"/tmp/{uuid.uuid4().hex}.txt",
        content_fingerprint=uuid.uuid4().hex,
        file_type="txt",
        engine="test",
        markdown="x",
        title="t",
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[],
        tags=[],
        warnings=warnings,
    )


def test_warnings_round_trip_via_find_by_fingerprint(pg_dedup_store):
    """store_document + find_by_fingerprint preserves warnings."""
    coll = f"bl22-find-{uuid.uuid4().hex[:8]}"
    doc = _doc(coll, warnings=["NUL (0x00) byte stripped: count=3", "encoding fallback"])
    pg_dedup_store.store_document(doc)

    found = pg_dedup_store.find_by_fingerprint(coll, doc.content_fingerprint)
    assert found is not None
    assert found.warnings == [
        "NUL (0x00) byte stripped: count=3",
        "encoding fallback",
    ]


def test_warnings_round_trip_via_list_documents(pg_dedup_store):
    """list_documents returns StoredDocument objects with warnings populated."""
    coll = f"bl22-list-{uuid.uuid4().hex[:8]}"
    doc_with = _doc(coll, warnings=["w1"])
    doc_without = _doc(coll, warnings=[])
    pg_dedup_store.store_document(doc_with)
    pg_dedup_store.store_document(doc_without)

    docs, total = pg_dedup_store.list_documents(collection=coll, limit=10)
    assert total == 2
    by_fp = {d.content_fingerprint: d for d in docs}
    assert by_fp[doc_with.content_fingerprint].warnings == ["w1"]
    assert by_fp[doc_without.content_fingerprint].warnings == []


def test_warnings_update_on_resurrection(pg_dedup_store):
    """Re-ingest after soft-delete overwrites the warnings list (ON CONFLICT path)."""
    coll = f"bl22-resurrect-{uuid.uuid4().hex[:8]}"
    doc_v1 = _doc(coll, warnings=["original warning"])
    pg_dedup_store.store_document(doc_v1)
    pg_dedup_store.soft_delete_document(doc_v1.document_id)

    # Re-ingest with the same fingerprint but different warnings.
    doc_v2 = _doc(coll, warnings=["post-resurrect warning"])
    doc_v2.content_fingerprint = doc_v1.content_fingerprint
    pg_dedup_store.store_document(doc_v2)

    found = pg_dedup_store.find_by_fingerprint(coll, doc_v1.content_fingerprint)
    assert found is not None
    assert found.warnings == ["post-resurrect warning"]
