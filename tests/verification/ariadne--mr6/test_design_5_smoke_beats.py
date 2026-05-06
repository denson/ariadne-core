"""Verification probes for ariadne--mr6 (Batch C): chunker post-pass min-token
coalesce. CAPTAIN_VERA's job is to chase design §5 smoke beats that ADA's unit
tests do not exercise directly, plus the design §6 weak-point-1 regression
shape that ADA's residual #2 flagged.

ADA's tests/test_chunker_coalesce.py covers probes 7a-7d (the named edge cases
in design §5) plus helper-direct unit tests, the strategy gate, and a bug-
detection regression test against the empirical 9f143eb3 doc shape. What ADA
did NOT directly probe at the unit-test level:

  - Probe 4a (count): post-fix chunk count drops materially on a multi-
    section heading-heavy doc that mimics 9f143eb3's enumerated bare-
    heading sample set (`## Step 1`, `## Step 2`, `## Column`, `## Plan`,
    `## Note`, etc.).
  - Probe 4b (floor): no chunk is below the 50-token floor on the same
    multi-chunk synthetic doc. (ADA's TestBugDetection covers a smaller
    shape; this one stresses the multi-section case the diagnostic
    enumerated.)
  - Probe 4c (no single-line "## " chunk regardless of length): a chunk
    whose only text is a single-line heading must not survive even when
    the heading title alone clears the 200-character combine threshold.
  - Probe 4d (sample-set non-recurrence): for each of the 14 enumerated
    bare-heading sample texts from `bw show ariadne--a3i`, none should
    appear as a standalone chunk in any reasonable post-fix output.
  - Probe 6 (no regression on well-behaved docs): a doc with sections
    of 200-500 tokens each, no bare headings, should not see significant
    chunk-count or chunk-content drift post-fix.
  - Design §6 weak point 1 / ADA residual #2: the loosened §2 condition
    can produce an oversized accumulator (1500-char Step 1 + ten empty
    `## StepN`); _split_at_paragraphs catches it downstream WITHOUT data
    loss. Regression-protection for the pathological loosened-§2 shape.

These probes operate against the WORKTREE build artifact (commit 6414c0d).
Post-merge production smoke (probe 5 — search-still-works against canary
collection) is OUT OF SCOPE for this seat per the brief; PLINY runs it.
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


def _is_bare_heading(text: str) -> bool:
    """A single-line markdown heading with no body — design §5 probe 4c."""
    s = text.strip()
    return s.startswith("## ") and s.count("\n") == 0


def _below_floor_count(chunks: list[Chunk], floor: int = 50) -> int:
    """Count chunks below the floor, EXCLUDING the single-chunk-doc case."""
    if len(chunks) <= 1:
        return 0
    return sum(1 for c in chunks if c.token_count < floor)


# Empirical bare-heading sample set from `bw show ariadne--a3i` (15 samples,
# the diagnostic agent enumerated these as the wild bare-heading texts that
# survived pre-fix in doc 9f143eb3). One sample (`'put_file_path}") |     |
#   |'`) is a markdown-table-pipe fragment, NOT a bare heading — it's out
# of scope for §3 (the brief explicitly defers table-pipe handling), so this
# probe set excludes it. The remaining 14 are bare-heading samples we expect
# the post-fix chunker NOT to emit as standalone chunks.
BARE_HEADING_SAMPLES = [
    "## Step 1",
    "## Step 2",
    "## Step 3",
    "## Step 4",
    "## Column",
    "## Requirement",
    "## Your task",
    "## Plan\n\n{plan}",
    "## Error:\n\n{bug}",
    "## --- 7. Data Preview ---\n\n19",
    "## Load the JSON data from the file",
]


# ── Probe 4a/4b — synthetic 9f143eb3-shaped multi-section doc ────────────────


class TestProbe4MultiSectionHeadingHeavy:
    """Post-fix on a synthetic doc mimicking 9f143eb3's heading-heavy shape:
    several large sections interleaved with bare-heading sandwiches.

    Pre-fix shape would emit one bare-heading chunk per sandwich AND one bare-
    heading chunk per content-bearing-but-trivially-short section (e.g.,
    `## Step 2\\n\\nx.`). Post-fix: zero chunks below the 50-token floor.
    """

    def _build_md(self) -> str:
        big = "Substantial body content for this section of the document. " * 12
        # Includes: large->bare->bare->large (probe 7c shape), tiny-body
        # sandwich (TestBugDetection shape), final bare heading (probe 7b
        # shape), AND a long heading title that pre-fix would emit alone
        # if treated naively.
        return textwrap.dedent(
            f"""\
            ## Introduction

            {big}

            ## Step 1

            {big}

            ## Step 2

            ## Step 3

            x.

            ## Column

            {big}

            ## Requirement

            {big}

            ## Your task

            ## Plan

            {{plan}}

            ## Error:

            {{bug}}

            ## --- 7. Data Preview ---

            19

            ## Load the JSON data from the file

            {big}

            ## Note
            """
        )

    def test_4a_chunk_count_is_sensible_for_multi_section_doc(self):
        """Probe 4a: total chunk count is ≤ number of large content sections,
        not one chunk per heading. A naive chunker would emit ~10+ chunks
        (one per heading + bodies); the coalesce should yield ~5-7."""
        md = self._build_md()
        chunks = chunk_document(md, "doc-4a", "default", "pdf")
        # 5 large content sections (Introduction, Step 1, Column, Requirement,
        # Load JSON) — coalesce merges trivial sections into them. Allow a
        # generous upper bound that still detects the pre-fix 11+ regression.
        assert 1 <= len(chunks) <= 8, (
            f"expected 1-8 chunks for {len(BARE_HEADING_SAMPLES)+5} headings, "
            f"got {len(chunks)}"
        )

    def test_4b_no_chunk_below_floor(self):
        """Probe 4b: every chunk is at or above min_chunk_tokens=50 (unless
        single-chunk-doc)."""
        md = self._build_md()
        chunks = chunk_document(md, "doc-4b", "default", "pdf")
        below = [c for c in chunks if c.token_count < 50]
        if len(chunks) > 1:
            assert below == [], (
                f"sub-floor chunks survived: "
                f"{[(c.chunk_index, c.token_count, c.text[:60]) for c in below]}"
            )

    def test_4c_no_single_line_heading_chunk(self):
        """Probe 4c: no chunk is a single-line `## ...` heading regardless of
        the heading-title length. (A pathological long title could clear the
        200-char combine threshold without the post-pass.)"""
        md = self._build_md()
        chunks = chunk_document(md, "doc-4c", "default", "pdf")
        bare = [c for c in chunks if _is_bare_heading(c.text)]
        assert bare == [], (
            f"single-line heading chunks survived: {[c.text for c in bare]}"
        )

    def test_4c_pathological_long_heading_title_still_caught(self):
        """A heading title >200 chars would pre-fix clear `combine_under_n_chars`
        as a single section, then chunk_document strips and prepends to
        emit it as a single-line chunk. The §3 floor (50 tokens) catches
        this because a single-line title — even 200 chars — has only one
        line and the floor rejects it on token_count if the title is short
        enough, or on the single-line `##` invariant if not.

        This probe constructs the worst case: a heading title long enough to
        clear BOTH the 200-char threshold AND the 50-token floor (so neither
        §2 nor §3 floor catches it on length). Even so, post-fix the chunk
        should not be a bare single-line heading because the post-pass
        coalesce should leave content visible — OR, if the test fails, that
        is itself useful information about an §3 gap.
        """
        # 250-character heading title — clears both 200-char §2 threshold
        # AND the ~50-token (~200-char) §3 floor.
        long_title = "A" * 250
        body = "Section content. " * 50
        md = textwrap.dedent(
            f"""\
            ## {long_title}

            {body}

            ## Tiny

            ## Final
            """
        )
        chunks = chunk_document(md, "doc-4c-pathological", "default", "pdf")
        # The original probe 4c invariant — no single-line `## ...` chunks —
        # must hold even for a long title.
        bare = [c for c in chunks if _is_bare_heading(c.text)]
        # NOTE: this assertion is the strongest form of probe 4c. If it
        # fails, the §3 algorithm has a gap — a long-title heading section
        # whose body is empty and whose neighbor is itself short can still
        # surface as a single-line chunk if the post-pass merges into it
        # without re-checking the bare-heading invariant. This is design-
        # level information.
        assert bare == [], (
            f"long-title heading survived as a single-line chunk: "
            f"{[c.text[:80] for c in bare]}"
        )

    def test_4d_no_sample_set_text_appears_as_standalone_chunk(self):
        """Probe 4d: none of the 11 bare-heading sample texts the diagnostic
        enumerated in `bw show ariadne--a3i` should appear as the COMPLETE
        text of any chunk. (They may appear as substrings inside larger
        merged chunks per design §6 weak point 3 option (b) — that's fine
        and intended; what we forbid is the standalone-chunk case.)"""
        md = self._build_md()
        chunks = chunk_document(md, "doc-4d", "default", "pdf")
        chunk_texts_stripped = {c.text.strip() for c in chunks}
        for sample in BARE_HEADING_SAMPLES:
            assert sample.strip() not in chunk_texts_stripped, (
                f"sample {sample!r} reappeared as a standalone chunk"
            )


# ── Probe 6 — no regression on well-behaved docs ─────────────────────────────


class TestProbe6NoRegressionOnWellBehavedDoc:
    """A doc whose sections are all 200-500 tokens, no bare headings, no
    sub-floor chunks pre-fix — should chunk identically (or near-identically)
    post-fix. The coalesce post-pass is a no-op for above-floor input.
    """

    def _build_md(self) -> str:
        # Each section ~ 200-300 tokens (~800-1200 chars). No section is below
        # the 200-char combine threshold OR the 50-token floor. There are no
        # bare headings.
        body_a = "Section A discusses the fundamental concept under review. " * 16
        body_b = "Section B builds on the previous section's framework. " * 16
        body_c = "Section C extends the analysis to a third configuration. " * 16
        body_d = "Section D draws conclusions and outlines future work. " * 16
        return textwrap.dedent(
            f"""\
            ## Introduction

            {body_a}

            ## Background

            {body_b}

            ## Method

            {body_c}

            ## Discussion

            {body_d}
            """
        )

    def test_well_behaved_chunk_count_unchanged(self):
        """Pre-fix and post-fix should yield the same chunk count on a doc
        with no sub-floor sections. We test by comparing the post-pass output
        to the pre-coalesce output (which we obtain by setting
        min_chunk_tokens=0 on the same fix code: the loosened §2 still
        runs, but the §3 coalesce becomes a no-op on the floor check).
        """
        md = self._build_md()

        cfg_no_floor = ChunkingConfig(strategy="by_title", min_chunk_tokens=0)
        chunks_no_floor = chunk_document(
            md, "doc-well-no-floor", "default", "pdf", config=cfg_no_floor
        )

        cfg_default = ChunkingConfig(strategy="by_title", min_chunk_tokens=50)
        chunks_default = chunk_document(
            md, "doc-well-default", "default", "pdf", config=cfg_default
        )

        assert len(chunks_default) == len(chunks_no_floor), (
            f"chunk count drift on well-behaved doc: "
            f"with-floor={len(chunks_default)} vs no-floor={len(chunks_no_floor)}"
        )
        # All chunks are above the floor on this doc by construction, so the
        # default-config result should also have no sub-floor chunks.
        for c in chunks_default:
            assert c.token_count >= 50, (
                f"unexpected sub-floor chunk on well-behaved doc: "
                f"index={c.chunk_index} tokens={c.token_count} text={c.text[:60]!r}"
            )

    def test_well_behaved_chunk_text_unchanged(self):
        """The chunk texts themselves should match between with-floor and
        no-floor runs on a well-behaved doc — no merges should fire."""
        md = self._build_md()
        cfg_no_floor = ChunkingConfig(strategy="by_title", min_chunk_tokens=0)
        chunks_no_floor = chunk_document(
            md, "doc-well", "default", "pdf", config=cfg_no_floor
        )
        cfg_default = ChunkingConfig(strategy="by_title", min_chunk_tokens=50)
        chunks_default = chunk_document(
            md, "doc-well", "default", "pdf", config=cfg_default
        )
        # Compare text content side-by-side.
        for i, (a, b) in enumerate(zip(chunks_no_floor, chunks_default)):
            assert a.text == b.text, (
                f"chunk[{i}] text drift on well-behaved doc:\n"
                f"  no-floor: {a.text[:120]!r}\n"
                f"  default : {b.text[:120]!r}"
            )


# ── Design §6 weak point 1 / ADA residual #2 — oversized accumulator ─────────


class TestWeakPoint1OversizedAccumulator:
    """Design §6 weak point 1: the loosened §2 condition can absorb 10 empty
    `## StepN` headings into a 1500-char `## Big` accumulator. The result is
    an oversized section that `_split_at_paragraphs` catches downstream.
    The test asserts: (a) all 10 step labels appear in the output (no data
    loss); (b) every output chunk respects max_characters; (c) no output
    chunk is below the 50-token floor.
    """

    def _build_md(self) -> str:
        # 1500-char body — RIGHT AT max_characters. Plus 10 empty `## StepN`
        # headings that the loosened §2 will merge in, pushing total well
        # past max_characters and triggering _split_at_paragraphs.
        big_body = "Body content for the big section. " * 45  # ~1530 chars
        # Construct the 10 empty headings.
        empty_steps = "\n\n".join(f"## Step {i}" for i in range(2, 12))
        return textwrap.dedent(
            f"""\
            ## Big

            {big_body}

            {empty_steps}
            """
        )

    def test_no_data_loss_after_oversized_accumulator_split(self):
        """All 10 `Step N` labels should appear somewhere in the output text,
        even if the chunker had to split the accumulator into multiple
        sub-chunks. The §3 coalesce + the loosened §2 + the existing
        _split_at_paragraphs path together must NOT silently drop content."""
        md = self._build_md()
        chunks = chunk_document(md, "doc-wp1", "default", "pdf")
        joined = "\n".join(c.text for c in chunks)
        for n in range(2, 12):
            assert f"Step {n}" in joined, (
                f"Step {n} was lost in chunking output. "
                f"Chunks: {[(c.chunk_index, c.text[:60]) for c in chunks]}"
            )
        assert "Big" in joined, "## Big heading lost"

    def test_no_chunk_exceeds_max_characters_after_split(self):
        """Even with a loosened §2 producing an oversized accumulator,
        downstream _split_at_paragraphs ensures no chunk substantially
        exceeds max_characters (1500). Allow a small tolerance for the
        re-prepended heading prefix."""
        md = self._build_md()
        chunks = chunk_document(md, "doc-wp1", "default", "pdf")
        for c in chunks:
            # Tolerance: max_characters is 1500; allow up to 1700 to account
            # for paragraph-split granularity + heading prefix re-injection.
            assert len(c.text) <= 1700, (
                f"chunk[{c.chunk_index}] is {len(c.text)} chars, exceeds "
                f"max_characters=1500 + tolerance=200"
            )

    def test_no_subfloor_chunk_after_split_and_coalesce(self):
        """The split-then-coalesce path must still respect the 50-token
        floor on its output."""
        md = self._build_md()
        chunks = chunk_document(md, "doc-wp1", "default", "pdf")
        if len(chunks) > 1:
            below = [c for c in chunks if c.token_count < 50]
            assert below == [], (
                f"sub-floor chunks emitted from oversized-accumulator path: "
                f"{[(c.chunk_index, c.token_count, c.text[:60]) for c in below]}"
            )


# ── Probe — chunker_index sequencing across coalesce + split paths ───────────


class TestChunkIndexSequencing:
    """When _coalesce_undersized renumbers, AND _split_at_paragraphs has run
    upstream (so the input list to _coalesce_undersized has gaps that get
    re-sequenced anyway in chunk_document's main loop), chunk_index must
    end up sequential 0..N-1 on the final output. This is asserted by ADA's
    test_renumbers_chunk_index_and_id_after_merge but only on a synthetic
    Chunk list — let's verify on the integration path."""

    def test_chunk_index_is_sequential_after_chunk_document(self):
        body = "Substantial body content for this section. " * 12
        md = textwrap.dedent(
            f"""\
            ## A

            {body}

            ## B

            ## C

            x.

            ## D

            {body}
            """
        )
        chunks = chunk_document(md, "doc-seq", "default", "pdf")
        for i, c in enumerate(chunks):
            assert c.chunk_index == i, (
                f"chunk_index not sequential at position {i}: got {c.chunk_index}"
            )
            assert c.chunk_id == f"doc-seq-chunk-{i:04d}", (
                f"chunk_id not regenerated at position {i}: got {c.chunk_id!r}"
            )
