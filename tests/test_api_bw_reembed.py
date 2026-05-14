"""Tests for the in-place re-embed mechanism — `POST /reembed` (ariadne--uuo.5).

Exercises the snapshot-driven ingest core (`_ingest_bw_snapshot`), the
per-slot doc-id resolver (`_resolve_ticket_doc_id_map`), the orphan
detection pass (`_detect_orphan_tickets`), and the re-embed orchestrator
(`_reembed_tickets`) wired through the `POST /api/bw/projects/{slug}/reembed`
route.

The 8 acceptance criteria from design §9 `uuo-5` map 1:1 to the
`test_ac<N>_*` functions below.

Strategy: the orchestrator reads the on-disk bw repo via
`pipeline.api.bw_repo` and reads SHA/author via `_bw_history_head` /
`_bw_body_author` (subprocess). Tests monkeypatch those four seams with
fixture data so the *real* `_process_single_document` + the in-memory
dedup/vector stores run end-to-end — the same in-memory path the rest of
the bw-ingest suite uses. The pre-uuo "polluted corpus" pre-state is
seeded by calling `_process_single_document` directly with
`inline_content == inline_embed_content` (the byte-identical-inputs shape
that was the shipped behavior before uuo-1/uuo-2 decoupled them).
"""

from __future__ import annotations

import asyncio
import tempfile
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.api import bw_ingest, bw_repo, bw_routes
from pipeline.api.bw_routes import router

from tests.conftest import override_auth


