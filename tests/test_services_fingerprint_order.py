"""Regression gates for ariadne--k7n: fingerprint computed BEFORE extraction.

Two adjacent gates close on opposite sides of the same load-bearing
property:

  test_extractor_not_called_on_hit
      Same source bytes ingested twice into the same collection (no
      force) — the second call must short-circuit via the dedup-skip
      path WITHOUT invoking the extractor. Pre-fix this was structurally
      impossible (extraction ran first; fingerprint came after); the new
      shape makes it possible AND mandatory. Regression gate against
      "fingerprint silently moved back to post-extraction."

  test_extractor_IS_called_when_force_True_even_with_matching_fingerprint
      Same source bytes ingested twice; the second call passes
      ``force=True``. The extractor MUST be invoked on both calls; the
      dedup short-circuit must NOT swallow the force flag. Regression
      gate against "force=True silently broken by the dedup
      short-circuit." Direct inverse of the test above.

Both tests mock the extractor — they are about CONTROL FLOW (when does
extraction run?), not extraction correctness.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pipeline import services
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore


_FIXTURE_TXT = (
    Path(__file__).parent / "fixtures" / "sample.txt"
)


class _DisabledEmbeddingClient:
    """Embedding disabled — keeps the test focused on extractor call-count.

    Mirrors the shape used by tests/test_services.py and
    tests/verification/ariadne--vsx/test_warnings_persistence.py."""

    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts: list[str]):  # pragma: no cover
        raise AssertionError("embed_texts should not be called when disabled")


def _make_extractor_mock(*, source_file: str) -> MagicMock:
    """Return a MagicMock standing in for ``services._extractor``.

    Each call to ``.extract(uri)`` returns a fresh ExtractionResult whose
    markdown is non-empty (so the empty-output branch of
    _process_single_document is not taken)."""
    mock = MagicMock()

    def _fake_extract(uri: str) -> ExtractionResult:
        return ExtractionResult(
            document_id="00000000-0000-0000-0000-000000000000",
            source_file=source_file,
            markdown="# fake extracted markdown\n\nhello world\n",
            title="fake",
            file_type="txt",
            pages=None,
            engine="markitdown-mock",
            processing_time_ms=1,
            output_tokens_estimate=10,
            token_savings_ratio=None,
            processing_chain=[
                {"step": "extraction", "tool": "markitdown-mock"}
            ],
            warnings=[],
            errors=[],
        )

    mock.extract.side_effect = _fake_extract
    return mock


def _kwargs(uri: str, *, collection: str, force: bool = False) -> dict:
    """Build the kwargs dict for _process_single_document.

    Provides agent_metadata.source_reference so the no-source-metadata
    hygiene warning does not fire — that warning is unrelated to the
    fingerprint-order property under test."""
    return dict(
        uri=uri,
        store=True,
        collection=collection,
        tags=[],
        force=force,
        agent_id="ada-k7n-probe",
        agent_type="pytest",
        model=None,
        initiated_by="ada",
        agent_notes="fingerprint-order regression probe",
        agent_metadata={"source_reference": "ariadne--k7n-probe"},
        chunking_config=None,
    )


def _install_clean_state(monkeypatch, *, source_file: str) -> MagicMock:
    """Install fresh in-memory stores, disable embedding, swap the
    extractor for a MagicMock. Returns the mock so the test can assert
    against ``mock.extract.call_count``."""
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    extractor_mock = _make_extractor_mock(source_file=source_file)
    monkeypatch.setattr(services, "_extractor", extractor_mock)
    return extractor_mock


def test_extractor_not_called_on_hit(monkeypatch):
    """Second ingest of identical bytes (no force) must dedup-skip
    BEFORE invoking the extractor — regression gate against
    'fingerprint moved back after extraction.'"""
    extractor = _install_clean_state(monkeypatch, source_file="sample.txt")
    uri = str(_FIXTURE_TXT)
    collection = "k7n_hit_probe"

    first = services._process_single_document(**_kwargs(uri, collection=collection))
    assert first.get("error") is not True, first
    assert first["was_dedup_skip"] is False
    assert extractor.extract.call_count == 1, (
        f"first ingest should have called the extractor exactly once, "
        f"got {extractor.extract.call_count}"
    )

    second = services._process_single_document(**_kwargs(uri, collection=collection))
    assert second.get("error") is not True, second
    assert second["was_dedup_skip"] is True, (
        "second ingest of identical bytes must dedup-skip"
    )
    assert extractor.extract.call_count == 1, (
        f"extractor.extract.call_count must remain 1 after dedup-skip; "
        f"got {extractor.extract.call_count} — fingerprint may have moved "
        "back to post-extraction (ariadne--k7n regression)"
    )


def test_extractor_IS_called_when_force_True_even_with_matching_fingerprint(
    monkeypatch,
):
    """Second ingest of identical bytes WITH force=True must NOT
    short-circuit — extractor must be invoked on both calls. Closes the
    silent-force-broken gate."""
    extractor = _install_clean_state(monkeypatch, source_file="sample.txt")
    uri = str(_FIXTURE_TXT)
    collection = "k7n_force_probe"

    first = services._process_single_document(**_kwargs(uri, collection=collection))
    assert first.get("error") is not True, first
    assert extractor.extract.call_count == 1

    second = services._process_single_document(
        **_kwargs(uri, collection=collection, force=True)
    )
    assert second.get("error") is not True, second
    # force=True suppresses the dedup-skip lookup; extraction MUST run.
    assert second["was_dedup_skip"] is False, (
        "force=True must bypass the dedup short-circuit"
    )
    assert extractor.extract.call_count == 2, (
        f"force=True must invoke extraction even when fingerprint matches; "
        f"got call_count={extractor.extract.call_count} — the dedup short-"
        "circuit may have swallowed the force flag (ariadne--k7n regression)"
    )


def test_fingerprint_byte_stable_across_extractor_drift(monkeypatch):
    """Bug-detection capability validation (per design §8 / brief step 8).

    Pre-fix: fingerprint = SHA256(normalize(extracted_markdown)). A
    flaky extractor that returns DIFFERENT markdown on two consecutive
    calls for the same source bytes would produce two different
    fingerprints, recreating the silent-dedup-bypass bug under
    ariadne--3o7.

    Post-fix: fingerprint = SHA256(raw_source_bytes). The extractor's
    output never enters the hash. Even if extraction is wildly
    non-deterministic, the same source bytes always produce the same
    fingerprint and the second ingest hits the dedup-skip path.
    """
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())

    # Drift mock: each call returns markdown with a different caption,
    # simulating vision-API non-determinism.
    drift_state = {"calls": 0}

    def _drifty_extract(uri: str) -> ExtractionResult:
        drift_state["calls"] += 1
        return ExtractionResult(
            document_id="00000000-0000-0000-0000-000000000000",
            source_file="sample.txt",
            markdown=f"# extracted run {drift_state['calls']}\n\ncaption variance run {drift_state['calls']}\n",
            title="drifty",
            file_type="txt",
            pages=None,
            engine="markitdown-drifty",
            processing_time_ms=1,
            output_tokens_estimate=10,
            token_savings_ratio=None,
            processing_chain=[
                {"step": "extraction", "tool": "markitdown-drifty"}
            ],
            warnings=[],
            errors=[],
        )

    extractor = MagicMock()
    extractor.extract.side_effect = _drifty_extract
    monkeypatch.setattr(services, "_extractor", extractor)

    uri = str(_FIXTURE_TXT)
    collection = "k7n_drift_probe"

    first = services._process_single_document(**_kwargs(uri, collection=collection))
    assert first.get("error") is not True, first
    fp_first = first["content_fingerprint"]

    # Pre-fix this would call extraction first and hash the (drifted)
    # markdown — different fingerprint, dedup miss, second store. Post-
    # fix the fingerprint is over raw bytes; extractor is never called
    # the second time because the dedup-skip fires first.
    second = services._process_single_document(**_kwargs(uri, collection=collection))
    assert second.get("error") is not True, second
    assert second["was_dedup_skip"] is True, (
        "Even with non-deterministic extraction, identical source bytes "
        "must dedup-skip — the fix's load-bearing property"
    )
    assert second["content_fingerprint"] == fp_first, (
        "Fingerprint must be byte-stable across extractor drift "
        "(ariadne--k7n core invariant)"
    )
    assert extractor.extract.call_count == 1, (
        "Extractor must run exactly once across two ingests of identical "
        "bytes; ran "
        f"{extractor.extract.call_count} times — fingerprint may have "
        "moved back to post-extraction"
    )
