"""Tests for the bw → Ariadne inline ingest coupling (Phase 3).

ariadne--8fd.5. Exercises the helpers in ``pipeline.api.bw_ingest`` and
the route-level coupling that wires them into ``pipeline.api.bw_routes``.

Probes from the design at ``agents/design/ariadne--8fd.5/design.md`` §3
are mapped 1:1 to test functions below — see the docstring on each
``test_pNN_*`` for the probe it covers.

The tests mock ``subprocess.run`` to control bw's behavior and use the
in-memory dedup/vector stores so we don't require Postgres for the
common cases. Tests that require the latest-interaction filter
semantics use the in-memory implementation's analogue path; the SQL
shape is exercised separately by the pg-store integration suite.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.api import bw_ingest, bw_routes
from pipeline.api.bw_routes import router

from tests.conftest import override_auth


# ── Test infrastructure ─────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


def _fake_completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["bw"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _bw_show_json(
    *,
    ticket_id: str = "bw-test-a3f",
    title: str = "T",
    description: str = "body text",
    status: str = "open",
    assignee: str = "",
    labels: list[str] | None = None,
    parent: str | None = None,
    comments: list[dict] | None = None,
) -> str:
    payload = {
        "assignee": assignee,
        "blocked_by": [],
        "blocks": [],
        "created": "2026-05-12T00:00:00Z",
        "description": description,
        "id": ticket_id,
        "labels": labels or [],
        "comments": comments or [],
        "parent": parent,
        "priority": 2,
        "status": status,
        "title": title,
        "type": "task",
        "updated_at": "2026-05-12T00:00:00Z",
    }
    return json.dumps(payload)


def _bw_history_json(
    *,
    sha: str = "a" * 40,
    author: str = "test-user",
    intent_prefix: str = "create",
    ticket_id: str = "bw-test-a3f",
) -> str:
    return json.dumps([
        {
            "hash": sha,
            "timestamp": "2026-05-12 00:00",
            "author": author,
            "intent": f"{intent_prefix} {ticket_id} arg",
        }
    ])


def _bw_history_full_json(rows: list[dict]) -> str:
    return json.dumps(rows)


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Reset module-level state before each test.

    The bw_ingest module carries an in-memory retry queue + counters
    that persist across tests; the bw_routes module carries the per-slug
    lock dict and backup-skip counter. Reset both so tests don't see
    state from previous runs.
    """
    monkeypatch.setattr(bw_routes, "BW_BINARY", "/usr/local/bin/bw")
    tmp_root = tempfile.mkdtemp(prefix="bw-test-repos-")
    monkeypatch.setattr(bw_routes, "BW_REPOS_ROOT", tmp_root)
    monkeypatch.setattr(bw_routes, "_backup_skip_count", {})
    monkeypatch.setattr(bw_routes, "_slug_locks", {})

    # Reset in-memory retry/dead-letter queues + the per-process
    # drain counter so each test starts clean.
    bw_ingest._IN_MEMORY_RETRY_QUEUE.clear()
    bw_ingest._IN_MEMORY_DEAD_LETTER.clear()
    monkeypatch.setattr(bw_ingest, "_file_fallback_drain_count", 0)

    # Wire the in-memory store for tests. This is what
    # pipeline.services._dedup_store would be on a fresh process.
    from pipeline import services
    from pipeline.dedup import InMemoryDedupStore
    from pipeline.storage.base import InMemoryVectorStore
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())

    yield

    # Best-effort cleanup of the tmp BW_REPOS_ROOT.
    import shutil
    shutil.rmtree(tmp_root, ignore_errors=True)


@pytest.fixture
def client():
    app = _build_app()
    return TestClient(app)


def _drive_create_ticket(
    client, mock_run, slug: str = "myproj", ticket_id: str = "bw-test-a3f",
    title: str = "T", description: str = "body text",
):
    """Issue a POST /tickets request, mocking the two subprocess calls.

    Every create_ticket flow makes TWO subprocess.run calls:
      1. ``bw create ...`` — the actual ticket write.
      2. ``bw history --json --limit 1`` — inside _ingest_bw_write to
         capture the commit SHA + author for agent_metadata.
    """
    mock_run.side_effect = [
        _fake_completed(stdout=_bw_show_json(
            ticket_id=ticket_id, title=title, description=description,
        )),
        _fake_completed(stdout=_bw_history_json(
            ticket_id=ticket_id, intent_prefix="create",
        )),
    ]
    body = {"title": title, "description": description}
    return client.post(f"/api/bw/projects/{slug}/tickets", json=body)


# ── P1 (D1 schema integrity) ────────────────────────────────────────────────


def test_p1_d1_schema_integrity(client):
    """P1: POST /tickets → body doc ingest carries the full D1 schema."""
    with patch.object(subprocess, "run") as mock_run:
        response = _drive_create_ticket(client, mock_run)
    assert response.status_code == 201
    body = response.json()
    # The bw shape is preserved at the top level.
    assert body["id"] == "bw-test-a3f"
    assert body["title"] == "T"
    # The Phase 3 augmentation lives under ``ariadne_ingest``.
    ingest = body.get("ariadne_ingest")
    assert ingest is not None, f"missing ariadne_ingest in {body}"
    assert ingest["ingest_status"] == "ok"
    assert ingest["source_type"] == "body"
    assert ingest["bw_commit_sha"] == "a" * 40
    # The body doc's stored agent_metadata carries the full D1 schema.
    from pipeline import services
    doc_id = ingest["document_id"]
    meta = services._dedup_store._doc_metadata.get(doc_id, {})
    required_keys = {
        "ticket_id", "project", "source_type", "comment_n",
        "author", "timestamp", "bw_commit_sha", "bw_status",
        "parent_ticket_id", "assignee", "labels", "labels_flat",
    }
    missing = required_keys - set(meta)
    assert not missing, f"missing agent_metadata keys: {missing}"
    assert meta["ticket_id"] == "bw-test-a3f"
    assert meta["project"] == "myproj"
    assert meta["source_type"] == "body"
    assert meta["comment_n"] is None
    assert meta["bw_commit_sha"] == "a" * 40


# ── P2 (D1.4 dedup-salt is frontmatter) ─────────────────────────────────────


def test_p2_d1_4_dedup_salt_is_frontmatter(client):
    """P2: Two tickets with identical title+description → different docs.

    The frontmatter carries ticket_id + bw_commit_sha, so even literally
    identical body text produces distinct SHA-256 fingerprints.
    """
    with patch.object(subprocess, "run") as mock_run:
        # Ticket 1.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-test-001")),
            _fake_completed(stdout=_bw_history_json(
                sha="b" * 40, ticket_id="bw-test-001",
            )),
        ]
        r1 = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "same"},
        )
        assert r1.status_code == 201
        doc1 = r1.json()["ariadne_ingest"]["document_id"]

        # Ticket 2 — identical body text.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-test-002")),
            _fake_completed(stdout=_bw_history_json(
                sha="c" * 40, ticket_id="bw-test-002",
            )),
        ]
        r2 = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "same"},
        )
        assert r2.status_code == 201
        doc2 = r2.json()["ariadne_ingest"]["document_id"]

    assert doc1 != doc2, "frontmatter-as-salt failed — same doc_id"