# ── Test infrastructure ─────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Reset module-level state before each test (mirrors test_api_bw_ingest)."""
    monkeypatch.setattr(bw_routes, "BW_BINARY", "/usr/local/bin/bw")
    tmp_root = tempfile.mkdtemp(prefix="bw-reembed-test-")
    monkeypatch.setattr(bw_routes, "BW_REPOS_ROOT", tmp_root)
    # No real .git tree is materialized — disable the initialized-repo
    # guard so _resolve_repo_path returns the tmp path.
    monkeypatch.setattr(bw_routes, "BW_REQUIRE_INITIALIZED_REPO", False)
    monkeypatch.setattr(bw_routes, "_backup_skip_count", {})
    monkeypatch.setattr(bw_routes, "_slug_locks", {})

    bw_ingest._IN_MEMORY_RETRY_QUEUE.clear()
    bw_ingest._IN_MEMORY_DEAD_LETTER.clear()
    monkeypatch.setattr(bw_ingest, "_file_fallback_drain_count", 0)

    from pipeline import services
    from pipeline.dedup import InMemoryDedupStore
    from pipeline.storage.base import InMemoryVectorStore
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())

    yield

    import shutil
    shutil.rmtree(tmp_root, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(_build_app())


# ── bw-repo + history fixture wiring ────────────────────────────────────────


def _ticket(
    *,
    ticket_id: str,
    title: str = "Fixture Ticket",
    description: str = "the body description text",
    ttype: str = "task",
    status: str = "open",
    comments: list[dict] | None = None,
) -> dict[str, Any]:
    """A `bw show`-shaped on-disk ticket dict (un-nested)."""
    return {
        "id": ticket_id,
        "title": title,
        "description": description,
        "type": ttype,
        "priority": 2,
        "status": status,
        "labels": [],
        "parent": "",
        "assignee": "",
        "blocked_by": [],
        "blocks": [],
        "created": "2026-05-12T00:00:00Z",
        "updated_at": "2026-05-12T00:00:00Z",
        "comments": comments or [],
    }


def _wire_repo(monkeypatch, tickets: dict[str, dict[str, Any]]) -> None:
    """Monkeypatch the on-disk bw-repo + history seams with fixture data.

    `tickets` maps ticket_id -> ticket dict. `list_ticket_ids` returns the
    sorted keys; `read_ticket` returns the dict (or raises BwRepoError for
    an unknown id). `_bw_history_head` / `_bw_body_author` return stable
    fixture values.
    """
    def _list(repo, *, timeout=None):
        return sorted(tickets.keys())

    def _read(repo, ticket_id, *, timeout=None):
        if ticket_id not in tickets:
            raise bw_repo.BwRepoError(f"no such ticket: {ticket_id}")
        return tickets[ticket_id]

    async def _head(slug, ticket_id):
        return ("f" * 40, "fixture-author")

    async def _body_author(slug, ticket_id):
        return "fixture-author"

    monkeypatch.setattr(bw_repo, "list_ticket_ids", _list)
    monkeypatch.setattr(bw_repo, "read_ticket", _read)
    monkeypatch.setattr(bw_ingest, "_bw_history_head", _head)
    monkeypatch.setattr(bw_ingest, "_bw_body_author", _body_author)


def _seed_polluted_doc(
    *,
    slug: str,
    ticket_id: str,
    source_type: str,
    comment_n: int | None,
    text: str,
) -> str:
    """Seed a pre-uuo 'polluted' doc into the in-memory stores.

    Calls `_process_single_document` with `inline_content` ==
    `inline_embed_content` == the YAML-frontmatter-salted payload — the
    byte-identical-two-inputs shape that was the shipped behavior before
    uuo-1/uuo-2 decoupled them. The resulting chunk text therefore carries
    the `---` frontmatter fence (the pollution uuo-2 strips). Returns the
    seeded `documents.id`.
    """
    from pipeline.services import _process_single_document

    metadata = {
        "ticket_id": ticket_id,
        "project": slug,
        "source_type": source_type,
        "comment_n": comment_n,
        "author": "old-author",
        "timestamp": "2026-05-10T00:00:00Z",
        "bw_commit_sha": "a" * 40,
        "bw_status": "open",
        "parent_ticket_id": None,
        "assignee": None,
        "labels": {},
        "labels_flat": [],
        # NOTE: deliberately NO ticket_title / ticket_type — the pre-uuo
        # corpus did not carry them, so the re-embed produces a *different*
        # fingerprint (design §3.3).
    }
    polluted = bw_ingest._render_payload(metadata, text)
    suffix = f"/{comment_n}" if comment_n is not None else ""
    uri = f"bw-bridge://{slug}/{ticket_id}/{source_type}{suffix}.md"
    result = _process_single_document(
        uri=uri,
        store=True,
        collection=slug,
        tags=[],
        force=False,
        agent_id="seed",
        agent_type="bw_bridge",
        model=None,
        initiated_by="test_seed",
        agent_notes=None,
        agent_metadata=metadata,
        chunking_config=None,
        ingest_config=None,
        action="ingest",
        inline_content=polluted,
        inline_embed_content=polluted,  # pre-uuo: same bytes for both
    )
    assert not result.get("error"), result
    return result["document_id"]


# ── Store-inspection helpers ────────────────────────────────────────────────


def _all_chunks(slug: str) -> list:
    from pipeline import services
    return [
        c for c in services._vector_store._chunks.values()
        if c.collection_id == slug
    ]


def _live_doc_ids(slug: str) -> set[str]:
    from pipeline import services
    store = services._dedup_store
    return {
        d.document_id for d in store._documents.values()
        if d.collection_id == slug and d.document_id not in store._deletions
    }


def _doc_fingerprint(doc_id: str) -> str | None:
    from pipeline import services
    for d in services._dedup_store._documents.values():
        if d.document_id == doc_id:
            return d.content_fingerprint
    return None


def _orphaned_chunk_count(slug: str) -> int:
    """Chunks whose document_id has no live documents row — must be 0."""
    live = _live_doc_ids(slug)
    return sum(1 for c in _all_chunks(slug) if c.document_id not in live)


# ── AC1 — the three-conjunct re-embed invariant (design §6.4.1) ─────────────


def test_ac1_three_conjunct_reembed_invariant(client, monkeypatch):
    """AC1: POST /reembed upholds the §6.4.1 three-conjunct invariant.

    (a) zero orphaned chunks, (b) every chunk derives from clean content
    (no `---` frontmatter fence), (c) post-reembed chunk count <=
    pre-reembed count; documents.id stable; bw repo untouched.
    """
    slug = "uuoproj"
    tid = "uuo-fix-001"
    # Pre-state: a body + 2 comments seeded with pre-uuo polluted content.
    body_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="body", comment_n=None,
        text="the body description text",
    )
    c1_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="comment", comment_n=1,
        text="first comment body",
    )
    c2_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="comment", comment_n=2,
        text="second comment body",
    )
    pre_chunk_count = len(_all_chunks(slug))
    assert pre_chunk_count > 0
    # Pre-state pollution: at least one chunk carries the `---` fence.
    assert any(c.text.lstrip().startswith("---") for c in _all_chunks(slug)), (
        "pre-state should be polluted with frontmatter"
    )

    _wire_repo(monkeypatch, {tid: _ticket(
        ticket_id=tid,
        title="Fix the thing",
        description="the body description text",
        comments=[
            {"text": "first comment body", "timestamp": "2026-05-12T00:00:00Z"},
            {"text": "second comment body", "timestamp": "2026-05-12T00:01:00Z"},
        ],
    )})

    r = client.post(f"/api/bw/projects/{slug}/reembed", json={"ticket_ids": [tid]})
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["reembedded"] == 3, summary  # body + 2 comments, all reused
    assert summary["fresh_inserted"] == 0, summary
    assert summary["errors"] == [], summary

    # Conjunct 1 — zero orphaned chunks.
    assert _orphaned_chunk_count(slug) == 0

    # Conjunct 2 — every chunk derives from clean content. VERA-uuo-2
    # flagged: assert on SUBSTANCE (no `---` fence, no salt keys), NOT a
    # literal `# ` — the chunker normalizes heading levels so a title
    # header may render as `## <title>`.
    for c in _all_chunks(slug):
        stripped = c.text.lstrip()
        assert not stripped.startswith("---"), (
            f"chunk still carries frontmatter fence: {c.text[:80]!r}"
        )
        assert "bw_commit_sha:" not in c.text, (
            f"chunk still carries salt key: {c.text[:120]!r}"
        )
        assert "labels_flat:" not in c.text

    # Conjunct 3 — post-reembed chunk count <= pre-reembed count.
    post_chunk_count = len(_all_chunks(slug))
    assert post_chunk_count <= pre_chunk_count, (
        f"post={post_chunk_count} > pre={pre_chunk_count}"
    )

    # documents.id stable — the same three ids, none orphaned.
    assert _live_doc_ids(slug) == {body_id, c1_id, c2_id}


