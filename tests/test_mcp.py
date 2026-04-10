"""Tests for the MCP server convert_document and search tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.server import FastMCP

from pipeline.chunking.chunker import Chunk
from pipeline.dedup import InMemoryDedupStore
from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig
from pipeline.mcp_server import (
    _dedup_store,
    _vector_store,
    app,
    configure_embedding,
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


@pytest.mark.asyncio
class TestConvertDocumentTool:
    async def test_convert_txt_returns_json(self):
        result = await convert_document(uri=str(FIXTURES / "sample.txt"))
        data = json.loads(result)
        assert "markdown" in data
        assert "Ariadne Core Test Document" in data["markdown"]
        assert data["engine"] == "markitdown"
        assert data["file_type"] == "txt"

    async def test_convert_html_returns_json(self):
        result = await convert_document(uri=str(FIXTURES / "sample.html"))
        data = json.loads(result)
        assert "Test HTML Document" in data["markdown"]

    async def test_convert_includes_provenance(self):
        result = await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            agent_id="test-agent",
            agent_type="pytest",
            model="test-model",
            initiated_by="user:test",
        )
        data = json.loads(result)
        prov = data["provenance"]
        assert prov["agent_id"] == "test-agent"
        assert prov["agent_type"] == "pytest"
        assert prov["model"] == "test-model"
        assert prov["initiated_by"] == "user:test"
        assert len(prov["processing_chain"]) == 1

    async def test_convert_default_collection(self):
        result = await convert_document(uri=str(FIXTURES / "sample.txt"))
        data = json.loads(result)
        assert data["collection"] == "default"

    async def test_convert_custom_collection(self):
        result = await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            collection="test-collection",
        )
        data = json.loads(result)
        assert data["collection"] == "test-collection"

    async def test_store_true_chunks_document(self):
        result = await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            store=True,
        )
        data = json.loads(result)
        assert data["store_status"] == "stored"
        assert "chunks_count" in data
        assert data["chunks_count"] > 0
        # Chunks should be in vector store
        assert _vector_store.count() > 0

    async def test_store_false_skips_chunking(self):
        result = await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            store=False,
        )
        data = json.loads(result)
        assert data["store_status"] == "skipped"
        assert _vector_store.count() == 0

    async def test_nonexistent_file_returns_error(self):
        result = await convert_document(uri="/nonexistent/file.pdf")
        data = json.loads(result)
        assert data["error"] is True

    async def test_app_is_fastmcp_instance(self):
        assert isinstance(app, FastMCP)
        assert app.name == "ariadne-core"

    async def test_response_includes_fingerprint(self):
        result = await convert_document(uri=str(FIXTURES / "sample.txt"))
        data = json.loads(result)
        assert "content_fingerprint" in data
        assert len(data["content_fingerprint"]) == 64

    async def test_first_ingest_not_dedup_skip(self):
        result = await convert_document(uri=str(FIXTURES / "sample.txt"))
        data = json.loads(result)
        assert data["was_dedup_skip"] is False

    async def test_chunking_config_override(self):
        result = await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            chunking_config={"strategy": "fixed_size", "max_characters": 200},
        )
        data = json.loads(result)
        assert data["chunks_count"] > 0


@pytest.mark.asyncio
class TestDedupIntegration:
    async def test_second_ingest_is_dedup_skip(self):
        """Same document ingested twice — second should be a dedup skip."""
        first = json.loads(
            await convert_document(uri=str(FIXTURES / "sample.txt"))
        )
        second = json.loads(
            await convert_document(uri=str(FIXTURES / "sample.txt"))
        )
        assert first["was_dedup_skip"] is False
        assert second["was_dedup_skip"] is True
        assert second["document_id"] == first["document_id"]

    async def test_dedup_skip_records_interaction(self):
        """Dedup skip should still record the interaction."""
        await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            agent_id="agent-1",
        )
        await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            agent_id="agent-2",
        )
        first = json.loads(
            await convert_document(uri=str(FIXTURES / "sample.txt"))
        )
        result = json.loads(
            await convert_document(
                uri=str(FIXTURES / "sample.txt"),
                agent_id="agent-3",
            )
        )
        assert result["was_dedup_skip"] is True
        assert len(result["interactions"]) == 4
        agent_ids = [i["agent_id"] for i in result["interactions"]]
        assert "agent-1" in agent_ids
        assert "agent-2" in agent_ids
        assert "agent-3" in agent_ids

    async def test_force_bypasses_dedup(self):
        """force=True should re-process even if fingerprint matches."""
        first = json.loads(
            await convert_document(uri=str(FIXTURES / "sample.txt"))
        )
        second = json.loads(
            await convert_document(
                uri=str(FIXTURES / "sample.txt"),
                force=True,
            )
        )
        assert first["was_dedup_skip"] is False
        assert second["was_dedup_skip"] is False
        assert second["document_id"] != first["document_id"]

    async def test_different_collection_no_dedup(self):
        """Same document in different collections should not dedup."""
        first = json.loads(
            await convert_document(
                uri=str(FIXTURES / "sample.txt"),
                collection="collection-a",
            )
        )
        second = json.loads(
            await convert_document(
                uri=str(FIXTURES / "sample.txt"),
                collection="collection-b",
            )
        )
        assert first["was_dedup_skip"] is False
        assert second["was_dedup_skip"] is False
        assert first["document_id"] != second["document_id"]

    async def test_multi_agent_interactions(self):
        """Two different agents ingest same doc — interactions should show both."""
        await convert_document(
            uri=str(FIXTURES / "sample.txt"),
            agent_id="ob1-nightly",
            agent_type="ob1",
        )
        result = json.loads(
            await convert_document(
                uri=str(FIXTURES / "sample.txt"),
                agent_id="cowork-session-7f2",
                agent_type="claude-cowork",
            )
        )
        assert result["was_dedup_skip"] is True
        assert len(result["interactions"]) == 2
        types = {i["agent_type"] for i in result["interactions"]}
        assert "ob1" in types
        assert "claude-cowork" in types


@pytest.mark.asyncio
class TestSearchTool:
    async def test_search_not_available_without_embedding(self):
        result = json.loads(await search(query="test"))
        assert result["error"] is True
        assert "no embedding API key" in result["message"]

    @patch.object(EmbeddingClient, "enabled", new_callable=lambda: property(lambda self: True))
    @patch.object(EmbeddingClient, "embed_query")
    async def test_search_returns_results(self, mock_embed_query, _mock_enabled):
        """Search with mocked embeddings returns matching chunks."""
        mock_embed_query.return_value = [1.0, 0.0, 0.0]

        # Manually insert a chunk with embedding
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            collection_id="default",
            chunk_index=0,
            text="Revenue grew 12% year-over-year.",
            token_count=8,
            embedding=[1.0, 0.0, 0.0],
            embedding_model="test-model",
        )
        _vector_store.insert([chunk])

        # Also add a dedup record so interactions work
        from pipeline.dedup import DocumentInteraction
        _dedup_store.record_interaction(
            DocumentInteraction(
                document_id="doc-1",
                collection_id="default",
                agent_id="test-agent",
                action="ingest",
            )
        )

        result = json.loads(await search(query="revenue growth"))
        assert result["results_count"] == 1
        assert result["results"][0]["text"] == "Revenue grew 12% year-over-year."
        assert result["results"][0]["relevance_score"] > 0
        assert len(result["results"][0]["interactions"]) == 1

    @patch.object(EmbeddingClient, "enabled", new_callable=lambda: property(lambda self: True))
    @patch.object(EmbeddingClient, "embed_query")
    async def test_search_respects_top_k(self, mock_embed_query, _mock_enabled):
        mock_embed_query.return_value = [1.0, 0.0]

        for i in range(10):
            _vector_store.insert(
                [
                    Chunk(
                        chunk_id=f"c{i}",
                        document_id="doc-1",
                        collection_id="default",
                        chunk_index=i,
                        text=f"Chunk {i}",
                        token_count=2,
                        embedding=[1.0, float(i) / 10],
                    )
                ]
            )

        result = json.loads(await search(query="test", top_k=3))
        assert result["results_count"] == 3

    @patch.object(EmbeddingClient, "enabled", new_callable=lambda: property(lambda self: True))
    @patch.object(EmbeddingClient, "embed_query")
    async def test_search_max_top_k_capped(self, mock_embed_query, _mock_enabled):
        mock_embed_query.return_value = [1.0]
        result = json.loads(await search(query="test", top_k=100))
        # top_k should be capped at 20
        assert result["top_k"] == 20

    @patch.object(EmbeddingClient, "enabled", new_callable=lambda: property(lambda self: True))
    @patch.object(EmbeddingClient, "embed_query")
    async def test_search_filter_by_collection(self, mock_embed_query, _mock_enabled):
        mock_embed_query.return_value = [1.0, 0.0]

        _vector_store.insert(
            [
                Chunk(
                    chunk_id="c1",
                    document_id="d1",
                    collection_id="alpha",
                    chunk_index=0,
                    text="Alpha chunk",
                    token_count=2,
                    embedding=[1.0, 0.0],
                ),
                Chunk(
                    chunk_id="c2",
                    document_id="d2",
                    collection_id="beta",
                    chunk_index=0,
                    text="Beta chunk",
                    token_count=2,
                    embedding=[1.0, 0.0],
                ),
            ]
        )

        result = json.loads(await search(query="test", collection="alpha"))
        assert result["results_count"] == 1
        assert result["results"][0]["collection"] == "alpha"

    @patch.object(EmbeddingClient, "enabled", new_callable=lambda: property(lambda self: True))
    @patch.object(EmbeddingClient, "embed_query")
    async def test_search_embed_failure(self, mock_embed_query, _mock_enabled):
        mock_embed_query.side_effect = RuntimeError("API error")
        result = json.loads(await search(query="test"))
        assert result["error"] is True
        assert "Failed to embed query" in result["message"]


@pytest.mark.asyncio
class TestImageWarning:
    async def test_image_jpg_warning_no_vision(self):
        """Image JPG with no vision API returns warning and still stores."""
        result = json.loads(
            await convert_document(
                uri=str(FIXTURES / "test_image.jpg"),
                store=True,
            )
        )
        assert result["was_dedup_skip"] is False
        assert result["store_status"] == "stored"
        assert any("VISION_API_KEY" in w for w in result.get("warnings", []))

    async def test_image_png_warning_no_vision(self):
        """Image PNG with no vision API returns warning."""
        result = json.loads(
            await convert_document(
                uri=str(FIXTURES / "test_image.png"),
                store=True,
            )
        )
        assert any("VISION_API_KEY" in w for w in result.get("warnings", []))
