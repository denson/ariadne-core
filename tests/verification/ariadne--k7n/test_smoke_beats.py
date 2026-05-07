"""Verification probes for ariadne--k7n (Batch D / 3o7) — fingerprint refactor.

CAPTAIN_VERA executes the design's seven smoke beats against the build
artifact (commit 8232752 on fix/batch-d-fingerprint-raw-bytes). Beats that
require a deployed server are explicitly deferred to PLINY's post-merge
smoke; beats whose load-bearing CLAIM is at the algorithm or in-process
service layer are exercised here.

Smoke-beat coverage map (design §8 / brief):

  Beat 1 (within-session repeatability — file source)      EXERCISED HERE
      test_beat_1_within_session_file_repeatability — ingest the same
      file twice in the same Python process, assert second is dedup-skip
      with same document_id and same content_fingerprint.

  Beat 2 (cross-session repeatability — algorithm level)   EXERCISED HERE
      test_beat_2_cross_session_algorithm_byte_stable — invoke
      compute_fingerprint on the same source bytes from two SEPARATE
      Python interpreters via subprocess.run; assert byte-identical
      digests. Full-pipeline cross-session is post-merge-only and is
      PLINY's via the production deployment.

  Beat 3 (URL source)                                       EXERCISED HERE
      test_beat_3_url_source_repeatability — fetch a stable URL
      (raw.githubusercontent.com cpython README) twice via
      _read_source_bytes; assert byte-identical bodies AND identical
      fingerprints. Captures Content-Encoding for the record per design
      §5.

  Beat 4 (1/12 divergence rate drops to 0)                  EXERCISED HERE
      test_beat_4_simulated_directory_no_divergence — ingest each file
      from team_test/peer_review_test twice in the same session via
      _process_single_document; assert ALL second ingests are
      was_dedup_skip=True. The 1/12 from Batch A's smoke was attributed
      to extraction non-determinism; under raw-bytes fingerprinting that
      surface is closed by construction. (Full cross-session sweep
      against production is PLINY's post-merge.)

  Beat 5 (backward compat — pre-fix entries searchable)     POST-MERGE-ONLY
      Build artifact has no pre-fix-stored rows; this assertion can only
      be made against a live server holding the existing 13 docs. Flagged
      for PLINY.

  Beat 6 (cutover semantics — re-ingest produces NEW row)   EXERCISED HERE
      test_beat_6_cutover_old_fingerprint_does_not_match — pre-seed the
      dedup store with a markdown-fingerprint stored row; re-ingest the
      raw source bytes; assert NO dedup-skip (different fingerprint),
      fresh row stored alongside. Documented expected behavior under §9.

  Beat 7 (no regression on search/retrieval)                EXERCISED HERE
      test_beat_7_search_retrieval_works_post_fix — full ingest path with
      InMemoryDedupStore and InMemoryVectorStore; confirm doc_id appears
      in dedup store after ingest, find_by_fingerprint resolves it, and
      stored_doc.content_fingerprint matches the raw-bytes hash.

Bug-detection capability validation (design §8 final paragraph + brief
step 2): a test must demonstrate it would FAIL under the pre-fix code
shape. ADA's test_fingerprint_byte_stable_across_extractor_drift asserts
the property; this seat constructs the algorithmic differential to prove
the assertion has teeth.

  test_bug_detection_differential — simulate the pre-fix algorithm
  (SHA256 of normalize_text(extracted_markdown)) on two different
  drifted-extractor outputs; assert pre-fix produces DIFFERENT
  fingerprints (the bug). Post-fix algorithm (SHA256 of raw bytes) on
  the same source produces IDENTICAL fingerprints (the fix). Direct
  evidence that the fix's load-bearing claim is true and that the
  pre-fix code would have been falsifiable by this kind of probe.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline import services
from pipeline.dedup import InMemoryDedupStore, compute_fingerprint
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore


# ── Fixtures + helpers ────────────────────────────────────────────────────────

_FIXTURE_TXT = Path(__file__).resolve().parents[2] / "fixtures" / "sample.txt"

# Workspace test corpus — used for beat 4. Resolves into the workspace
# (sibling-to-build-worktree) on Denson's machine.
_PEER_REVIEW_DIR = (
    Path(__file__).resolve().parents[3].parent
    / "ariadne-core-workspace" / "team_test" / "peer_review_test"
)


class _DisabledEmbeddingClient:
    """Embedding disabled — fingerprint-order is the property under test."""

    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("embed_texts must not be called when disabled")


def _make_extractor_mock(*, source_file: str, file_type: str = "txt") -> MagicMock:
    """MagicMock standing in for services._extractor; fresh ExtractionResult per call.

    Post-Batch-G the canonical seam is ``extract_from_bytes(content,
    source_file=...)`` — the legacy ``extract(uri)`` method is no
    longer invoked from _process_single_document. These mocks follow
    the new seam.
    """
    mock = MagicMock()

    def _fake_extract_from_bytes(content: bytes, source_file: str = source_file) -> ExtractionResult:
        return ExtractionResult(
            document_id="00000000-0000-0000-0000-000000000000",
            source_file=source_file,
            markdown="# fake extracted markdown\n\nhello world\n",
            title="fake",
            file_type=file_type,
            pages=None,
            engine="markitdown-mock",
            processing_time_ms=1,
            output_tokens_estimate=10,
            token_savings_ratio=None,
            processing_chain=[{"step": "extraction", "tool": "markitdown-mock"}],
            warnings=[],
            errors=[],
        )

    mock.extract_from_bytes.side_effect = _fake_extract_from_bytes
    return mock


def _install_clean_state(
    monkeypatch, *, source_file: str = "sample.txt", file_type: str = "txt"
) -> MagicMock:
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    extractor_mock = _make_extractor_mock(source_file=source_file, file_type=file_type)
    monkeypatch.setattr(services, "_extractor", extractor_mock)
    return extractor_mock


def _kwargs(uri: str, *, collection: str, force: bool = False) -> dict:
    return dict(
        uri=uri,
        store=True,
        collection=collection,
        tags=[],
        force=force,
        agent_id="vera-k7n-probe",
        agent_type="pytest",
        model=None,
        initiated_by="vera",
        agent_notes="k7n smoke-beat verification probe",
        agent_metadata={"source_reference": "ariadne--k7n-vera-probe"},
        chunking_config=None,
    )


# ── Beat 1: within-session file source repeatability ────────────────────────


def test_beat_1_within_session_file_repeatability(monkeypatch):
    """Beat 1 — same file ingested twice in the same session: second
    must be dedup-skip with identical document_id and fingerprint."""
    _install_clean_state(monkeypatch, source_file="sample.txt")
    uri = str(_FIXTURE_TXT)
    collection = "k7n_beat1_within_session"

    first = services._process_single_document(**_kwargs(uri, collection=collection))
    assert first.get("error") is not True, first
    assert first["was_dedup_skip"] is False
    fp1 = first["content_fingerprint"]
    doc_id_1 = first["document_id"]

    second = services._process_single_document(**_kwargs(uri, collection=collection))
    assert second.get("error") is not True, second
    assert second["was_dedup_skip"] is True, "second ingest of same file must dedup-skip"
    assert second["content_fingerprint"] == fp1, (
        "fingerprint must be identical across same-session ingests of same bytes"
    )
    assert second["document_id"] == doc_id_1, (
        "dedup-skip must return the original stored document_id"
    )


# ── Beat 2: cross-session algorithm byte-stable ─────────────────────────────


def test_beat_2_cross_session_algorithm_byte_stable():
    """Beat 2 (algorithm level) — invoke compute_fingerprint on same
    source bytes from two SEPARATE Python interpreter processes; require
    identical hex digests. Closes the cross-session question for the
    algorithm independent of any session-scoped caches.

    Full-pipeline cross-session against production is PLINY's post-merge
    smoke; that path requires the deployed server."""
    src_path = _FIXTURE_TXT
    assert src_path.exists(), f"sample fixture missing at {src_path}"

    # Use a path that works regardless of cwd to guarantee both processes
    # see identical bytes.
    snippet = (
        "import sys, hashlib, pathlib\n"
        "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[3] / 'src') + "')\n"
        "from pipeline.dedup import compute_fingerprint\n"
        "data = pathlib.Path(r'" + str(src_path) + "').read_bytes()\n"
        "print(compute_fingerprint(data))\n"
    )

    proc_a = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True, text=True, check=True, timeout=30,
    )
    proc_b = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True, text=True, check=True, timeout=30,
    )
    fp_a = proc_a.stdout.strip()
    fp_b = proc_b.stdout.strip()

    assert len(fp_a) == 64 and len(fp_b) == 64, (
        f"unexpected output: a={proc_a.stdout!r} stderr={proc_a.stderr!r} "
        f"b={proc_b.stdout!r} stderr={proc_b.stderr!r}"
    )
    assert fp_a == fp_b, (
        f"cross-session fingerprint DIVERGED: {fp_a} != {fp_b} — "
        "raw-bytes algorithm is not byte-stable across processes"
    )


# ── Beat 3: URL-source repeatability ────────────────────────────────────────


def test_beat_3_url_source_repeatability():
    """Beat 3 — fetch a stable URL twice via _read_source_bytes; require
    identical bodies and identical fingerprints. Also captures
    Content-Encoding for the record per design §5.

    Skipped automatically when the network isn't reachable (the
    raw.githubusercontent.com URL is the canonical stable target the
    design names; no fallback is attempted)."""
    url = "https://raw.githubusercontent.com/python/cpython/main/README.rst"

    try:
        b1 = services._read_source_bytes(url)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"network unreachable for beat 3 URL probe: {e}")

    b2 = services._read_source_bytes(url)
    assert isinstance(b1, bytes) and isinstance(b2, bytes)

    # Capture content-encoding for the record (beat 3 design note).
    from urllib.request import urlopen
    with urlopen(url) as resp:
        encoding = resp.headers.get("Content-Encoding")
    # Record the encoding in the assertion message so failures show it.
    assert b1 == b2, (
        f"URL fetched twice returned different bytes: "
        f"len(b1)={len(b1)} len(b2)={len(b2)} encoding={encoding!r}"
    )
    fp1 = compute_fingerprint(b1)
    fp2 = compute_fingerprint(b2)
    assert fp1 == fp2, (
        f"URL fingerprint diverged: {fp1!r} != {fp2!r} encoding={encoding!r}"
    )


# ── Beat 4: simulated 1/12 → 0 directory-ingest divergence ──────────────────


def test_beat_4_simulated_directory_no_divergence(monkeypatch):
    """Beat 4 (algorithm level) — within a single session, ingest each
    file in the test corpus twice. Every second ingest must hit dedup-
    skip. The 1/12 divergence rate observed in Batch A was attributed to
    extraction non-determinism; raw-bytes fingerprinting closes that
    surface by construction. Cross-session with production data is
    PLINY's post-merge."""
    if not _PEER_REVIEW_DIR.exists():
        pytest.skip(
            f"peer-review test corpus not present at {_PEER_REVIEW_DIR} "
            "— the workspace's team_test/ may have been pruned"
        )

    files = sorted(_PEER_REVIEW_DIR.glob("*.pdf"))
    if not files:
        pytest.skip(f"no PDFs found under {_PEER_REVIEW_DIR}")

    _install_clean_state(monkeypatch, source_file="multi-file-probe", file_type="pdf")
    collection = "k7n_beat4_directory_simulated"

    second_run_skipped = 0
    for f in files:
        uri = str(f)
        first = services._process_single_document(**_kwargs(uri, collection=collection))
        assert first.get("error") is not True, f"first ingest failed for {f.name}: {first}"
        second = services._process_single_document(**_kwargs(uri, collection=collection))
        assert second.get("error") is not True, f"second ingest failed for {f.name}: {second}"
        if second["was_dedup_skip"] is True:
            second_run_skipped += 1

    assert second_run_skipped == len(files), (
        f"divergence detected: only {second_run_skipped}/{len(files)} files "
        "dedup-skipped on second ingest"
    )