# ── AC2 — idempotency ───────────────────────────────────────────────────────


def test_ac2_idempotency(client, monkeypatch):
    """AC2: running /reembed twice yields an identical end state."""
    slug = "idemproj"
    tid = "idem-001"
    body_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="body", comment_n=None,
        text="body text here",
    )
    c1_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="comment", comment_n=1,
        text="a comment",
    )
    _wire_repo(monkeypatch, {tid: _ticket(
        ticket_id=tid, title="Idem", description="body text here",
        comments=[{"text": "a comment", "timestamp": "2026-05-12T00:00:00Z"}],
    )})

    r1 = client.post(f"/api/bw/projects/{slug}/reembed", json={"ticket_ids": [tid]})
    assert r1.status_code == 200, r1.text
    ids_after_1 = _live_doc_ids(slug)
    chunks_after_1 = len(_all_chunks(slug))

    def _chunk_text_by_doc(slug_):
        out: dict[str, str] = {}
        for c in sorted(_all_chunks(slug_), key=lambda x: x.chunk_id):
            out[c.document_id] = out.get(c.document_id, "") + c.text
        return out

    content_after_1 = _chunk_text_by_doc(slug)

    r2 = client.post(f"/api/bw/projects/{slug}/reembed", json={"ticket_ids": [tid]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["reembedded"] == 2, r2.json()

    # Identical end state — same doc ids, same chunk count, byte-identical
    # chunk content per doc, zero orphans. NOTE: the content_fingerprint
    # itself is NOT asserted stable across runs — `_build_agent_metadata`
    # stamps a fresh wall-clock `timestamp` into the salt on every ingest,
    # so the fingerprint drifts. That is harmless for the re-embed path:
    # the documents row is keyed/UPDATEd by `id`, not by fingerprint, so a
    # drifting fingerprint orphans/duplicates nothing. The *operational*
    # end state — what AC2 actually requires — is identical. See the
    # uuo-5 verdict's "design/shipped drift" note.
    assert _live_doc_ids(slug) == ids_after_1 == {body_id, c1_id}
    assert len(_all_chunks(slug)) == chunks_after_1
    assert _chunk_text_by_doc(slug) == content_after_1
    assert _orphaned_chunk_count(slug) == 0


# ── AC3 — dry_run ───────────────────────────────────────────────────────────


def test_ac3_dry_run_writes_nothing(client, monkeypatch):
    """AC3: dry_run=true returns counts + orphaned_tickets, writes nothing."""
    slug = "dryproj"
    tid = "dry-001"
    body_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="body", comment_n=None,
        text="body",
    )
    # An orphaned doc: lives in pgvector, but its ticket is NOT in the repo.
    orphan_id = _seed_polluted_doc(
        slug=slug, ticket_id="dry-orphan-999", source_type="body",
        comment_n=None, text="orphan body",
    )
    pre_fp = _doc_fingerprint(body_id)
    pre_chunks = len(_all_chunks(slug))

    _wire_repo(monkeypatch, {tid: _ticket(
        ticket_id=tid, title="Dry", description="body",
        comments=[{"text": "c", "timestamp": "2026-05-12T00:00:00Z"}],
    )})

    r = client.post(f"/api/bw/projects/{slug}/reembed", json={"dry_run": True})
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["dry_run"] is True
    assert summary["tickets_enumerated"] == 1
    # body + 1 comment would be touched.
    assert summary["docs_would_reembed"] == 2, summary
    assert summary["reembedded"] == 0
    assert summary["fresh_inserted"] == 0
    # Orphan detection runs even on a dry run.
    assert "dry-orphan-999" in summary["orphaned_tickets"], summary

    # Nothing written: fingerprint + chunk count unchanged, orphan doc
    # still present (NOT auto-deleted).
    assert _doc_fingerprint(body_id) == pre_fp
    assert len(_all_chunks(slug)) == pre_chunks
    assert orphan_id in _live_doc_ids(slug)


# ── AC4 — changed fingerprint UPDATEs in place, no orphan row ────────────────


def test_ac4_changed_fingerprint_updates_in_place(client, monkeypatch):
    """AC4: a re-embed whose new fingerprint differs does NOT leave the old row.

    The pre-uuo doc has no ticket_title key, so the re-embed (which adds
    ticket_title/ticket_type to the salt) produces a DIFFERENT fingerprint.
    update_document_content must UPDATE the existing row in place, not
    INSERT a second one.
    """
    slug = "fpproj"
    tid = "fp-001"
    body_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="body", comment_n=None,
        text="body content",
    )
    pre_fp = _doc_fingerprint(body_id)
    assert len(_live_doc_ids(slug)) == 1

    _wire_repo(monkeypatch, {tid: _ticket(
        ticket_id=tid, title="Has A Title", description="body content",
    )})

    r = client.post(f"/api/bw/projects/{slug}/reembed", json={"ticket_ids": [tid]})
    assert r.status_code == 200, r.text
    assert r.json()["reembedded"] == 1, r.json()

    # Exactly ONE live doc — the same id — and its fingerprint CHANGED.
    assert _live_doc_ids(slug) == {body_id}
    post_fp = _doc_fingerprint(body_id)
    assert post_fp is not None and post_fp != pre_fp, (
        "fingerprint should change (ticket_title now in the salt) but the "
        "row must be UPDATEd in place, not duplicated"
    )


