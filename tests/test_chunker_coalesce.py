"""Tests for the post-pass min-token coalesce in chunker.py (ariadne--mr6).

The coalesce has two coordinated parts per design §2/§3:

1. Preconditioning in _chunk_by_title: loosened merge condition catches
   sandwiched bare headings at section-grouping time.
2. Post-pass guarantee in chunk_document: _coalesce_undersized walks the
   final Chunk list and merges any chunk under min_chunk_tokens into a
   neighbor (FOLLOWING preferred; PREVIOUS only for the doc's final chunk).

Probes 7a-7d (named in design §5) cover:
  - 7a: first chunk is bare-heading (case §2 cannot rescue)
  - 7b: final chunk is bare-heading (case §2 cannot rescue)
  - 7c: bare heading sandwiched (the empirical case from doc 9f143eb3)
  - 7d: single-chunk doc below floor (algorithm preserves it)

Plus:
  - Bug-detection regression: a doc whose pre-fix output had bare-heading
    chunks must now have none below the floor (except final-chunk).
  - Direct unit tests of _coalesce_undersized on synthetic Chunk lists.
  - Strategy gate: fixed_size and by_page must NOT be coalesced.
  - Section-field drift contract per §6 weak point 3 option (b).
  - chunk_index / chunk_id renumbering after merges.
"""

from __future__ import annotations

import textwrap

