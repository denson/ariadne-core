"""ADA residual-chase probes for ariadne--k7n.

Per CAPTAIN_VERA brief, these chase ADA's residuals 3, 5, and 7:

  Residual 3 (error-class change): "Source read failed:" prefix on
      nonexistent file; routes/CLI must propagate document_id=None and
      derive source_file from the URI without exploding.

  Residual 5 (soft-delete-resurrection under cutover): a soft-deleted
      pre-fix row with markdown-fingerprint plus a re-ingest of the same
      raw bytes (post-fix code) must NOT trigger the resurrection
      warning (different fingerprint by design); a fresh row is stored
      alongside.

  Residual 7 (logging fires): the dedup-skip and dedup-miss-store
      logger.info calls actually emit at runtime, with the documented
      structured-extras shape.

Residual 1 (cutover scale): not testable — design-time disposition.
Residual 2 (memory regime): not easily testable without a large-file
    fixture; flagged as post-merge or post-ship monitor.
Residual 4 (URL double-fetch on cache miss): observable in network
    traces but doesn't lend itself to a deterministic unit assertion;
    flagged in the verdict as not-observed-as-blocker.
Residual 6 (benchmarks contract change): spot-confirmed at the file
    level by reading run_benchmarks.py — covered in the verdict, not as
    a new probe (the benchmark module is exercised by
    tests/test_benchmarks.py which still passes 13/13).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline import services
from pipeline.dedup import InMemoryDedupStore, StoredDocument
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore


_FIXTURE_TXT = Path(__file__).resolve().parents[2] / "fixtures" / "sample.txt"


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


def _make_extractor_mock(*, source_file: str = "sample.txt") -> MagicMock:
    """Stub services._extractor.

    Post-Batch-G the canonical seam called by _process_single_document is
    ``extract_from_bytes(content, source_file=...)``. The legacy
    ``extract(uri)`` method still exists on the real extractor but is
    no longer invoked from the canonical flow; these mocks follow the
    new seam.
    """
    mock = MagicMock()

    def _fake_extract_from_bytes(content, source_file=source_file):
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
            processing_chain=[{"step": "extraction", "tool": "markitdown-mock"}],
            warnings=[],
            errors=[],
        )

    mock.extract_from_bytes.side_effect = _fake_extract_from_bytes
    return mock


def _install_clean(monkeypatch) -> MagicMock:
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    mock = _make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", mock)
    return mock


def _kwargs(uri: str, *, collection: str, force: bool = False, store: bool = True) -> dict:
    return dict(
        uri=uri,
        store=store,
        collection=collection,
        tags=[],
        force=force,
        agent_id="vera-residual-probe",
        agent_type="pytest",
        model=None,
        initiated_by="vera",
        agent_notes="k7n residual probe",
        agent_metadata={"source_reference": "ariadne--k7n-residual"},
        chunking_config=None,
    )


# ── Residual 3: error-class change shape ────────────────────────────────────


def test_residual_3_nonexistent_file_error_shape(monkeypatch):
    """Source-read failure must surface as the new error response:
      - error: True
      - message: starts with "Source read failed:"
      - document_id: None (caller-side None-tolerance gate; routes.py:286
        propagates this through HTTPException detail)
      - source_file: derived from the URI (not the absolute path)
    The extractor must not be invoked on this path."""
    extractor = _install_clean(monkeypatch)
    nonexistent = "/tmp/this/path/does/not/exist/k7n_probe_phantom_file.txt"
    response = services._process_single_document(
        **_kwargs(nonexistent, collection="k7n_residual3")
    )
    assert response["error"] is True
    assert response["message"].startswith("Source read failed:"), response["message"]
    assert response["document_id"] is None
    # source_file is the basename of the URI path
    assert response["source_file"] == "k7n_probe_phantom_file.txt", response
    # Extractor must NOT have been called on this path — the source read
    # fails before extraction is reached.
    assert extractor.extract_from_bytes.call_count == 0


def test_residual_3_nonexistent_file_url_error_shape(monkeypatch):
    """Same shape with a URL that fails to fetch (use a clearly-invalid
    host so we get a deterministic error rather than depending on the
    network)."""
    extractor = _install_clean(monkeypatch)
    bad_url = "http://localhost:1/this-port-is-not-listening/file.txt"
    response = services._process_single_document(
        **_kwargs(bad_url, collection="k7n_residual3_url")
    )
    assert response["error"] is True
    assert response["message"].startswith("Source read failed:"), response["message"]
    assert response["document_id"] is None
    assert response["source_file"] == "file.txt"
    assert extractor.extract_from_bytes.call_count == 0


# ── Residual 5: soft-delete-resurrection under cutover ──────────────────────


def test_residual_5_soft_delete_resurrection_under_cutover(monkeypatch):
    """A pre-fix row stored with a markdown-derived fingerprint, then
    soft-deleted, must NOT trigger the resurrection warning when the
    same source bytes are re-ingested under the post-fix algorithm.

    Per design §9: the new raw-bytes fingerprint will not equal the
    stored markdown-derived fingerprint, so the would_resurrect probe
    returns False (no soft-deleted row at the new key). A fresh row is
    stored alongside the soft-deleted pre-fix row.

    Documented expected behavior under cutover, not a regression."""
    import hashlib
    import re

    _install_clean(monkeypatch)
    uri = str(_FIXTURE_TXT)
    collection = "k7n_residual5_cutover"

    # 1) Pre-seed the pre-fix row with a markdown-derived fingerprint.
    pre_fix_md = "# fake extracted markdown\n\nhello world\n"
    pre_fix_fp = hashlib.sha256(
        re.sub(r"\s+", " ", pre_fix_md.lower().strip()).encode("utf-8")
    ).hexdigest()
    pre_fix_doc = StoredDocument(
        document_id="pre-fix-doc-residual5",
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

    # 2) Soft-delete the pre-fix row.
    services._dedup_store.soft_delete_document("pre-fix-doc-residual5")

    # 3) Re-ingest the same source bytes via the post-fix code path.
    response = services._process_single_document(**_kwargs(uri, collection=collection))
    assert response.get("error") is not True, response
    assert response["was_dedup_skip"] is False, (
        "soft-deleted pre-fix row must not match new raw-bytes fingerprint"
    )

    # 4) Confirm the resurrection warning did NOT fire on this path.
    resurrection_phrase = "previously soft-deleted and has been resurrected"
    fired = [w for w in response["warnings"] if resurrection_phrase in w]
    assert not fired, (
        "resurrection warning must not fire under cutover when "
        f"fingerprint algorithm changed: {fired}"
    )

    # 5) Both rows coexist: soft-deleted pre-fix at its old fp,
    # active post-fix at its new fp.
    pre_fix_visible = services._dedup_store.find_by_fingerprint(
        collection, pre_fix_fp, include_deleted=False
    )
    pre_fix_any = services._dedup_store.find_by_fingerprint(
        collection, pre_fix_fp, include_deleted=True
    )
    assert pre_fix_visible is None, "pre-fix row should still be soft-deleted"
    assert pre_fix_any is not None, "pre-fix row should still exist with deleted_at"

    new_fp = response["content_fingerprint"]
    new_active = services._dedup_store.find_by_fingerprint(
        collection, new_fp, include_deleted=False
    )
    assert new_active is not None, "post-fix row must be active and findable"
    assert new_active.document_id != "pre-fix-doc-residual5", (
        "must be a fresh document_id, not the resurrected pre-fix row"
    )


# ── Residual 7: logging fires with documented structured-extras shape ───────


def test_residual_7_dedup_skip_logger_fires(monkeypatch, caplog):
    """The logger.info('dedup-skip', extra=...) call must fire on a
    cache hit, with the documented structured extras: collection,
    fingerprint_prefix (8 hex chars), source_file, algorithm='raw-bytes'."""
    _install_clean(monkeypatch)
    uri = str(_FIXTURE_TXT)
    collection = "k7n_residual7_skip"

    # First ingest — store the doc.
    services._process_single_document(**_kwargs(uri, collection=collection))

    # Second ingest under caplog — must fire the dedup-skip log.
    caplog.set_level(logging.INFO, logger="pipeline.services")
    second = services._process_single_document(**_kwargs(uri, collection=collection))
    assert second["was_dedup_skip"] is True

    skip_records = [r for r in caplog.records if r.message == "dedup-skip"]
    assert skip_records, (
        f"dedup-skip log not emitted; records: "
        f"{[(r.name, r.message) for r in caplog.records]}"
    )
    rec = skip_records[0]
    assert getattr(rec, "collection", None) == collection
    fp_prefix = getattr(rec, "fingerprint_prefix", None)
    assert isinstance(fp_prefix, str) and len(fp_prefix) == 8, (
        f"fingerprint_prefix must be 8 hex chars; got {fp_prefix!r}"
    )
    assert getattr(rec, "source_file", None) == "sample.txt"
    assert getattr(rec, "algorithm", None) == "raw-bytes"


def test_residual_7_dedup_miss_store_logger_fires(monkeypatch, caplog):
    """The logger.info('dedup-miss-store', extra=...) call must fire on
    cache miss + store, with the documented extras."""
    _install_clean(monkeypatch)
    uri = str(_FIXTURE_TXT)
    collection = "k7n_residual7_miss"

    caplog.set_level(logging.INFO, logger="pipeline.services")
    response = services._process_single_document(**_kwargs(uri, collection=collection))
    assert response["was_dedup_skip"] is False

    miss_records = [r for r in caplog.records if r.message == "dedup-miss-store"]
    assert miss_records, (
        f"dedup-miss-store log not emitted; records: "
        f"{[(r.name, r.message) for r in caplog.records]}"
    )
    rec = miss_records[0]
    assert getattr(rec, "collection", None) == collection
    fp_prefix = getattr(rec, "fingerprint_prefix", None)
    assert isinstance(fp_prefix, str) and len(fp_prefix) == 8
    assert getattr(rec, "source_file", None) == "sample.txt"
    assert getattr(rec, "algorithm", None) == "raw-bytes"
