"""Tests for the embedding API client (Gemini native batchEmbedContents)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig


class TestEmbeddingConfig:
    def test_defaults(self):
        config = EmbeddingConfig()
        assert config.model == "gemini-embedding-001"
        assert config.dimensions == 1536
        assert config.base_url == "https://generativelanguage.googleapis.com/v1beta"
        assert config.api_key == ""

    def test_custom(self):
        config = EmbeddingConfig(
            model="gemini-embedding-001",
            dimensions=512,
            api_key="test-key",
        )
        assert config.model == "gemini-embedding-001"
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
                "embeddings": [
                    {"values": [0.1, 0.2, 0.3]},
                    {"values": [0.4, 0.5, 0.6]},
                ]
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
        # Native batchEmbedContents does not report token usage.
        assert result.total_tokens == 0
        assert result.model == "gemini-embedding-001"
        assert result.processing_time_ms >= 0

    # test_embed_texts_preserves_order removed: native batchEmbedContents
    # returns embeddings in request order; no client-side sort to test.

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
            {"embeddings": [{"values": [0.1]}]}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = EmbeddingClient(EmbeddingConfig(api_key="test-key"))
        result = client.embed_texts(["hello"])
        chain = result.processing_chain_entry

        assert chain["step"] == "embedding"
        assert chain["tool"].startswith("gemini:")
        assert "ts" in chain
        assert "ms" in chain
        assert chain["chunks_embedded"] == 1

    @patch("pipeline.embedding.embedder.urlopen")
    def test_embed_query(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"embeddings": [{"values": [0.1, 0.2, 0.3]}]}
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
            {"embeddings": [{"values": [0.1]}]}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        config = EmbeddingConfig(
            api_key="test-key",
            model="my-model",
            base_url="https://custom.api/v1beta",
        )
        client = EmbeddingClient(config)
        client.embed_texts(["hello"])

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        # URL: .../models/<model>:batchEmbedContents
        assert "custom.api" in req.full_url
        assert req.full_url.endswith(":batchEmbedContents")
        assert "/models/my-model" in req.full_url
        body = json.loads(req.data)
        assert "requests" in body
        assert body["requests"][0]["model"].endswith("my-model")
        assert body["requests"][0]["content"]["parts"][0]["text"] == "hello"
        # Header is x-goog-api-key; urllib.request.Request title-cases the
        # first segment, so accept either form.
        header_val = req.headers.get("X-goog-api-key") or req.headers.get(
            "x-goog-api-key"
        )
        assert header_val == "test-key"
        assert "Authorization" not in req.headers