# ── AC5 — ticket with no resolved doc id is INSERTed fresh, not skipped ──────


def test_ac5_zero_resolved_ids_inserts_fresh(client, monkeypatch):
    """AC5: a bw ticket with no existing documents.id is INSERTed fresh."""
    slug = "freshproj"
    tid = "fresh-001"
    # No pre-seeded docs at all — this ticket was never ingested.
    assert _live_doc_ids(slug) == set()

    _wire_repo(monkeypatch, {tid: _ticket(
        ticket_id=tid, title="Never Ingested", description="brand new body",
        comments=[{"text": "fresh comment", "timestamp": "2026-05-12T00:00:00Z"}],
    )})

    r = client.post(f"/api/bw/projects/{slug}/reembed", json={"ticket_ids": [tid]})
    assert r.status_code == 200, r.text
    summary = r.json()
    # Both body + comment are fresh inserts, NOT skipped.
    assert summary["fresh_inserted"] == 2, summary
    assert summary["reembedded"] == 0, summary
    assert summary["errors"] == [], summary

    # A documents row + clean chunks now exist for the ticket.
    assert len(_live_doc_ids(slug)) == 2
    chunks = _all_chunks(slug)
    assert len(chunks) > 0
    assert _orphaned_chunk_count(slug) == 0
    for c in chunks:
        assert not c.text.lstrip().startswith("---")