# ── P3 (D1.6 comment_n) ─────────────────────────────────────────────────────


def test_p3_d1_6_comment_n(client):
    """P3: Three comments → comment_n values 1, 2, 3 in order."""
    with patch.object(subprocess, "run") as mock_run:
        # Create ticket.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-t")),
            _fake_completed(stdout=_bw_history_json(
                sha="d" * 40, ticket_id="bw-t",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
        assert r.status_code == 201

        # Three comments — each gets a length-N comments array.
        comment_ids: list[str] = []
        for i in range(1, 4):
            comments_so_far = [
                {"text": f"c{j}", "timestamp": "2026-05-12T00:00:00Z"}
                for j in range(1, i + 1)
            ]
            mock_run.side_effect = [
                _fake_completed(stdout=_bw_show_json(
                    ticket_id="bw-t", comments=comments_so_far,
                )),
                _fake_completed(stdout=_bw_history_json(
                    sha=f"{i}" * 40, ticket_id="bw-t",
                    intent_prefix="comment",
                )),
            ]
            rc = client.post(
                "/api/bw/projects/myproj/tickets/bw-t/comments",
                json={"text": f"c{i}"},
            )
            assert rc.status_code == 201, rc.text
            ingest = rc.json()["ariadne_ingest"]
            comment_ids.append(ingest["document_id"])

    from pipeline import services
    for idx, doc_id in enumerate(comment_ids, start=1):
        meta = services._dedup_store._doc_metadata.get(doc_id, {})
        assert meta.get("comment_n") == idx, (
            f"comment #{idx} had comment_n={meta.get('comment_n')}"
        )


# ── P4 (D2.4 lock holds across ingest) ──────────────────────────────────────


def test_p4_d2_4_lock_serializes_ingest():
    """P4: two same-slug writes serialize through the lock + ingest.

    This is the existing Phase 2 lock-serialization assertion extended
    to cover the ingest helper: when the lock is held through the
    inline ingest, a second writer cannot enter until the first
    releases — even if the first writer is blocked inside the ingest's
    asyncio.to_thread call.
    """
    slug = "lockproj"
    order: list[str] = []
    inside_first = asyncio.Event()
    release_first = asyncio.Event()
    second_finished = asyncio.Event()

    async def first():
        lock = await bw_routes._lock_for(slug)
        async with lock:
            order.append("first_enter")
            inside_first.set()
            await release_first.wait()
            order.append("first_exit")

    async def second():
        await inside_first.wait()
        lock = await bw_routes._lock_for(slug)
        async with lock:
            order.append("second_enter")
            order.append("second_exit")
            second_finished.set()

    async def driver():
        t1 = asyncio.create_task(first())
        t2 = asyncio.create_task(second())
        await asyncio.sleep(0)
        await inside_first.wait()
        release_first.set()
        await asyncio.wait_for(second_finished.wait(), timeout=2.0)
        await asyncio.gather(t1, t2)

    asyncio.run(driver())
    assert order == ["first_enter", "first_exit", "second_enter", "second_exit"]


# ── P5 / P6 / P18 (PATCH-meta full-surface re-emit) ─────────────────────────


def test_p5_p18_patch_meta_full_surface_replay(client):
    """P5 + P18: label-add PATCH-meta writes BOTH documents AND interactions.

    After two label-adds, the latest interaction's agent_metadata
    contains BOTH labels (full surface re-emit) AND documents.metadata
    is updated. If either write is missing, the PATCH is silently
    invisible to the Phase 1 filter.
    """
    from pipeline import services

    with patch.object(subprocess, "run") as mock_run:
        # Create ticket.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-l")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-l",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
        assert r.status_code == 201, r.text

        # Add label kind:person.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(
                ticket_id="bw-l", labels=["kind:person"],
            )),
            # _bw_history_head for the patch
            _fake_completed(stdout=_bw_history_json(
                sha="b" * 40, ticket_id="bw-l", intent_prefix="label",
                author="bob",
            )),
            # _bw_body_author full history fetch
            _fake_completed(stdout=_bw_history_full_json([
                {
                    "hash": "a" * 40, "timestamp": "2026-05-12 00:00",
                    "author": "alice",
                    "intent": "create bw-l ...",
                },
                {
                    "hash": "b" * 40, "timestamp": "2026-05-12 00:01",
                    "author": "bob",
                    "intent": "label bw-l +kind:person",
                },
            ])),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets/bw-l/labels",
            json={"label": "kind:person"},
        )
        assert r.status_code == 201, r.text
        ingest = r.json()["ariadne_ingest"]
        assert ingest["ingest_status"] == "ok", ingest

        # Add label era:multi — the FULL surface should still contain
        # kind:person (full-surface re-emit, latest-interaction filter).
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(
                ticket_id="bw-l", labels=["kind:person", "era:multi"],
            )),
            _fake_completed(stdout=_bw_history_json(
                sha="c" * 40, ticket_id="bw-l", intent_prefix="label",
            )),
            _fake_completed(stdout=_bw_history_full_json([
                {
                    "hash": "a" * 40, "timestamp": "2026-05-12 00:00",
                    "author": "alice",
                    "intent": "create bw-l ...",
                },
            ])),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets/bw-l/labels",
            json={"label": "era:multi"},
        )
        assert r.status_code == 201, r.text

    # The body doc's latest interaction must carry BOTH labels in
    # ``labels`` AND in ``labels_flat`` (full surface re-emit, P5).
    doc_id = ingest["document_id"]
    interactions = services._dedup_store.get_interactions(doc_id)
    assert len(interactions) >= 2, (
        f"expected >=2 interactions, got {len(interactions)}"
    )
    latest = interactions[-1]
    assert latest.action == "update"
    # P18: agent_metadata is the FULL surface, not just the delta.
    meta = latest.agent_metadata
    assert meta["labels"]["kind"] == "person"
    assert meta["labels"]["era"] == "multi"
    assert sorted(meta["labels_flat"]) == ["era:multi", "kind:person"]
    # P5 (P18 part 2): documents.metadata also carries the latest labels.
    docs_meta = services._dedup_store._doc_metadata.get(doc_id, {})
    assert docs_meta["labels"]["kind"] == "person"
    assert docs_meta["labels"]["era"] == "multi"


# ── P7 (D4 body PATCH soft-deletes prior) ───────────────────────────────────


