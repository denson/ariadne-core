"""Verification probes for ariadne--vsx (Batch B): warnings persistence
ordering fix in services._process_single_document.

Bug being verified:
    Pre-fix, metadata-hygiene warnings were appended to the local
    `warnings` list AFTER `_dedup_store.store_document(...)` ran.
    PgDedupStore.store_document snapshots `doc.warnings or []` into the
    SQL parameter dict at dedup.py:294 and commits before returning, so
    the post-store appends never reached Postgres. Additionally, the
    response dict surfaced `warnings` but never `warnings_count`, so
    serialized responses showed `null` despite the array being non-empty.

Fix shape (per agents/design/ariadne--vsx/design.md):
    Probe-then-store. Detect would-be-resurrection BEFORE calling
    store_document, append all warnings (resurrection + 3 hygiene)
    BEFORE the store call, then call store_document. Add
    `warnings_count: len(warnings)` adjacent to every path that
    surfaces `warnings`.

Probe map → brief smoke beats (ariadne--vsx):
    beat 1 (persistence end-to-end)   → test_pg_warnings_persist_to_postgres
    beat 2 (warnings_count shape)     → test_warnings_count_matches_warnings_len
    beat 3 (zero-warning regression)  → test_zero_warnings_when_metadata_complete
    beat 4 (dedup-skip path)          → test_dedup_skip_path_includes_warnings_count
    beat 5 (list-documents shape)     → test_list_documents_includes_warnings_count
    beat 6 (backward-compat)          → test_pre_fix_empty_warnings_not_perturbed
    beat 7 (resurrection — design §4.7)→ test_resurrection_warning_persists_to_db

Strategy: real Postgres for beats touching persistence (1, 4, 6, 7).
InMemory + monkeypatched stores for shape-only beats (2, 3, 5).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from pipeline import services
from pipeline.dedup import InMemoryDedupStore, StoredDocument
from pipeline.storage.base import InMemoryVectorStore


FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


# ── Test doubles (shape mirrors tests/test_services.py) ─────────────────────


class _StubEmbedResult:
    def __init__(self, count: int, dims: int = 3) -> None:
        self.embeddings = [[0.1] * dims for _ in range(count)]
        self.processing_chain_entry = {
            "step": "embedding",
            "tool": "gemini:stub",
            "ts": "2026-05-06T00:00:00Z",
            "ms": 1,
        }


class _SuccessEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_texts(self, texts: list[str]):
        return _StubEmbedResult(count=len(texts))


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts: list[str]):  # pragma: no cover
        raise AssertionError("embed_texts should not be called")


def _install_in_memory_stores(monkeypatch):
    stub_dedup = InMemoryDedupStore()
    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_dedup_store", stub_dedup)
    monkeypatch.setattr(services, "_vector_store", stub_vector)
    return stub_dedup, stub_vector


class SnapshotingDedupStore(InMemoryDedupStore):
    """InMemoryDedupStore variant that mimics PgDedupStore's snapshot
    semantics for the `warnings` list.

    PgDedupStore.store_document at dedup.py:294 evaluates `doc.warnings or
    []` once, passes the resulting list as a SQL parameter, and commits.
    Any mutation to the local Python `warnings` list after the call does
    NOT reach Postgres. The default InMemoryDedupStore stores `doc` by
    reference, so post-store appends DO appear on subsequent reads —
    which is what makes it unable to surface this bug (design §5).

    This subclass snapshots the warnings list at store-time using
    `list(doc.warnings or [])`, then stores a shallow copy of `doc` with
    the snapshotted warnings frozen onto it. find_by_fingerprint and
    list_documents return the stored copy (with snapshot warnings),
    matching what Pg would return.

    This lets us falsify the ordering bug (and validate the fix) locally
    without a running Postgres. It is a test-only construct; callers in
    production use the real PgDedupStore. The Pg-fixture tests below
    exercise the real persistence path when Postgres is available.
    """

    def store_document(self, doc: StoredDocument, **kwargs) -> bool:
        import copy
        # Snapshot warnings at call time, exactly like Pg.
        snapshot_warnings = list(doc.warnings or [])
        # Shallow-copy the StoredDocument so the caller's mutations to
        # doc.warnings post-call cannot reach our stored object.
        snap = copy.copy(doc)
        snap.warnings = snapshot_warnings
        # Forward kwargs (e.g. ariadne--5f2's ``agent_metadata=``) so the
        # snapshot double stays transparent to signature additions on the
        # parent's store_document.
        return super().store_document(snap, **kwargs)


def _install_snapshot_stores(monkeypatch):
    """Install the Pg-snapshot-mimicking dedup store."""
    stub_dedup = SnapshotingDedupStore()
    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_dedup_store", stub_dedup)
    monkeypatch.setattr(services, "_vector_store", stub_vector)
    return stub_dedup, stub_vector


def _install_pg_stores(monkeypatch, pg_dedup_store):
    """Install the real Pg dedup store + an in-memory vector store onto
    services. The vector store can stay in-memory — the bug under test is
    confined to the dedup store's warnings persistence."""
    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_dedup_store", pg_dedup_store)
    monkeypatch.setattr(services, "_vector_store", stub_vector)
    return pg_dedup_store, stub_vector