# ── AC6 — orphan ticket: detect-and-report, NOT auto-delete ─────────────────


def test_ac6_orphan_ticket_detected_not_deleted(client, monkeypatch, caplog):
    """AC6: a doc whose ticket_id is absent from the bw repo is reported.

    It appears in orphaned_tickets + produces a `reembed-orphan-ticket`
    log line, and is NOT auto-deleted.
    """
    slug = "orphanproj"
    repo_tid = "orphan-live-001"
    orphan_tid = "orphan-gone-999"
    # One ticket in the repo, one doc whose ticket is gone from the repo.
    _seed_polluted_doc(
        slug=slug, ticket_id=repo_tid, source_type="body", comment_n=None,
        text="live body",
    )
    orphan_doc_id = _seed_polluted_doc(
        slug=slug, ticket_id=orphan_tid, source_type="body", comment_n=None,
        text="orphan body",
    )

    _wire_repo(monkeypatch, {repo_tid: _ticket(
        ticket_id=repo_tid, title="Live", description="live body",
    )})

    import logging
    with caplog.at_level(logging.WARNING, logger="ariadne.bw.ingest"):
        r = client.post(f"/api/bw/projects/{slug}/reembed", json={})
    assert r.status_code == 200, r.text
    summary = r.json()

    # Reported in the response.
    assert orphan_tid in summary["orphaned_tickets"], summary
    assert repo_tid not in summary["orphaned_tickets"], summary
    # Structured log line emitted.
    assert any(
        rec.message == "reembed-orphan-ticket" for rec in caplog.records
    ), [r.message for r in caplog.records]
    # NOT auto-deleted — the orphan doc is still live.
    assert orphan_doc_id in _live_doc_ids(slug)


# ── AC7 — per-ticket lock: no interleave WITHIN a ticket, OK between ─────────


def test_ac7_per_ticket_lock_scope(monkeypatch):
    """AC7: a live write cannot interleave WITHIN one ticket's re-embed.

    The orchestrator acquires `_lock_for(slug)` per ticket, held across
    body + the entire comments loop. A live writer that tries to acquire
    the same lock while a ticket is mid-re-embed must wait until that
    ticket's body + comments are all done — but CAN acquire it between
    tickets.

    This test drives `_reembed_tickets` directly and instruments the
    snapshot core to record interleave order: a competing "live writer"
    coroutine tries to grab the lock during the run.
    """
    slug = "lockreembed"
    t1, t2 = "lock-t1", "lock-t2"
    _wire_repo(monkeypatch, {
        t1: _ticket(
            ticket_id=t1, title="T1", description="t1 body",
            comments=[
                {"text": "t1c1", "timestamp": "2026-05-12T00:00:00Z"},
                {"text": "t1c2", "timestamp": "2026-05-12T00:01:00Z"},
            ],
        ),
        t2: _ticket(
            ticket_id=t2, title="T2", description="t2 body",
            comments=[{"text": "t2c1", "timestamp": "2026-05-12T00:00:00Z"}],
        ),
    })

    events: list[str] = []
    real_snapshot = bw_ingest._ingest_bw_snapshot

    async def _instrumented(**kwargs):
        events.append(
            f"reembed:{kwargs['ticket_id']}:{kwargs['source_type']}"
            f":{kwargs.get('comment_n')}"
        )
        # Yield control so a competing coroutine gets a chance to run —
        # if the lock weren't held across the whole ticket, the live
        # writer could slip in here mid-ticket.
        await asyncio.sleep(0)
        return await real_snapshot(**kwargs)

    monkeypatch.setattr(bw_ingest, "_ingest_bw_snapshot", _instrumented)

    async def _driver():
        # Competing live writer: waits until the re-embed has started,
        # then tries to grab the per-slug lock and records when it got in.
        async def live_writer():
            # Let the re-embed task start and acquire the lock for t1.
            while not events:
                await asyncio.sleep(0)
            lock = await bw_routes._lock_for(slug)
            async with lock:
                events.append("live-write")

        reembed_task = asyncio.create_task(
            bw_ingest._reembed_tickets(slug=slug, agent_id="test")
        )
        writer_task = asyncio.create_task(live_writer())
        await asyncio.wait_for(
            asyncio.gather(reembed_task, writer_task), timeout=5.0
        )
        return reembed_task.result()

    summary = asyncio.run(_driver())
    assert summary["reembedded"] == 0  # nothing pre-seeded
    # t1: body + c1 + c2 = 3; t2: body + c1 = 2; total = 5 fresh inserts.
    assert summary["fresh_inserted"] == 5, summary

    # The live-write must NOT appear between a ticket's body and its last
    # comment. Find the live-write index and assert it lands on a
    # ticket boundary — i.e. all of t1's docs come before it OR all of
    # t1's docs come after it (and likewise t2).
    lw = events.index("live-write")
    t1_events = [
        i for i, e in enumerate(events) if e.startswith(f"reembed:{t1}:")
    ]
    t2_events = [
        i for i, e in enumerate(events) if e.startswith(f"reembed:{t2}:")
    ]
    # For each ticket, the live-write index must be entirely before all
    # of that ticket's events or entirely after — never strictly inside.
    for tevents in (t1_events, t2_events):
        assert tevents, events
        inside = min(tevents) < lw < max(tevents)
        assert not inside, (
            f"live write interleaved WITHIN a ticket's re-embed: "
            f"events={events}"
        )