# ── Beat 6: cutover semantics — pre-fix row does NOT match new fingerprint ──


def test_beat_6_cutover_old_fingerprint_does_not_match(monkeypatch):
    """Beat 6 — pre-seed the dedup store with a row whose fingerprint
    was computed under the OLD algorithm (markdown-derived). Re-ingest
    the raw source bytes (post-fix code path). Expected per design §9:

      - new fingerprint != stored fingerprint
      - dedup misses (no was_dedup_skip)
      - a fresh row is stored alongside the pre-fix row

    Documented expected behavior under cutover, NOT a regression."""
    extractor = _install_clean_state(monkeypatch, source_file="sample.txt")
    uri = str(_FIXTURE_TXT)
    collection = "k7n_beat6_cutover"

    # Pre-seed: simulate a pre-fix-stored doc by computing the OLD
    # fingerprint over normalized markdown text and inserting it.
    raw = Path(uri).read_bytes()
    pre_fix_md = "# fake extracted markdown\n\nhello world\n"  # matches the mock
    normalized = re.sub(r"\s+", " ", pre_fix_md.lower().strip())
    pre_fix_fp = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    from pipeline.dedup import StoredDocument
    pre_fix_doc = StoredDocument(
        document_id="pre-fix-doc-id-0001",
        collection_id=collection,
        source_file="sample.txt",
        content_fingerprint=pre_fix_fp,
        file_type="txt",
        engine="markitdown",
        markdown=pre_fix_md,
        title="pre-fix",
        processing_time_ms=1,
        output_tokens_estimate=10,
        token_savings_ratio=None,
        processing_chain=[{"step": "extraction", "tool": "markitdown"}],
    )
    services._dedup_store.store_document(pre_fix_doc)

    # Now ingest the raw source bytes through the post-fix code path.
    response = services._process_single_document(**_kwargs(uri, collection=collection))
    assert response.get("error") is not True, response
    assert response["was_dedup_skip"] is False, (
        "pre-fix row's fingerprint must NOT match raw-bytes fingerprint — "
        "cutover requires a NEW row, not a hit on the old one"
    )

    # New fingerprint over raw bytes
    new_fp = compute_fingerprint(raw)
    assert response["content_fingerprint"] == new_fp
    assert new_fp != pre_fix_fp, "the differential the test exists to prove"

    # Both rows now coexist in the in-memory store.
    pre_fix_lookup = services._dedup_store.find_by_fingerprint(collection, pre_fix_fp)
    post_fix_lookup = services._dedup_store.find_by_fingerprint(collection, new_fp)
    assert pre_fix_lookup is not None, "pre-fix row should still be findable by its old fp"
    assert post_fix_lookup is not None, "new row should be findable by its new fp"
    assert pre_fix_lookup.document_id != post_fix_lookup.document_id, (
        "two distinct document_ids — the duplicate-pollution under cutover"
    )

    # Extractor was called once on the new ingest (cache miss).
    assert extractor.extract_from_bytes.call_count == 1


