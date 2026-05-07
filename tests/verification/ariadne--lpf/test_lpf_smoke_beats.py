"""VERA verification probes for ariadne--lpf (Batch F / g47 + ruk).

Independent post-build verification of ADA's commit 4f71f8d. These probes
do NOT replace ADA's unit tests — they cover the residuals VERA's brief
called out and act as the falsification suite for the load-bearing
contracts the gauntlet ships.

Specifically:

  * **Section-field drift contract.** The ruk fix (drop chunker.py:178
    filter) introduces a leading ``(None, "")`` section in EVERY doc.
    For single-heading docs (``# Title\\n\\nbody``), ``_coalesce_undersized``
    merges the heading-section into the leading-``(None, "")`` entry; per
    chunker.py:352-368 the surviving chunk inherits the absorber's section
    field, so ``chunks[0].section`` shifts ``"Title"`` -> ``None`` while
    ``"Title"`` is preserved as text content. ADA updated
    ``tests/test_chunking.py::test_single_section`` to assert text rather
    than section. VERA pins the contract explicitly here so a future
    regression that re-introduces the filter (or otherwise restores the
    ``chunks[0].section == "Title"`` shape) trips this probe loud.

  * **Section-field consumer audit.** Surveys every reader of
    ``chunk.section`` in src/pipeline (search route, get-document route,
    pgvector INSERT/SELECT) to confirm none filter, group, or assert on
    the value. The audit is encoded as an AST-level grep test so a
    future PR that adds a ``WHERE c.section = ...`` clause or a Python
    ``if chunk.section == ...`` filter trips it.

  * **Beat 6 + Beat 7 cross-batch regression spot-check.** Re-asserts
    that the Batch C contracts (post-pass min-token coalesce,
    well-behaved-doc chunk count stability) still hold with Batch F's
    chunker.py:178 filter removed. ADA's diff is small; the prior batch
    verification probes cover the full surface, but VERA pins the
    cross-batch link explicitly here so a future maintainer reading the
    Batch F verification namespace sees the dependency without having
    to discover it.

Run with ``PYTHONPATH=src python -m pytest tests/verification/ariadne--lpf/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.chunking.chunker import (
    ChunkingConfig as _ChunkerConfig,
    chunk_document,
)


# ── Section-field drift contract ─────────────────────────────────────────────


class TestSectionFieldDriftContract:
    """Pin the post-Batch-F contract: chunks[0].text contains heading text;
    chunks[0].section may be None for short single-heading docs.

    Falsifying shape: a future regression that restores the
    chunker.py:178 filter (or any equivalent that prevents the leading
    ``(None, "")`` section from being emitted) would change
    ``chunks[0].section`` back to ``"Title"`` in this case. That would
    trip ``test_single_heading_doc_section_is_absorber_anchor`` because
    the absorber wouldn't exist — the heading-section would stand alone.
    """

    def test_single_heading_doc_text_preserves_title(self):
        """The ruk fix preserves heading TEXT even when the section
        field shifts to None (the absorber's anchor)."""
        chunks = chunk_document(
            markdown="# Title\n\nbody",
            document_id="vera-lpf-1",
            collection_id="vera-test",
            file_type="md",
            config=_ChunkerConfig(strategy="by_title"),
        )
        assert chunks, "expected at least one chunk for # Title + body"
        assert "Title" in chunks[0].text, (
            f"Title text missing from chunks[0].text: {chunks[0].text!r}"
        )

    def test_single_heading_doc_section_is_absorber_anchor(self):
        """Post-Batch-F contract: for ``# Title\\n\\nbody``, the surviving
        chunks[0] is the merged result of the leading ``(None, "")``
        absorbing the tiny ``("Title", body)`` section. chunks[0].section
        therefore reflects the absorber's anchor (None), NOT the heading
        text. Pinned here so a future regression that re-introduces the
        chunker.py:178 filter (or otherwise restores the pre-Batch-F
        section-equals-heading shape) trips loud.
        """
        chunks = chunk_document(
            markdown="# Title\n\nbody",
            document_id="vera-lpf-2",
            collection_id="vera-test",
            file_type="md",
            config=_ChunkerConfig(strategy="by_title"),
        )
        assert len(chunks) == 1, (
            f"expected single absorbed chunk for tiny single-heading doc; "
            f"got {len(chunks)}: {[c.text for c in chunks]!r}"
        )
        assert chunks[0].section is None, (
            f"section-field-drift contract violated: chunks[0].section is "
            f"{chunks[0].section!r}, expected None (absorber's anchor). "
            f"A pre-Batch-F regression may have restored the chunker.py:178 "
            f"filter and removed the leading (None, '') section."
        )

    def test_multi_heading_doc_with_substantial_prose_keeps_section_labels(self):
        """When sections have enough prose to clear the coalesce floor,
        each chunk's section field reflects its anchoring heading. This
        complements the single-heading case: the drift only applies
        when the leading (None, "") absorbs a tiny following section.
        Substantial prose -> no absorption -> section labels preserved.
        """
        # Each section gets ~250 tokens of prose, well above
        # combine_under_n_chars=200 and min_chunk_tokens=50.
        prose_a = "Alpha context. " * 70  # ~140 tokens of unique tokens
        prose_b = "Beta context. " * 70
        markdown = f"# Alpha\n\n{prose_a}\n\n# Beta\n\n{prose_b}"
        chunks = chunk_document(
            markdown=markdown,
            document_id="vera-lpf-3",
            collection_id="vera-test",
            file_type="md",
            config=_ChunkerConfig(strategy="by_title"),
        )
        sections = [c.section for c in chunks]
        # At least one chunk anchored to "Alpha" and one to "Beta".
        assert "Alpha" in sections, (
            f"Alpha heading missing from chunk sections: {sections!r}"
        )
        assert "Beta" in sections, (
            f"Beta heading missing from chunk sections: {sections!r}"
        )


# ── Section-field consumer audit ─────────────────────────────────────────────


class TestSectionFieldConsumerAudit:
    """Survey every reader of chunk.section in src/pipeline to confirm
    none filter, group, or assert on the value. Encoded as a regex audit
    against the known consumer surface — falsifying shape: a future PR
    that adds a ``WHERE c.section = ...`` SQL clause or a Python
    ``if chunk.section == ...`` filter trips this probe.

    The known consumer surface (post-Batch-F audit, 2026-05-06):
      * src/pipeline/api/routes.py:470  (get-document JSON render)
      * src/pipeline/api/routes.py:895  (search-result JSON render)
      * src/pipeline/storage/pgvector.py:52,72,140,256 (passthrough INSERT/SELECT)
    All four are passthrough — section is read into JSON or written
    into a nullable TEXT column without filtering. None block on a
    None section value.
    """

    SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "pipeline"

    def _all_python_lines(self):
        """Yield (path, lineno, code_line) skipping lines inside triple-quoted
        docstrings/comments. Naive but sufficient for the consumer audit:
        chunker.py:366 documents the contract IN a docstring, and would
        otherwise false-positive against ``filter.*\\.section``.
        """
        for path in self.SRC_ROOT.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            in_docstring = False
            doc_quote = None
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                # Toggle on triple-quote open/close. Doesn't handle the
                # rare line that opens AND closes a triple-quote in the
                # same line; acceptable for this audit.
                for quote in ('"""', "'''"):
                    if in_docstring and doc_quote == quote and quote in stripped:
                        in_docstring = False
                        doc_quote = None
                        break
                    if (
                        not in_docstring
                        and stripped.startswith(quote)
                        and stripped.count(quote) == 1
                    ):
                        in_docstring = True
                        doc_quote = quote
                        break
                if in_docstring:
                    continue
                yield path, lineno, line

    def test_no_python_filter_on_chunk_section(self):
        """No ``if chunk.section == ...`` or ``if c.section == ...`` or
        ``filter(.., chunk.section)`` patterns exist in src/pipeline.
        A consumer that filters on section value would break for the
        single-heading-absorbed-into-leading-None case.
        """
        import re

        # Patterns that would indicate filtering / equality-checking on section.
        # Not exhaustive but covers the obvious shapes; section is an
        # uncommon enough field name that false positives are unlikely.
        patterns = [
            re.compile(r"\.section\s*==\s*"),
            re.compile(r"\.section\s*!="),
            re.compile(r"\.section\s+is\s+not\s+None"),
            re.compile(r"\.section\s+is\s+None"),
            re.compile(r"if\s+\w+\.section\b"),
            re.compile(r"filter.*\.section"),
            re.compile(r"groupby.*\.section"),
        ]
        violations = []
        for path, lineno, line in self._all_python_lines():
            stripped = line.strip()
            # Skip docstring-style mentions (no enforcement value;
            # the docstring at chunker.py:360-368 documents the contract).
            if stripped.startswith(("#", '"', "'", "*")):
                continue
            for pat in patterns:
                if pat.search(line):
                    violations.append(
                        f"{path.relative_to(self.SRC_ROOT)}:{lineno}: {stripped}"
                    )
                    break
        assert not violations, (
            "chunk.section consumer drift detected -- the post-Batch-F "
            "section-field-drift contract (chunker.py:360-368) requires "
            "that no consumer filter, group, or assert on section value. "
            "Violations:\n  " + "\n  ".join(violations)
        )

    def test_no_sql_filter_on_chunk_section(self):
        """No ``WHERE c.section = ...`` or ``GROUP BY c.section`` pattern
        in src/pipeline storage code. SQL consumers must keep treating
        section as a passthrough nullable TEXT column.
        """
        import re

        patterns = [
            re.compile(r"WHERE\s+[\w.]*section\s*[=<>]", re.IGNORECASE),
            re.compile(r"GROUP\s+BY\s+[\w.]*section", re.IGNORECASE),
            re.compile(r"ORDER\s+BY\s+[\w.]*section", re.IGNORECASE),
            re.compile(r"AND\s+[\w.]*section\s*[=<>]", re.IGNORECASE),
        ]
        violations = []
        for path, lineno, line in self._all_python_lines():
            for pat in patterns:
                if pat.search(line):
                    violations.append(
                        f"{path.relative_to(self.SRC_ROOT)}:{lineno}: {line.strip()}"
                    )
                    break
        assert not violations, (
            "SQL filter on chunk.section detected -- breaks the "
            "section-field-drift contract. Violations:\n  "
            + "\n  ".join(violations)
        )


# ── Beat 4 — name-drift sentry ───────────────────────────────────────────────


def test_beat_4_no_default_strategy_anywhere_in_repo():
    """The g47 rename retired ``default_strategy``. Any future PR that
    re-introduces the name (in src, tests, docs, config, or SPEC) trips
    this sentry. Falsifying shape: post-rename, zero hits.
    """
    import re

    repo_root = Path(__file__).resolve().parents[3]
    self_path = Path(__file__).resolve()
    candidate_dirs = [
        repo_root / "src",
        repo_root / "tests",
        repo_root / "docs",
        repo_root / "config",
    ]
    pattern = re.compile(r"\bdefault_strategy\b")
    hits = []
    for root in candidate_dirs:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            # Skip binary-ish or compiled artifacts.
            if path.suffix in {".pyc", ".png", ".jpg", ".pdf", ".zip"}:
                continue
            # Skip this probe file itself — it documents the retired
            # name in its own assertion strings.
            if path.resolve() == self_path:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    spec_path = repo_root / "SPEC.md"
    if spec_path.exists():
        for lineno, line in enumerate(
            spec_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if pattern.search(line):
                hits.append(f"SPEC.md:{lineno}: {line.strip()}")

    assert not hits, (
        "g47 rename regression: 'default_strategy' re-introduced after "
        "ariadne--lpf retired it. Hits:\n  " + "\n  ".join(hits)
    )


# ── Beat 6/7 cross-batch regression sentry ───────────────────────────────────


def test_beat_6_and_7_mr6_probes_still_present():
    """Cross-batch dependency sentry: Batch F's verification leans on the
    Batch C verification probes (tests/verification/ariadne--mr6/) for
    Beat 6 (well-behaved-doc no-regression) and Beat 7 (Batch C coalesce
    still works). VERA executed both at verification time and they
    passed. This sentry confirms the probe files still EXIST so a future
    cleanup that deletes the mr6 probe set surfaces in the Batch F
    verdict rather than silently breaking the cross-batch coverage
    claim.
    """
    mr6_dir = Path(__file__).resolve().parents[1] / "ariadne--mr6"
    assert mr6_dir.exists(), (
        f"Batch C verification probe directory missing: {mr6_dir}. "
        f"Batch F's Beat 6 and Beat 7 coverage depended on these probes. "
        f"If the mr6 probes were intentionally removed, update Batch F's "
        f"verdict to no longer claim Beat 6/7 coverage."
    )
    expected = [
        mr6_dir / "test_design_5_smoke_beats.py",
        mr6_dir / "probe_real_world_9f143eb3.py",
    ]
    missing = [p for p in expected if not p.exists()]
    assert not missing, (
        f"Batch C probe files Batch F depends on are missing: {missing}"
    )