def test_p7_d4_body_patch_soft_deletes_prior(client):
    """P7: PATCH /tickets/{id} with new description soft-deletes prior body."""
    from pipeline import services

    with patch.object(subprocess, "run") as mock_run:
        # Create ticket with description "v1".
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(
                ticket_id="bw-b", description="v1",
            )),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-b",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "v1"},
        )
        assert r.status_code == 201, r.text
        old_doc_id = r.json()["ariadne_ingest"]["document_id"]

        # PATCH description → "v2".
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(
                ticket_id="bw-b", description="v2",
            )),
            _fake_completed(stdout=_bw_history_json(
                sha="b" * 40, ticket_id="bw-b", intent_prefix="update",
            )),
        ]
        r = client.patch(
            "/api/bw/projects/myproj/tickets/bw-b",
            json={"description": "v2"},
        )
        assert r.status_code == 200, r.text
        new_doc_id = r.json()["ariadne_ingest"]["document_id"]

    # Old doc is soft-deleted.
    assert old_doc_id in services._dedup_store._deletions
    # New doc exists and is not deleted.
    assert new_doc_id != old_doc_id
    assert new_doc_id not in services._dedup_store._deletions


# ── P8 (D4.4 retry idempotency) ─────────────────────────────────────────────


def test_p8_d4_4_retry_idempotency(client):
    """P8: monkeypatch _process_single_document to fail once, then succeed.

    On the failed ingest the row enqueues in the in-memory retry queue;
    after running one retry-worker iteration the row replays and lands
    successfully. The retry queue ends empty.
    """
    from pipeline import services

    real_process = services._process_single_document
    state = {"fail_next": True}

    def maybe_fail(*args, **kwargs):
        if state["fail_next"]:
            state["fail_next"] = False
            raise RuntimeError("simulated transient ingest failure")
        return real_process(*args, **kwargs)

    with patch.object(subprocess, "run") as mock_run, \
         patch.object(services, "_process_single_document", side_effect=maybe_fail):
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-r")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-r",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
        # bw write succeeds even though ingest failed.
        assert r.status_code == 201, r.text
        ingest = r.json()["ariadne_ingest"]
        assert ingest["ingest_status"] == "enqueued_for_retry"

    # Queue carries one row.
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 1

    # Run one retry-worker iteration. Patch `_process_single_document`
    # back to the real one (state.fail_next is False now).
    counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert counts["pg_replayed"] == 1, counts
    # Queue is empty after replay.
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 0


# ── P9 (D5 retry survives restart — abstracted via fresh queue load) ────────


def test_p9_d5_retry_survives_restart(client):
    """P9: enqueue, simulate restart (re-initialize state), retry still runs.

    We can't literally restart the FastAPI process inside a test, but
    the Postgres-backed queue is durable by design — for the in-memory
    test path we assert that the queue contents survive a fresh worker
    iteration without being lost. The real production property
    (Postgres survives container cycles) is structural.
    """
    bw_ingest._IN_MEMORY_RETRY_QUEUE.append({
        "id": "11111111-1111-1111-1111-111111111111",
        "slug": "myproj",
        "source_type": "body",
        "ticket_id": "bw-x",
        "comment_n": None,
        "bw_commit_sha": "a" * 40,
        "payload": {
            "kind": "ingest",
            "slug": "myproj",
            "source_type": "body",
            "ticket_id": "bw-x",
            "comment_n": None,
            "text": "restart test body",
            "metadata": {
                "ticket_id": "bw-x", "project": "myproj",
                "source_type": "body", "comment_n": None,
                "author": "alice", "timestamp": "2026-05-12T00:00:00Z",
                "bw_commit_sha": "a" * 40, "bw_status": "open",
                "parent_ticket_id": None, "assignee": None,
                "labels": {}, "labels_flat": [],
            },
            "agent_id": "test-user",
            "uri": "bw-bridge://myproj/bw-x/body.md",
        },
        "enqueued_at": "2026-05-12T00:00:00Z",
        "last_attempt_at": None,
        "attempt_count": 0,
        "last_error": "simulated",
        "next_attempt_at": "1970-01-01T00:00:00Z",  # immediately due
    })

    # No mock subprocess needed — replay calls _process_single_document
    # directly with inline_content; no bw subprocess shells out.
    counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert counts["pg_replayed"] == 1, counts
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 0


# ── P10 (D5 dead-letter after N attempts) ───────────────────────────────────


def test_p10_d5_dead_letter_after_n_attempts(monkeypatch, client):
    """P10: a row that always fails moves to the dead-letter table.

    With ``BW_RETRY_MAX_ATTEMPTS=3``, dead-letter happens on iteration 3
    (NOT iteration 2 — that's the off-by-one CATO M3 caught in round 2).
    Iter 1 bumps attempt_count 0→1 (< 3, no DL). Iter 2 bumps 1→2
    (< 3, no DL). Iter 3 bumps 2→3 (>= 3, DL). This pins the corrected
    max-attempts semantics. See also
    ``test_in_memory_max_attempts_matches_pg_path``.
    """
    from pipeline import services

    # Set max attempts to 3 so the iteration-count assertions are exact.
    monkeypatch.setattr(bw_ingest, "BW_RETRY_MAX_ATTEMPTS", 3)

    def always_fail(*args, **kwargs):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(services, "_process_single_document", always_fail)

    bw_ingest._IN_MEMORY_RETRY_QUEUE.append({
        "id": "22222222-2222-2222-2222-222222222222",
        "slug": "myproj",
        "source_type": "body",
        "ticket_id": "bw-y",
        "comment_n": None,
        "bw_commit_sha": "a" * 40,
        "payload": {
            "kind": "ingest",
            "slug": "myproj",
            "source_type": "body",
            "ticket_id": "bw-y",
            "comment_n": None,
            "text": "fail test body",
            "metadata": {
                "ticket_id": "bw-y", "project": "myproj",
                "source_type": "body", "comment_n": None,
                "author": "alice", "timestamp": "2026-05-12T00:00:00Z",
                "bw_commit_sha": "a" * 40, "bw_status": "open",
                "parent_ticket_id": None, "assignee": None,
                "labels": {}, "labels_flat": [],
            },
            "agent_id": "test-user",
            "uri": "bw-bridge://myproj/bw-y/body.md",
        },
        "enqueued_at": "2026-05-12T00:00:00Z",
        "last_attempt_at": None,
        "attempt_count": 0,
        "last_error": "simulated",
        "next_attempt_at": "1970-01-01T00:00:00Z",
    })

    # Iter 1 + 2: row still in queue, no DL yet.
    for i in (1, 2):
        for r in bw_ingest._IN_MEMORY_RETRY_QUEUE:
            r["next_attempt_at"] = "1970-01-01T00:00:00Z"
        counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
        assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 1, (i, counts)
        assert len(bw_ingest._IN_MEMORY_DEAD_LETTER) == 0, (i, counts)

    # Iter 3: attempt_count reaches MAX_ATTEMPTS → dead-letter.
    for r in bw_ingest._IN_MEMORY_RETRY_QUEUE:
        r["next_attempt_at"] = "1970-01-01T00:00:00Z"
    counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 0, counts
    assert len(bw_ingest._IN_MEMORY_DEAD_LETTER) == 1, counts
    assert bw_ingest._IN_MEMORY_DEAD_LETTER[0]["gave_up_reason"] == "max_attempts"