# ── AC8 — per-slot mapping: comment-3 lands on comment-3's old id ───────────


def test_ac8_per_slot_mapping_comment_3(client, monkeypatch):
    """AC8: comment-3's new content lands on comment-3's old documents.id.

    Seeds body + 3 comments with distinct text, captures each slot's id,
    re-embeds, and asserts every slot's content landed on its OWN old id —
    in particular comment-3 did not land on comment-1's id.
    """
    slug = "slotproj"
    tid = "slot-001"
    body_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="body", comment_n=None,
        text="the body",
    )
    c1_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="comment", comment_n=1,
        text="comment one text",
    )
    c2_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="comment", comment_n=2,
        text="comment two text",
    )
    c3_id = _seed_polluted_doc(
        slug=slug, ticket_id=tid, source_type="comment", comment_n=3,
        text="comment three text",
    )
    # All four ids must be distinct for the test to mean anything.
    assert len({body_id, c1_id, c2_id, c3_id}) == 4

    _wire_repo(monkeypatch, {tid: _ticket(
        ticket_id=tid, title="Slot Map", description="the body",
        comments=[
            {"text": "comment one text", "timestamp": "2026-05-12T00:00:00Z"},
            {"text": "comment two text", "timestamp": "2026-05-12T00:01:00Z"},
            {"text": "comment three text", "timestamp": "2026-05-12T00:02:00Z"},
        ],
    )})

    r = client.post(f"/api/bw/projects/{slug}/reembed", json={"ticket_ids": [tid]})
    assert r.status_code == 200, r.text
    assert r.json()["reembedded"] == 4, r.json()
    assert r.json()["fresh_inserted"] == 0, r.json()

    # Same four ids, none orphaned, none duplicated.
    assert _live_doc_ids(slug) == {body_id, c1_id, c2_id, c3_id}

    # comment-3's id now carries comment-3's content — assert the chunk
    # text under c3_id contains "comment three", not "comment one".
    c3_chunks = [c for c in _all_chunks(slug) if c.document_id == c3_id]
    assert c3_chunks, "comment-3 doc has no chunks"
    c3_text = " ".join(c.text for c in c3_chunks)
    assert "comment three text" in c3_text, c3_text
    assert "comment one text" not in c3_text, c3_text

    c1_chunks = [c for c in _all_chunks(slug) if c.document_id == c1_id]
    c1_text = " ".join(c.text for c in c1_chunks)
    assert "comment one text" in c1_text, c1_text
    assert "comment three text" not in c1_text, c1_text


# ── Extra: unknown ticket_id is reported, not silently dropped ───────────────


def test_unknown_ticket_id_reported_as_error(client, monkeypatch):
    """A ticket_id not present in the bw repo surfaces in `errors`."""
    slug = "unkproj"
    tid = "unk-real-001"
    _wire_repo(monkeypatch, {tid: _ticket(ticket_id=tid, title="Real")})

    r = client.post(
        f"/api/bw/projects/{slug}/reembed",
        json={"ticket_ids": [tid, "unk-ghost-999"]},
    )
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["tickets_enumerated"] == 1  # only the real one walked
    assert any(
        e.get("ticket_id") == "unk-ghost-999" for e in summary["errors"]
    ), summary
