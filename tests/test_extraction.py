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

    def test_nul_bytes_stripped_from_markdown(self):
        result = self.extractor.extract(str(FIXTURES / "nul_byte_sample.txt"))
        assert "\x00" not in result.markdown

    def test_nul_bytes_produce_warning(self):
        result = self.extractor.extract(str(FIXTURES / "nul_byte_sample.txt"))
        assert any(
            ("NUL" in w or "0x00" in w) and "3" in w for w in result.warnings
        ), f"Expected NUL-strip warning with count, got: {result.warnings}"

    def test_clean_txt_no_nul_warning(self):
        result = self.extractor.extract(str(FIXTURES / "sample.txt"))
        assert not any(
            "NUL" in w or "0x00" in w for w in result.warnings
        ), f"No NUL warning expected on clean file, got: {result.warnings}"


def test_encoding_detection_gate_overrides_llm_on_low_byte_confidence(
    tmp_path, monkeypatch
):
    """Mojibake: byte detector says low confidence; LLM is fooled and votes
    coherent=true. Final coherent must be False."""
    from pipeline.extraction import markitdown as md_mod
    from pipeline.extraction.text_encoding import LanguageValidation

    fake_txt = tmp_path / "mojibake.txt"
    fake_txt.write_text("pretend this is mojibake", encoding="utf-8")

    def fake_detect(path):
        return ("pretend decoded text", "windows-1252", 0.0)

    def fake_validate(text, config):
        return LanguageValidation(
            coherent=True,
            language="en",
            script="Latin",
            confidence="high",
            notes="",
            model="gemini-2.0-flash",
            skipped=False,
        )

    monkeypatch.setattr(md_mod, "detect_and_decode", fake_detect)
    monkeypatch.setattr(md_mod, "validate_language", fake_validate)

    extractor = md_mod.MarkItDownExtractor(enable_plugins=False)
    result = extractor.extract(str(fake_txt))

    enc_step = next(
        (s for s in result.processing_chain if s["step"] == "encoding_detection"),
        None,
    )
    assert enc_step is not None, "encoding_detection step missing from chain"
    assert enc_step["coherent"] is False, (
        f"Expected coherent=False when byte confidence is 0.0 "
        f"(mojibake gate), got {enc_step}"
    )
    assert enc_step["llm_coherent"] is True, (
        "LLM's raw opinion should still be preserved in llm_coherent"
    )
    assert enc_step["encoding_confidence"] == 0.0
    assert any(
        "text may be garbled" in w for w in result.warnings
    ), "Expected garbled-text warning when gate demotes coherent to False"


def test_encoding_detection_happy_path_both_signals_agree(tmp_path, monkeypatch):
    """Happy path: byte confidence high AND LLM coherent → final coherent=True."""
    from pipeline.extraction import markitdown as md_mod
    from pipeline.extraction.text_encoding import LanguageValidation

    fake_txt = tmp_path / "clean.txt"
    fake_txt.write_text("Real clean English text for the test.", encoding="utf-8")

    def fake_detect(path):
        return ("Real clean English text for the test.", "utf_8", 0.9)

    def fake_validate(text, config):
        return LanguageValidation(
            coherent=True,
            language="en",
            script="Latin",
            confidence="high",
            notes="",
            model="gemini-2.0-flash",
            skipped=False,
        )

    monkeypatch.setattr(md_mod, "detect_and_decode", fake_detect)
    monkeypatch.setattr(md_mod, "validate_language", fake_validate)

    extractor = md_mod.MarkItDownExtractor(enable_plugins=False)
    result = extractor.extract(str(fake_txt))

    enc_step = next(
        (s for s in result.processing_chain if s["step"] == "encoding_detection"),
        None,
    )
    assert enc_step is not None, "encoding_detection step missing from chain"
    assert enc_step["coherent"] is True
    assert enc_step["llm_coherent"] is True
    assert enc_step["encoding_confidence"] == 0.9
    assert not any(
        "text may be garbled" in w for w in result.warnings
    ), "No garbled-text warning on happy path"


def test_encoding_gate_drives_suspect_tags_on_mojibake(tmp_path, monkeypatch):
    """Mojibake: byte detector says low confidence; LLM is fooled and votes
    coherent=true. Suggested tags must include encoding:suspect and
    status:needs-review so agents can filter the doc out of search."""
    from pipeline.extraction import markitdown as md_mod
    from pipeline.extraction.text_encoding import LanguageValidation

    fake_txt = tmp_path / "mojibake.txt"
    fake_txt.write_text("pretend this is mojibake", encoding="utf-8")

    def fake_detect(path):
        return ("pretend decoded text", "windows-1252", 0.0)

    def fake_validate(text, config):
        return LanguageValidation(
            coherent=True,
            language="en",
            script="Latin",
            confidence="high",
            notes="",
            model="gemini-2.0-flash",
            skipped=False,
        )

    monkeypatch.setattr(md_mod, "detect_and_decode", fake_detect)
    monkeypatch.setattr(md_mod, "validate_language", fake_validate)

    extractor = md_mod.MarkItDownExtractor(enable_plugins=False)
    result = extractor.extract(str(fake_txt))

    assert "encoding:suspect" in result.suggested_tags, (
        f"Expected encoding:suspect tag when byte confidence is 0.0 "
        f"(mojibake gate), got {result.suggested_tags}"
    )
    assert "status:needs-review" in result.suggested_tags, (
        f"Expected status:needs-review tag when byte confidence is 0.0, "
        f"got {result.suggested_tags}"
    )