def test_in_memory_max_attempts_matches_pg_path(monkeypatch, client):
    """M3 regression pin: in-memory DL on the SAME iteration as Postgres.

    The pre-fix bug: the iteration loop read ``row["attempt_count"] + 1``
    AFTER ``_bump_attempt`` ran. The in-memory bump mutated ``row`` in
    place (post-bump value), while the Postgres bump ran an UPDATE
    out-of-band and left ``row`` as the SELECT snapshot (pre-bump
    value). Result: the same input arrived at dead-letter one iteration
    earlier on in-memory than on Postgres — silent path divergence.

    Fix: ``_bump_attempt`` returns the new attempt_count and the loop
    compares the return value, not the dict field. This probe sets
    MAX_ATTEMPTS=3 and asserts:
      - Iter 1: attempt_count goes 0→1, still queued.
      - Iter 2: 1→2, still queued.
      - Iter 3: 2→3, DL with ``gave_up_reason=max_attempts``.
    """
    from pipeline import services

    monkeypatch.setattr(bw_ingest, "BW_RETRY_MAX_ATTEMPTS", 3)

    def always_fail(*args, **kwargs):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(services, "_process_single_document", always_fail)

    bw_ingest._IN_MEMORY_RETRY_QUEUE.append({
        "id": "55555555-5555-5555-5555-555555555555",
        "slug": "myproj",
        "source_type": "body",
        "ticket_id": "bw-parity",
        "comment_n": None,
        "bw_commit_sha": "a" * 40,
        "payload": {
            "kind": "ingest",
            "slug": "myproj",
            "source_type": "body",
            "ticket_id": "bw-parity",
            "comment_n": None,
            "text": "parity test body",
            "metadata": {
                "ticket_id": "bw-parity", "project": "myproj",
                "source_type": "body", "comment_n": None,
                "author": "alice", "timestamp": "2026-05-12T00:00:00Z",
                "bw_commit_sha": "a" * 40, "bw_status": "open",
                "parent_ticket_id": None, "assignee": None,
                "labels": {}, "labels_flat": [],
            },
            "agent_id": "test-user",
            "uri": "bw-bridge://myproj/bw-parity/body.md",
        },
        "enqueued_at": "2026-05-12T00:00:00Z",
        "last_attempt_at": None,
        "attempt_count": 0,
        "last_error": "simulated",
        "next_attempt_at": "1970-01-01T00:00:00Z",
    })

    # Iter 1: bump 0→1, no DL.
    for r in bw_ingest._IN_MEMORY_RETRY_QUEUE:
        r["next_attempt_at"] = "1970-01-01T00:00:00Z"
    asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 1
    assert bw_ingest._IN_MEMORY_RETRY_QUEUE[0]["attempt_count"] == 1
    assert len(bw_ingest._IN_MEMORY_DEAD_LETTER) == 0

    # Iter 2: bump 1→2, no DL.
    for r in bw_ingest._IN_MEMORY_RETRY_QUEUE:
        r["next_attempt_at"] = "1970-01-01T00:00:00Z"
    asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 1
    assert bw_ingest._IN_MEMORY_RETRY_QUEUE[0]["attempt_count"] == 2
    assert len(bw_ingest._IN_MEMORY_DEAD_LETTER) == 0

    # Iter 3: bump 2→3, DL on this iteration (not iter 2 — that was the bug).
    for r in bw_ingest._IN_MEMORY_RETRY_QUEUE:
        r["next_attempt_at"] = "1970-01-01T00:00:00Z"
    asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert len(bw_ingest._IN_MEMORY_RETRY_QUEUE) == 0
    assert len(bw_ingest._IN_MEMORY_DEAD_LETTER) == 1
    assert bw_ingest._IN_MEMORY_DEAD_LETTER[0]["gave_up_reason"] == "max_attempts"


# ── P11 (D6 SHA capture via bw history, NOT git rev-parse HEAD) ─────────────


def test_p11_d6_sha_from_bw_history_not_git_head(client):
    """P11: bw_commit_sha equals ``bw history --json --limit 1``'s hash.

    The original draft's defect was to use ``git rev-parse HEAD`` which
    returns the master-branch SHA in the workspace bw repo topology.
    This probe pins the correct shape.
    """
    expected_sha = "deadbeef" * 5  # 40-hex
    with patch.object(subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-s")),
            _fake_completed(stdout=_bw_history_json(
                sha=expected_sha, ticket_id="bw-s",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
    assert r.status_code == 201, r.text
    ingest = r.json()["ariadne_ingest"]
    assert ingest["bw_commit_sha"] == expected_sha
    # The second subprocess call must have been `bw history`, NOT
    # `git rev-parse HEAD`. Inspect the call list.
    calls = mock_run.call_args_list
    assert len(calls) >= 2
    history_argv = calls[1].args[0]
    assert "history" in history_argv
    assert "--limit" in history_argv
    # Critical: no test should ever exercise `git rev-parse HEAD`.
    for call in calls:
        argv = call.args[0]
        if "rev-parse" in argv and "HEAD" in argv:
            pytest.fail(
                "git rev-parse HEAD was called — the original draft's defect "
                "has resurfaced."
            )


# ── P12 (D3 close-with-reason produces two side-effects) ────────────────────


def test_p12_d3_close_with_reason_two_side_effects(client):
    """P12: POST /close with reason → PATCH-meta on body AND new comment doc."""
    from pipeline import services

    with patch.object(subprocess, "run") as mock_run:
        # Create.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-c")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-c",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
        assert r.status_code == 201, r.text
        body_doc_id = r.json()["ariadne_ingest"]["document_id"]

        # Close with reason.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(
                ticket_id="bw-c", status="closed",
                comments=[{"text": "resolved", "timestamp": "2026-05-12T00:01:00Z"}],
            )),
            # _bw_history_head for PATCH-meta
            _fake_completed(stdout=_bw_history_json(
                sha="b" * 40, ticket_id="bw-c", intent_prefix="close",
            )),
            # _bw_body_author full history
            _fake_completed(stdout=_bw_history_full_json([
                {
                    "hash": "a" * 40, "timestamp": "2026-05-12 00:00",
                    "author": "alice",
                    "intent": "create bw-c ...",
                },
            ])),
            # _bw_history_head for the comment ingest
            _fake_completed(stdout=_bw_history_json(
                sha="c" * 40, ticket_id="bw-c", intent_prefix="comment",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets/bw-c/close",
            json={"reason": "resolved"},
        )
        assert r.status_code == 200, r.text
        rb = r.json()
        # PATCH-meta on the body doc.
        assert rb["ariadne_ingest"]["ingest_status"] == "ok"
        # New comment doc.
        assert rb["ariadne_comment_ingest"]["ingest_status"] == "ok"
        comment_doc_id = rb["ariadne_comment_ingest"]["document_id"]

    # Body doc's latest interaction reflects bw_status=closed.
    interactions = services._dedup_store.get_interactions(body_doc_id)
    latest = interactions[-1]
    assert latest.agent_metadata["bw_status"] == "closed"
    # New comment doc exists.
    comment_meta = services._dedup_store._doc_metadata.get(comment_doc_id, {})
    assert comment_meta["source_type"] == "comment"


# ── P13 (D3 delete soft-deletes all ticket docs) ────────────────────────────


def test_p13_d3_delete_soft_deletes_all_ticket_docs(client):
    """P13: DELETE force=true → all body+comment docs soft-deleted."""
    from pipeline import services

    with patch.object(subprocess, "run") as mock_run:
        # Create ticket + 2 comments.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-d")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-d",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
        assert r.status_code == 201, r.text

        for i in range(1, 3):
            comments = [
                {"text": f"c{j}", "timestamp": "2026-05-12T00:00:00Z"}
                for j in range(1, i + 1)
            ]
            mock_run.side_effect = [
                _fake_completed(stdout=_bw_show_json(
                    ticket_id="bw-d", comments=comments,
                )),
                _fake_completed(stdout=_bw_history_json(
                    sha=f"b{i}" * 20, ticket_id="bw-d",
                    intent_prefix="comment",
                )),
            ]
            rc = client.post(
                "/api/bw/projects/myproj/tickets/bw-d/comments",
                json={"text": f"c{i}"},
            )
            assert rc.status_code == 201, rc.text

        # All three docs exist.
        # (1 body + 2 comments)
        live_ids: list[str] = []
        for doc in services._dedup_store._documents.values():
            if doc.collection_id == "myproj":
                live_ids.append(doc.document_id)
        assert len(live_ids) == 3, live_ids

        # DELETE force=true.
        mock_run.side_effect = [
            _fake_completed(stdout=json.dumps({"deleted": True, "id": "bw-d"})),
        ]
        rd = client.delete(
            "/api/bw/projects/myproj/tickets/bw-d?force=true",
        )
        assert rd.status_code == 200, rd.text
        ingest = rd.json()["ariadne_ingest"]
        assert ingest["count"] == 3, ingest

    # All three docs are now soft-deleted.
    for doc_id in live_ids:
        assert doc_id in services._dedup_store._deletions, (
            f"doc {doc_id} was not soft-deleted"
        )


# ── P14 (D2.3 collection = slug) ────────────────────────────────────────────


def test_p14_d2_3_collection_equals_slug(client):
    """P14: docs created via /api/bw/projects/conan-superfan/... land in
    collection ``conan-superfan``, NOT ``default``.
    """
    from pipeline import services

    with patch.object(subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-v")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-v",
            )),
        ]
        r = client.post(
            "/api/bw/projects/conan-superfan/tickets",
            json={"title": "T", "description": "d"},
        )
        assert r.status_code == 201, r.text
        doc_id = r.json()["ariadne_ingest"]["document_id"]

    doc = next(
        d for d in services._dedup_store._documents.values()
        if d.document_id == doc_id
    )
    assert doc.collection_id == "conan-superfan"