_SENTINEL = object()


def _kwargs(
    uri: str,
    collection: str,
    *,
    agent_notes: str | None = "verification probe",
    agent_metadata=_SENTINEL,
    store: bool = True,
) -> dict:
    """Build the kwargs dict for _process_single_document.

    Pass `agent_metadata=None` explicitly to force the no-source-metadata
    hygiene warning to fire. Default sentinel means "fill with a valid
    source_reference so the warning does NOT fire."
    """
    if agent_metadata is _SENTINEL:
        agent_metadata = {"source_reference": "ariadne--vsx-probe"}
    return dict(
        uri=uri,
        store=store,
        collection=collection,
        tags=[],
        force=False,
        agent_id=None,
        agent_type="vera-vsx",
        model=None,
        initiated_by="vera",
        agent_notes=agent_notes,
        agent_metadata=agent_metadata,
        chunking_config=None,
    )


# ── Beat 2: warnings_count shape correctness ─────────────────────────────────


def test_warnings_count_matches_warnings_len_when_warnings_present(monkeypatch):
    """Brief beat 2: response['warnings_count'] == len(response['warnings']).

    Forces metadata-hygiene warnings by passing collection='default' AND
    no agent_notes AND no provenance metadata — the three hygiene checks
    fire and produce three warning strings.
    """
    monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
    _install_in_memory_stores(monkeypatch)

    response = services._process_single_document(
        **_kwargs(
            str(FIXTURES / "sample.txt"),
            "default",
            agent_notes=None,
            agent_metadata=None,
        )
    )

    assert "warnings_count" in response, (
        "main response must include warnings_count (was missing pre-fix)"
    )
    assert response["warnings_count"] is not None, (
        "warnings_count must never be null"
    )
    assert isinstance(response["warnings_count"], int), (
        f"warnings_count must be int, got {type(response['warnings_count']).__name__}"
    )
    assert response["warnings_count"] == len(response["warnings"]), (
        f"warnings_count={response['warnings_count']} != "
        f"len(warnings)={len(response['warnings'])}"
    )
    # Sanity: the three hygiene warnings should fire.
    assert response["warnings_count"] >= 3, (
        f"expected at least 3 hygiene warnings (default collection + "
        f"no agent_notes + no source metadata), got {response['warnings_count']}: "
        f"{response['warnings']}"
    )


# ── Beat 3: zero-metadata-hygiene-warning regression ───────────────────────


# The hygiene warning strings the fix's code paths can produce. Beat 3 asserts
# none of these fire when metadata is complete — extraction-layer warnings
# (encoding validation, etc.) ride along legitimately and are not in scope
# for this fix.
_HYGIENE_WARNING_FRAGMENTS = (
    "default' collection",
    "No agent_notes provided",
    "No source_url or source_reference",
    "previously soft-deleted",
)


