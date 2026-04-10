"""Tests for search filters: source_file, file_type, tags."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.chunking.chunker import Chunk
from pipeline.dedup import InMemoryDedupStore, StoredDocument
from pipeline.embedding.embedder import EmbeddingClient
from pipeline.mcp_server import (
    _dedup_store,
    _vector_store,
    convert_document,
    search,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_stores():
    """Reset stores between tests."""
    _dedup_store._documents.clear()
    _dedup_store._interactions.clear()
    _vector_store._chunks.clear()


def _add_doc_and_chunks(
    doc_id: str,
    source_file: str,
    file_type: str,
    collection: str,
    tags: list[str],
    chunk_texts: list[str],
    embedding: list[float],
):
    """Helper: add a document to dedup store and chunks to vector store."""
    from pipeline.dedup import compute_fingerprint

    doc = StoredDocument(
        document_id=doc_id,
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint(" ".join(chunk_texts)),
        file_type=file_type,
        engine="markitdown",
        markdown=" ".join(chunk_texts),
        title=source_file,
        processing_time_ms=10,
        output_tokens_estimate=50,
        token_savings_ratio=None,
        processing_chain=[],
        tags=tags,
    )
    _dedup_store.store_document(doc)

    for i, text in enumerate(chunk_texts):
        chunk = Chunk(
            chunk_id=f"{doc_id}-chunk-{i:04d}",
            document_id=doc_id,
            collection_id=collection,
            chunk_index=i,
            text=text,
            token_count=len(text) // 4,
            embedding=list(embedding),
            embedding_model="test-model",
        )
        _vector_store.insert([chunk])


@pytest.fixture
def _setup_test_docs():
    """Create 3 documents with distinct characteristics for filter testing."""
    _add_doc_and_chunks(
        doc_id="doc-report",
        source_file="report.pdf",
        file_type="pdf",
        collection="research",
        tags=["quarterly", "finance"],
        chunk_texts=["Revenue grew 12% in Q4.", "Expenses were flat."],
        embedding=[1.0, 0.0, 0.0],
    )
    _add_doc_and_chunks(
        doc_id="doc-slides",
        source_file="slides.pptx",
        file_type="pptx",
        collection="research",
        tags=["quarterly", "presentations"],
        chunk_texts=["Slide 1: Quarterly update", "Slide 2: Revenue chart"],
        embedding=[0.9, 0.1, 0.0],
    )
    _add_doc_and_chunks(
        doc_id="doc-notes",
        source_file="notes.txt",
        file_type="txt",
        collection="daily",
        tags=["meeting"],
        chunk_texts=["Meeting notes from standup."],
        embedding=[0.0, 1.0, 0.0],
    )


@pytest.mark.asyncio
class TestSearchFilters:
    @patch.object(
        EmbeddingClient,
        "enabled",
        new_callable=lambda: property(lambda self: True),
    )
    @patch.object(EmbeddingClient, "embed_query")
    async def test_filter_source_file(
        self, mock_embed, _mock_enabled, _setup_test_docs
    ):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        result = json.loads(
            await search(query="revenue", filters={"source_file": "report"})
        )
        assert result["results_count"] > 0
        for r in result["results"]:
            assert r["document_id"] == "doc-report"

    @patch.object(
        EmbeddingClient,
        "enabled",
        new_callable=lambda: property(lambda self: True),
    )
    @patch.object(EmbeddingClient, "embed_query")
    async def test_filter_file_type(
        self, mock_embed, _mock_enabled, _setup_test_docs
    ):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        result = json.loads(
            await search(query="slides", filters={"file_type": "pptx"})
        )
        assert result["results_count"] > 0
        for r in result["results"]:
            assert r["document_id"] == "doc-slides"

    @patch.object(
        EmbeddingClient,
        "enabled",
        new_callable=lambda: property(lambda self: True),
    )
    @patch.object(EmbeddingClient, "embed_query")
    async def test_filter_tags_single(
        self, mock_embed, _mock_enabled, _setup_test_docs
    ):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        result = json.loads(
            await search(query="revenue", filters={"tags": ["finance"]})
        )
        assert result["results_count"] > 0
        for r in result["results"]:
            assert r["document_id"] == "doc-report"

    @patch.object(
        EmbeddingClient,
        "enabled",
        new_callable=lambda: property(lambda self: True),
    )
    @patch.object(EmbeddingClient, "embed_query")
    async def test_filter_tags_or_logic(
        self, mock_embed, _mock_enabled, _setup_test_docs
    ):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        result = json.loads(
            await search(query="quarterly", filters={"tags": ["quarterly"]})
        )
        doc_ids = {r["document_id"] for r in result["results"]}
        assert "doc-report" in doc_ids
        assert "doc-slides" in doc_ids

    @patch.object(
        EmbeddingClient,
        "enabled",
        new_callable=lambda: property(lambda self: True),
    )
    @patch.object(EmbeddingClient, "embed_query")
    async def test_filter_combined_and(
        self, mock_embed, _mock_enabled, _setup_test_docs
    ):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        result = json.loads(
            await search(
                query="revenue",
                filters={"file_type": "pdf", "tags": ["quarterly"]},
            )
        )
        assert result["results_count"] > 0
        for r in result["results"]:
            assert r["document_id"] == "doc-report"

    @patch.object(
        EmbeddingClient,
        "enabled",
        new_callable=lambda: property(lambda self: True),
    )
    @patch.object(EmbeddingClient, "embed_query")
    async def test_filter_unknown_key_ignored(
        self, mock_embed, _mock_enabled, _setup_test_docs
    ):
        mock_embed.return_value = [1.0, 0.0, 0.0]
        result = json.loads(
            await search(
                query="revenue", filters={"nonexistent_key": "value"}
            )
        )
        # Should return results normally, not error
        assert "error" not in result or result.get("error") is not True
        assert result["results_count"] > 0