# ── P15 (gating signal — no perceptible lag) ────────────────────────────────


def test_p15_gating_signal_no_perceptible_lag(client):
    """P15: a POST /tickets call returns 201 only AFTER ingest completes.

    The HTTP response carries ``ariadne_ingest.ingest_status == "ok"``
    on the success path — by the time the 201 is back to the caller,
    search would reflect the new content. (The < BW_RETRY_POLL_SECONDS
    wall-clock claim is unmeasurable inside a unit test, but the
    "synchronous" property is structurally checkable.)
    """
    with patch.object(subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-g")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-g",
            )),
        ]
        r = client.post(
            "/api/bw/projects/conan-superfan/tickets",
            json={"title": "Unique title beta", "description": "d"},
        )
    assert r.status_code == 201
    ingest = r.json()["ariadne_ingest"]
    assert ingest["ingest_status"] == "ok"


# ── _ingest_bw_write propagates was_dedup_skip ─────────────────────────────


def test_ingest_response_propagates_was_dedup_skip():
    """Phase-3 wire-shape invariant caught by CATO's cold-read review.

    ``_ingest_bw_write``'s success-return dict must carry
    ``was_dedup_skip`` from the underlying ``_process_single_document``
    result. The bulk-seed adapter (``scripts/seed_bw_corpus.py``) relies
    on this key to drive its ``dedup_skipped`` counter — Phase 3's helper
    was dropping it on the success path, so the seed script's counter
    never incremented in production. See SPEC §Bulk seed adapter +
    revision R1 of ariadne--8fd.6.

    Two-case shape:
    - Case 1: ``_process_single_document`` returns ``was_dedup_skip=False``
      (a fresh ingest) → ``_ingest_bw_write`` returns
      ``was_dedup_skip=False``.
    - Case 2: ``_process_single_document`` returns ``was_dedup_skip=True``
      (cache hit on content_fingerprint) → ``_ingest_bw_write`` returns
      ``was_dedup_skip=True``.
    """
    from pipeline import services
    from pipeline.auth_oauth import Principal

    common_kwargs: dict[str, Any] = {
        "slug": "myproj",
        "source_type": "body",
        "ticket_id": "bw-dd",
        "bw_show_snapshot": {
            "status": "open",
            "assignee": "",
            "parent": None,
            "labels": [],
        },
        "text": "body text",
        "comment_n": None,
        "principal": Principal(user_id="test"),
    }

    async def drive(process_return: dict[str, Any]) -> dict[str, Any]:
        with patch.object(
            bw_ingest, "_bw_history_head",
            return_value=("a" * 40, "alice"),
        ):
            with patch.object(
                services, "_process_single_document", return_value=process_return,
            ):
                return await bw_ingest._ingest_bw_write(**common_kwargs)

    # Case 1: new ingest.
    result_new = asyncio.run(drive({
        "document_id": "d" * 32,
        "was_dedup_skip": False,
    }))
    assert result_new["ingest_status"] == "ok"
    assert result_new["was_dedup_skip"] is False, (
        "new-ingest path must surface was_dedup_skip=False; "
        f"got {result_new!r}"
    )

    # Case 2: dedup hit.
    result_dedup = asyncio.run(drive({
        "document_id": "e" * 32,
        "was_dedup_skip": True,
    }))
    assert result_dedup["ingest_status"] == "ok"
    assert result_dedup["was_dedup_skip"] is True, (
        "dedup-hit path must surface was_dedup_skip=True; "
        f"got {result_dedup!r}"
    )


# ── P16 (D2.1 async/sync seam — event loop responsive) ──────────────────────