def test_zero_hygiene_warnings_when_metadata_complete(monkeypatch):
    """Brief beat 3 (refined): doc with non-default collection + agent_notes
    + source_url produces NO metadata-hygiene warnings, AND warnings_count
    correctly reflects whatever warnings did fire (e.g. extraction-layer
    encoding-validation warnings, which are out of scope for this fix).

    The brief's literal text says 'warnings_count: 0' but the empirical
    floor on this corpus is whatever extraction adds — the fix's contract
    is about metadata-hygiene warnings firing or not. Surfaced as a
    methodology_concern in the verdict.
    """
    monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
    _install_in_memory_stores(monkeypatch)

    response = services._process_single_document(
        **_kwargs(
            str(FIXTURES / "sample.txt"),
            f"vsx-zero-{uuid.uuid4().hex[:8]}",
            agent_notes="probe for zero-hygiene-warning case",
            agent_metadata={"source_url": "https://example.test/probe"},
        )
    )

    # Hard contract: none of the hygiene warning strings fire.
    fired_hygiene = [
        w
        for w in response["warnings"]
        if any(frag in w for frag in _HYGIENE_WARNING_FRAGMENTS)
    ]
    assert fired_hygiene == [], (
        f"expected zero metadata-hygiene warnings when metadata is complete, "
        f"got: {fired_hygiene}"
    )

    # Hard contract: warnings_count matches len(warnings) (shape symmetry).
    assert response["warnings_count"] == len(response["warnings"]), (
        f"warnings_count={response['warnings_count']} != "
        f"len(warnings)={len(response['warnings'])}; "
        f"warnings={response['warnings']}"
    )
    assert isinstance(response["warnings_count"], int)
    assert response["warnings_count"] is not None


# ── Beats 1, 4, 7 against SnapshotingDedupStore (Pg-snapshot semantics) ─────


