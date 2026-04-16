"""MarkItDown wrapper for document extraction."""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlretrieve

from markitdown import MarkItDown

from pipeline.extraction.text_encoding import detect_and_decode, validate_language
from pipeline.config import load_config


@dataclass
class ExtractionResult:
    """Result of a document extraction."""

    document_id: str
    source_file: str
    markdown: str
    title: str | None
    file_type: str
    pages: int | None
    engine: str
    processing_time_ms: int
    output_tokens_estimate: int
    token_savings_ratio: float | None
    processing_chain: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    suggested_tags: list[str] = field(default_factory=list)


def _guess_file_type(source: str) -> str:
    """Extract file extension from a URI or path."""
    parsed = urlparse(source)
    path = parsed.path if parsed.scheme else source
    ext = Path(path).suffix.lower().lstrip(".")
    return ext or "unknown"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(1, len(text) // 4)


class MarkItDownExtractor:
    """Wraps Microsoft's MarkItDown for document-to-Markdown conversion."""

    def __init__(self, enable_plugins: bool = True) -> None:
        self._md = MarkItDown(enable_plugins=enable_plugins)

    def extract(self, uri: str) -> ExtractionResult:
        """Convert a document at the given URI to Markdown.

        Args:
            uri: file://, http://, https://, or local path.

        Returns:
            ExtractionResult with the converted Markdown and metadata.
        """
        document_id = str(uuid.uuid4())
        source_file = Path(urlparse(uri).path).name if "://" in uri else Path(uri).name
        file_type = _guess_file_type(uri)

        start = time.perf_counter()
        warnings: list[str] = []
        errors: list[str] = []

        # Resolve URI to a local path for conversion
        local_path = self._resolve_uri(uri)

        # For .txt files, decode with charset-normalizer and use the decoded
        # text directly as markdown. MarkItDown's content sniffer (Magika)
        # misdetects valid UTF-8 as ASCII, crashing on multi-byte characters.
        encoding_info: dict[str, Any] | None = None
        txt_decoded: str | None = None
        if file_type == "txt":
            try:
                decoded_text, detected_encoding, enc_confidence = detect_and_decode(
                    Path(local_path)
                )
                encoding_info = {
                    "detected_encoding": detected_encoding,
                    "encoding_confidence": enc_confidence,
                }
                txt_decoded = decoded_text
            except Exception as e:
                errors.append(f"Encoding detection failed: {e}")
                encoding_info = None

        if txt_decoded is not None:
            # .txt: use charset-normalizer output directly, skip MarkItDown
            markdown = txt_decoded
            title = None
            # Still clean up URL download temp files if applicable
            if local_path != uri and local_path != self._strip_file_scheme(uri):
                try:
                    os.unlink(local_path)
                except OSError:
                    pass
        else:
            # All non-.txt files (and .txt fallback if detection failed)
            try:
                result = self._md.convert(local_path)
                markdown = result.markdown or ""
                title = result.title
            except Exception as e:
                errors.append(str(e))
                markdown = ""
                title = None
            finally:
                # Clean up temp files from URL downloads
                if local_path != uri and local_path != self._strip_file_scheme(uri):
                    try:
                        os.unlink(local_path)
                    except OSError:
                        pass

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        output_tokens = _estimate_tokens(markdown)

        # Warn about images needing vision API when output is empty/trivial
        _IMAGE_TYPES = {"jpg", "jpeg", "png", "gif"}
        if file_type in _IMAGE_TYPES and len(markdown.strip()) < 20:
            warnings.append(
                "Image files require a vision API key (VISION_API_KEY) for "
                "content extraction. Without it, images are accepted but "
                "produce empty output."
            )

        processing_chain = [
            {
                "step": "extraction",
                "tool": "markitdown",
                "ts": datetime.now(timezone.utc).isoformat(),
                "ms": elapsed_ms,
            }
        ]

        # Encoding detection + LLM language validation for .txt files
        suggested_tags: list[str] = []
        if file_type == "txt" and encoding_info is not None:
            detected_encoding = encoding_info["detected_encoding"]
            enc_confidence = encoding_info["encoding_confidence"]

            # LLM language validation
            validation_start = time.perf_counter()
            try:
                config = load_config()
                lang_result = validate_language(markdown, config.image_enrichment)
            except Exception:
                from pipeline.config import ImageEnrichmentConfig
                lang_result = validate_language(markdown, ImageEnrichmentConfig())
            validation_ms = int((time.perf_counter() - validation_start) * 1000)

            processing_chain.append({
                "step": "encoding_detection",
                "detected_encoding": detected_encoding,
                "encoding_confidence": enc_confidence,
                "language": lang_result.language,
                "language_script": lang_result.script,
                "language_confidence": lang_result.confidence,
                "coherent": lang_result.coherent,
                "llm_model": lang_result.model,
                "ts": datetime.now(timezone.utc).isoformat(),
                "ms": validation_ms,
            })

            # Warnings
            if detected_encoding.lower() not in ("utf-8", "ascii", "utf_8"):
                warnings.append(
                    f"Source file encoding: {detected_encoding} (not UTF-8)"
                )
            if lang_result.confidence == "low":
                warnings.append("Encoding validation: low confidence")
            if not lang_result.coherent:
                warnings.append("Encoding validation: text may be garbled")

            # Tags
            if detected_encoding.lower() not in ("utf-8", "ascii", "utf_8"):
                suggested_tags.append(f"encoding:{detected_encoding}")
            if lang_result.language and lang_result.language != "unknown":
                suggested_tags.append(f"language:{lang_result.language}")
            if lang_result.confidence == "low":
                suggested_tags.append("encoding:low-confidence")
            if not lang_result.coherent:
                suggested_tags.append("encoding:suspect")
                suggested_tags.append("status:needs-review")

        return ExtractionResult(
            document_id=document_id,
            source_file=source_file,
            markdown=markdown,
            title=title,
            file_type=file_type,
            pages=None,  # MarkItDown doesn't reliably report page count
            engine="markitdown",
            processing_time_ms=elapsed_ms,
            output_tokens_estimate=output_tokens,
            token_savings_ratio=None,  # Can't calculate without knowing input size
            processing_chain=processing_chain,
            warnings=warnings,
            errors=errors,
            suggested_tags=suggested_tags,
        )

    def _resolve_uri(self, uri: str) -> str:
        """Resolve a URI to a local file path, downloading if needed."""
        if uri.startswith("file://"):
            return self._strip_file_scheme(uri)

        if uri.startswith(("http://", "https://")):
            return self._download_to_temp(uri)

        # Assume local path
        return uri

    @staticmethod
    def _strip_file_scheme(uri: str) -> str:
        """Convert file:// URI to local path."""
        parsed = urlparse(uri)
        return parsed.path

    @staticmethod
    def _download_to_temp(url: str) -> str:
        """Download a URL to a temp file, preserving extension."""
        ext = Path(urlparse(url).path).suffix
        fd, path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        urlretrieve(url, path)
        return path
