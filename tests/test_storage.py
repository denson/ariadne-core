"""Tests for the vector store abstraction and in-memory implementation."""

import pytest

from pipeline.chunking.chunker import Chunk
from pipeline.storage.base import InMemoryVectorStore, SearchResult, _cosine_similarity


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(a, a) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 1e-6

    def test_similar_vectors(self):
        a = [1.0, 1.0]
        b = [1.0, 0.9]
        score = _cosine_similarity(a, b)
        assert score > 0.9

    def test_different_lengths_returns_zero(self):
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector_returns_zero(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def _make_chunk(
    chunk_id: str = "c1",
    doc_id: str = "doc-1",
    collection: str = "default",
    text: str = "test",
    embedding: list[float] | None = None,
    index: int = 0,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=doc_id,
        collection_id=collection,
        chunk_index=index,
        text=text,
        token_count=len(text) // 4,
        embedding=embedding,
    )


class TestInMemoryVectorStore:
    def setup_method(self):
        self.store = InMemoryVectorStore()

    def test_insert_and_count(self):
        chunks = [
            _make_chunk("c1", embedding=[1.0, 0.0]),
            _make_chunk("c2", embedding=[0.0, 1.0]),
        ]
        self.store.insert(chunks)
        assert self.store.count() == 2

    def test_search_returns_ranked(self):
        self.store.insert(
            [
                _make_chunk("c1", embedding=[1.0, 0.0, 0.0]),
                _make_chunk("c2", embedding=[0.0, 1.0, 0.0]),
                _make_chunk("c3", embedding=[0.9, 0.1, 0.0]),
            ]
        )
        results = self.store.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3
        # c1 should be first (identical to query), c3 second (very similar)
        assert results[0].chunk.chunk_id == "c1"
        assert results[1].chunk.chunk_id == "c3"
        assert results[0].score > results[1].score > results[2].score

    def test_search_top_k(self):
        self.store.insert(
            [
                _make_chunk(f"c{i}", embedding=[float(i), 0.0])
                for i in range(10)
            ]
        )
        results = self.store.search([1.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_search_skips_no_embedding(self):
        self.store.insert(
            [
                _make_chunk("c1", embedding=[1.0, 0.0]),
                _make_chunk("c2", embedding=None),
            ]
        )
        results = self.store.search([1.0, 0.0])
        assert len(results) == 1
        assert results[0].chunk.chunk_id == "c1"

    def test_search_filter_by_collection(self):
        self.store.insert(
            [
                _make_chunk("c1", collection="alpha", embedding=[1.0, 0.0]),
                _make_chunk("c2", collection="beta", embedding=[1.0, 0.0]),
            ]
        )
        results = self.store.search(
            [1.0, 0.0], filters={"collection": "alpha"}
        )
        assert len(results) == 1
        assert results[0].chunk.collection_id == "alpha"

    def test_search_filter_by_document(self):
        self.store.insert(
            [
                _make_chunk("c1", doc_id="d1", embedding=[1.0, 0.0]),
                _make_chunk("c2", doc_id="d2", embedding=[1.0, 0.0]),
            ]
        )
        results = self.store.search(
            [1.0, 0.0], filters={"document_id": "d1"}
        )
        assert len(results) == 1
        assert results[0].document_id == "d1"

    def test_delete_by_id(self):
        self.store.insert(
            [
                _make_chunk("c1", embedding=[1.0, 0.0]),
                _make_chunk("c2", embedding=[0.0, 1.0]),
            ]
        )
        self.store.delete(["c1"])
        assert self.store.count() == 1

    def test_delete_nonexistent_is_noop(self):
        self.store.delete(["nonexistent"])
        assert self.store.count() == 0

    def test_delete_by_document(self):
        self.store.insert(
            [
                _make_chunk("c1", doc_id="doc-1", embedding=[1.0, 0.0]),
                _make_chunk("c2", doc_id="doc-1", embedding=[0.0, 1.0]),
                _make_chunk("c3", doc_id="doc-2", embedding=[1.0, 1.0]),
            ]
        )
        self.store.delete_by_document("doc-1")
        assert self.store.count() == 1

    def test_count_with_filter(self):
        self.store.insert(
            [
                _make_chunk("c1", collection="a"),
                _make_chunk("c2", collection="a"),
                _make_chunk("c3", collection="b"),
            ]
        )
        assert self.store.count({"collection": "a"}) == 2
        assert self.store.count({"collection": "b"}) == 1

    def test_search_result_fields(self):
        self.store.insert(
            [_make_chunk("c1", doc_id="d1", collection="col", embedding=[1.0])]
        )
        results = self.store.search([1.0])
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.document_id == "d1"
        assert r.collection_id == "col"
        assert r.score > 0
        assert r.chunk.chunk_id == "c1"

    def test_empty_store_search(self):
        results = self.store.search([1.0, 0.0])
        assert results == []

    def test_empty_store_count(self):
        assert self.store.count() == 0