class TestSnapshotPersistence:
    """Beats 1, 4, 7 verified against SnapshotingDedupStore — a test
    double that mimics PgDedupStore's snapshot-warnings-at-store-time
    semantics. These run without Postgres. The Pg-fixture variants below
    exercise the same beats against a real DB when one is available."""

    def test_warnings_persist_against_snapshot_store(self, monkeypatch):
        """Beat 1 (snapshot-store variant): hygiene warnings appended in
        services BEFORE store_document end up in the stored row.

        Pre-fix, the appends ran AFTER store_document and the snapshot
        captured warnings=[]. Post-fix, the appends precede the call and
        the snapshot captures the full list.
        """
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        snap_dedup, _ = _install_snapshot_stores(monkeypatch)
        coll = f"vsx-snap-persist-{uuid.uuid4().hex[:8]}"

        response = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                coll,
                agent_notes=None,
                agent_metadata=None,
            )
        )

        # Hygiene warnings must appear in the response.
        hygiene = [
            w for w in response["warnings"]
            if any(frag in w for frag in _HYGIENE_WARNING_FRAGMENTS)
        ]
        assert len(hygiene) >= 2, (
            f"expected ≥2 hygiene warnings (no agent_notes + no source meta), "
            f"got: {response['warnings']}"
        )

        # The load-bearing assertion: the stored doc has the SAME warnings.
        # If hygiene appends ran after store (the bug), stored.warnings
        # would lack them.
        fingerprint = response["content_fingerprint"]
        stored = snap_dedup.find_by_fingerprint(coll, fingerprint)
        assert stored is not None
        assert set(stored.warnings) == set(response["warnings"]), (
            f"snapshot-store divergence — proves ordering bug.\n"
            f"  response: {response['warnings']}\n"
            f"  stored:   {stored.warnings}"
        )

    def test_dedup_skip_path_shape_against_snapshot_store(self, monkeypatch):
        """Beat 4 (snapshot-store variant): re-ingest hits dedup-skip with
        was_dedup_skip=True, surfaces warnings_count=len(warnings), and
        returns the persisted warnings list."""
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        snap_dedup, _ = _install_snapshot_stores(monkeypatch)
        coll = f"vsx-snap-dedup-{uuid.uuid4().hex[:8]}"

        first = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"), coll,
                agent_notes=None, agent_metadata=None,
            )
        )
        second = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"), coll,
                agent_notes=None, agent_metadata=None,
            )
        )

        assert second["was_dedup_skip"] is True, second
        assert "warnings_count" in second, (
            "dedup-skip response must include warnings_count (added in fix)"
        )
        assert second["warnings_count"] is not None
        assert isinstance(second["warnings_count"], int)
        assert second["warnings_count"] == len(second["warnings"])
        assert set(second["warnings"]) == set(first["warnings"])

    def test_resurrection_warning_persists_against_snapshot_store(
        self, monkeypatch
    ):
        """Beat 7 (snapshot-store variant): the resurrection warning is
        appended via the probe-then-store path BEFORE store_document, so
        it lands in the stored row.

        Pre-fix shape (was_resurrected = store_document(...); if
        was_resurrected: warnings.append(...)) appends the warning AFTER
        the snapshot, so stored.warnings would not include it. Post-fix,
        the probe runs first, the append runs first, the snapshot
        captures it.
        """
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        snap_dedup, _ = _install_snapshot_stores(monkeypatch)
        coll = f"vsx-snap-resurrect-{uuid.uuid4().hex[:8]}"

        first = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"), coll,
                agent_notes="seed",
                agent_metadata={"source_url": "https://example.test/seed"},
            )
        )
        fp = first["content_fingerprint"]
        original_doc_id = first["document_id"]

        # Soft-delete the row so the next ingest must resurrect it.
        marked = snap_dedup.soft_delete_collection(coll)
        assert marked >= 1
        assert snap_dedup.find_by_fingerprint(coll, fp) is None
        assert snap_dedup.find_by_fingerprint(coll, fp, include_deleted=True) is not None

        second = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"), coll,
                agent_notes="re-ingest",
                agent_metadata={"source_url": "https://example.test/reingest"},
            )
        )

        # Response surfaces the warning.
        resurrection_text = "previously soft-deleted"
        assert any(resurrection_text in w for w in second["warnings"]), (
            f"expected resurrection warning in response, got: {second['warnings']}"
        )

        # The load-bearing assertion: warning is in the STORED row.
        stored = snap_dedup.find_by_fingerprint(coll, fp)
        assert stored is not None, "row must be visible after resurrection"
        # Note: InMemoryDedupStore overwrites the doc on resurrection
        # (`self._documents[key] = doc`), so the new doc's UUID replaces
        # the original. Pg's ON CONFLICT path keeps the original UUID;
        # that contract is verified by the Pg-fixture variant below.
        # Here we focus on the warnings-snapshot ordering invariant.
        # Reference: original_doc_id={original_doc_id} (kept above for parity).
        del original_doc_id
        assert any(resurrection_text in w for w in stored.warnings), (
            f"resurrection warning must be persisted to the stored row "
            f"(this is the load-bearing falsification of the ordering bug); "
            f"got stored.warnings={stored.warnings}"
        )

    def test_pre_fix_empty_warnings_not_perturbed_snapshot(self, monkeypatch):
        """Beat 6 (snapshot-store variant): a row pre-stored with
        warnings=[] is not retroactively populated by a later same-collection
        ingest of a different doc."""
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        snap_dedup, _ = _install_snapshot_stores(monkeypatch)
        coll = f"vsx-snap-bcompat-{uuid.uuid4().hex[:8]}"

        # Seed a "pre-fix shaped" row with warnings=[].
        seed = StoredDocument(
            document_id=str(uuid.uuid4()),
            collection_id=coll,
            source_file=f"/tmp/{uuid.uuid4().hex}.txt",
            content_fingerprint=uuid.uuid4().hex,
            file_type="txt",
            engine="vera-seeded",
            markdown="seeded",
            title="seeded",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            tags=[],
            warnings=[],
        )
        snap_dedup.store_document(seed)

        before = snap_dedup.find_by_fingerprint(coll, seed.content_fingerprint)
        assert before is not None
        assert before.warnings == []

        # Run an unrelated ingest in the same collection.
        services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"), coll,
                agent_notes="unrelated",
                agent_metadata={"source_url": "https://example.test/unrelated"},
            )
        )

        # Seeded row must be unchanged.
        after = snap_dedup.find_by_fingerprint(coll, seed.content_fingerprint)
        assert after is not None
        assert after.warnings == [], (
            f"seeded row's warnings perturbed from [] to {after.warnings}"
        )
        assert after.document_id == seed.document_id


