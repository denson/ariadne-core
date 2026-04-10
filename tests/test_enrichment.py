"""Tests for image enrichment post-processing and vision client."""

import base64
import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.enrichment.images import (
    ImageEnricher,
    ImageEnrichmentResult,
    _has_description,
    _resolve_image_path,
)
from pipeline.enrichment.vision import VisionClient, VisionConfig

FIXTURES = Path(__file__).parent / "fixtures"


class TestVisionConfig:
    def test_defaults(self):
        config = VisionConfig()
        assert config.base_url == "https://api.openai.com/v1"
        assert config.model == "gpt-4o-mini"
        assert config.api_key == ""

    def test_custom(self):
        config = VisionConfig(
            base_url="https://custom.api/v1",
            api_key="test-key",
            model="gpt-4o",
        )
        assert config.base_url == "https://custom.api/v1"
        assert config.api_key == "test-key"


class TestVisionClient:
    def test_describe_image_from_path_missing_file(self):
        config = VisionConfig(api_key="test-key")
        client = VisionClient(config)
        with pytest.raises(FileNotFoundError):
            client.describe_image_from_path("/nonexistent/image.png")

    @patch("pipeline.enrichment.vision.urlopen")
    def test_describe_image_from_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "A test image"}}]}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        config = VisionConfig(api_key="test-key")
        client = VisionClient(config)
        result = client.describe_image_from_url("https://example.com/img.png")
        assert result == "A test image"

        # Verify the API was called with correct payload
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data)
        assert body["model"] == "gpt-4o-mini"
        assert len(body["messages"][0]["content"]) == 2
        assert body["messages"][0]["content"][1]["type"] == "image_url"

    @patch("pipeline.enrichment.vision.urlopen")
    def test_api_error_raises_runtime_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        config = VisionConfig(api_key="test-key")
        client = VisionClient(config)
        with pytest.raises(RuntimeError, match="Vision API call failed"):
            client.describe_image_from_url("https://example.com/img.png")


class TestImageEnricher:
    def _make_enricher(self, api_key: str = "test-key") -> ImageEnricher:
        config = VisionConfig(api_key=api_key)
        return ImageEnricher(config)

    def test_disabled_when_no_api_key(self):
        enricher = ImageEnricher(VisionConfig(api_key=""))
        assert enricher.enabled is False

    def test_disabled_when_no_config(self):
        enricher = ImageEnricher(None)
        assert enricher.enabled is False

    def test_disabled_returns_unchanged_markdown(self):
        enricher = ImageEnricher(None)
        md = "# Hello\n\n![pic](image.png)\n"
        result = enricher.enrich(md)
        assert result.markdown == md
        assert result.images_processed == 0

    def test_enabled_when_api_key_set(self):
        enricher = self._make_enricher()
        assert enricher.enabled is True

    @patch.object(VisionClient, "describe_image_from_url")
    def test_enrich_http_image(self, mock_describe):
        mock_describe.return_value = "A photo of a cat"
        enricher = self._make_enricher()
        md = "# Doc\n\n![cat](https://example.com/cat.png)\n\nMore text."
        result = enricher.enrich(md)
        assert result.images_processed == 1
        assert "**Image description:** A photo of a cat" in result.markdown
        assert "![cat](https://example.com/cat.png)" in result.markdown

    @patch.object(VisionClient, "describe_image_from_url")
    def test_enrich_multiple_images(self, mock_describe):
        mock_describe.side_effect = ["Description 1", "Description 2"]
        enricher = self._make_enricher()
        md = "![img1](https://example.com/1.png)\n\n![img2](https://example.com/2.png)\n"
        result = enricher.enrich(md)
        assert result.images_processed == 2
        assert "Description 1" in result.markdown
        assert "Description 2" in result.markdown

    @patch.object(VisionClient, "describe_image_from_url")
    def test_skip_already_described_images(self, mock_describe):
        enricher = self._make_enricher()
        md = textwrap.dedent("""\
            ![chart](https://example.com/chart.png)

            > **Image description:** An existing description.

            Some text.
        """)
        result = enricher.enrich(md)
        assert result.images_processed == 0
        assert result.images_skipped == 1
        mock_describe.assert_not_called()

    def test_unresolvable_image_skipped(self):
        enricher = self._make_enricher()
        md = "![pic](relative/nonexistent.png)\n"
        result = enricher.enrich(md)
        assert result.images_processed == 0
        assert result.images_skipped == 1
        assert any("Could not resolve" in e for e in result.errors)

    @patch.object(VisionClient, "describe_image_from_url")
    def test_vision_api_error_skips_image(self, mock_describe):
        mock_describe.side_effect = RuntimeError("API error")
        enricher = self._make_enricher()
        md = "![pic](https://example.com/img.png)\n"
        result = enricher.enrich(md)
        assert result.images_processed == 0
        assert result.images_skipped == 1
        assert any("Vision API error" in e for e in result.errors)

    @patch.object(VisionClient, "describe_image_from_url")
    def test_processing_chain_entry(self, mock_describe):
        mock_describe.return_value = "A test image"
        enricher = self._make_enricher()
        md = "![pic](https://example.com/img.png)\n"
        result = enricher.enrich(md)
        chain = result.processing_chain_entry
        assert chain["step"] == "image_enrichment"
        assert chain["tool"] == "openai:gpt-4o-mini"
        assert "ts" in chain
        assert "ms" in chain
        assert chain["images_processed"] == 1

    @patch.object(VisionClient, "describe_image_from_path")
    def test_enrich_local_image(self, mock_describe):
        mock_describe.return_value = "A local image"
        enricher = self._make_enricher()
        # Create a temp image fixture
        img_path = FIXTURES / "_temp_enrichment_test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
        try:
            md = f"![pic]({img_path})\n"
            result = enricher.enrich(md)
            assert result.images_processed == 1
            assert "A local image" in result.markdown
        finally:
            img_path.unlink(missing_ok=True)

    @patch.object(VisionClient, "describe_image_from_base64")
    def test_enrich_data_url_image(self, mock_describe):
        mock_describe.return_value = "A base64 image"
        enricher = self._make_enricher()
        b64 = base64.b64encode(b"fake-image-data").decode()
        md = f"![pic](data:image/png;base64,{b64})\n"
        result = enricher.enrich(md)
        assert result.images_processed == 1
        assert "A base64 image" in result.markdown


class TestHelpers:
    def test_has_description_true(self):
        md = "![pic](img.png)\n\n> **Image description:** Foo bar."
        # match_end is after the image tag
        end = md.index(")") + 1
        assert _has_description(md, end) is True

    def test_has_description_false(self):
        md = "![pic](img.png)\n\nSome other text."
        end = md.index(")") + 1
        assert _has_description(md, end) is False

    def test_resolve_http_url(self):
        result = _resolve_image_path("https://example.com/img.png", None)
        assert result == "https://example.com/img.png"

    def test_resolve_data_url(self):
        result = _resolve_image_path("data:image/png;base64,abc", None)
        assert result == "data:image/png;base64,abc"

    def test_resolve_nonexistent_local(self):
        result = _resolve_image_path("nonexistent.png", None)
        assert result is None

    def test_resolve_relative_to_source_dir(self):
        # sample.txt exists in fixtures
        result = _resolve_image_path("sample.txt", str(FIXTURES))
        assert result is not None