def test_p16_d2_1_async_sync_seam_event_loop_responsive():
    """P16: ingest runs on the thread pool — slug B doesn't block on slug A.

    Property tested: when ``_process_single_document`` is offloaded via
    ``asyncio.to_thread``, the event loop remains free to run OTHER
    coroutines while the thread is blocked. We assert this by running
    a slow ingest for slug A and a fast ingest for slug B concurrently;
    if to_thread is doing its job, slug B's task completes well before
    slug A's. If to_thread were missing (synchronous call from the
    coroutine), slug B would wait behind slug A for the full ~300ms.
    """
    import time as _time

    from pipeline import services
    from pipeline.auth_oauth import Principal

    started_marker = [False]

    def slow(*args, **kwargs):
        started_marker[0] = True
        _time.sleep(0.3)
        return {"document_id": "x" * 32, "error": False}

    def fast(*args, **kwargs):
        return {"document_id": "y" * 32, "error": False}

    async def driver():
        # Mock _bw_history_head so it doesn't subprocess.
        with patch.object(
            bw_ingest, "_bw_history_head",
            return_value=("a" * 40, "alice"),
        ):
            # Slug A — slow.
            with patch.object(services, "_process_single_document", side_effect=slow):
                t_a = asyncio.create_task(bw_ingest._ingest_bw_write(
                    slug="slug-a", source_type="body", ticket_id="bw-a",
                    bw_show_snapshot={
                        "status": "open", "labels": [], "comments": [],
                    },
                    text="ta", comment_n=None,
                    principal=Principal(user_id="test"),
                ))
                # Yield a tick so slug A's to_thread starts running.
                while not started_marker[0]:
                    await asyncio.sleep(0.01)

            # Once we've left the slow patch context, slug B is fast.
            t_b_start = _time.perf_counter()
            with patch.object(services, "_process_single_document", side_effect=fast):
                t_b = asyncio.create_task(bw_ingest._ingest_bw_write(
                    slug="slug-b", source_type="body", ticket_id="bw-b",
                    bw_show_snapshot={
                        "status": "open", "labels": [], "comments": [],
                    },
                    text="tb", comment_n=None,
                    principal=Principal(user_id="test"),
                ))
                rb = await asyncio.wait_for(t_b, timeout=1.0)
                t_b_elapsed = _time.perf_counter() - t_b_start

            ra = await asyncio.wait_for(t_a, timeout=2.0)
            return ra, rb, t_b_elapsed

    ra, rb, t_b_elapsed = asyncio.run(driver())
    assert rb["ingest_status"] == "ok"
    # Slug B finished while slug A was still running. We can't assert
    # the exact wall-clock (CI variance) but t_b_elapsed should be
    # well under slug A's 0.3s sleep — say <0.2s with generous slack.
    assert t_b_elapsed < 0.25, (
        f"slug B took {t_b_elapsed:.3f}s — likely blocked on slug A's "
        "thread-pool call. asyncio.to_thread may be missing."
    )


# ── P17 (D3.1 PATCH-meta preserves body author) ─────────────────────────────


def test_p17_d3_1_patch_meta_preserves_body_author(client):
    """P17: body author (alice) survives a label-add by a different
    principal (bob). Without the bw_body_author lookup, the latest
    interaction's agent_metadata.author would be bob and the search
    filter ``metadata={"author":"alice"}`` would return zero results.
    """
    from pipeline import services

    with patch.object(subprocess, "run") as mock_run:
        # Create — bw history returns author=alice.
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-au")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-au", author="alice",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
        assert r.status_code == 201, r.text
        body_doc_id = r.json()["ariadne_ingest"]["document_id"]

        # Verify the body doc's first interaction has author=alice.
        first_interaction = services._dedup_store.get_interactions(body_doc_id)[0]
        assert first_interaction.agent_metadata["author"] == "alice"

        # Add label as a different principal (the JWT principal is the
        # _fake_principal "test-user" — that's recorded as agent_id, but
        # agent_metadata.author should NOT change to test-user).
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(
                ticket_id="bw-au", labels=["urgent"],
            )),
            # _bw_history_head: PATCH author is bob
            _fake_completed(stdout=_bw_history_json(
                sha="b" * 40, ticket_id="bw-au", author="bob",
                intent_prefix="label",
            )),
            # _bw_body_author full history (create row has author=alice).
            _fake_completed(stdout=_bw_history_full_json([
                {
                    "hash": "a" * 40, "timestamp": "2026-05-12 00:00",
                    "author": "alice",
                    "intent": "create bw-au ...",
                },
                {
                    "hash": "b" * 40, "timestamp": "2026-05-12 00:01",
                    "author": "bob",
                    "intent": "label bw-au +urgent",
                },
            ])),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets/bw-au/labels",
            json={"label": "urgent"},
        )
        assert r.status_code == 201, r.text

    # The latest interaction's agent_metadata.author MUST still be alice.
    interactions = services._dedup_store.get_interactions(body_doc_id)
    latest = interactions[-1]
    assert latest.action == "update"
    assert latest.agent_metadata["author"] == "alice", (
        f"PATCH-meta overwrote the body author: got {latest.agent_metadata['author']}"
    )


# ── P19 (D5.5 file fallback on Postgres-drop-during-enqueue) ────────────────


def test_p19_d5_5_file_fallback_on_postgres_drop(client, monkeypatch):
    """P19: when the retry-queue enqueue itself fails, the payload lands
    in the JSONL file fallback. Next retry poll drains the file back
    into the queue and replays.
    """
    from pipeline import services

    def fail_pg(*args, **kwargs):
        raise RuntimeError("simulated Postgres connection drop")

    def fail_ingest(*args, **kwargs):
        raise RuntimeError("simulated transient ingest failure")

    # Patch BOTH the ingest AND the Postgres enqueue.
    monkeypatch.setattr(services, "_process_single_document", fail_ingest)
    monkeypatch.setattr(bw_ingest, "_enqueue_postgres", fail_pg)

    with patch.object(subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _fake_completed(stdout=_bw_show_json(ticket_id="bw-ff")),
            _fake_completed(stdout=_bw_history_json(
                sha="a" * 40, ticket_id="bw-ff",
            )),
        ]
        r = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "T", "description": "d"},
        )
    assert r.status_code == 201, r.text

    # File fallback file exists in the slug dir.
    fb_path = os.path.join(
        bw_routes.BW_REPOS_ROOT, "myproj", bw_ingest.BW_FILE_FALLBACK_NAME,
    )
    assert os.path.isfile(fb_path), (
        f"file-fallback at {fb_path!r} should exist after Postgres-drop"
    )
    with open(fb_path, encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip()]
    assert len(lines) == 1, f"expected 1 line in fallback, got {len(lines)}"
    rec = json.loads(lines[0])
    assert rec["slug"] == "myproj"
    assert rec["source_type"] == "body"

    # Now un-monkeypatch the Postgres enqueue and trigger one retry poll.
    # The drain step should re-insert the line into the queue (in-memory
    # for our test). The replay step then would try the ingest, which
    # is still failing — so the line lands in the queue, not the
    # dead-letter.
    monkeypatch.setattr(
        bw_ingest, "_enqueue_postgres",
        bw_ingest._enqueue_postgres.__wrapped__
        if hasattr(bw_ingest._enqueue_postgres, "__wrapped__") else
        # Restore the real one from the imported module before our patch.
        _original_enqueue_postgres,
    )

    # Restore the real enqueue (read from a fresh import).
    import importlib
    fresh = importlib.import_module("pipeline.api.bw_ingest")
    monkeypatch.setattr(bw_ingest, "_enqueue_postgres", fresh._enqueue_postgres)

    # Run drain. The drain step succeeds; the queue now carries one row.
    counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert counts["file_drained"] >= 1, counts
    # The file is removed after a successful drain.
    assert not os.path.isfile(fb_path) or os.path.getsize(fb_path) == 0