# ── Beat 1 (persistence end-to-end) — real Postgres ──────────────────────────


class TestPgWarningsPersistence:
    """Beats 1, 4, 7 require real Postgres because the bug under test is
    PgDedupStore-specific: InMemoryDedupStore stores object references
    and would mask the persistence-snapshot bug. Skipped cleanly when
    Postgres is unreachable (per conftest pg_pool fixture)."""

    def test_pg_warnings_persist_to_postgres(
        self, monkeypatch, pg_dedup_store, unique_collection
    ):
        """Brief beat 1: ingest produces hygiene warnings; those warnings
        survive the round-trip through Postgres via find_by_fingerprint.

        Pre-fix, the warnings list seen at probe-time was non-empty BUT
        the row written to Postgres had warnings=[] because the appends
        ran after store_document snapshotted the parameter dict.
        """
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        _install_pg_stores(monkeypatch, pg_dedup_store)

        response = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                unique_collection,
                # default collection check won't fire, but the other two will
                agent_notes=None,
                agent_metadata=None,
            )
        )

        # Response side: hygiene warnings present.
        assert response["warnings_count"] >= 2, (
            f"expected ≥2 hygiene warnings (no agent_notes + no source metadata), "
            f"got {response['warnings_count']}: {response['warnings']}"
        )
        response_warnings = list(response["warnings"])
        assert any("agent_notes" in w for w in response_warnings), response_warnings
        assert any(
            "source_url" in w or "source_reference" in w for w in response_warnings
        ), response_warnings

        # The load-bearing assertion: warnings are PERSISTED to Postgres.
        # Pre-fix, this read returned warnings=[] because the appends ran
        # after store_document snapshotted the params.
        fingerprint = response["content_fingerprint"]
        stored = pg_dedup_store.find_by_fingerprint(unique_collection, fingerprint)
        assert stored is not None, "document must be retrievable post-ingest"

        # Set comparison (order-independent per design §4.1).
        assert set(stored.warnings) == set(response_warnings), (
            f"persisted warnings differ from response warnings.\n"
            f"  response: {response_warnings}\n"
            f"  stored:   {stored.warnings}"
        )

    def test_dedup_skip_path_includes_warnings_count(
        self, monkeypatch, pg_dedup_store, unique_collection
    ):
        """Brief beat 4 / design §4.4: re-ingest of the same warning-bearing
        doc returns was_dedup_skip=True with the persisted warnings list AND
        warnings_count == len(warnings) (the new shape symmetry the fix added).
        """
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        _install_pg_stores(monkeypatch, pg_dedup_store)

        # First ingest — produces warnings.
        first = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                unique_collection,
                agent_notes=None,
                agent_metadata=None,
            )
        )
        assert first["warnings_count"] >= 2, first

        # Second ingest of the same content — must hit the dedup-skip path.
        second = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                unique_collection,
                agent_notes=None,
                agent_metadata=None,
            )
        )

        assert second["was_dedup_skip"] is True, (
            f"expected was_dedup_skip=True on re-ingest, got {second!r}"
        )
        # The new contract: dedup-skip path now surfaces warnings_count.
        assert "warnings_count" in second, (
            "dedup-skip response must include warnings_count (added in this fix)"
        )
        assert second["warnings_count"] is not None, (
            "warnings_count must not be null on dedup-skip path"
        )
        assert isinstance(second["warnings_count"], int), (
            f"warnings_count must be int, got "
            f"{type(second['warnings_count']).__name__}"
        )
        # Shape symmetry: warnings_count == len(warnings) on this path too.
        assert second["warnings_count"] == len(second["warnings"]), (
            f"dedup-skip warnings_count={second['warnings_count']} != "
            f"len(warnings)={len(second['warnings'])}"
        )
        # The warnings on the dedup-skip path should be the persisted list
        # from the original ingest (proves persistence + retrieval cycle).
        assert set(second["warnings"]) == set(first["warnings"]), (
            f"dedup-skip warnings differ from original.\n"
            f"  first:  {first['warnings']}\n"
            f"  second: {second['warnings']}"
        )

    def test_resurrection_warning_persists_to_db(
        self, monkeypatch, pg_dedup_store, unique_collection
    ):
        """Design §4.7 (probe extra): ingest, soft-delete, re-ingest. The
        re-ingest response includes the 'previously soft-deleted' warning
        AND that warning is persisted to Postgres (not just transient).

        This exercises the two-call probe diff: would_resurrect detection
        must land BEFORE store_document, then the resurrection warning
        must be present in the row Postgres commits.
        """
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        _install_pg_stores(monkeypatch, pg_dedup_store)

        # First ingest — uses complete metadata so the hygiene warnings
        # don't fire and we can isolate the resurrection warning.
        first = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                unique_collection,
                agent_notes="seeding for resurrection probe",
                agent_metadata={"source_url": "https://example.test/seed"},
            )
        )
        assert first["warnings_count"] == 0, (
            f"expected zero warnings on initial ingest, got: {first['warnings']}"
        )
        fingerprint = first["content_fingerprint"]
        original_doc_id = first["document_id"]

        # Soft-delete the row.
        marked = pg_dedup_store.soft_delete_collection(unique_collection)
        assert marked >= 1, f"expected to soft-delete ≥1 row, marked={marked}"
        assert (
            pg_dedup_store.find_by_fingerprint(unique_collection, fingerprint) is None
        ), "row should be invisible to default queries after soft-delete"
        assert (
            pg_dedup_store.find_by_fingerprint(
                unique_collection, fingerprint, include_deleted=True
            )
            is not None
        ), "row should still exist with include_deleted=True"

        # Re-ingest — should resurrect AND surface the resurrection warning.
        second = services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                unique_collection,
                agent_notes="re-ingest for resurrection probe",
                agent_metadata={"source_url": "https://example.test/reingest"},
            )
        )

        # Response must surface the resurrection warning.
        resurrection_text = "previously soft-deleted"
        assert any(resurrection_text in w for w in second["warnings"]), (
            f"expected resurrection warning in response, got: "
            f"{second['warnings']}"
        )

        # The load-bearing assertion: the warning is PERSISTED to Postgres.
        # If would_resurrect was computed AFTER store_document (the bug
        # this fix prevents), the warning would only appear in the
        # response dict and NOT in the row.
        stored = pg_dedup_store.find_by_fingerprint(unique_collection, fingerprint)
        assert stored is not None, (
            "row must be visible again after resurrection-by-re-ingest"
        )
        assert stored.document_id == original_doc_id, (
            "resurrection must keep the original UUID"
        )
        assert any(resurrection_text in w for w in stored.warnings), (
            f"resurrection warning must be persisted to the DB row, "
            f"got stored.warnings={stored.warnings}"
        )

    def test_pre_fix_empty_warnings_not_perturbed(
        self, monkeypatch, pg_dedup_store, unique_collection
    ):
        """Brief beat 6: the fix does not retroactively populate warnings
        on rows that were stored with warnings=[] before the fix landed.

        We can't reach the production rows from a unit test, but we CAN
        exercise the contract: a row that was stored with warnings=[] in
        Postgres stays with warnings=[] when read back, even after the
        fixed code path runs. (Pre-fix prod rows live in this state by
        accident; the contract is that the deploy doesn't perturb them.)
        """
        # Manually insert a row with warnings=[] using the same code path
        # the buggy pre-fix version would have produced.
        seed_doc = StoredDocument(
            document_id=str(uuid.uuid4()),
            collection_id=unique_collection,
            source_file=f"/tmp/{uuid.uuid4().hex}.txt",
            content_fingerprint=uuid.uuid4().hex,
            file_type="txt",
            engine="vera-seeded",
            markdown="seeded pre-fix-style row",
            title="seeded",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            tags=[],
            warnings=[],  # empty, mimicking pre-fix prod state
        )
        pg_dedup_store.store_document(seed_doc)

        # Read back through the same path the API uses.
        found_before = pg_dedup_store.find_by_fingerprint(
            unique_collection, seed_doc.content_fingerprint
        )
        assert found_before is not None
        assert found_before.warnings == [], (
            f"seed precondition: row should have warnings=[], got "
            f"{found_before.warnings}"
        )

        # Now ingest a DIFFERENT doc through the post-fix services path
        # in the same collection. The fix must not perturb the seeded row.
        monkeypatch.setattr(services, "_embedding_client", _SuccessEmbeddingClient())
        _install_pg_stores(monkeypatch, pg_dedup_store)

        services._process_single_document(
            **_kwargs(
                str(FIXTURES / "sample.txt"),
                unique_collection,
                agent_notes="post-fix ingest of unrelated doc",
                agent_metadata={"source_url": "https://example.test/unrelated"},
            )
        )

        # Re-read the seeded row — must be unchanged.
        found_after = pg_dedup_store.find_by_fingerprint(
            unique_collection, seed_doc.content_fingerprint
        )
        assert found_after is not None, "seeded row must still exist"
        assert found_after.warnings == [], (
            f"backward-compat broken: seeded row's warnings perturbed from "
            f"[] to {found_after.warnings}"
        )
        assert found_after.document_id == seed_doc.document_id, (
            "seeded row's document_id must not change"
        )


