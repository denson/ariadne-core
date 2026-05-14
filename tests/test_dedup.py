"""Tests for the dedup gate — fingerprinting, collision detection, interactions."""

from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)


class TestFingerprint:
    """Raw-bytes fingerprint contract (ariadne--k7n).

    test_normalization_applied was deliberately removed: under the
    bytes-only API, two byte sequences that differ in whitespace or case
    are NOT byte-equal and (correctly) produce different fingerprints.
    The replacement is test_byte_stability below.
    """

    def test_deterministic(self):
        fp1 = compute_fingerprint(b"Hello World")
        fp2 = compute_fingerprint(b"Hello World")
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        fp1 = compute_fingerprint(b"Hello World")
        fp2 = compute_fingerprint(b"Goodbye World")
        assert fp1 != fp2

    def test_returns_hex_sha256(self):
        fp = compute_fingerprint(b"test")
        assert len(fp) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in fp)

    def test_byte_stability(self):
        """Identical bytes produce identical fingerprints across calls.
        Replacement for the removed test_normalization_applied — the new
        contract guarantees byte-stability, not whitespace/case
        equivalence."""
        payload = b"\x00\x01\x02 some bytes \xff\xfe"
        fp1 = compute_fingerprint(payload)
        fp2 = compute_fingerprint(bytes(payload))  # fresh bytes object
        fp3 = compute_fingerprint(bytearray(payload))  # bytearray accepted
        fp4 = compute_fingerprint(memoryview(payload))  # memoryview accepted
        assert fp1 == fp2 == fp3 == fp4

        # Whitespace/case-different inputs are NOT byte-equal under the
        # new contract — semantic that test_normalization_applied
        # asserted is intentionally gone.
        fp_canonical = compute_fingerprint(b"Hello World")
        fp_padded = compute_fingerprint(b"  hello   world  \n")
        assert fp_canonical != fp_padded

    def test_rejects_str_input(self):
        """Fail-fast guard against silent string-coercion regressions."""
        import pytest as _pytest
        with _pytest.raises(TypeError) as exc:
            compute_fingerprint("Hello World")  # type: ignore[arg-type]
        assert "raw bytes" in str(exc.value)


class TestInMemoryDedupStore:
    def setup_method(self):
        self.store = InMemoryDedupStore()
        self.doc = StoredDocument(
            document_id="doc-1",
            collection_id="default",
            source_file="test.txt",
            content_fingerprint="abc123",
            file_type="txt",
            engine="markitdown",
            markdown="# Hello",
            title="Hello",
            processing_time_ms=42,
            output_tokens_estimate=10,
            token_savings_ratio=None,
            processing_chain=[{"step": "extraction", "tool": "markitdown"}],
        )

    def test_store_and_find(self):
        self.store.store_document(self.doc)
        found = self.store.find_by_fingerprint("default", "abc123")
        assert found is not None
        assert found.document_id == "doc-1"

    def test_find_miss(self):
        found = self.store.find_by_fingerprint("default", "nonexistent")
        assert found is None

    def test_collection_scoped(self):
        self.store.store_document(self.doc)
        # Same fingerprint, different collection — should not match
        found = self.store.find_by_fingerprint("other-collection", "abc123")
        assert found is None

    def test_record_and_get_interactions(self):
        interaction = DocumentInteraction(
            document_id="doc-1",
            collection_id="default",
            agent_id="test-agent",
            agent_type="pytest",
            action="ingest",
            was_dedup_skip=False,
        )
        self.store.record_interaction(interaction)
        interactions = self.store.get_interactions("doc-1")
        assert len(interactions) == 1
        assert interactions[0].agent_id == "test-agent"
        assert interactions[0].was_dedup_skip is False

    def test_multiple_interactions(self):
        for i in range(3):
            self.store.record_interaction(
                DocumentInteraction(
                    document_id="doc-1",
                    collection_id="default",
                    agent_id=f"agent-{i}",
                    was_dedup_skip=i > 0,
                )
            )
        interactions = self.store.get_interactions("doc-1")
        assert len(interactions) == 3
        assert interactions[0].was_dedup_skip is False
        assert interactions[1].was_dedup_skip is True

    def test_no_interactions(self):
        assert self.store.get_interactions("nonexistent") == []

    def test_update_document_content_updates_in_place(self):
        """ariadne--uuo.1 acceptance (3): update_document_content on an
        existing row with old fingerprint F_old UPDATEs the row in place —
        same document_id, new fingerprint, new markdown, shallow-merged
        metadata — and creates no second row."""
        # Seed a row with F_old and some initial metadata.
        self.store.store_document(
            self.doc, agent_metadata={"ticket_id": "uuo", "keep_me": "yes"}
        )
        assert len(self.store._documents) == 1

        result = self.store.update_document_content(
            "doc-1",
            content_fingerprint="def456",  # F_new — different from F_old
            markdown="# Updated body",
            source_file="test.txt",
            title="Updated",
            processing_chain=[{"step": "extraction", "tool": "markitdown"}],
            processing_time_ms=99,
            output_tokens_estimate=20,
            token_savings_ratio=0.5,
            tags=["re-embedded"],
            warnings=[],
            agent_metadata={"keep_me": "overwritten", "new_key": "added"},
        )
        assert result is True

        # No second row — the UPDATE re-keyed in place, not inserted.
        assert len(self.store._documents) == 1, self.store._documents

        # Old fingerprint no longer resolves; new one does — same doc id.
        assert self.store.find_by_fingerprint("default", "abc123") is None
        found = self.store.find_by_fingerprint("default", "def456")
        assert found is not None
        assert found.document_id == "doc-1"
        assert found.content_fingerprint == "def456"
        assert found.markdown == "# Updated body"
        assert found.title == "Updated"
        assert found.tags == ["re-embedded"]

        # Metadata shallow-merged: unmentioned key preserved, named key
        # overwritten, new key added — mirrors store_document's || merge.
        meta = self.store._doc_metadata["doc-1"]
        assert meta == {
            "ticket_id": "uuo",
            "keep_me": "overwritten",
            "new_key": "added",
        }

    def test_update_document_content_missing_id_returns_false(self):
        """ariadne--uuo.1: a missing document_id is a caller error —
        update_document_content returns False and inserts nothing (design
        §6.5.2: re-embed must resolve a real id; a missing id means the
        zero-resolved-IDs INSERT-fresh branch should have run instead)."""
        result = self.store.update_document_content(
            "no-such-doc",
            content_fingerprint="def456",
            markdown="# body",
            source_file="x.txt",
            title=None,
            processing_chain=[],
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=0.0,
            tags=[],
            warnings=[],
            agent_metadata=None,
        )
        assert result is False
        assert self.store._documents == {}