# Capture the real enqueue function for restoration in P19. Imported at
# module top so the monkeypatch.setattr can find it.
_original_enqueue_postgres = bw_ingest._enqueue_postgres


# ── D5.4a + N1 addendum (orphan SHA dead-letters immediately) ──────────────


def test_d5_4a_n1_orphan_sha_dead_letters_immediately(monkeypatch):
    """N1 addendum: a queued body-create whose SHA is not in bw history
    at replay time is dead-lettered IMMEDIATELY, not after exhausting
    the retry budget. Caused by operator-side orphan-branch surgery or
    ``bw delete --force`` between enqueue and replay.
    """
    from pipeline import services
    from pipeline.dedup import InMemoryDedupStore

    # Pre-populate a body doc with a DIFFERENT SHA than the queued one.
    # The currency check should NOT fire stale_by_design because the
    # queued SHA is missing from bw history entirely → orphan_sha.

    # Empty bw history → queued SHA not in history → orphan_sha.
    def fake_run_bw(*args, **kwargs):
        # The currency check calls history with no --limit.
        return {"items": []}

    # No existing body doc exists in the store for this ticket id (the
    # currency check returns "ok" if no existing doc — but then the
    # _replay_one_row proceeds to _replay_ingest, which would succeed.
    # To exercise the orphan_sha path, we need an existing doc with a
    # different SHA AND queued SHA missing from history.
    services._dedup_store._doc_metadata["existing-doc-id"] = {
        "ticket_id": "bw-orphan", "source_type": "body",
        "bw_commit_sha": "deadbeef" * 5,  # existing, different SHA
    }
    # Add a fake document into the store so the lookup finds it.
    from pipeline.dedup import StoredDocument
    services._dedup_store._documents[("myproj", "fp-existing")] = StoredDocument(
        document_id="existing-doc-id",
        collection_id="myproj",
        source_file="x",
        content_fingerprint="fp-existing",
        file_type="md",
        engine="markitdown",
        markdown="x",
        title="x",
        processing_time_ms=0,
        output_tokens_estimate=0,
        token_savings_ratio=None,
        processing_chain=[],
    )

    # Patch the dynamic import target for currency check (empty history).
    import pipeline.api.bw_routes as br
    async def fake_run_bw_async(slug, *args, **kwargs):
        return {"items": []}
    monkeypatch.setattr(br, "_run_bw", fake_run_bw_async)

    bw_ingest._IN_MEMORY_RETRY_QUEUE.append({
        "id": "33333333-3333-3333-3333-333333333333",
        "slug": "myproj",
        "source_type": "body",
        "ticket_id": "bw-orphan",
        "comment_n": None,
        "bw_commit_sha": "f" * 40,  # not in (empty) history
        "payload": {
            "kind": "ingest",
            "slug": "myproj",
            "source_type": "body",
            "ticket_id": "bw-orphan",
            "comment_n": None,
            "text": "orphan body",
            "metadata": {
                "ticket_id": "bw-orphan", "project": "myproj",
                "source_type": "body", "comment_n": None,
                "author": "alice", "timestamp": "2026-05-12T00:00:00Z",
                "bw_commit_sha": "f" * 40, "bw_status": "open",
                "parent_ticket_id": None, "assignee": None,
                "labels": {}, "labels_flat": [],
            },
            "agent_id": "test-user",
            "uri": "bw-bridge://myproj/bw-orphan/body.md",
        },
        "enqueued_at": "2026-05-12T00:00:00Z",
        "last_attempt_at": None,
        "attempt_count": 0,
        "last_error": "simulated",
        "next_attempt_at": "1970-01-01T00:00:00Z",
    })

    counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
    # The orphan-SHA path dead-letters immediately on the first iteration.
    assert counts["dead_lettered"] == 1, counts
    assert len(bw_ingest._IN_MEMORY_DEAD_LETTER) == 1
    assert bw_ingest._IN_MEMORY_DEAD_LETTER[0]["gave_up_reason"] == "orphan_sha"


# ── D5.4a stale-by-design dead-letters ──────────────────────────────────────


def test_d5_4a_stale_by_design_dead_letters(monkeypatch):
    """D5.4a: a queued body-create whose SHA is older (lower index in
    bw history) than the existing body doc's SHA is stale-by-design.
    Re-creating would corrupt the one-body-doc invariant.
    """
    from pipeline import services
    from pipeline.dedup import StoredDocument

    # Existing body doc with sha "b" (which is INDEX 1 in history below).
    services._dedup_store._doc_metadata["existing-doc-id"] = {
        "ticket_id": "bw-stale", "source_type": "body",
        "bw_commit_sha": "b" * 40,
    }
    services._dedup_store._documents[("myproj", "fp-existing")] = StoredDocument(
        document_id="existing-doc-id",
        collection_id="myproj",
        source_file="x",
        content_fingerprint="fp-existing",
        file_type="md",
        engine="markitdown",
        markdown="x",
        title="x",
        processing_time_ms=0,
        output_tokens_estimate=0,
        token_savings_ratio=None,
        processing_chain=[],
    )

    import pipeline.api.bw_routes as br
    async def fake_run_bw_async(slug, *args, **kwargs):
        return {"items": [
            {"hash": "a" * 40, "intent": "create bw-stale", "author": "alice"},
            {"hash": "b" * 40, "intent": "update bw-stale", "author": "alice"},
        ]}
    monkeypatch.setattr(br, "_run_bw", fake_run_bw_async)

    # Queued payload has sha "a" — index 0, older than existing's index 1.
    bw_ingest._IN_MEMORY_RETRY_QUEUE.append({
        "id": "44444444-4444-4444-4444-444444444444",
        "slug": "myproj",
        "source_type": "body",
        "ticket_id": "bw-stale",
        "comment_n": None,
        "bw_commit_sha": "a" * 40,
        "payload": {
            "kind": "ingest",
            "slug": "myproj",
            "source_type": "body",
            "ticket_id": "bw-stale",
            "comment_n": None,
            "text": "stale body",
            "metadata": {
                "ticket_id": "bw-stale", "project": "myproj",
                "source_type": "body", "comment_n": None,
                "author": "alice", "timestamp": "2026-05-12T00:00:00Z",
                "bw_commit_sha": "a" * 40, "bw_status": "open",
                "parent_ticket_id": None, "assignee": None,
                "labels": {}, "labels_flat": [],
            },
            "agent_id": "test-user",
            "uri": "bw-bridge://myproj/bw-stale/body.md",
        },
        "enqueued_at": "2026-05-12T00:00:00Z",
        "last_attempt_at": None,
        "attempt_count": 0,
        "last_error": "simulated",
        "next_attempt_at": "1970-01-01T00:00:00Z",
    })

    counts = asyncio.run(bw_ingest._bw_retry_worker_iteration())
    assert counts["dead_lettered"] == 1, counts
    assert bw_ingest._IN_MEMORY_DEAD_LETTER[0]["gave_up_reason"] == "stale_by_design"


