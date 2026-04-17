"""Image enrichment post-processing.

Scans Markdown output for image references, sends each to a vision API,
and injects descriptions back into the Markdown. Designed to run as
pipeline step 2 (after extraction, before chunking).

If no vision API is configured (no API key), images are left as-is.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pipeline.enrichment.vision import VisionClient, VisionConfig

# Matches Markdown image syntax: ![alt](src)
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Matches an existing image description block we've already injected
_DESCRIPTION_BLOCK = re.compile(
    r"\n> \*\*Image description:\*\*.*?(?=\n[^>]|\Z)", re.DOTALL
)


@dataclass
class ImageEnrichmentResult:
    """Result of the image enrichment step."""

    markdown: str
    images_processed: int
    images_skipped: int
    errors: list[str] = field(default_factory=list)
    processing_time_ms: int = 0
    processing_chain_entry: dict[str, Any] = field(default_factory=dict)


def _has_description(markdown: str, match_end: int) -> bool:
    """Check if the image already has a description block after it."""
    rest = markdown[match_end:]
    # Look for description block immediately after (possibly separated by newline)
    return rest.lstrip("\n").startswith("> **Image description:**")


def _resolve_image_path(image_src: str, source_dir: str | None) -> str | None:
    """Resolve an image source to an accessible path or URL.

    Returns None if the image can't be resolved.
    """
    parsed = urlparse(image_src)

    # HTTP(S) URL — use directly
    if parsed.scheme in ("http", "https"):
        return image_src

    # data: URL — use directly
    if parsed.scheme == "data":
        return image_src

    # Local path — try to resolve relative to source document
    if source_dir:
        candidate = Path(source_dir) / image_src
        if candidate.exists():
            return str(candidate)

    # Absolute path
    if Path(image_src).is_absolute() and Path(image_src).exists():
        return image_src

    return None


class ImageEnricher:
    """Post-processes Markdown to add vision-generated image descriptions."""

    def __init__(self, config: VisionConfig | None = None) -> None:
        self._config = config
        self._client = VisionClient(config) if config and config.api_key else None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def enrich(
        self, markdown: str, source_dir: str | None = None
    ) -> ImageEnrichmentResult:
        """Scan Markdown for images and add descriptions.

        Args:
            markdown: The Markdown content to enrich.
            source_dir: Directory of the source document (for resolving
                relative image paths).

        Returns:
            ImageEnrichmentResult with enriched Markdown and stats.
        """
        if not self.enabled:
            return ImageEnrichmentResult(
                markdown=markdown,
                images_processed=0,
                images_skipped=0,
                processing_chain_entry={},
            )

        start = time.perf_counter()
        images_processed = 0
        images_skipped = 0
        errors: list[str] = []

        # Find all images and process in reverse order so offsets stay valid
        matches = list(_IMAGE_PATTERN.finditer(markdown))

        for match in reversed(matches):
            alt_text = match.group(1)
            image_src = match.group(2)

            # Skip if already has a description
            if _has_description(markdown, match.end()):
                images_skipped += 1
                continue

            # Try to resolve the image
            resolved = _resolve_image_path(image_src, source_dir)
            if resolved is None:
                images_skipped += 1
                errors.append(f"Could not resolve image: {image_src}")
                continue

            # Get description from vision API
            try:
                description = self._describe_image(resolved)
                # Inject description block after the image
                desc_block = f"\n\n> **Image description:** {description}"
                markdown = (
                    markdown[: match.end()] + desc_block + markdown[match.end() :]
                )
                images_processed += 1
            except Exception as e:
                images_skipped += 1
                errors.append(f"Vision API error for {image_src}: {e}")

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        chain_entry = {
            "step": "image_enrichment",
            "tool": f"gemini:{self._config.model}" if self._config else "none",
            "ts": datetime.now(timezone.utc).isoformat(),
            "ms": elapsed_ms,
            "images_processed": images_processed,
        }

        return ImageEnrichmentResult(
            markdown=markdown,
            images_processed=images_processed,
            images_skipped=images_skipped,
            errors=errors,
            processing_time_ms=elapsed_ms,
            processing_chain_entry=chain_entry,
        )

    def describe_image(self, file_path: str) -> str:
        """Get a description for a standalone image file via the vision API.

        Unlike ``enrich()``, which scans Markdown for embedded image references,
        this calls the vision client directly on a single image file. Used for
        standalone image ingestion where MarkItDown produces no extractable text.
        """
        assert self._client is not None
        return self._client.describe_image_from_path(file_path)

    def _describe_image(self, image_ref: str) -> str:
        """Get a description for an image via the vision API."""
        assert self._client is not None

        parsed = urlparse(image_ref)

        if parsed.scheme == "data":
            # data:image/png;base64,... — extract mime and data
            header, data = image_ref.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            return self._client.describe_image_from_base64(data, mime)

        if parsed.scheme in ("http", "https"):
            return self._client.describe_image_from_url(image_ref)

        # Local file path
        return self._client.describe_image_from_path(image_ref)