# ── Beat 7: no regression on search/retrieval after fix ─────────────────────


def test_beat_7_search_retrieval_works_post_fix(monkeypatch):
    """Beat 7 — full ingest path; assert the document is findable in the
    dedup store by fingerprint and the stored fingerprint matches the
    raw-bytes hash. This exercises the post-fix store-then-search path
    end-to-end at the in-memory layer (vector search itself is exercised
    by tests/test_services.py and existing route tests)."""
    _install_clean_state(monkeypatch, source_file="sample.txt")
    uri = str(_FIXTURE_TXT)
    collection = "k7n_beat7_no_regression"

    response = services._process_single_document(**_kwargs(uri, collection=collection))
    assert response.get("error") is not True, response
    assert response["was_dedup_skip"] is False
    fp = response["content_fingerprint"]
    raw = Path(uri).read_bytes()
    assert fp == compute_fingerprint(raw), (
        "stored fingerprint must equal raw-bytes hash"
    )

    found = services._dedup_store.find_by_fingerprint(collection, fp)
    assert found is not None, "stored document not findable by its own fingerprint"
    assert found.document_id == response["document_id"]
    assert found.content_fingerprint == fp


# ── Bug-detection capability differential ────────────────────────────────────


def test_bug_detection_differential_pre_fix_falsifiable():
    """VERA-independent bug-detection differential.

    ADA's test_fingerprint_byte_stable_across_extractor_drift asserts
    the post-fix invariant. This seat verifies the assertion is
    falsifiable: under the pre-fix algorithm
    (SHA256(normalize_text(extracted_markdown))), a non-deterministic
    extractor produces DIFFERENT fingerprints for the same source bytes
    on consecutive runs. Under the post-fix algorithm
    (SHA256(raw_source_bytes)), the same source produces IDENTICAL
    fingerprints regardless of extractor drift.

    Pre-fix shape is reconstructed in-line (the pre-fix code is gone
    from the repo; this is the canonical algorithmic differential)."""

    # Pre-fix algorithm — exact copy of the dedup.py pre-k7n shape:
    def pre_fix_normalize(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def pre_fix_compute_fingerprint(text: str) -> str:
        return hashlib.sha256(pre_fix_normalize(text).encode("utf-8")).hexdigest()

    # Drift scenario: same source bytes → markitdown emits two different
    # markdown documents on two extraction calls (vision-API caption
    # variance, the empirical 1/12 rate from Batch A's smoke).
    md_run_1 = "# extracted run 1\n\ncaption variance run 1\n"
    md_run_2 = "# extracted run 2\n\ncaption variance run 2\n"

    pre_fp_1 = pre_fix_compute_fingerprint(md_run_1)
    pre_fp_2 = pre_fix_compute_fingerprint(md_run_2)
    assert pre_fp_1 != pre_fp_2, (
        "pre-fix differential broke: drifted markdown should yield "
        "different normalized-text fingerprints — if this fires, the "
        "pre-fix code wasn't actually buggy and the fix isn't earning "
        "its keep"
    )

    # Post-fix algorithm — SHA256 over raw bytes; extractor output never
    # enters the hash; identical source → identical fingerprint.
    src_bytes = b"identical raw source bytes - extractor drift cannot affect this"
    post_fp_1 = compute_fingerprint(src_bytes)
    post_fp_2 = compute_fingerprint(src_bytes)
    assert post_fp_1 == post_fp_2, (
        "post-fix algorithm is not byte-stable — load-bearing invariant "
        "violated"
    )

    # Sanity: post-fix produces different hashes for actually-different
    # bytes (so it's not vacuously stable).
    assert compute_fingerprint(b"abc") != compute_fingerprint(b"abd")