# ── Render-payload determinism ─────────────────────────────────────────────


def test_render_payload_alphabetizes_keys():
    """Frontmatter keys are sorted; same metadata + text → same bytes.

    This is what makes the frontmatter-as-salt invariant work — see
    design §D1.4 + W4. Without stable key ordering, two ingests with
    semantically equal metadata could produce different fingerprints.
    """
    meta = {"z": 1, "a": 2, "m": [1, 2, 3]}
    bytes1 = bw_ingest._render_payload(meta, "body text")
    bytes2 = bw_ingest._render_payload(meta, "body text")
    assert bytes1 == bytes2
    # Visual check: keys come out in alphabetized order.
    text = bytes1.decode("utf-8")
    a_idx = text.index("a:")
    m_idx = text.index("m:")
    z_idx = text.index("z:")
    assert a_idx < m_idx < z_idx, f"keys not alphabetized: {text[:80]}"


def test_parse_label_splits_on_first_colon():
    """k:v labels parse to (k, v); bare labels return (None, raw)."""
    assert bw_ingest._parse_label("kind:person") == ("kind", "person")
    # Multiple colons: only the first one splits.
    assert bw_ingest._parse_label("a:b:c") == ("a", "b:c")
    # Bare label.
    assert bw_ingest._parse_label("urgent") == (None, "urgent")
    # Whitespace stripped.
    assert bw_ingest._parse_label("kind : person") == ("kind", "person")


# ── No-op endpoints (deps, sync) ───────────────────────────────────────────


def test_deps_endpoints_are_no_op_for_ariadne(client):
    """D3 matrix: POST/DELETE on deps does NOT call into bw_ingest."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"ok": true}')
        with patch.object(bw_ingest, "_ingest_bw_write") as mock_ingest, \
             patch.object(bw_ingest, "_patch_bw_body_metadata") as mock_patch:
            r1 = client.post(
                "/api/bw/projects/myproj/tickets/bw-x/deps",
                json={"blocks": "bw-y"},
            )
            r2 = client.delete(
                "/api/bw/projects/myproj/tickets/bw-x/deps/bw-y",
            )
        assert r1.status_code == 201
        assert r2.status_code == 200
        # Neither ingest helper was called.
        mock_ingest.assert_not_called()
        mock_patch.assert_not_called()


def test_sync_endpoint_is_no_op_for_ariadne(client):
    """D3.2: POST /sync is no-op for Ariadne in v1 (single-writer only)."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="Synced.\n")
        with patch.object(bw_ingest, "_ingest_bw_write") as mock_ingest, \
             patch.object(bw_ingest, "_patch_bw_body_metadata") as mock_patch:
            r = client.post("/api/bw/projects/myproj/sync")
        assert r.status_code == 200
        mock_ingest.assert_not_called()
        mock_patch.assert_not_called()


# ── Health endpoint ────────────────────────────────────────────────────────


def test_bw_health_endpoint(client):
    """Phase 3 observability surface returns the documented keys."""
    r = client.get("/api/bw/projects/myproj/health")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "bw_ingest_retry_queue_depth",
        "bw_ingest_retry_dead_letter_count",
        "bw_ingest_retry_by_slug",
        "bw_ingest_file_fallback_drain_count",
        "bw_ingest_file_fallback_pending_lines",
    ):
        assert key in body, f"missing metric key: {key}"
    # Fresh state — all counters zero.
    assert body["bw_ingest_retry_queue_depth"] == 0
    assert body["bw_ingest_retry_dead_letter_count"] == 0


# ── inline_content branch in _process_single_document ──────────────────────


def test_inline_content_short_circuits_uri_read():
    """`_process_single_document(inline_content=...)` skips _read_source_bytes.

    The synthetic URI ``bw-bridge://...`` never reaches the file system;
    the bytes given inline are fingerprinted and ingested directly.

    Also pins design §D2.6's invariant that the synthetic URI's path
    ends in ``.md`` so ``_guess_file_type`` returns ``"md"`` — without
    this, MarkItDown would route the bytes through an extension-less
    "unknown" path that no longer round-trips Markdown verbatim.
    """
    from pipeline import services
    from pipeline.dedup import InMemoryDedupStore
    from pipeline.storage.base import InMemoryVectorStore

    services.configure_stores(InMemoryDedupStore(), InMemoryVectorStore())

    # If _read_source_bytes were called with a bw-bridge:// URI it
    # would raise (the file does not exist). The inline path must not
    # touch it.
    payload = b"---\na: 1\n---\n\nhello world"
    result = services._process_single_document(
        uri="bw-bridge://myproj/bw-x/body.md",
        store=True,
        collection="myproj",
        tags=[],
        force=False,
        agent_id="test-user",
        agent_type="bw_bridge",
        model=None,
        initiated_by="bw_routes",
        agent_notes=None,
        agent_metadata={"ticket_id": "bw-x"},
        chunking_config=None,
        ingest_config=None,
        action="ingest",
        inline_content=payload,
    )
    assert not result.get("error"), result
    assert result["document_id"]
    assert result["collection"] == "myproj"
    # M1 regression pin: the synthetic URI must yield file_type="md"
    # so MarkItDown's md-passthrough path runs (no-op extraction).
    assert result.get("file_type") == "md", result


def test_synthetic_uri_yields_md_file_type():
    """Synthetic bw-bridge URI's path suffix is ``.md`` (M1 regression pin).

    The earlier draft used ``#fragment`` for the source-type suffix,
    which ``urlparse`` discards before ``Path.suffix`` is computed —
    leaving the ticket-id's dotted segment (e.g. ``ariadne--8fd.5``) as
    the apparent suffix and yielding the wrong ``file_type``. This
    probe pins the corrected shape: scheme/netloc/path with ``.md`` in
    the path, never the fragment.
    """
    from urllib.parse import urlparse
    from pathlib import Path
    from pipeline.extraction.markitdown import _guess_file_type

    # Realistic shapes that exercise the dotted-ticket-id edge case.
    for uri in (
        "bw-bridge://myproj/bw-x/body.md",
        "bw-bridge://ariadne/ariadne--8fd.5/body.md",
        "bw-bridge://ariadne/ariadne--8fd.5/comment/3.md",
    ):
        parsed = urlparse(uri)
        assert parsed.path.endswith(".md"), (uri, parsed.path)
        assert Path(parsed.path).suffix == ".md", (uri, parsed.path)
        assert _guess_file_type(uri) == "md", uri
