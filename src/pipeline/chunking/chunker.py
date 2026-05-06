"""Document chunking strategies.

Splits Markdown into semantically coherent chunks for embedding and retrieval.
Three strategies: by_title (heading boundaries), by_page (page markers),
and fixed_size (character windows with overlap).

Auto-selects strategy by file type, with caller override via chunking_config.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# Matches Markdown headings (# through ######)
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Matches page break markers that MarkItDown may insert
_PAGE_BREAK_PATTERN = re.compile(
    r"(?:^|\n)(?:---\s*Page\s+\d+\s*---|<!-- page \d+ -->)\s*\n", re.IGNORECASE
)

# Rough token estimate: ~4 characters per token
_CHARS_PER_TOKEN = 4


@dataclass
class ChunkingConfig:
    """Configuration for the chunking step."""

    strategy: str = "by_title"
    max_characters: int = 1500
    new_after_n_chars: int = 1000
    overlap: int = 200
    combine_under_n_chars: int = 200
    # Floor below which chunks are coalesced into a neighbor (by_title only).
    # 50 tokens × _CHARS_PER_TOKEN=4 ≈ 200 chars, deliberately aligned with
    # combine_under_n_chars but acting at a different stage (post-construction).
    min_chunk_tokens: int = 50


@dataclass
class Chunk:
    """A single chunk of a document."""

    chunk_id: str
    document_id: str
    collection_id: str
    chunk_index: int
    text: str
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    token_count: int = 0
    embedding_model: str | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def auto_select_strategy(file_type: str, markdown: str) -> ChunkingConfig:
    """Auto-select chunking strategy based on file type and content.

    Args:
        file_type: File extension without dot (e.g., "pdf", "pptx").
        markdown: The extracted Markdown content.

    Returns:
        ChunkingConfig with the appropriate strategy and parameters.
    """
    ft = file_type.lower().lstrip(".")

    if ft == "pptx":
        return ChunkingConfig(strategy="by_page")

    if ft in ("csv", "xlsx", "xls"):
        return ChunkingConfig(strategy="fixed_size")

    # Check if text-like content has headings
    if ft in ("txt", "log", "md"):
        has_headings = bool(_HEADING_PATTERN.search(markdown))
        if has_headings:
            return ChunkingConfig(strategy="by_title")
        # No headings — fixed_size with high overlap
        return ChunkingConfig(strategy="fixed_size", overlap=400)

    # Default for pdf, docx, html, etc.
    return ChunkingConfig(strategy="by_title")


def chunk_document(
    markdown: str,
    document_id: str,
    collection_id: str,
    file_type: str,
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    """Chunk a Markdown document into segments for embedding.

    Args:
        markdown: The Markdown content to chunk.
        document_id: ID of the source document.
        collection_id: Collection the document belongs to.
        file_type: File type (for auto-selecting strategy).
        config: Optional chunking config override. If None, auto-selects.

    Returns:
        List of Chunk objects.
    """
    if not markdown.strip():
        return []

    if config is None:
        config = auto_select_strategy(file_type, markdown)

    if config.strategy == "by_title":
        raw_chunks = _chunk_by_title(markdown, config)
    elif config.strategy == "by_page":
        raw_chunks = _chunk_by_page(markdown, config)
    elif config.strategy == "fixed_size":
        raw_chunks = _chunk_fixed_size(markdown, config)
    else:
        raise ValueError(f"Unknown chunking strategy: {config.strategy}")

    chunks = []
    for i, (text, section, page) in enumerate(raw_chunks):
        text = text.strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                chunk_id=f"{document_id}-chunk-{i:04d}",
                document_id=document_id,
                collection_id=collection_id,
                chunk_index=i,
                text=text,
                section=section,
                page_start=page,
                page_end=page,
                token_count=estimate_tokens(text),
            )
        )

    # ariadne--mr6 (design §3): post-pass min-token coalesce, by_title only.
    # fixed_size has overlap=200 by default, so concatenating two consecutive
    # fixed_size chunks would double-count the overlap region. by_page is
    # untouched per the brief's scope. The coalesce runs on already-built
    # Chunk objects so it can be unit-tested directly.
    if config.strategy == "by_title":
        chunks = _coalesce_undersized(chunks, config.min_chunk_tokens)

    return chunks


def _chunk_by_title(
    markdown: str, config: ChunkingConfig
) -> list[tuple[str, str | None, int | None]]:
    """Split Markdown by heading boundaries.

    Each heading starts a new section. Sections exceeding max_characters
    are further split at paragraph boundaries. Tiny sections are merged
    with the next one.
    """
    # Split into sections by heading
    sections: list[tuple[str | None, str]] = []
    last_end = 0
    current_heading = None

    for match in _HEADING_PATTERN.finditer(markdown):
        # Content before this heading belongs to the previous section
        content = markdown[last_end : match.start()]
        if content.strip() or sections:
            sections.append((current_heading, content))
        current_heading = match.group(2).strip()
        last_end = match.end()

    # Remaining content after last heading
    remaining = markdown[last_end:]
    sections.append((current_heading, remaining))

    # Combine tiny sections
    #
    # NOTE (ariadne--mr6, design §2): the original guard required BOTH the
    # previous accumulator AND the current section to be tiny. That lets a
    # bare-heading section (text effectively empty) survive whenever its
    # predecessor was large — the empirical "## Step 2" survives because
    # "## Step 1" already grew past combine_under_n_chars. We loosen the
    # condition: if the *current* section is tiny and there is anything to
    # merge into, merge. This catches sandwiched bare headings at section-
    # grouping time. Cases this still misses (first-section, final-section,
    # post-paragraph-split) are picked up by the post-pass min-token floor
    # in chunk_document via _coalesce_undersized.
    combined: list[tuple[str | None, str]] = []
    for heading, text in sections:
        if combined and len(text.strip()) < config.combine_under_n_chars:
            prev_heading, prev_text = combined[-1]
            # Re-add the heading as text when merging
            if heading:
                merged = prev_text.rstrip() + f"\n\n## {heading}\n" + text
            else:
                merged = prev_text + text
            combined[-1] = (prev_heading, merged)
        else:
            combined.append((heading, text))

    # Split oversized sections and produce output tuples
    result: list[tuple[str, str | None, int | None]] = []
    for heading, text in combined:
        text = text.strip()
        if not text:
            continue

        # Re-prepend the heading so the chunk is self-contained
        if heading:
            text = f"## {heading}\n\n{text}"

        if len(text) <= config.max_characters:
            result.append((text, heading, None))
        else:
            # Split at paragraph boundaries
            for sub in _split_at_paragraphs(text, config):
                result.append((sub, heading, None))

    return result


def _chunk_by_page(
    markdown: str, config: ChunkingConfig
) -> list[tuple[str, str | None, int | None]]:
    """Split Markdown by page break markers.

    Falls back to fixed_size if no page markers are found.
    """
    pages = _PAGE_BREAK_PATTERN.split(markdown)

    if len(pages) <= 1:
        # No page markers — fall back to fixed_size
        return _chunk_fixed_size(markdown, config)

    result: list[tuple[str, str | None, int | None]] = []
    for i, page_text in enumerate(pages):
        page_text = page_text.strip()
        if not page_text:
            continue
        page_num = i + 1

        if len(page_text) <= config.max_characters:
            result.append((page_text, None, page_num))
        else:
            # Split oversized pages
            for sub in _split_at_paragraphs(page_text, config):
                result.append((sub, None, page_num))

    return result


def _chunk_fixed_size(
    markdown: str, config: ChunkingConfig
) -> list[tuple[str, str | None, int | None]]:
    """Split Markdown into fixed-size character windows with overlap."""
    text = markdown.strip()
    if not text:
        return []

    max_chars = config.max_characters
    overlap = config.overlap
    step = max(1, max_chars - overlap)

    result: list[tuple[str, str | None, int | None]] = []
    pos = 0

    while pos < len(text):
        end = pos + max_chars
        chunk_text = text[pos:end]

        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            # Look for last paragraph break within the window
            last_para = chunk_text.rfind("\n\n")
            if last_para > max_chars // 2:
                chunk_text = chunk_text[: last_para + 1]
                end = pos + last_para + 1
            else:
                # Try sentence boundary
                last_period = chunk_text.rfind(". ")
                if last_period > max_chars // 2:
                    chunk_text = chunk_text[: last_period + 1]
                    end = pos + last_period + 1

        result.append((chunk_text, None, None))

        # Advance by step, but at least past the current end minus overlap
        pos = max(pos + step, end - overlap)
        if pos <= result[-1][0].__len__() + (pos - step) - max_chars:
            # Safety: always advance
            pos = end

    return result


def _split_at_paragraphs(
    text: str, config: ChunkingConfig
) -> list[str]:
    """Split a long text at paragraph boundaries, respecting max_characters."""
    paragraphs = re.split(r"\n\n+", text)
    result: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para.strip()

        if len(candidate) <= config.max_characters:
            current = candidate
        else:
            if current:
                result.append(current)
            # If single paragraph exceeds max, force-split it
            if len(para) > config.max_characters:
                for i in range(0, len(para), config.max_characters):
                    result.append(para[i : i + config.max_characters])
                current = ""
            else:
                current = para.strip()

    if current:
        result.append(current)

    return result


def _coalesce_undersized(chunks: list[Chunk], min_tokens: int) -> list[Chunk]:
    """Merge any chunk under min_tokens into a neighbor (FOLLOWING preferred).

    Walks the chunk list once with re-test: if chunks[i].token_count < min_tokens,
    merge it INTO chunks[i+1] (text prepended, target survives) and re-test the
    merged target on the next iteration without advancing i. If chunks[i] is the
    final chunk and below the floor, merge it INTO chunks[i-1] (text appended)
    instead. If chunks[i] is the only chunk in the document and below the floor,
    keep it as-is (deleting content is worse than retaining a small chunk).

    After all merges: chunk_index is renumbered sequentially, chunk_id is
    regenerated to match (matching the f"{document_id}-chunk-{i:04d}" pattern
    used in chunk_document), and token_count is recomputed on every surviving
    chunk via estimate_tokens.

    Section-field drift contract (per design §6 weak point 3, option (b)):
    when chunks[i] (sub-floor) merges into chunks[i+1], the surviving chunk
    keeps chunks[i+1].section. Its text now begins with chunks[i]'s heading
    prose (e.g., "## Step 2\\n\\n" then Step 3's body). This is intentional —
    the alternative (stripping the leading heading) would silently delete
    content for the sake of label consistency, and no current SQL/Python code
    in the codebase filters or groups by chunk.section. The contract: after
    coalesce, chunk.section names the section the chunk was anchored to at
    construction, not necessarily every heading appearing in chunk.text.

    Whitespace hygiene: each merge applies rstrip()/lstrip() at the boundary
    and a final strip() to the merged text. This matters because a freshly-
    merged chunk may itself merge again on the next iteration; without the
    boundary strip, repeated merges would accumulate "\\n\\n" separators.

    Idempotence (sort of): the function strictly decreases len(chunks) on every
    merge, so it always terminates. Calling _coalesce_undersized again on its
    own output is a no-op when min_tokens is unchanged: each remaining chunk
    is either at/above the floor, or is the only chunk in the document.
    """
    if not chunks:
        return chunks

    i = 0
    while i < len(chunks):
        c = chunks[i]
        if c.token_count >= min_tokens:
            i += 1
            continue
        if i + 1 < len(chunks):
            # Merge INTO the FOLLOWING chunk: text prepended, target survives.
            target = chunks[i + 1]
            merged_text = (c.text.rstrip() + "\n\n" + target.text.lstrip()).strip()
            target.text = merged_text
            target.token_count = estimate_tokens(merged_text)
            del chunks[i]
            # Do not advance i; re-test the merged target on the next loop pass.
        elif i > 0:
            # Final chunk, no follower: merge INTO the PREVIOUS chunk.
            prev = chunks[i - 1]
            merged_text = (prev.text.rstrip() + "\n\n" + c.text.lstrip()).strip()
            prev.text = merged_text
            prev.token_count = estimate_tokens(merged_text)
            del chunks[i]
            break  # nothing left to walk
        else:
            # Single sub-floor chunk; keep it. Better to retain content than
            # delete the entire document's text for the sake of a floor.
            break

    # Re-index chunk_index and regenerate chunk_id sequentially.
    # The chunk_id pattern matches chunk_document's f"{document_id}-chunk-{i:04d}"
    # so post-pass output is indistinguishable from a chunker that emitted these
    # boundaries in the first place.
    for idx, ch in enumerate(chunks):
        ch.chunk_index = idx
        ch.chunk_id = f"{ch.document_id}-chunk-{idx:04d}"

    return chunks
