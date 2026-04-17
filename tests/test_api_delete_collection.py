"""Tests for DELETE /api/collections/{name} and its ?purge=true option.

The ?purge=true flag is what operators use to fully reset a collection
before a fresh re-ingest. Without it the old fingerprints stay in the
table (soft-deleted) and every re-ingest silently resurrects the prior
row — the Phase 8 bug pattern.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.auth import set_require_auth
from pipeline.api.routes import router
from pipeline.dedup import (
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.storage.base import InMemoryVectorStore


def _build_app() -> FastAPI:
    set_require_auth(False)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _seed_doc(store: InMemoryDedupStore, collection: str, content: bytes) -> str:
    fp = compute_fingerprint(content.decode("utf-8", errors="replace"))
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


class TestDeleteCollection:
    def setup_method(self):
        self.app = _build_app()
        self.client = TestClient(self.app)
        self.dedup = InMemoryDedupStore()
        self.vector = InMemoryVectorStore()
        services.configure_stores(self.dedup, self.vector)

    def test_default_is_soft_delete(self):
        """No query param → soft-delete (48h restore window preserved)."""
        coll = f"tc_{uuid.uuid4().hex[:8]}"
        _seed_doc(self.dedup, coll, b"hello")
        _seed_doc(self.dedup, coll, b"world")

        resp = self.client.delete(f"/api/collections/{coll}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["documents_marked"] == 2
        assert "documents_purged" not in body

        # The rows still exist in the store — they're just soft-deleted,
        # which is what keeps restore possible within 48h.
        assert self.dedup.find_by_fingerprint(
            coll, compute_fingerprint("hello"), include_deleted=True
        ) is not None

    def test_purge_true_hard_deletes(self):
        """?purge=true → hard-delete, returns documents_purged count."""
        coll = f"tc_{uuid.uuid4().hex[:8]}"
        _seed_doc(self.dedup, coll, b"hello")
        _seed_doc(self.dedup, coll, b"world")

        resp = self.client.delete(f"/api/collections/{coll}?purge=true")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "documents_purged" in body
        assert body["documents_purged"] == 2
        assert "Not recoverable" in body["message"]

        # Row is gone even from include_deleted queries.
        assert self.dedup.find_by_fingerprint(
            coll, compute_fingerprint("hello"), include_deleted=True
        ) is None

    def test_reingest_after_purge_is_a_fresh_row_not_a_resurrection(self):
        """After ?purge=true, re-ingesting identical content produces a
        brand-new row (was_resurrected=False). This is the operator flow
        we recommend for resetting a collection."""
        coll = f"tc_{uuid.uuid4().hex[:8]}"
        _seed_doc(self.dedup, coll, b"reset me")

        resp = self.client.delete(f"/api/collections/{coll}?purge=true")
        assert resp.status_code == 200

        # Re-ingest same content
        fp = compute_fingerprint("reset me")
        new_doc = StoredDocument(
            document_id=str(uuid.uuid4()),
            collection_id=coll,
            source_file="reset.txt",
            content_fingerprint=fp,
            file_type="txt",
            engine="markitdown",
            markdown="reset me",
            title="reset",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            tags=[],
        )
        was_resurrected = self.dedup.store_document(new_doc)
        assert was_resurrected is False, (
            "After ?purge=true there is no prior soft-deleted row, so "
            "the re-ingest must be a fresh insert."
        )
        assert self.dedup.find_by_fingerprint(coll, fp) is not None

    def test_default_delete_leaves_ghost_that_resurrects_on_reingest(self):
        """Without ?purge=true, a re-ingest over a just-deleted collection
        resurrects the prior row. This documents *why* ?purge=true exists
        (and protects against someone "fixing" the default)."""
        coll = f"tc_{uuid.uuid4().hex[:8]}"
        original_id = _seed_doc(self.dedup, coll, b"ghost content")

        resp = self.client.delete(f"/api/collections/{coll}")
        assert resp.status_code == 200

        # Re-ingest identical content
        fp = compute_fingerprint("ghost content")
        new_doc = StoredDocument(
            document_id=str(uuid.uuid4()),  # new UUID on the caller side
            collection_id=coll,
            source_file="ghost.txt",
            content_fingerprint=fp,
            file_type="txt",
            engine="markitdown",
            markdown="ghost content",
            title="ghost",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            tags=[],
        )
        was_resurrected = self.dedup.store_document(new_doc)
        assert was_resurrected is True, (
            "Soft-delete + re-ingest of the same fingerprint must be "
            "flagged as a resurrection so agents get a warning."
        )
        # After the InMemoryDedupStore fix, the doc is visible again.
        assert self.dedup.find_by_fingerprint(coll, fp) is not None
