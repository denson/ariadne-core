"""Tests for the services layer's document processing pipeline."""

from pathlib import Path

import pytest

from pipeline import services
from pipeline.embedding.embedder import EmbeddingClient

FIXTURES = Path(__file__).parent / "fixtures"


class _StubEmbedResult:
    """Stand-in for EmbeddingResult — not used on the failure path, but
    kept for shape parity if a future test exercises the success path."""

    embeddings: list[list[float]] = []
    processing_chain_entry = {"step": "embedding", "tool": "gemini:stub"}


class _FailingEmbeddingClient:
    """Mimics EmbeddingClient's public surface: .enabled, .model, .embed_texts."""

    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_texts(self, texts: list[str]):
        raise RuntimeError("simulated provider 503 during batchEmbedContents")


def test_embedding_failure_sets_store_status_error_and_skips_vector_write(
    monkeypatch,
):
    """A RuntimeError from the embedding provider during store-mode ingest
    must produce store_status='error', chunks_count=0, a warning message,
    and MUST NOT insert unembedded chunks into the vector store.

    This protects against the pre-Phase-8 regression where embedding
    failures were swallowed into warnings while chunks were still
    inserted without vectors — making documents appear stored but
    invisible to search."""

    # Replace module-level globals with test doubles.
    stub_embed = _FailingEmbeddingClient()
    monkeypatch.setattr(services, "_embedding_client", stub_embed)

    # Fresh in-memory vector store so we can inspect state.
    from pipeline.storage.base import InMemoryVectorStore

    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_vector_store", stub_vector)

    response = services._process_single_document(
        uri=str(FIXTURES / "sample.txt"),
        store=True,
        collection="test_embed_fail",
        tags=[],
        force=False,
        agent_id=None,
        agent_type="test",
        model=None,
        initiated_by="test",
        agent_notes="test: embedding failure path",
        agent_metadata={"source_reference": "test-fixture"},
        chunking_config=None,
    )

    assert response["store_status"] == "error", response
    assert response["chunks_count"] == 0, response
    assert any(
        "Embedding failed" in w for w in response.get("warnings", [])
    ), f"Expected 'Embedding failed' warning, got {response.get('warnings')}"

    # Nothing should have been inserted into the vector store on the
    # failure path.
    assert stub_vector._chunks == {}, (
        f"Vector store got {len(stub_vector._chunks)} chunks on a "
        f"failed-embedding path — chunks should not be inserted without "
        f"embeddings."
    )