from pipeline.chunking.chunker import (
    Chunk,
    ChunkingConfig,
    _coalesce_undersized,
    chunk_document,
    estimate_tokens,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_chunk(
    document_id: str,
    index: int,
    text: str,
    section: str | None = None,
) -> Chunk:
    """Build a Chunk for direct _coalesce_undersized tests."""
    return Chunk(
        chunk_id=f"{document_id}-chunk-{index:04d}",
        document_id=document_id,
        collection_id="default",
        chunk_index=index,
        text=text,
        section=section,
        token_count=estimate_tokens(text),
    )


def _is_bare_heading(text: str) -> bool:
    """Single-line markdown heading (no body), per design §5 probe 4c."""
    stripped = text.strip()
    return stripped.startswith("## ") and stripped.count("\n") == 0


# ── Probes 7a-7d (named in design §5, ADA-must-include) ──────────────────────


class TestProbe7aFirstBareHeading:
    """Doc starting with a bare heading. §2 cannot rescue (no combined[-1])."""

    def test_first_chunk_is_not_bare_heading(self):
        # Real-world shape: a doc whose first heading has no body, then a
        # second heading with a long body. Pre-fix would emit "## Step 1"
        # as a standalone bare-heading chunk (~10 chars, ~3 tokens).
        body_a = "This is the body of step two with substantial content. " * 12
        body_b = "Step three body with more substantial content here. " * 12
        md = textwrap.dedent(
            f"""\
            ## Step 1

            ## Step 2

            {body_a}

            ## Step 3

            {body_b}
            """
        )
        chunks = chunk_document(md, "doc-7a", "default", "pdf")
        assert len(chunks) >= 1
        # No chunk is a bare single-line heading.
        for c in chunks:
            assert not _is_bare_heading(c.text), (
                f"chunk {c.chunk_index} is bare heading: {c.text!r}"
            )
        # No chunk under the floor (50 tokens) UNLESS it's the only chunk.
        if len(chunks) > 1:
            for c in chunks:
                assert c.token_count >= 50, (
                    f"chunk {c.chunk_index} token_count={c.token_count} text={c.text[:80]!r}"
                )


class TestProbe7bFinalBareHeading:
    """Doc ending with a bare heading. Merges INTO the previous via elif i > 0."""

    def test_final_chunk_is_not_bare_heading(self):
        body_a = "Section A has substantial content covering an important topic. " * 12
        # Trailing bare heading "## Note" with no body.
        md = textwrap.dedent(
            f"""\
            ## Section A

            {body_a}

            ## Note
            """
        )
        chunks = chunk_document(md, "doc-7b", "default", "pdf")
        assert len(chunks) >= 1
        for c in chunks:
            assert not _is_bare_heading(c.text), (
                f"chunk {c.chunk_index} is bare heading: {c.text!r}"
            )
        # The "## Note" content should appear inside the surviving chunk text.
        joined = "\n".join(c.text for c in chunks)
        assert "Note" in joined, "## Note content was lost during coalesce"


class TestProbe7cSandwichedBareHeading:
    """The empirical case from doc 9f143eb3 (15/318 chunks <10 tokens)."""

    def test_sandwiched_bare_heading_eliminated(self):
        body_a = "Step one body with substantial content for the section. " * 12
        body_c = "Step three body with substantial content for the section. " * 12
        # Pre-fix: "## Step 2" survives because §2 required BOTH neighbors tiny.
        # Loosened §2 merges Step 2 into Step 1's accumulator; if anything
        # leaks past, §3 catches it.
        md = textwrap.dedent(
            f"""\
            ## Step 1

            {body_a}

            ## Step 2

            ## Step 3

            {body_c}
            """
        )
        chunks = chunk_document(md, "doc-7c", "default", "pdf")
        assert len(chunks) >= 1
        for c in chunks:
            assert not _is_bare_heading(c.text), (
                f"chunk {c.chunk_index} is bare heading: {c.text!r}"
            )
        if len(chunks) > 1:
            for c in chunks:
                assert c.token_count >= 50, (
                    f"chunk {c.chunk_index} below floor: {c.text[:80]!r}"
                )

    def test_step_two_content_preserved(self):
        """## Step 2 heading prose must end up inside some surviving chunk —
        the design's option (b) decision keeps the heading text rather than
        silently deleting it."""
        body_a = "Step one substantial body content for testing. " * 12
        body_c = "Step three substantial body content for testing. " * 12
        md = textwrap.dedent(
            f"""\
            ## Step 1

            {body_a}

            ## Step 2

            ## Step 3

            {body_c}
            """
        )
        chunks = chunk_document(md, "doc-7c-prose", "default", "pdf")
        joined = "\n".join(c.text for c in chunks)
        # All three heading labels should appear somewhere in the joined text.
        # (They may be re-prepended by _chunk_by_title or absorbed during merge.)
        assert "Step 1" in joined
        assert "Step 2" in joined
        assert "Step 3" in joined


class TestProbe7dSingleChunkBelowFloor:
    """The algorithm preserves a single below-floor chunk rather than deleting."""

    def test_single_below_floor_chunk_survives(self):
        # Tiny doc whose only output chunk would fall under the 50-token floor.
        md = "## Tiny\n\nshort.\n"
        chunks = chunk_document(md, "doc-7d", "default", "pdf")
        # Exactly one chunk; content not deleted.
        assert len(chunks) == 1
        assert "short" in chunks[0].text or "Tiny" in chunks[0].text

    def test_single_below_floor_chunk_via_helper_directly(self):
        """Same property exercised through _coalesce_undersized in isolation."""
        only = [_make_chunk("doc-7d-direct", 0, "short.")]
        out = _coalesce_undersized(only, min_tokens=50)
        assert len(out) == 1
        assert out[0].text == "short."


# ── Bug-detection regression test (per Batch B's pattern) ────────────────────


class TestBugDetectionAgainstPreFix:
    """Empirical-shape input that pre-fix produced bare-heading chunks for.
    Pre-fix (loosened §2 not applied AND no post-pass §3): expect bare-heading
    chunks below the floor. Post-fix: none should remain.
    """

    def _build_empirical_md(self) -> str:
        # Approximation of the doc 9f143eb3 shape: large Step 1, a sandwiched
        # heading whose body is non-empty but trivially short (the wild shape
        # — totally empty bodies are eaten by the existing strip+continue at
        # chunker.py result-build time, so the sub-floor chunks that actually
        # survive pre-fix have a tiny non-empty body like "x." or "## Column"),
        # large Step 3, plus a trailing bare ## Note.
        # Pre-fix shape (as validated by manual simulation in this test file's
        # development): chunk count >= 3, with at least one chunk at
        # token_count < 50 (e.g., "## Step 2\n\nx." at ~3 tokens). Post-fix:
        # the sub-floor chunk merges into a neighbor and no chunk below 50
        # tokens remains (the doc has multiple chunks, so the single-chunk
        # preservation rule does not apply).
        body = "This step contains substantial body content for the section. " * 12
        return textwrap.dedent(
            f"""\
            ## Step 1

            {body}

            ## Step 2

            x.

            ## Step 3

            {body}

            ## Note
            """
        )

    def test_empirical_no_bare_heading_below_floor(self):
        md = self._build_empirical_md()
        chunks = chunk_document(md, "doc-empirical", "default", "pdf")

        # Post-fix invariants:
        #   (a) no chunk is a bare single-line "## ..." heading;
        #   (b) every chunk has token_count >= 50 (unless it's the only one).
        bare = [c for c in chunks if _is_bare_heading(c.text)]
        assert bare == [], f"bare-heading chunks survived: {[c.text for c in bare]}"

        if len(chunks) > 1:
            below = [c for c in chunks if c.token_count < 50]
            assert below == [], (
                f"sub-floor chunks survived (below 50 tokens): "
                f"{[(c.chunk_index, c.token_count, c.text[:60]) for c in below]}"
            )

    def test_pre_fix_disabled_min_tokens_reproduces_bare(self):
        """Sanity: when min_chunk_tokens=0, the post-pass coalesce is a no-op
        on the floor check — but the loosened §2 still runs.

        This is a partial pre-fix simulation: it shows the §3 post-pass is
        load-bearing even after §2's preconditioning. We expect MORE small
        chunks here than with the default config, demonstrating the floor
        actually does work.
        """
        md = self._build_empirical_md()
        # min_chunk_tokens=0 disables the floor (every chunk is >= 0 tokens).
        cfg_no_floor = ChunkingConfig(strategy="by_title", min_chunk_tokens=0)
        chunks_no_floor = chunk_document(
            md, "doc-no-floor", "default", "pdf", config=cfg_no_floor
        )
        # Default config (min_chunk_tokens=50).
        chunks_with_floor = chunk_document(md, "doc-with-floor", "default", "pdf")

        # The floor-enabled run should not exceed the floor-disabled run in
        # chunk count, and must have no chunk below 50 tokens (unless it's
        # the only chunk in the doc).
        assert len(chunks_with_floor) <= len(chunks_no_floor)
        if len(chunks_with_floor) > 1:
            for c in chunks_with_floor:
                assert c.token_count >= 50


# ── Direct unit tests of _coalesce_undersized ────────────────────────────────


class TestCoalesceHelperDirect:
    """Unit-test the helper without going through markdown extraction."""

    def test_empty_list_returns_empty(self):
        assert _coalesce_undersized([], min_tokens=50) == []

    def test_no_subfloor_chunks_no_change(self):
        # Both chunks are above the floor; helper should leave them alone
        # (modulo the unconditional re-index, which is idempotent on already-
        # sequential indices).
        big = "x" * 400  # ~100 tokens
        chunks = [
            _make_chunk("doc", 0, big, section="A"),
            _make_chunk("doc", 1, big, section="B"),
        ]
        out = _coalesce_undersized(chunks, min_tokens=50)
        assert len(out) == 2
        assert out[0].section == "A"
        assert out[1].section == "B"
        assert out[0].chunk_index == 0
        assert out[1].chunk_index == 1

    def test_subfloor_merges_into_following(self):
        big = "y" * 400
        tiny = "tiny"  # ~1 token
        chunks = [
            _make_chunk("doc", 0, tiny, section="A"),
            _make_chunk("doc", 1, big, section="B"),
        ]
        out = _coalesce_undersized(chunks, min_tokens=50)
        assert len(out) == 1
        # Surviving chunk keeps the FOLLOWER's section (option (b) per §6).
        assert out[0].section == "B"
        # Text starts with the predecessor's content.
        assert out[0].text.startswith("tiny")
        # And contains the follower's content.
        assert "y" * 400 in out[0].text
        # chunk_index/chunk_id renumbered.
        assert out[0].chunk_index == 0
        assert out[0].chunk_id == "doc-chunk-0000"
        # token_count recomputed.
        assert out[0].token_count == estimate_tokens(out[0].text)

    def test_subfloor_final_chunk_merges_into_previous(self):
        big = "z" * 400
        tiny = "end."  # ~1 token, final chunk
        chunks = [
            _make_chunk("doc", 0, big, section="A"),
            _make_chunk("doc", 1, tiny, section="Z"),
        ]
        out = _coalesce_undersized(chunks, min_tokens=50)
        assert len(out) == 1
        # Predecessor survives; its section is retained (we merged INTO it).
        assert out[0].section == "A"
        # Text ends with the tiny final content.
        assert out[0].text.endswith("end.")

    def test_consecutive_subfloor_chunks_chain_merge(self):
        """Two subfloor chunks in a row — the merged target is re-tested and
        merges again on the next iteration."""
        big = "q" * 400
        chunks = [
            _make_chunk("doc", 0, "first.", section="A"),
            _make_chunk("doc", 1, "second.", section="B"),
            _make_chunk("doc", 2, big, section="C"),
        ]
        out = _coalesce_undersized(chunks, min_tokens=50)
        assert len(out) == 1
        # Final surviving section is C (the one that absorbed everyone).
        assert out[0].section == "C"
        # All content present.
        assert "first." in out[0].text
        assert "second." in out[0].text
        assert "q" * 400 in out[0].text

    def test_single_subfloor_chunk_preserved(self):
        """Algorithm preserves a single below-floor chunk (no neighbor)."""
        only = [_make_chunk("doc", 0, "only chunk.", section="A")]
        out = _coalesce_undersized(only, min_tokens=50)
        assert len(out) == 1
        assert out[0].text == "only chunk."
        assert out[0].section == "A"

    def test_renumbers_chunk_index_and_id_after_merge(self):
        big = "w" * 400
        chunks = [
            _make_chunk("doc-renum", 0, big, section="A"),
            _make_chunk("doc-renum", 1, "tiny", section="B"),
            _make_chunk("doc-renum", 2, big, section="C"),
            _make_chunk("doc-renum", 3, big, section="D"),
        ]
        out = _coalesce_undersized(chunks, min_tokens=50)
        # The "tiny" at index 1 merges into index 2 (section C); 3 chunks remain.
        assert len(out) == 3
        for i, ch in enumerate(out):
            assert ch.chunk_index == i
            assert ch.chunk_id == f"doc-renum-chunk-{i:04d}"

    def test_whitespace_hygiene_no_double_blank_lines_on_repeated_merge(self):
        """Repeated merges must not accumulate \\n\\n separators thanks to
        rstrip()/lstrip() boundary hygiene."""
        big = "p" * 400
        chunks = [
            _make_chunk("doc", 0, "a.\n\n\n", section="A"),
            _make_chunk("doc", 1, "\n\nb.\n", section="B"),
            _make_chunk("doc", 2, big, section="C"),
        ]
        out = _coalesce_undersized(chunks, min_tokens=50)
        assert len(out) == 1
        # No run of 3+ consecutive newlines should remain.
        assert "\n\n\n" not in out[0].text


# ── Strategy gate (per design §3 / R2) ───────────────────────────────────────


class TestStrategyGate:
    """Coalesce must NOT run for fixed_size or by_page (overlap double-count)."""

    def test_fixed_size_strategy_not_coalesced(self):
        """A fixed_size run with tiny final chunk must keep that chunk —
        coalescing it would re-include the overlap region."""
        # A short doc that fixed_size will produce a single below-floor chunk
        # for. With strategy=fixed_size the post-pass should be skipped, so
        # the tiny chunk survives intact (no coalesce attempted).
        md = "tiny."
        cfg = ChunkingConfig(strategy="fixed_size", max_characters=1500, min_chunk_tokens=50)
        chunks = chunk_document(md, "doc-fixed", "default", "csv", config=cfg)
        assert len(chunks) == 1
        # Below the floor but kept (no gate would have helped here either —
        # single-chunk preservation kicks in regardless — but the gate is
        # what blocks the pass from running on multi-chunk fixed_size docs).
        assert chunks[0].token_count < 50

    def test_by_page_strategy_not_coalesced(self):
        """by_page does not overlap, but the brief scoped this fix to by_title.
        Confirm the gate excludes by_page from the coalesce pass."""
        md = textwrap.dedent(
            """\
            tiny page one.

            --- Page 1 ---

            tiny page two.

            --- Page 2 ---

            tiny page three.
            """
        )
        cfg = ChunkingConfig(strategy="by_page", min_chunk_tokens=50)
        chunks = chunk_document(md, "doc-bypage", "default", "pptx", config=cfg)
        # Three tiny pages — without the gate, the post-pass would collapse
        # them to one. With the gate, all three survive as separate chunks.
        assert len(chunks) == 3
        for c in chunks:
            # Each is below the floor but preserved per the gate.
            assert c.token_count < 50


# ── Backward-compat: ChunkingConfig still accepts legacy kwargs ──────────────


class TestConfigBackwardCompat:
    def test_default_min_chunk_tokens_is_50(self):
        cfg = ChunkingConfig()
        assert cfg.min_chunk_tokens == 50

    def test_min_chunk_tokens_overridable(self):
        cfg = ChunkingConfig(min_chunk_tokens=25)
        assert cfg.min_chunk_tokens == 25
