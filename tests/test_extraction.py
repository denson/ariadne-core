"""Tests for the MarkItDown extraction wrapper."""

from pathlib import Path

import pytest

from pipeline.extraction.markitdown import ExtractionResult, MarkItDownExtractor

FIXTURES = Path(__file__).parent / "fixtures"


class TestMarkItDownExtractor:
    def setup_method(self):
        self.extractor = MarkItDownExtractor(enable_plugins=False)

    def test_extract_txt_returns_result(self):
        result = self.extractor.extract(str(FIXTURES / "sample.txt"))
        assert isinstance(result, ExtractionResult)
        assert result.engine == "markitdown"
        assert result.file_type == "txt"
        assert result.source_file == "sample.txt"
        assert result.document_id  # non-empty UUID

    def test_extract_txt_contains_content(self):
        result = self.extractor.extract(str(FIXTURES / "sample.txt"))
        assert "Ariadne Core Test Document" in result.markdown
        assert "Section One" in result.markdown
        assert result.errors == []

    def test_extract_html(self):
        result = self.extractor.extract(str(FIXTURES / "sample.html"))
        assert result.file_type == "html"
        assert "Test HTML Document" in result.markdown
        assert "PDF extraction" in result.markdown
        assert result.errors == []

    def test_extract_file_uri(self):
        path = FIXTURES / "sample.txt"
        result = self.extractor.extract(f"file://{path.as_posix()}")
        assert "Ariadne Core Test Document" in result.markdown
        assert result.errors == []

    def test_extract_nonexistent_file_reports_error(self):
        result = self.extractor.extract("/nonexistent/file.pdf")
        assert len(result.errors) > 0
        assert result.markdown == ""

    def test_processing_chain_recorded(self):
        result = self.extractor.extract(str(FIXTURES / "sample.txt"))
        # Phase 5 appends an `encoding_detection` step for .txt files when
        # language validation runs. First step is always `extraction`.
        assert len(result.processing_chain) >= 1
        step = result.processing_chain[0]
        assert step["step"] == "extraction"
        assert step["tool"] == "markitdown"
        assert "ts" in step
        assert "ms" in step

    def test_token_estimate_positive(self):
        result = self.extractor.extract(str(FIXTURES / "sample.txt"))
        assert result.output_tokens_estimate > 0

    def test_processing_time_recorded(self):
        result = self.extractor.extract(str(FIXTURES / "sample.txt"))
        assert result.processing_time_ms >= 0

    def test_extract_image_jpg_warns_no_vision(self):
        result = self.extractor.extract(str(FIXTURES / "test_image.jpg"))
        assert result.file_type == "jpg"
        assert any("VISION_API_KEY" in w for w in result.warnings)

    def test_extract_image_png_warns_no_vision(self):
        result = self.extractor.extract(str(FIXTURES / "test_image.png"))
        assert result.file_type == "png"
        assert any("VISION_API_KEY" in w for w in result.warnings)

    def test_extract_audio_wav(self):
        wav_path = FIXTURES / "test_audio.wav"
        if not wav_path.exists():
            pytest.skip("No WAV fixture available")
        result = self.extractor.extract(str(wav_path))
        assert result.file_type == "wav"
        # MarkItDown's AudioConverter may error on a synthetic sine wave
        # (no recognizable speech), but the extraction wrapper should handle it.
        # The key assertion is that it doesn't crash and returns a result.
        assert isinstance(result.markdown, str)
