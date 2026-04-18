"""Tests for the services layer's document processing pipeline."""

from pathlib import Path

from pipeline import services

FIXTURES = Path(__file__).parent / "fixtures"


class _StubEmbedResult:
    """Stand-in for EmbeddingResult returned by embed_texts on success."""

    def __init__(self, count: int, dims: int = 3) -> None:
        self.embeddings = [[0.1] * dims for _ in range(count)]
        self.processing_chain_entry = {
            "step": "embedding",
            "tool": "gemini:stub",
            "ts": "2026-04-18T00:00:00Z",
            "ms": 1,
        }


class _FailingEmbeddingClient:
    """Embedding client that raises RuntimeError on every call."""

    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_texts(self, texts: list[str]):
        raise RuntimeError("simulated provider 503 during batchEmbedContents")


class _SuccessEmbeddingClient:
    """Embedding client that returns fake embeddings sized to the input."""

    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_texts(self, texts: list[str]):
        return _StubEmbedResult(count=len(texts))


class _DisabledEmbeddingClient:
    """Embedding client with enabled=False — chunks land without vectors."""

    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts: list[str]):  # pragma: no cover
        raise AssertionError("embed_texts must not be called when enabled=False")


def _fresh_stores(monkeypatch):
    """Install fresh in-memory stores on the services module."""
    from pipeline.dedup import InMemoryDedupStore
    from pipeline.storage.base import InMemoryVectorStore

    stub_dedup = InMemoryDedupStore()
    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_dedup_store", stub_dedup)
    monkeypatch.setattr(services, "_vector_store", stub_vector)
    return stub_dedup, stub_vector


def _common_kwargs(uri: str, collection: str, store: bool = True) -> dict:
    return dict(
        uri=uri,
        store=store,
        collection=collection,
        tags=[],
        force=False,
        agent_id=None,
        agent_type="test",
        model=None,
        initiated_by="test",
        agent_notes="test",
        agent_metadata={"source_reference": "test-fixture"},
        chunking_config=None,
    )


def test_embedding_failure_returns_error_and_writes_no_documents_row(monkeypatch):
    """BL-19 transactional guarantee: when embed fails, the function
    returns an error dict and NO documents row, chunks, vectors, or
    interaction row is written."""

    monkeypatch.setattr(services, "_embedding_client", _FailingEmbeddingClient())
    stub_dedup, stub_vector = _fresh_stores(monkeypatch)

    response = services._process_single_document(
        **_common_kwargs(str(FIXTURES / "sample.txt"), "test_embed_fail")
    )

    assert response["error"] is True, response
    assert "Embedding failed" in response["message"], response
    assert response["document_id"] is None, response
    assert response["store_status"] == "error", response
    assert response["chunks_count"] == 0, response
    assert stub_vector._chunks == {}, (
        f"Vector store got {len(stub_vector._chunks)} chunks on a failed-"
        f"embedding path — no chunks should be inserted."
    )
    # The BL-19 assertion: no documents row and no interaction row.
    assert stub_dedup._documents == {}, (
        f"Dedup store got {len(stub_dedup._documents)} documents on a "
        f"failed-embedding path — no row should be inserted."
    )
    assert stub_dedup._interactions == {}, (
        f"Dedup store recorded {len(stub_dedup._interactions)} interactions "
        f"on a failed-embedding path — no interaction should be recorded."
    )


def test_embedding_success_writes_documents_row_and_chunks_and_interaction(
    monkeypatch,
):
    """Happy path: embed succeeds, so we get a documents row, chunks with
    vectors, and an interaction row."""

    monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
    stub_dedup, stub_vector = _fresh_stores(monkeypatch)

    response = services._process_single_document(
        **_common_kwargs(str(FIXTURES / "sample.txt"), "test_embed_ok")
    )

    assert not response.get("error"), response
    assert response["document_id"], response
    assert response["store_status"] == "stored", response
    assert response["chunks_count"] > 0, response
    assert len(stub_vector._chunks) > 0
    assert len(stub_dedup._documents) == 1
    doc_id = response["document_id"]
    assert len(stub_dedup._interactions.get(doc_id, [])) == 1


def test_store_false_writes_no_documents_row(monkeypatch):
    """store=False is a one-time extraction: it returns the full markdown
    but writes nothing to the dedup or vector store."""

    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    stub_dedup, stub_vector = _fresh_stores(monkeypatch)

    response = services._process_single_document(
        **_common_kwargs(
            str(FIXTURES / "sample.txt"), "test_store_false", store=False
        )
    )

    assert "error" not in response, response
    assert response["store_status"] == "not_stored", response
    assert response["chunks_count"] == 0, response
    assert "Ariadne Core Test Document" in response["markdown"], response
    assert stub_dedup._documents == {}, (
        f"store=False wrote {len(stub_dedup._documents)} documents row(s) — "
        f"one-time extraction should not persist."
    )
    assert stub_vector._chunks == {}


def test_embedding_disabled_writes_documents_row_and_chunks_without_vectors(
    monkeypatch,
):
    """Vectors-disabled mode: chunks still land, but every chunk has
    embedding=None. store_status=stored."""

    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    stub_dedup, stub_vector = _fresh_stores(monkeypatch)

    response = services._process_single_document(
        **_common_kwargs(str(FIXTURES / "sample.txt"), "test_embed_off")
    )

    assert "error" not in response, response
    assert response["store_status"] == "stored", response
    assert response["chunks_count"] > 0, response
    assert len(stub_dedup._documents) == 1
    assert len(stub_vector._chunks) > 0
    for chunk in stub_vector._chunks.values():
        assert chunk.embedding is None, (
            f"Chunk {chunk.chunk_id} has an embedding despite disabled client."
        )
