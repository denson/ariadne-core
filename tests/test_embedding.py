"""Tests for the embedding API client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig


class TestEmbeddingConfig:
    def test_defaults(self):
        config = EmbeddingConfig()
        assert config.model == "text-embedding-3-small"
        assert config.dimensions == 1536
        assert config.base_url == "https://api.openai.com/v1"
        assert config.api_key == ""

    def test_custom(self):
        config = EmbeddingConfig(
            model="text-embedding-3-small",
            dimensions=512,
            api_key="test-key",
        )
        assert config.model == "text-embedding-3-small"
        assert config.dimensions == 512


class TestEmbeddingClient:
    def test_disabled_without_api_key(self):
        client = EmbeddingClient(EmbeddingConfig())
        assert client.enabled is False

    def test_disabled_without_config(self):
        client = EmbeddingClient()
        assert client.enabled is False

    def test_enabled_with_api_key(self):
        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        assert client.enabled is True

    def test_model_property(self):
        client = EmbeddingClient(EmbeddingConfig(model="my-model"))
        assert client.model == "my-model"

    def test_dimensions_property(self):
        client = EmbeddingClient(EmbeddingConfig(dimensions=768))
        assert client.dimensions == 768

    def test_embed_texts_disabled_raises(self):
        client = EmbeddingClient()
        with pytest.raises(RuntimeError, match="not configured"):
            client.embed_texts(["hello"])

    def test_embed_query_disabled_raises(self):
        client = EmbeddingClient()
        with pytest.raises(RuntimeError, match="not configured"):
            client.embed_query("hello")

    @patch("pipeline.embedding.embedder.urlopen")
    def test_embed_texts_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                ],
                "usage": {"total_tokens": 10},
            }
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        result = client.embed_texts(["hello", "world"])

        assert len(result.embeddings) == 2
        assert result.embeddings[0] == [0.1, 0.2, 0.3]
        assert result.embeddings[1] == [0.4, 0.5, 0.6]
        assert result.total_tokens == 10
        assert result.model == "text-embedding-3-small"
        assert result.processing_time_ms >= 0

    @patch("pipeline.embedding.embedder.urlopen")
    def test_embed_texts_preserves_order(self, mock_urlopen):
        """API may return embeddings out of order — client should sort by index."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"total_tokens": 8},
            }
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        result = client.embed_texts(["a", "b"])

        assert result.embeddings[0] == [0.1, 0.2]
        assert result.embeddings[1] == [0.4, 0.5]

    @patch("pipeline.embedding.embedder.urlopen")
    def test_embed_texts_empty_list(self, mock_urlopen):
        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        result = client.embed_texts([])
        assert result.embeddings == []
        assert result.total_tokens == 0
        mock_urlopen.assert_not_called()

    @patch("pipeline.embedding.embedder.urlopen")
    def test_api_error_raises_runtime_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        with pytest.raises(RuntimeError, match="Embedding API call failed"):
            client.embed_texts(["hello"])

    @patch("pipeline.embedding.embedder.urlopen")
    def test_processing_chain_entry(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "data": [{"index": 0, "embedding": [0.1]}],
                "usage": {"total_tokens": 5},
            }
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        result = client.embed_texts(["hello"])
        chain = result.processing_chain_entry

        assert chain["step"] == "embedding"
        assert "embedding-3-small" in chain["tool"]
        assert "ts" in chain
        assert "ms" in chain
        assert chain["chunks_embedded"] == 1

    @patch("pipeline.embedding.embedder.urlopen")
    def test_embed_query(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"total_tokens": 3},
            }
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        embedding = client.embed_query("test query")
        assert embedding == [0.1, 0.2, 0.3]

    @patch("pipeline.embedding.embedder.urlopen")
    def test_api_call_format(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "data": [{"index": 0, "embedding": [0.1]}],
                "usage": {"total_tokens": 1},
            }
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        config = EmbeddingConfig(
            api_key="test-key",
            model="my-model",
            base_url="https://custom.api/v1",
        )
        client = EmbeddingClient(config)
        client.embed_texts(["hello"])

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "custom.api" in req.full_url
        assert req.full_url.endswith("/embeddings")
        body = json.loads(req.data)
        assert body["model"] == "my-model"
        assert body["input"] == ["hello"]
        assert req.headers["Authorization"] == "Bearer test-key"