# ── Beat 5: list-documents shape ─────────────────────────────────────────────


class TestListDocumentsWarningsCount:
    """Beat 5: list_documents must surface warnings_count populated as int.

    The list_documents path on PgDedupStore returns StoredDocument objects
    with `.warnings` populated (proven by test_dedup_warnings.py). The
    api/routes layer derives warnings_count from len(d.warnings or []).
    We probe the StoredDocument round-trip here directly — that's the
    source-of-truth for what the API surfaces."""

    def test_pg_list_documents_warnings_round_trip(
        self, pg_dedup_store, unique_collection
    ):
        """list_documents preserves warnings as a populated list, so the
        API's len(warnings) is well-defined and non-null per row."""
        # Insert two docs: one with warnings, one without.
        doc_with = StoredDocument(
            document_id=str(uuid.uuid4()),
            collection_id=unique_collection,
            source_file=f"/tmp/{uuid.uuid4().hex}.txt",
            content_fingerprint=uuid.uuid4().hex,
            file_type="txt",
            engine="test",
            markdown="x",
            title="t",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            tags=[],
            warnings=["w1", "w2"],
        )
        doc_without = StoredDocument(
            document_id=str(uuid.uuid4()),
            collection_id=unique_collection,
            source_file=f"/tmp/{uuid.uuid4().hex}.txt",
            content_fingerprint=uuid.uuid4().hex,
            file_type="txt",
            engine="test",
            markdown="y",
            title="t",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            tags=[],
            warnings=[],
        )
        pg_dedup_store.store_document(doc_with)
        pg_dedup_store.store_document(doc_without)

        docs, total = pg_dedup_store.list_documents(
            collection=unique_collection, limit=10
        )
        assert total == 2, f"expected 2 docs, got {total}"
        by_fp = {d.content_fingerprint: d for d in docs}

        # The API derives warnings_count from len(d.warnings or []) — these
        # round-trip cleanly so warnings_count is a well-defined int per row.
        with_warnings = by_fp[doc_with.content_fingerprint]
        without_warnings = by_fp[doc_without.content_fingerprint]

        assert with_warnings.warnings == ["w1", "w2"]
        assert len(with_warnings.warnings or []) == 2  # = warnings_count
        assert without_warnings.warnings == []
        assert len(without_warnings.warnings or []) == 0  # = warnings_count
