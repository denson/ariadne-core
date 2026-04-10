"""Tests for the dedup gate — fingerprinting, collision detection, interactions."""

from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
    normalize_text,
)


class TestNormalization:
    def test_lowercase(self):
        assert normalize_text("Hello World") == "hello world"

    def test_trim_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_collapse_whitespace(self):
        assert normalize_text("hello   world\n\tfoo") == "hello world foo"

    def test_combined(self):
        assert normalize_text("  Hello   World  \n") == "hello world"


class TestFingerprint:
    def test_deterministic(self):
        fp1 = compute_fingerprint("Hello World")
        fp2 = compute_fingerprint("Hello World")
        assert fp1 == fp2

    def test_normalization_applied(self):
        fp1 = compute_fingerprint("Hello World")
        fp2 = compute_fingerprint("  hello   world  \n")
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        fp1 = compute_fingerprint("Hello World")
        fp2 = compute_fingerprint("Goodbye World")
        assert fp1 != fp2

    def test_returns_hex_sha256(self):
        fp = compute_fingerprint("test")
        assert len(fp) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in fp)


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
