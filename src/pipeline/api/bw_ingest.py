"""Inline bw → Ariadne ingest helpers (Phase 3 / ariadne--8fd.5).

Every Phase 2 bw HTTP write endpoint calls one of two helpers in this
module after ``_run_bw`` returns success and before the per-slug lock
releases:

  • ``_ingest_bw_write`` — create a new Ariadne document for a fresh bw
    body or comment.
  • ``_patch_bw_body_metadata`` — re-emit the full ``agent_metadata``
    surface against an existing body document so the latest-interaction
    filter (Phase 1) sees the new label / status / assignee.

Both helpers are async; both wrap every blocking Postgres / Gemini call
in ``asyncio.to_thread`` so the FastAPI event loop stays responsive for
coroutines targeting OTHER slugs while the lock-holder embeds.

On any ingest exception, the failed payload is enqueued for retry — first
against the ``bw_ingest_retry_queue`` Postgres table, falling back to a
JSONL file at ``${BW_REPOS_ROOT}/{slug}/.bw_ingest_dead_letter.jsonl`` if
the Postgres enqueue itself fails (the Postgres-drop-during-enqueue case
called out in design §D5.5). A background retry-worker (``_bw_retry_worker``)
drains both surfaces on a poll interval.

**Module placement note (design §D2.2 deviation).** Design §D2.2 placed
these helpers inline in ``bw_routes.py``. Implementation hoisted them
into this sibling module to keep ``bw_routes.py`` under the workspace's
soft 1500-line cap and to keep the routing surface focused on HTTP
shape (request → bw subprocess → response) rather than on
Ariadne-write internals. ``bw_routes.py`` calls into this module via a
function-local import so the routing layer doesn't pull the
ingest-stack at module-load time, which also breaks the
``services.py → bw_ingest.py → services.py`` cycle that would
otherwise form (``_ingest_bw_write`` calls ``_process_single_document``
which is defined in ``services.py``). The lazy import is the load-bearing
piece; the file split is the cosmetic consequence.

See ``agents/design/ariadne--8fd.5/design.md`` for the full spec —
particularly §D1 (frontmatter schema), §D2 (coupling seam), §D3 (the
22-endpoint matrix), §D5 (retry shape), and §D6 (bw_commit_sha capture).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from pipeline.auth_oauth import Principal

logger = logging.getLogger("ariadne.bw.ingest")


# ── Configuration ───────────────────────────────────────────────────────────
#
# Retry-worker knobs are read at module import time from the environment.
# Tests override via monkeypatch on this module.

# Poll interval between retry-queue drain attempts. Most polls return zero
# rows (the SELECT against ``next_attempt_at`` hits the index and returns
# empty), so 30s is cheap and gives "no perceptible lag" recovery in the
# common Gemini-blip case.
BW_RETRY_POLL_SECONDS: float = float(os.environ.get("BW_RETRY_POLL_SECONDS", "30"))

# Max rows drained per poll. Bounded so a backlog after a long outage
# doesn't lock the event loop on one tick. Default 10 leaves headroom for
# the embedding round-trip (~1.5s) under typical Gemini throughput.
BW_RETRY_BATCH_SIZE: int = int(os.environ.get("BW_RETRY_BATCH_SIZE", "10"))

# Exponential-backoff base + ceiling. 30s base, 1h max → attempt cadence
# 30s, 60s, 2m, 4m, ..., 1h, 1h, 1h. With 24 attempts and a 1h ceiling
# the dead-letter trigger is ~20h after first failure for a hard-down
# upstream — long enough that a Gemini outage rebounds before exhaustion,
# short enough that a misconfigured deploy isn't silent for days.
BW_RETRY_BASE_BACKOFF_SECONDS: float = float(
    os.environ.get("BW_RETRY_BASE_BACKOFF_SECONDS", "30")
)
BW_RETRY_MAX_BACKOFF_SECONDS: float = float(
    os.environ.get("BW_RETRY_MAX_BACKOFF_SECONDS", "3600")
)
BW_RETRY_MAX_ATTEMPTS: int = int(os.environ.get("BW_RETRY_MAX_ATTEMPTS", "24"))

# File-fallback dead-letter filename, per slug. Lives in the bw repo's
# persistent volume — the same directory the bw repo's ``.git/`` lives in
# — so a Postgres-down failure mode is recoverable from on-disk state
# alone. Atomic-append-by-line; atomic-rename-then-drain on retry poll.
BW_FILE_FALLBACK_NAME: str = ".bw_ingest_dead_letter.jsonl"
BW_FILE_FALLBACK_DRAINING_NAME: str = ".bw_ingest_dead_letter.draining.jsonl"

# Per-process counters for the observability surface (D5.3). Reset on
# process restart; persistent counts come from the Postgres tables.
_file_fallback_drain_count: int = 0


# ── Render helpers ──────────────────────────────────────────────────────────


def _render_payload(metadata: dict[str, Any], text: str) -> bytes:
    """Render the ingest payload: frontmatter + blank line + body.

    Frontmatter is YAML between ``---`` lines with keys emitted in
    alphabetized order so the resulting bytes are byte-stable for the
    same metadata dict (the fingerprint downstream is SHA-256 over
    these bytes — see ``compute_fingerprint`` at dedup.py). Using
    sorted keys also doubles as the dedup-salt property called out in
    design §D1.4: because ``ticket_id``, ``comment_n``, and
    ``bw_commit_sha`` differ per occurrence, two comments with literally
    identical body text on the same ticket produce different fingerprints.

    No normalization is applied to ``text`` (no whitespace collapse, no
    encoding translation, no markdown-fixup). The exact bytes bw stored
    are the exact bytes ingested.
    """
    # ``json.dumps`` with sort_keys produces a stable, YAML-compatible
    # representation for the simple value types we use (str / int /
    # bool / None / list[str] / dict[str,str]). Using JSON-inside-YAML
    # avoids depending on PyYAML for a write-side helper (PyYAML is in
    # the project dependencies but adds latency and edge cases for
    # nested dicts). YAML accepts JSON as a subset, so callers reading
    # the frontmatter with PyYAML still parse it.
    body_lines: list[str] = ["---"]
    for key in sorted(metadata):
        value = metadata[key]
        body_lines.append(f"{key}: {json.dumps(value, sort_keys=True)}")
    body_lines.append("---")
    body_lines.append("")
    body_lines.append(text)
    return "\n".join(body_lines).encode("utf-8")


# Label kinds whose value carries enough standalone semantic signal to be
# worth folding into the embedded text (Anthropic "Contextual Retrieval").
# Everything NOT in this allowlist — bare labels, unknown kinds, mutable
# operational labels — still reaches ``documents.metadata.labels`` /
# ``labels_flat`` for structured filtering, but does NOT pollute the chunk
# text. "Meaningful" is a reviewable judgment call, so it is an explicit
# frozenset rather than a heuristic (design §3.4). Widening it is a
# one-line change followed by a re-embed (uuo-5) — cheap by construction.
_EMBED_LABEL_ALLOWLIST: frozenset[str] = frozenset({
    "hypothesis", "manifest_type", "customer", "topic", "area",
})


def _render_embed_content(metadata: dict[str, Any], text: str) -> bytes:
    """Render the clean embed/extract content: contextual header + body.

    The decoupled sibling of ``_render_payload`` (design §3.2). Where
    ``_render_payload`` produces the dedup-salt input (full sorted-YAML
    frontmatter + body — the bytes the fingerprint is SHA-256'd over),
    this produces the bytes that are actually extracted, chunked,
    embedded, and stored as chunk text.

    The two differ deliberately:

      • NO YAML frontmatter — no ``--- ... ---`` block. The per-occurrence
        salt keys (``ticket_id`` / ``comment_n`` / ``bw_commit_sha`` /
        ``timestamp`` / ``assignee`` / graph edges) are pollution in the
        embed space: every chunk vector would be partly "about" them and
        every chunk would share that prefix. They stay in
        ``documents.metadata`` for structured filtering; they never enter
        the embedded text.
      • A SELECTIVE contextual header — the ticket title (``# <title>``),
        the ticket type, and only those kinded labels in
        ``_EMBED_LABEL_ALLOWLIST``. Body docs historically got the title
        via the create path's text-concat; comment docs got nothing — a
        bare comment had no anchor to its parent ticket. The header gives
        body and comment docs a symmetric, meaningful anchor.

    ``ticket_title`` / ``ticket_type`` are populated by
    ``_build_agent_metadata`` (sourced from the ``bw show`` snapshot —
    design §3.3). When they are absent (graceful degradation — a thinner
    snapshot, an older retry-queue payload), the header simply shrinks or
    disappears and this falls through to the bare body bytes. The body
    ``text`` is never normalized — same byte-fidelity contract as
    ``_render_payload``.
    """
    header_lines: list[str] = []
    title = metadata.get("ticket_title")
    ttype = metadata.get("ticket_type")
    if title:
        header_lines.append(f"# {title}")
    if ttype:
        header_lines.append(f"Ticket type: {ttype}")
    # Only allowlisted kinded labels — explicit, reviewable enrichment.
    for kind, value in (metadata.get("labels") or {}).items():
        if kind in _EMBED_LABEL_ALLOWLIST:
            header_lines.append(f"{kind}: {value}")
    if header_lines:
        return ("\n".join(header_lines) + "\n\n" + text).encode("utf-8")
    return text.encode("utf-8")


def _parse_label(raw: str) -> tuple[str | None, str]:
    """Split a bw label into (kind, value) using the first ``:``.

    A bare label (no colon) returns ``(None, raw)`` — the caller skips
    these for the structured ``labels`` dict but always records them in
    ``labels_flat``. Per design §D1.8.
    """
    if ":" in raw:
        kind, _, value = raw.partition(":")
        kind = kind.strip()
        value = value.strip()
        if kind:
            return kind, value
    return None, raw


def _build_agent_metadata(
    *,
    ticket_id: str,
    slug: str,
    source_type: str,
    comment_n: Optional[int],
    bw_commit_sha: str,
    bw_status: Optional[str],
    bw_author: Optional[str],
    bw_assignee: Optional[str],
    bw_parent: Optional[str],
    bw_labels: list[str],
    bw_timestamp: str,
    ticket_title: Optional[str] = None,
    ticket_type: Optional[str] = None,
) -> dict[str, Any]:
    """Compose the full ``agent_metadata`` dict per design §D1.3.

    The full surface MUST be re-emitted on every PATCH-meta call — the
    Phase 1 filter resolves against the latest interaction's metadata,
    so a partial payload would silently drop ``ticket_id`` / ``project``
    / etc. from the search-filter surface. See §1 fact 1 in the design.

    ``ticket_title`` / ``ticket_type`` (ariadne--uuo.2): the parent
    ticket's title and type, sourced from the ``bw show`` snapshot at the
    call site. They serve two purposes — they join the
    ``documents.metadata`` JSONB surface (free, they flow through
    ``agent_metadata``), AND they feed ``_render_embed_content``'s
    contextual header (design §3.3). Both default to ``None``: callers
    that cannot cheaply source them (or whose snapshot is thinner than
    ``bw show --json``) simply omit them, and the embed-content header
    degrades gracefully to a bare body.
    """
    labels_dict: dict[str, str] = {}
    labels_flat: list[str] = []
    for raw in bw_labels:
        kind, value = _parse_label(raw)
        if kind is not None:
            # Per design §D1.8 W8: if two labels share the same kind
            # (e.g., ``kind:person`` and ``kind:venue``), the second
            # overwrites the first. Operator convention is
            # one-value-per-kind; flagged as a weakness in design §4.
            labels_dict[kind] = value
        # Every label — kinded or bare — joins labels_flat in raw form.
        labels_flat.append(raw)

    return {
        "ticket_id": ticket_id,
        "project": slug,
        "source_type": source_type,
        "comment_n": comment_n,
        "author": bw_author,
        "timestamp": bw_timestamp,
        "bw_commit_sha": bw_commit_sha,
        "bw_status": bw_status,
        "parent_ticket_id": bw_parent,
        "assignee": bw_assignee,
        "labels": labels_dict,
        "labels_flat": labels_flat,
        "ticket_title": ticket_title,
        "ticket_type": ticket_type,
    }


def _now_utc_isoformat() -> str:
    """RFC3339 UTC timestamp for ``agent_metadata.timestamp``.

    Captured at the API boundary inside the per-slug lock, immediately
    after the bw subprocess returns success. Monotonic per slug because
    the lock serializes writes.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── bw history helpers ──────────────────────────────────────────────────────
#
# Both helpers below call ``bw history --json`` against the per-slug repo.
# They live in this module (not in bw_routes.py) because they are part of
# the ingest helper's call graph — only the ingest helpers need them; the
# bw HTTP surface itself exposes history at GET /tickets/{id}/history with
# its own pass-through to ``bw history``.


async def _bw_history_head(slug: str, ticket_id: str) -> tuple[str, str | None]:
    """Return ``(commit_sha, author)`` for the most recent bw mutation.

    Called inside the per-slug lock immediately after ``_run_bw`` returns
    success. The lock guarantees this row is the just-completed mutation
    (no other writer can interleave). Returns the 40-hex commit SHA and
    the author string from bw's perspective (the ``--author`` flag value,
    or the git user.name default).

    Falls back to ``git -C {repo} rev-parse refs/heads/beadwork`` (author
    unknown) if ``bw history --json --limit 1`` returns an unexpected
    shape — see design §D6 + W3 for why both paths exist.

    Per design §D6: this is the authoritative shape for ``bw_commit_sha``.
    Do NOT switch to ``git rev-parse HEAD`` — that returns the master-branch
    SHA in this repo topology, NOT the orphan-branch tip, and Phase 1's
    R1 finding was precisely this defect.
    """
    # Lazy import — ``bw_routes`` imports this module, so importing it
    # at the top would create a cycle. We need ``_run_bw`` here because
    # it carries the slug → repo path resolution, the timeout, and the
    # error-mapping all the bw subprocess work depends on.
    from pipeline.api.bw_routes import _run_bw

    try:
        result = await _run_bw(
            slug, "history", ticket_id, "--json", "--limit", "1",
            json_output=True,
        )
    except HTTPException:
        # Treat any bw error here as a graceful fallback to git plumbing.
        # The fallback is intentionally informational-only — we lose the
        # author signal, but we still get a SHA that callers can use as
        # provenance.
        return await _bw_history_head_fallback(slug), None

    # ``_run_bw`` wraps JSON-array returns as ``{"items": [...]}``. The
    # ``bw history --json --limit 1`` shape is a single-element list,
    # so the wrapped shape is ``{"items": [{hash, author, intent, timestamp}]}``.
    items: list[dict[str, Any]] | None = None
    if isinstance(result, dict):
        items = result.get("items") if "items" in result else None
        # Some bw shapes return a dict directly (single-row, no wrap).
        if items is None and "hash" in result:
            items = [result]
    if items and isinstance(items, list):
        row = items[0]
        if isinstance(row, dict):
            sha = row.get("hash")
            author = row.get("author")
            if isinstance(sha, str) and len(sha) == 40:
                return sha, author

    # Shape rotation — fall back to git plumbing (no author available).
    logger.warning(
        "bw_history_head: unexpected shape (slug=%s, ticket=%s); falling back to git",
        slug, ticket_id,
    )
    return await _bw_history_head_fallback(slug), None


async def _bw_history_head_fallback(slug: str) -> str:
    """Read ``refs/heads/beadwork`` directly via git plumbing.

    Specifically the ref name ``refs/heads/beadwork`` — NOT the bare ``HEAD``
    (which empirically resolves to the master-branch SHA in this repo,
    because the bw working tree HEAD does not track the orphan branch).
    Used only when ``bw history --json`` returns an unexpected shape.
    """
    from pipeline.api.bw_routes import _resolve_repo_path

    repo_path = _resolve_repo_path(slug)
    proc = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", repo_path, "rev-parse", "refs/heads/beadwork"],
        capture_output=True, text=True, timeout=5.0, check=False,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "bw_commit_sha_capture_failed",
                "stderr": (proc.stderr or "").strip(),
            },
        )
    return proc.stdout.strip()


async def _bw_body_author(slug: str, ticket_id: str) -> str | None:
    """Return the original body author from bw history.

    The bw ``create`` row's ``author`` field is the canonical body author,
    stable across all subsequent PATCH / label-add / status-change calls
    (bw history is append-only commits on an orphan branch — no command
    rewrites the create commit). Per design §D3.1 step 2: this is what
    must flow into ``agent_metadata.author`` on every PATCH-meta call so
    Phase 1's ``metadata={"author":"alice"}`` filter keeps returning the
    body docs alice authored even after a different principal PATCHes
    them.

    Returns ``None`` (with a WARNING log) when the create row cannot be
    found — data corruption or pre-bw-0.12 ticket. Caller proceeds with
    ``author=None`` rather than crashing.
    """
    from pipeline.api.bw_routes import _run_bw

    try:
        result = await _run_bw(
            slug, "history", ticket_id, "--json",
            json_output=True,
        )
    except HTTPException:
        return None

    items: list[dict[str, Any]] | None = None
    if isinstance(result, dict):
        items = result.get("items") if "items" in result else None
    if not items or not isinstance(items, list):
        return None

    create_prefix = f"create {ticket_id}"
    for row in items:
        if not isinstance(row, dict):
            continue
        intent = row.get("intent") or ""
        if intent.startswith(create_prefix):
            return row.get("author")

    logger.warning(
        "bw_body_author: no 'create' row in history (slug=%s, ticket=%s)",
        slug, ticket_id,
    )
    return None


# ── Body-doc lookup ─────────────────────────────────────────────────────────


def _resolve_body_doc_id(*, slug: str, ticket_id: str) -> str | None:
    """Find the active body document for a ticket, or None.

    Looks up ``documents`` filtered by ``collection_id`` (resolved from
    ``slug``), ``metadata.ticket_id``, ``metadata.source_type='body'``,
    and ``deleted_at IS NULL``. One body doc per ticket is the invariant;
    a >1 match indicates a prior PATCH-body that didn't soft-delete (see
    §D4.1's forward-compat note) and we pick the most recent by
    ``created_at`` with a WARNING.

    Sync function — callers wrap in ``asyncio.to_thread``. Per design
    §D3.1 step 5 + §W2: at v1 scale this is a SEQ SCAN against
    ``documents`` (the Phase 1 GIN index covers ``document_interactions``,
    not ``documents``); fine at 10²-10³ docs per collection, would need a
    partial index at full-corpus scale (Phase 4's problem).
    """
    from pipeline.services import _dedup_store

    # Use the InMemoryDedupStore's underlying dict for the test path; for
    # PgDedupStore we use a parameterized SELECT against the pool. The
    # branch is necessary because the in-memory store keys by
    # (collection, fingerprint) and has no JSONB containment operator.
    from pipeline.dedup import InMemoryDedupStore, PgDedupStore

    if isinstance(_dedup_store, InMemoryDedupStore):
        # Linear scan over the test fixture. At dev scale this is
        # negligible; the test path never holds enough docs to matter.
        candidates: list = []
        for doc in _dedup_store._documents.values():
            if doc.collection_id != slug:
                continue
            if doc.document_id in _dedup_store._deletions:
                continue
            meta = _dedup_store._doc_metadata.get(doc.document_id, {})
            if (
                meta.get("ticket_id") == ticket_id
                and meta.get("source_type") == "body"
            ):
                candidates.append(doc)
        if not candidates:
            return None
        if len(candidates) > 1:
            logger.warning(
                "_resolve_body_doc_id: %d body docs for (slug=%s, ticket=%s); picking latest",
                len(candidates), slug, ticket_id,
            )
        # Sort by created_at descending; pick the latest.
        candidates.sort(key=lambda d: d.created_at or "", reverse=True)
        return candidates[0].document_id

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id::text, d.created_at
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(slug)s
                      AND d.metadata @> %(needle)s::jsonb
                      AND d.deleted_at IS NULL
                    ORDER BY d.created_at DESC
                    LIMIT 2
                    """,
                    {
                        "slug": slug,
                        "needle": json.dumps({
                            "ticket_id": ticket_id,
                            "source_type": "body",
                        }),
                    },
                )
                rows = cur.fetchall()
                if not rows:
                    return None
                if len(rows) > 1:
                    logger.warning(
                        "_resolve_body_doc_id: >1 body docs for "
                        "(slug=%s, ticket=%s); picking latest",
                        slug, ticket_id,
                    )
                return rows[0][0]

    return None


def _resolve_all_ticket_doc_ids(*, slug: str, ticket_id: str) -> list[str]:
    """Return all active document IDs (body + comments) for a ticket.

    Used by the soft-delete-on-ticket-delete path (design §D3 row for
    ``DELETE /tickets/{id}?force=true``). Returns an empty list if no
    matching docs exist (already-deleted, race with another writer).
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import InMemoryDedupStore, PgDedupStore

    if isinstance(_dedup_store, InMemoryDedupStore):
        ids: list[str] = []
        for doc in _dedup_store._documents.values():
            if doc.collection_id != slug:
                continue
            if doc.document_id in _dedup_store._deletions:
                continue
            meta = _dedup_store._doc_metadata.get(doc.document_id, {})
            if meta.get("ticket_id") == ticket_id:
                ids.append(doc.document_id)
        return ids

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id::text
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(slug)s
                      AND d.metadata @> %(needle)s::jsonb
                      AND d.deleted_at IS NULL
                    """,
                    {
                        "slug": slug,
                        "needle": json.dumps({"ticket_id": ticket_id}),
                    },
                )
                return [row[0] for row in cur.fetchall()]
    return []


def _resolve_ticket_doc_id_map(
    *, slug: str, ticket_id: str
) -> dict[tuple[str, Optional[int]], str]:
    """Return a per-slot ``{(source_type, comment_n): documents.id}`` map.

    ariadne--uuo.5 (design §6.7.2, W-7). ``_resolve_all_ticket_doc_ids``
    returns a *bare, unordered* list of document IDs for a ticket — it
    cannot tell the re-embed path *which* id is the body and which is
    comment-3. The in-place re-embed must write comment-3's new content to
    comment-3's *old* ``documents.id``, not comment-1's — so it needs the
    per-slot mapping, keyed on the ``source_type`` + ``comment_n`` keys
    that ``_build_agent_metadata`` already writes into
    ``documents.metadata``.

    Slot key shape:
      • body  → ``("body", None)``
      • comment N → ``("comment", N)``

    A slot the re-embed walk asks for that is **absent** from this map is
    exactly the §6.7.2 zero-resolved-IDs case — the caller takes the
    ``existing_document_id=None`` fresh-INSERT fall-through. This makes the
    map robust to a comment-count mismatch between original ingest and
    re-embed (the W-7 / VERA-uuo-2 robustness concern): a comment slot
    with no prior doc is simply INSERTed fresh, never orphaned.

    Defensive shapes handled:
      • ``>1`` doc for the same slot (a prior PATCH-body that didn't
        soft-delete, or a duplicate ingest) — the latest by ``created_at``
        wins, with a WARNING, mirroring ``_resolve_body_doc_id``.
      • a doc with a missing/None ``source_type`` — skipped (it cannot be
        slot-mapped; it will surface via ``_resolve_all_ticket_doc_ids``
        for the orphan/diagnostic paths but is not a re-embed target).

    Sync function — callers wrap in ``asyncio.to_thread``.
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import InMemoryDedupStore, PgDedupStore

    def _slot_key(meta: dict[str, Any]) -> tuple[str, Optional[int]] | None:
        source_type = meta.get("source_type")
        if source_type not in ("body", "comment"):
            return None
        comment_n = meta.get("comment_n")
        if source_type == "comment":
            # comment_n must be an int to identify the slot; a comment doc
            # with no comment_n cannot be slot-mapped.
            if not isinstance(comment_n, int):
                return None
            return ("comment", comment_n)
        return ("body", None)

    if isinstance(_dedup_store, InMemoryDedupStore):
        # slot -> list of (created_at, doc_id) so we can pick latest on a
        # duplicate slot.
        buckets: dict[tuple[str, Optional[int]], list[tuple[str, str]]] = {}
        for doc in _dedup_store._documents.values():
            if doc.collection_id != slug:
                continue
            if doc.document_id in _dedup_store._deletions:
                continue
            meta = _dedup_store._doc_metadata.get(doc.document_id, {})
            if meta.get("ticket_id") != ticket_id:
                continue
            slot = _slot_key(meta)
            if slot is None:
                continue
            buckets.setdefault(slot, []).append(
                (doc.created_at or "", doc.document_id)
            )
        result: dict[tuple[str, Optional[int]], str] = {}
        for slot, rows in buckets.items():
            if len(rows) > 1:
                logger.warning(
                    "_resolve_ticket_doc_id_map: %d docs for slot %s "
                    "(slug=%s, ticket=%s); picking latest",
                    len(rows), slot, slug, ticket_id,
                )
            rows.sort(key=lambda r: r[0], reverse=True)
            result[slot] = rows[0][1]
        return result

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id::text,
                           d.metadata->>'source_type',
                           d.metadata->>'comment_n',
                           d.created_at
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(slug)s
                      AND d.metadata @> %(needle)s::jsonb
                      AND d.deleted_at IS NULL
                    ORDER BY d.created_at DESC
                    """,
                    {
                        "slug": slug,
                        "needle": json.dumps({"ticket_id": ticket_id}),
                    },
                )
                # created_at DESC ordering means the FIRST row seen for a
                # slot is the latest — setdefault keeps it and ignores the
                # older duplicates.
                pg_result: dict[tuple[str, Optional[int]], str] = {}
                seen_dupes: set[tuple[str, Optional[int]]] = set()
                for doc_id, source_type, comment_n_raw, _created in cur.fetchall():
                    comment_n: Optional[int] = None
                    if comment_n_raw is not None:
                        try:
                            comment_n = int(comment_n_raw)
                        except (TypeError, ValueError):
                            comment_n = None
                    slot = _slot_key(
                        {"source_type": source_type, "comment_n": comment_n}
                    )
                    if slot is None:
                        continue
                    if slot in pg_result:
                        seen_dupes.add(slot)
                        continue
                    pg_result[slot] = doc_id
                for slot in seen_dupes:
                    logger.warning(
                        "_resolve_ticket_doc_id_map: >1 docs for slot %s "
                        "(slug=%s, ticket=%s); picked latest",
                        slot, slug, ticket_id,
                    )
                return pg_result
    return {}


# ── Helper 1: new-doc ingest ────────────────────────────────────────────────


async def _ingest_bw_snapshot(
    *,
    slug: str,
    source_type: str,           # 'body' | 'comment'
    ticket_id: str,
    bw_show_snapshot: dict[str, Any],  # a bw show-shaped snapshot dict
    text: str,
    comment_n: Optional[int],
    agent_id: str,
    bw_commit_sha: str,
    bw_author: Optional[str],
    force: bool = False,
    existing_document_id: Optional[str] = None,
    enqueue_on_failure: bool = True,
) -> dict[str, Any]:
    """Snapshot-driven ingest core — shared by the live-write and re-embed paths.

    ariadne--uuo.5 (design §6.1, §6.2). ``_ingest_bw_write`` is the
    live-write path: it fetches the just-completed mutation's SHA + author
    via ``_bw_history_head`` and then delegates here. The ``POST /reembed``
    route is the re-embed path: it walks *existing* tickets, reads each
    one's current orphan-branch SHA, resolves the existing ``documents.id``
    per body/comment slot, and calls here with ``force=True`` +
    ``existing_document_id=<resolved id or None>``.

    This core does **NO bw history calls** — ``bw_commit_sha`` and
    ``bw_author`` are passed IN. That is the whole point of the extraction:
    a re-embed has no "just-completed write" to read history for.

    Parameters that differ per path:

      • ``bw_commit_sha`` / ``bw_author`` — for a live write these come from
        ``_bw_history_head`` (the mutation that just happened); for a
        re-embed they come from the existing ticket's current state.
      • ``force`` — MUST be ``True`` on the re-embed path (design §6.4): the
        ``force`` branch in ``_process_single_document`` runs
        ``delete_by_document`` before ``insert``, clearing the old chunks
        the new chunks (same ``effective_document_id``) are about to
        replace. Without it the old chunks survive and the new chunks
        silently drop on the chunk PK collision. ``False`` for live writes
        (a fresh doc has no old chunks).
      • ``existing_document_id`` — when supplied, ``_process_single_document``
        resolves ``effective_document_id`` to it and routes the
        documents-row write through ``update_document_content``
        (UPDATE-by-id) instead of ``store_document`` (INSERT). ``None``
        takes the fresh-INSERT path — exactly what a live write does, and
        what the §6.7.2 zero-resolved-IDs branch of ``/reembed`` does.
      • ``enqueue_on_failure`` — the live-write path enqueues a failed
        ingest for background retry (the bw write already succeeded and is
        canonical). The re-embed path sets this ``False``: a re-embed
        failure is collected into the route's ``errors`` summary and is
        recoverable by re-running ``/reembed`` for that ticket (design
        §6.4 idempotency) — routing it through the retry queue would
        replay it as a fresh ``force=False`` ingest, losing the
        ``existing_document_id`` reuse.

    Returns the ingest result dict on success, or a small ack/error dict
    on a failure (enqueued for retry, or surfaced for the caller).
    """
    metadata = _build_agent_metadata(
        ticket_id=ticket_id,
        slug=slug,
        source_type=source_type,
        comment_n=comment_n,
        bw_commit_sha=bw_commit_sha,
        bw_status=bw_show_snapshot.get("status"),
        bw_author=bw_author,
        bw_assignee=bw_show_snapshot.get("assignee") or None,
        bw_parent=bw_show_snapshot.get("parent") or None,
        bw_labels=list(bw_show_snapshot.get("labels") or []),
        bw_timestamp=_now_utc_isoformat(),
        # ariadne--uuo.2: title/type feed both documents.metadata and the
        # _render_embed_content contextual header. All four bw mutation
        # subcommands whose --json becomes this snapshot — create / comment
        # / close / patch(update) — carry top-level "title"/"type" EXCEPT
        # `close`, whose --json nests the issue under "issue"; the close
        # route unwraps it before calling this helper (see bw_routes.py).
        # The re-embed path reads `bw show --json` (un-nested) so title/type
        # are top-level there too.
        ticket_title=bw_show_snapshot.get("title") or None,
        ticket_type=bw_show_snapshot.get("type") or None,
    )
    # ariadne--uuo.2: two decoupled artifacts from one metadata dict.
    #   payload_bytes  — the dedup-salt input; SHA-256'd for the fingerprint.
    #                    UNCHANGED function: this is the D1.4 property source.
    #   embed_bytes    — the clean contextual-header + body input; extracted,
    #                    chunked, embedded, stored as chunk text. NEVER hashed.
    payload_bytes = _render_payload(metadata, text)
    embed_bytes = _render_embed_content(metadata, text)

    # Synthetic URI — purely informational (displayed as source_file in
    # observability surfaces, never parsed for I/O). The ``.md`` lives in
    # the URL **path** (not the fragment) so ``urlparse(uri).path`` ends
    # in ``.md``; ``_guess_file_type`` then picks up ``"md"`` and
    # MarkItDown treats the bytes as Markdown text — a no-op extraction
    # that returns the same bytes verbatim. The earlier shape used a
    # ``#fragment`` for the source-type suffix, but ``urlparse`` discards
    # fragments before path-suffix inspection (and ``Path.suffix`` of the
    # bare ticket id ``ariadne--8fd.5`` returns ``.5``, the dotted
    # version-segment), so the resulting ``file_type`` was wrong.
    comment_suffix = f"/{comment_n}" if comment_n is not None else ""
    uri = f"bw-bridge://{slug}/{ticket_id}/{source_type}{comment_suffix}.md"

    # Lazy import to avoid the cycle services.py → bw_ingest.py.
    from pipeline.services import _process_single_document

    try:
        result = await asyncio.to_thread(
            _process_single_document,
            uri=uri,
            store=True,
            collection=slug,
            tags=[],
            force=force,
            agent_id=agent_id,
            agent_type="bw_bridge",
            model=None,
            initiated_by="bw_routes",
            agent_notes=None,
            agent_metadata=metadata,
            chunking_config=None,
            ingest_config=None,
            action="ingest",
            inline_content=payload_bytes,
            inline_embed_content=embed_bytes,
            existing_document_id=existing_document_id,
        )
    except Exception as e:
        if enqueue_on_failure:
            # Ingest raised. Enqueue for retry; the bw write already
            # succeeded (live-write path).
            logger.warning(
                "bw_ingest_failed: enqueuing for retry "
                "(slug=%s, ticket=%s, type=%s): %s",
                slug, ticket_id, source_type, e,
            )
            await _enqueue_retry(
                slug=slug,
                source_type=source_type,
                ticket_id=ticket_id,
                comment_n=comment_n,
                bw_commit_sha=bw_commit_sha,
                payload={
                    "kind": "ingest",
                    "slug": slug,
                    "source_type": source_type,
                    "ticket_id": ticket_id,
                    "comment_n": comment_n,
                    "text": text,
                    "metadata": metadata,
                    "agent_id": agent_id,
                    "uri": uri,
                },
                error=e,
            )
            return {
                "ingest_status": "enqueued_for_retry",
                "ticket_id": ticket_id,
                "source_type": source_type,
                "bw_commit_sha": bw_commit_sha,
                "error": str(e),
            }
        # Re-embed path: surface the failure to the caller (the /reembed
        # route collects it into its `errors` summary). Recoverable by
        # re-running /reembed for this ticket (design §6.4 idempotency).
        logger.warning(
            "bw_reembed_failed: surfacing to caller "
            "(slug=%s, ticket=%s, type=%s): %s",
            slug, ticket_id, source_type, e,
        )
        return {
            "ingest_status": "error",
            "ticket_id": ticket_id,
            "source_type": source_type,
            "bw_commit_sha": bw_commit_sha,
            "error": str(e),
        }

    # ``documents.metadata`` is now seeded at INSERT time by
    # ``store_document(agent_metadata=...)`` inside _process_single_document
    # (ariadne--5f2). The previous inline update_document_metadata seed
    # call was the workaround for store_document not populating the
    # column; it has been subsumed and removed.

    # _process_single_document can return ``{"error": True, ...}`` for
    # non-exception failures (extraction empty, embedding failed, the
    # uuo-1 update_document_content "no documents row" caller error, etc.).
    # Live-write path enqueues those for retry; re-embed path surfaces them.
    if isinstance(result, dict) and result.get("error"):
        if enqueue_on_failure:
            logger.warning(
                "bw_ingest_error_dict: enqueuing for retry "
                "(slug=%s, ticket=%s, type=%s): %s",
                slug, ticket_id, source_type, result.get("message"),
            )
            await _enqueue_retry(
                slug=slug,
                source_type=source_type,
                ticket_id=ticket_id,
                comment_n=comment_n,
                bw_commit_sha=bw_commit_sha,
                payload={
                    "kind": "ingest",
                    "slug": slug,
                    "source_type": source_type,
                    "ticket_id": ticket_id,
                    "comment_n": comment_n,
                    "text": text,
                    "metadata": metadata,
                    "agent_id": agent_id,
                    "uri": uri,
                },
                error=RuntimeError(str(result.get("message"))),
            )
            return {
                "ingest_status": "enqueued_for_retry",
                "ticket_id": ticket_id,
                "source_type": source_type,
                "bw_commit_sha": bw_commit_sha,
                "error": result.get("message"),
            }
        logger.warning(
            "bw_reembed_error_dict: surfacing to caller "
            "(slug=%s, ticket=%s, type=%s): %s",
            slug, ticket_id, source_type, result.get("message"),
        )
        return {
            "ingest_status": "error",
            "ticket_id": ticket_id,
            "source_type": source_type,
            "bw_commit_sha": bw_commit_sha,
            "error": result.get("message"),
        }

    return {
        "ingest_status": "ok",
        "document_id": result.get("document_id"),
        "source_type": source_type,
        "bw_commit_sha": bw_commit_sha,
        # Propagated from _process_single_document so callers
        # (notably the bulk-seed adapter — see SPEC §Bulk seed adapter)
        # can distinguish "POSTed but Ariadne already had identical
        # content" from "newly ingested". The enqueue-for-retry paths
        # above leave this key absent (the ingest didn't actually run,
        # so dedup semantics are undefined).
        "was_dedup_skip": bool(result.get("was_dedup_skip", False)),
    }


async def _ingest_bw_write(
    *,
    slug: str,
    source_type: str,           # 'body' | 'comment'
    ticket_id: str,
    bw_show_snapshot: dict[str, Any],  # the bw show --json dict after the write
    text: str,
    comment_n: Optional[int],
    principal: Principal,
) -> dict[str, Any]:
    """Create a new Ariadne document for a fresh bw body or comment.

    Called inside the per-slug lock, AFTER ``_run_bw`` returns success
    and AFTER ``_backup_push`` runs. The lock is held through this
    function so ordering between bw and Ariadne is preserved (see
    design §D2.4 + W1).

    ariadne--uuo.5: this is now a thin wrapper around
    ``_ingest_bw_snapshot``. It still does the one thing the snapshot core
    deliberately does NOT — fetch the just-completed mutation's SHA +
    author from ``bw history`` — then delegates the metadata-build /
    render / store / retry-handling tail to the shared core with
    ``force=False`` (a fresh doc has no old chunks) and
    ``existing_document_id=None`` (fresh INSERT via ``store_document``).

    Per §D6 author semantics: for new-doc ingest, the just-completed
    mutation's author IS the doc author (the actor who just made the
    POST /tickets is the body author; the actor who just made the
    POST /comments is the comment author). For PATCH-meta, the original
    body author is fetched separately — see ``_patch_bw_body_metadata``.

    Failure mode: any exception while ingesting enqueues the payload for
    background retry (Postgres queue → file fallback). Returns the
    ingest result dict on success, or a small ack dict on enqueued retry.
    """
    sha, sha_author = await _bw_history_head(slug, ticket_id)
    return await _ingest_bw_snapshot(
        slug=slug,
        source_type=source_type,
        ticket_id=ticket_id,
        bw_show_snapshot=bw_show_snapshot,
        text=text,
        comment_n=comment_n,
        agent_id=principal.user_id,
        bw_commit_sha=sha,
        bw_author=sha_author,
        force=False,
        existing_document_id=None,
        enqueue_on_failure=True,
    )


# ── In-place re-embed (ariadne--uuo.5) ──────────────────────────────────────
#
# The GOOD migration path (design §6). `POST /reembed` walks existing bw
# tickets on disk and re-ingests each body + comment in place — same
# `documents.id`, new clean embed-content under the uuo-2 logic — without
# recreating any bw ticket. `_reembed_tickets` is the orchestrator the
# route delegates to; `_detect_orphan_tickets` is the §6.7.1
# detect-and-report pass.


def _collection_ticket_ids(slug: str) -> set[str]:
    """Return the set of distinct ``ticket_id``s present in the slug's docs.

    ariadne--uuo.5 (design §6.7.1). Reads the live (non-deleted)
    ``documents`` rows for the slug's collection and collects every
    ``metadata.ticket_id``. The set difference ``this - repo_ticket_ids``
    is the orphaned-ticket set: docs in pgvector whose source ticket is no
    longer in the on-disk bw repo, so the ``/reembed`` walk never visits
    them and they keep stale chunks invisibly.

    Sync function — callers wrap in ``asyncio.to_thread``.
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import InMemoryDedupStore, PgDedupStore

    if isinstance(_dedup_store, InMemoryDedupStore):
        ids: set[str] = set()
        for doc in _dedup_store._documents.values():
            if doc.collection_id != slug:
                continue
            if doc.document_id in _dedup_store._deletions:
                continue
            meta = _dedup_store._doc_metadata.get(doc.document_id, {})
            tid = meta.get("ticket_id")
            if isinstance(tid, str) and tid:
                ids.add(tid)
        return ids

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT d.metadata->>'ticket_id'
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(slug)s
                      AND d.deleted_at IS NULL
                      AND d.metadata->>'ticket_id' IS NOT NULL
                    """,
                    {"slug": slug},
                )
                return {row[0] for row in cur.fetchall() if row[0]}
    return set()


def _detect_orphan_tickets(slug: str, repo_ticket_ids: set[str]) -> list[str]:
    """Return the orphaned-ticket set + emit a structured log line per orphan.

    ariadne--uuo.5 (design §6.7.1). An orphaned ticket is one whose docs
    live in pgvector but whose ID is absent from the on-disk bw repo
    enumeration (``repo_ticket_ids``). The ``/reembed`` walk cannot
    re-embed them (no source ticket to read) — but it must make the
    invisible visible. This is **detect-and-report, not auto-delete**:
    auto-deleting on a transient state (a partially-synced repo, a ticket
    mid-rename) would be destructive; the disposition is an operator call.

    Emits a ``reembed-orphan-ticket`` WARNING per orphan so it surfaces in
    deployment logs, and returns the sorted orphan list for the route's
    summary response.
    """
    orphans = sorted(_collection_ticket_ids(slug) - repo_ticket_ids)
    for ticket_id in orphans:
        logger.warning(
            "reembed-orphan-ticket",
            extra={
                "slug": slug,
                "ticket_id": ticket_id,
                "reason": (
                    "documents row in pgvector but ticket absent from the "
                    "on-disk bw repo — not re-embedded, not deleted"
                ),
            },
        )
    return orphans


async def _reembed_tickets(
    *,
    slug: str,
    ticket_ids: Optional[list[str]] = None,
    dry_run: bool = False,
    agent_id: str,
) -> dict[str, Any]:
    """Re-embed bw tickets in place — the ``POST /reembed`` orchestrator.

    ariadne--uuo.5 (design §6.3). Walks the on-disk bw repo for ``slug``,
    and for each ticket re-ingests the body + every comment via
    ``_ingest_bw_snapshot(force=True, existing_document_id=...)`` so the
    new clean (uuo-2) embed-content lands on the *same* ``documents.id``s.

    Per-ticket lock scope (design §6.8, W-3): the shipped per-slug
    ``_lock_for(slug)`` primitive is acquired/released at the **per-ticket
    boundary** — held atomically across one ticket's body + entire
    comments loop, released between tickets. This closes the half-state
    window (a live write landing between a ticket's body and comment-3
    re-embed) without holding the lock for the whole multi-hour corpus
    run.

    Reconciliation branches:
      • §6.7.1 — docs in pgvector but absent from the bw repo are
        detected, logged (``reembed-orphan-ticket``), and returned in
        ``orphaned_tickets``; never auto-deleted.
      • §6.7.2 — a ticket the walk visits whose slot has no resolved
        ``documents.id`` is INSERTed fresh (``existing_document_id=None``
        fall-through), never skipped.

    ``dry_run=True`` enumerates + counts + runs the §6.7.1 orphan
    detection, and writes nothing (no ``_process_single_document`` call).

    Fingerprint note: ``content_fingerprint`` drifts run-to-run because
    ``_build_agent_metadata`` stamps a fresh wall-clock ``bw_timestamp``
    into the salt on every ingest. Idempotency holds anyway — the
    re-embed path keys by ``documents.id`` (via ``update_document_content``),
    never by fingerprint, and always passes ``force=True``. (Design §6.4's
    "fingerprint stable across runs" prose is stale; the stable
    operational end-state is ids + chunk count + chunk content.)

    Returns the summary dict:
      ``{reembedded, fresh_inserted, orphaned_tickets, errors, dry_run}``.
    """
    # bw_routes import is lazy because bw_routes imports this module;
    # importing it at the top would create a cycle. bw_repo (stdlib-only,
    # no cycle) is imported function-locally too, simply to keep both
    # _reembed_tickets dependencies co-located at the one call site.
    from pipeline.api.bw_routes import _lock_for, _resolve_repo_path
    from pipeline.api import bw_repo

    repo_path = _resolve_repo_path(slug)

    # Enumerate the on-disk bw repo. A bounded git timeout keeps a wedged
    # invocation from pinning the request thread.
    try:
        all_repo_ids = await asyncio.to_thread(
            bw_repo.list_ticket_ids, repo_path, timeout=30.0
        )
    except bw_repo.BwRepoConfigError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "bw_repo_enumeration_failed", "message": str(exc)},
        ) from exc
    except bw_repo.BwRepoError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "bw_repo_enumeration_failed", "message": str(exc)},
        ) from exc

    repo_ticket_ids = set(all_repo_ids)

    # Restrict to the caller's subset if supplied (uuo-6's 20-ticket A/B
    # and per-ticket recovery use this). Unknown IDs are reported as
    # errors rather than silently dropped.
    errors: list[dict[str, Any]] = []
    if ticket_ids is not None:
        requested = list(dict.fromkeys(ticket_ids))  # de-dup, preserve order
        walk_ids = [tid for tid in requested if tid in repo_ticket_ids]
        for tid in requested:
            if tid not in repo_ticket_ids:
                errors.append({
                    "ticket_id": tid,
                    "error": "ticket_id not present in the on-disk bw repo",
                })
    else:
        walk_ids = list(all_repo_ids)

    # §6.7.1 orphan detection — runs for both dry-run and live.
    orphaned_tickets = await asyncio.to_thread(
        _detect_orphan_tickets, slug, repo_ticket_ids
    )

    reembedded = 0
    fresh_inserted = 0

    if dry_run:
        # Enumerate + count + orphan-detect only — write nothing. The
        # "count" is the number of docs that *would* be touched: body +
        # comments per visited ticket.
        would_touch = 0
        for tid in walk_ids:
            try:
                ticket = await asyncio.to_thread(
                    bw_repo.read_ticket, repo_path, tid, timeout=30.0
                )
            except bw_repo.BwRepoError as exc:
                errors.append({"ticket_id": tid, "error": str(exc)})
                continue
            comments = ticket.get("comments") or []
            would_touch += 1 + len(comments)  # body + each comment
        return {
            "dry_run": True,
            "tickets_enumerated": len(walk_ids),
            "docs_would_reembed": would_touch,
            "reembedded": 0,
            "fresh_inserted": 0,
            "orphaned_tickets": orphaned_tickets,
            "errors": errors,
        }

    # Live re-embed. One ticket at a time, lock held per-ticket.
    lock = await _lock_for(slug)
    for tid in walk_ids:
        try:
            ticket = await asyncio.to_thread(
                bw_repo.read_ticket, repo_path, tid, timeout=30.0
            )
        except bw_repo.BwRepoError as exc:
            errors.append({"ticket_id": tid, "error": str(exc)})
            continue

        # Resolve this ticket's existing per-slot doc IDs ONCE, before the
        # lock — a read-only query, and the slot map is stable for the
        # duration of the ticket's re-embed because the lock (acquired
        # next) blocks any live write to the slug. Resolving inside vs
        # outside the lock is equivalent for correctness; outside keeps
        # the lock-held critical section to just the writes.
        slot_map = await asyncio.to_thread(
            _resolve_ticket_doc_id_map, slug=slug, ticket_id=tid
        )

        # SHA for the salt: the existing ticket's current orphan-branch
        # tip (design §6.2 — "the current state of this ticket, which is
        # exactly the salt we want"). Author for the body: the original
        # create-row author, stable across mutations.
        sha, _sha_author = await _bw_history_head(slug, tid)
        body_author = await _bw_body_author(slug, tid)

        # ── per-ticket lock: body + entire comments loop held atomically ──
        async with lock:
            # Body doc.
            body_slot: tuple[str, Optional[int]] = ("body", None)
            body_existing_id = slot_map.get(body_slot)
            body_result = await _ingest_bw_snapshot(
                slug=slug,
                source_type="body",
                ticket_id=tid,
                bw_show_snapshot=ticket,
                text=ticket.get("description") or "",
                comment_n=None,
                agent_id=agent_id,
                bw_commit_sha=sha,
                bw_author=body_author,
                force=True,
                existing_document_id=body_existing_id,
                enqueue_on_failure=False,
            )
            if body_result.get("ingest_status") == "ok":
                if body_existing_id is not None:
                    reembedded += 1
                else:
                    fresh_inserted += 1
            else:
                errors.append({
                    "ticket_id": tid,
                    "source_type": "body",
                    "error": body_result.get("error"),
                })

            # Comments — comment_n is 1-indexed, matching the live
            # comment-add path's `len(comments)` rule.
            comments = ticket.get("comments") or []
            for idx, comment in enumerate(comments, start=1):
                if not isinstance(comment, dict):
                    errors.append({
                        "ticket_id": tid,
                        "source_type": "comment",
                        "comment_n": idx,
                        "error": "comment entry is not an object",
                    })
                    continue
                comment_slot: tuple[str, Optional[int]] = ("comment", idx)
                comment_existing_id = slot_map.get(comment_slot)
                # The comment's own author from the on-disk JSON; falls
                # back to the body author when bw didn't record one.
                comment_author = comment.get("author") or body_author
                comment_result = await _ingest_bw_snapshot(
                    slug=slug,
                    source_type="comment",
                    ticket_id=tid,
                    bw_show_snapshot=ticket,
                    text=comment.get("text") or "",
                    comment_n=idx,
                    agent_id=agent_id,
                    bw_commit_sha=sha,
                    bw_author=comment_author,
                    force=True,
                    existing_document_id=comment_existing_id,
                    enqueue_on_failure=False,
                )
                if comment_result.get("ingest_status") == "ok":
                    if comment_existing_id is not None:
                        reembedded += 1
                    else:
                        fresh_inserted += 1
                else:
                    errors.append({
                        "ticket_id": tid,
                        "source_type": "comment",
                        "comment_n": idx,
                        "error": comment_result.get("error"),
                    })
        # ── lock released here — a live write to the slug CAN now land
        #    before the next ticket's re-embed begins (design §6.8). ──

    return {
        "dry_run": False,
        "tickets_enumerated": len(walk_ids),
        "reembedded": reembedded,
        "fresh_inserted": fresh_inserted,
        "orphaned_tickets": orphaned_tickets,
        "errors": errors,
    }


# ── Helper 2: PATCH-meta on existing body doc ───────────────────────────────


async def _patch_bw_body_metadata(
    *,
    slug: str,
    ticket_id: str,
    bw_show_snapshot: dict[str, Any],
    principal: Principal,
) -> dict[str, Any]:
    """Re-emit the full ``agent_metadata`` surface against the body doc.

    Called for label-add, label-remove, status-change, defer/undefer,
    start, close-without-reason, and the fields-only branch of
    ``PATCH /tickets/{id}``. The bw repo just received a mutation that
    DOES NOT create a new document but DOES change the searchable
    surface — labels, status, assignee, parent — so the body doc's
    latest interaction must be updated.

    Per design §D3.1: MUST send the FULL agent_metadata surface
    (re-derived from bw state), not a delta. Phase 1's filter resolves
    against the latest interaction, so a partial surface would silently
    drop ``ticket_id`` / ``project`` / ``author`` from the filter
    visibility of subsequent searches.

    The body author is preserved across the PATCH by re-reading
    ``bw history`` and filtering to the ``create`` row (see
    ``_bw_body_author``). Step 2 of §D3.1.
    """
    sha, _patch_author = await _bw_history_head(slug, ticket_id)
    body_author = await _bw_body_author(slug, ticket_id)

    metadata = _build_agent_metadata(
        ticket_id=ticket_id,
        slug=slug,
        source_type="body",
        comment_n=None,
        bw_commit_sha=sha,
        bw_status=bw_show_snapshot.get("status"),
        bw_author=body_author,  # <-- body author, NOT patch author
        bw_assignee=bw_show_snapshot.get("assignee") or None,
        bw_parent=bw_show_snapshot.get("parent") or None,
        bw_labels=list(bw_show_snapshot.get("labels") or []),
        bw_timestamp=_now_utc_isoformat(),
        # ariadne--uuo.2: keep documents.metadata complete on PATCH-meta —
        # title/type are part of the full re-emitted surface. The bw
        # mutation subcommands feeding this path (update / start / label /
        # defer / reopen / close-without-reason) carry top-level
        # "title"/"type" in their --json; the close route unwraps its
        # nested "issue" shape before calling here.
        ticket_title=bw_show_snapshot.get("title") or None,
        ticket_type=bw_show_snapshot.get("type") or None,
    )

    try:
        doc_id = await asyncio.to_thread(
            _resolve_body_doc_id, slug=slug, ticket_id=ticket_id,
        )
        if doc_id is None:
            # No body doc exists yet (e.g., the body-create ingest failed
            # and is still in the retry queue). Skip the PATCH; the retry
            # worker will land the body doc on a later poll with the
            # body-create payload. The label / status mutation is in bw
            # and will be visible to Ariadne when the retry succeeds and
            # the next PATCH-meta lands.
            logger.info(
                "bw_patch_meta: no body doc yet for (slug=%s, ticket=%s); "
                "deferring PATCH-meta until body doc lands",
                slug, ticket_id,
            )
            return {
                "ingest_status": "deferred_no_body_doc",
                "ticket_id": ticket_id,
                "bw_commit_sha": sha,
            }

        # Two storage-layer calls in order, both on the thread pool —
        # see design §D2.1's "Why both calls are required, and in this
        # order" paragraph. The shape mirrors routes.py:860-922
        # (PATCH /api/documents/{id}), with the load-bearing difference
        # that we pass the FULL surface to both calls instead of the
        # caller's partial PATCH body.
        from pipeline.services import _dedup_store
        from pipeline.dedup import DocumentInteraction

        await asyncio.to_thread(
            _dedup_store.update_document_metadata,
            document_id=doc_id,
            agent_metadata=metadata,
        )
        await asyncio.to_thread(
            _dedup_store.record_interaction,
            DocumentInteraction(
                document_id=doc_id,
                collection_id=slug,
                agent_id=principal.user_id,
                agent_type="bw_bridge",
                initiated_by="bw_routes",
                agent_notes=None,
                agent_metadata=metadata,
                action="update",
                was_dedup_skip=False,
            ),
        )
    except Exception as e:
        logger.warning(
            "bw_patch_meta_failed: enqueuing for retry (slug=%s, ticket=%s): %s",
            slug, ticket_id, e,
        )
        await _enqueue_retry(
            slug=slug,
            source_type="patch_meta",
            ticket_id=ticket_id,
            comment_n=None,
            bw_commit_sha=sha,
            payload={
                "kind": "patch_meta",
                "slug": slug,
                "ticket_id": ticket_id,
                "metadata": metadata,
                "agent_id": principal.user_id,
            },
            error=e,
        )
        return {
            "ingest_status": "enqueued_for_retry",
            "ticket_id": ticket_id,
            "bw_commit_sha": sha,
            "error": str(e),
        }

    return {
        "ingest_status": "ok",
        "document_id": doc_id,
        "agent_metadata": metadata,
        "bw_commit_sha": sha,
    }


# ── Helper 3: soft-delete on ticket delete ──────────────────────────────────


async def _soft_delete_ticket_docs(*, slug: str, ticket_id: str) -> dict[str, Any]:
    """Soft-delete every Ariadne doc for a ticket (body + comments).

    Called from the ``DELETE /tickets/{id}?force=true`` route after bw's
    own delete returns success. Idempotent — re-delete is a no-op
    because the lookup filters on ``deleted_at IS NULL``.
    """
    from pipeline.services import _dedup_store

    ids = await asyncio.to_thread(
        _resolve_all_ticket_doc_ids, slug=slug, ticket_id=ticket_id,
    )
    for doc_id in ids:
        try:
            await asyncio.to_thread(_dedup_store.soft_delete_document, doc_id)
        except Exception as e:
            logger.warning(
                "bw_soft_delete_failed: (slug=%s, ticket=%s, doc=%s): %s",
                slug, ticket_id, doc_id, e,
            )
    return {"deleted_doc_ids": ids, "count": len(ids)}


# ── Soft-delete on body PATCH (design §D4) ──────────────────────────────────


async def _soft_delete_body_docs(*, slug: str, ticket_id: str) -> list[str]:
    """Soft-delete every body doc for a ticket.

    Used by ``PATCH /tickets/{id}`` when ``description`` (or ``title``)
    changes — per design §D4.1, the old body is soft-deleted before the
    new body is ingested. Returns the list of soft-deleted document IDs
    for observability.
    """
    from pipeline.services import _dedup_store

    # We need only body docs here; reuse _resolve_all_ticket_doc_ids and
    # filter, since the LIMIT-2 cap on _resolve_body_doc_id is wrong for
    # the "soft-delete every match" semantics described in §D4.1.
    ids: list[str] = []
    from pipeline.dedup import InMemoryDedupStore, PgDedupStore

    def _enumerate() -> list[str]:
        out: list[str] = []
        if isinstance(_dedup_store, InMemoryDedupStore):
            for doc in _dedup_store._documents.values():
                if doc.collection_id != slug:
                    continue
                if doc.document_id in _dedup_store._deletions:
                    continue
                meta = _dedup_store._doc_metadata.get(doc.document_id, {})
                if (
                    meta.get("ticket_id") == ticket_id
                    and meta.get("source_type") == "body"
                ):
                    out.append(doc.document_id)
            return out
        if isinstance(_dedup_store, PgDedupStore):
            with _dedup_store._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.id::text
                        FROM documents d
                        JOIN collections col ON d.collection_id = col.id
                        WHERE col.name = %(slug)s
                          AND d.metadata @> %(needle)s::jsonb
                          AND d.deleted_at IS NULL
                        """,
                        {
                            "slug": slug,
                            "needle": json.dumps({
                                "ticket_id": ticket_id,
                                "source_type": "body",
                            }),
                        },
                    )
                    return [row[0] for row in cur.fetchall()]
        return out

    ids = await asyncio.to_thread(_enumerate)
    for doc_id in ids:
        try:
            await asyncio.to_thread(_dedup_store.soft_delete_document, doc_id)
        except Exception as e:
            logger.warning(
                "bw_soft_delete_body_failed: (slug=%s, ticket=%s, doc=%s): %s",
                slug, ticket_id, doc_id, e,
            )
    return ids


# ── Retry-queue plumbing ────────────────────────────────────────────────────


async def _enqueue_retry(
    *,
    slug: str,
    source_type: str,
    ticket_id: str,
    comment_n: Optional[int],
    bw_commit_sha: str,
    payload: dict[str, Any],
    error: Exception,
) -> None:
    """Insert the failed ingest into ``bw_ingest_retry_queue``.

    On any exception from the Postgres insert, fall back to the on-disk
    JSONL file at ``${BW_REPOS_ROOT}/{slug}/.bw_ingest_dead_letter.jsonl``
    so the failure doesn't go silent on a Postgres-down failure mode
    (the Postgres-drop-during-enqueue case from design §D5.5 / W6).
    """
    try:
        await asyncio.to_thread(
            _enqueue_postgres,
            slug=slug,
            source_type=source_type,
            ticket_id=ticket_id,
            comment_n=comment_n,
            bw_commit_sha=bw_commit_sha,
            payload=payload,
            error=error,
        )
    except Exception as pg_e:
        logger.warning(
            "bw_ingest_retry_pg_enqueue_failed: falling back to file "
            "(slug=%s, ticket=%s, type=%s): %s",
            slug, ticket_id, source_type, pg_e,
        )
        await asyncio.to_thread(
            _enqueue_file_fallback,
            slug=slug,
            source_type=source_type,
            ticket_id=ticket_id,
            comment_n=comment_n,
            bw_commit_sha=bw_commit_sha,
            payload=payload,
            error=error,
            pg_error=pg_e,
        )


def _enqueue_postgres(
    *,
    slug: str,
    source_type: str,
    ticket_id: str,
    comment_n: Optional[int],
    bw_commit_sha: str,
    payload: dict[str, Any],
    error: Exception,
) -> None:
    """Synchronous: insert one row into ``bw_ingest_retry_queue``."""
    from pipeline.services import _dedup_store
    from pipeline.dedup import PgDedupStore

    # In-memory store path is for tests only; we use a module-level dict
    # to stand in for the table so tests can drive the retry behavior
    # without spinning Postgres.
    if not isinstance(_dedup_store, PgDedupStore):
        _IN_MEMORY_RETRY_QUEUE.append({
            "id": str(uuid.uuid4()),
            "slug": slug,
            "source_type": source_type,
            "ticket_id": ticket_id,
            "comment_n": comment_n,
            "bw_commit_sha": bw_commit_sha,
            "payload": payload,
            "enqueued_at": _now_utc_isoformat(),
            "last_attempt_at": None,
            "attempt_count": 0,
            "last_error": str(error),
            "next_attempt_at": _now_utc_isoformat(),
        })
        return

    with _dedup_store._pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bw_ingest_retry_queue (
                    slug, source_type, ticket_id, comment_n,
                    bw_commit_sha, payload, last_error
                ) VALUES (
                    %(slug)s, %(source_type)s, %(ticket_id)s, %(comment_n)s,
                    %(bw_commit_sha)s, %(payload)s::jsonb, %(last_error)s
                )
                """,
                {
                    "slug": slug,
                    "source_type": source_type,
                    "ticket_id": ticket_id,
                    "comment_n": comment_n,
                    "bw_commit_sha": bw_commit_sha,
                    "payload": json.dumps(payload),
                    "last_error": str(error),
                },
            )
        conn.commit()


# In-memory retry queue used by the test path (and any deploy not yet on
# Postgres). Read by ``_bw_retry_worker`` when the dedup store is not a
# PgDedupStore. Holds dicts in the same shape as the Postgres rows.
_IN_MEMORY_RETRY_QUEUE: list[dict[str, Any]] = []
_IN_MEMORY_DEAD_LETTER: list[dict[str, Any]] = []


def _enqueue_file_fallback(
    *,
    slug: str,
    source_type: str,
    ticket_id: str,
    comment_n: Optional[int],
    bw_commit_sha: str,
    payload: dict[str, Any],
    error: Exception,
    pg_error: Exception,
) -> None:
    """Append the failed payload to the per-slug JSONL fallback.

    Append-only one-line-per-record format. Atomic-by-line: open in
    ``'a'`` mode, write a single line ending with ``\\n``, fsync, close.
    The OS guarantees per-line atomicity for appends under ``O_APPEND``
    semantics on POSIX; on Windows the test path uses the in-memory
    fallback above and never touches the filesystem.
    """
    from pipeline.api.bw_routes import BW_REPOS_ROOT

    slug_dir = os.path.join(BW_REPOS_ROOT, slug)
    try:
        os.makedirs(slug_dir, exist_ok=True)
    except OSError as e:
        # If we can't even create the slug dir, log loudly. This is a
        # deploy problem — the bw repo's persistent volume is unreachable.
        logger.error(
            "bw_ingest_file_fallback_mkdir_failed (slug=%s): %s",
            slug, e,
        )
        return

    path = os.path.join(slug_dir, BW_FILE_FALLBACK_NAME)
    record = {
        "slug": slug,
        "source_type": source_type,
        "ticket_id": ticket_id,
        "comment_n": comment_n,
        "bw_commit_sha": bw_commit_sha,
        "payload": payload,
        "original_attempt_at": _now_utc_isoformat(),
        "error_class": type(error).__name__,
        "error_message": str(error),
        "pg_error_class": type(pg_error).__name__,
        "pg_error_message": str(pg_error),
    }
    line = json.dumps(record) + "\n"
    # 'a' mode opens append-only; fsync flushes the line to disk so a
    # crash doesn't lose it.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            # Some filesystems (tmpfs on certain configs) don't fsync;
            # treat as best-effort.
            pass


def _drain_file_fallback(slug: str) -> int:
    """Drain the file-fallback queue for one slug back into Postgres.

    Atomic-rename → read → re-INSERT → cleanup. Per design §D5.5 step 4.
    Returns the count of lines successfully drained. Lines that fail to
    re-INSERT into Postgres are appended back to a fresh
    ``.bw_ingest_dead_letter.jsonl`` so the next poll picks them up.
    """
    global _file_fallback_drain_count
    from pipeline.api.bw_routes import BW_REPOS_ROOT

    slug_dir = os.path.join(BW_REPOS_ROOT, slug)
    src = os.path.join(slug_dir, BW_FILE_FALLBACK_NAME)
    draining = os.path.join(slug_dir, BW_FILE_FALLBACK_DRAINING_NAME)

    if not os.path.exists(src):
        return 0

    # Atomic rename — any concurrent enqueue after this point lands in a
    # fresh src file that gets picked up on the next poll.
    try:
        os.replace(src, draining)
    except OSError as e:
        logger.warning(
            "bw_ingest_file_fallback_rename_failed (slug=%s): %s", slug, e,
        )
        return 0

    drained = 0
    requeued: list[str] = []
    try:
        with open(draining, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    logger.warning(
                        "bw_ingest_file_fallback_bad_json (slug=%s): "
                        "dropping line", slug,
                    )
                    continue
                try:
                    _enqueue_postgres(
                        slug=rec["slug"],
                        source_type=rec["source_type"],
                        ticket_id=rec["ticket_id"],
                        comment_n=rec.get("comment_n"),
                        bw_commit_sha=rec["bw_commit_sha"],
                        payload=rec["payload"],
                        error=RuntimeError(rec.get("error_message") or "(unknown)"),
                    )
                    drained += 1
                except Exception as e:
                    logger.warning(
                        "bw_ingest_file_fallback_pg_re_insert_failed "
                        "(slug=%s): %s",
                        slug, e,
                    )
                    requeued.append(line)
    finally:
        # If anything was re-queued (Postgres still flaky), write it
        # back to a fresh src file. Otherwise just delete the draining
        # file so we don't try to re-drain it.
        if requeued:
            with open(src, "a", encoding="utf-8") as fh:
                for line in requeued:
                    fh.write(line + "\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
        try:
            os.remove(draining)
        except OSError:
            pass

    if drained:
        _file_fallback_drain_count += drained
    return drained


def _file_fallback_pending_lines() -> int:
    """Sum of pending lines across all slugs' ``.bw_ingest_dead_letter.jsonl``.

    Cheap glob — at v1 scale (handful of slugs) this is microseconds.
    """
    from pipeline.api.bw_routes import BW_REPOS_ROOT

    total = 0
    if not os.path.isdir(BW_REPOS_ROOT):
        return 0
    for entry in os.listdir(BW_REPOS_ROOT):
        path = os.path.join(BW_REPOS_ROOT, entry, BW_FILE_FALLBACK_NAME)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                total += sum(1 for line in fh if line.strip())
        except OSError:
            continue
    return total


def _file_fallback_drain_count_metric() -> int:
    """Cumulative drained-line count since process start."""
    return _file_fallback_drain_count


# ── Retry replay ────────────────────────────────────────────────────────────


def _backoff_seconds(attempt_count: int) -> float:
    """Exponential backoff with ceiling. Pure function; no I/O."""
    delay = BW_RETRY_BASE_BACKOFF_SECONDS * (2 ** max(0, attempt_count))
    return min(delay, BW_RETRY_MAX_BACKOFF_SECONDS)


async def _replay_one_row(row: dict[str, Any]) -> tuple[bool, str | None]:
    """Replay one retry-queue row. Returns ``(success, reason_to_dead_letter)``.

    ``success=True`` means the ingest replay succeeded — caller deletes
    the row. ``success=False`` and ``reason_to_dead_letter is None``
    means retryable failure — caller bumps the attempt count. ``success=False``
    and ``reason_to_dead_letter`` is a string means caller must move the
    row to the dead-letter table immediately (e.g., the body-doc
    currency check from §D5.4a says this payload is stale-by-design).
    """
    payload: dict[str, Any] = row["payload"]
    kind = payload.get("kind", "ingest")
    slug = row["slug"]
    ticket_id = row["ticket_id"]
    sha_queued = row["bw_commit_sha"]

    # D5.4a: body-doc currency check.
    if kind == "ingest" and payload.get("source_type") == "body":
        check = await _body_doc_currency_check(
            slug=slug, ticket_id=ticket_id, sha_queued=sha_queued,
        )
        if check == "stale_by_design":
            return False, "stale_by_design"
        if check == "orphan_sha":
            return False, "orphan_sha"

    try:
        if kind == "ingest":
            await _replay_ingest(payload)
        elif kind == "patch_meta":
            await _replay_patch_meta(payload)
        else:
            logger.warning("retry_worker: unknown payload kind=%r", kind)
            return False, f"unknown_kind:{kind}"
    except Exception as e:
        logger.warning(
            "retry_worker: replay failed (slug=%s, ticket=%s, kind=%s): %s",
            slug, ticket_id, kind, e,
        )
        return False, None
    return True, None


async def _body_doc_currency_check(
    *, slug: str, ticket_id: str, sha_queued: str,
) -> str:
    """Decide whether the queued body-create payload is still current.

    Returns one of:
      - ``"ok"`` — no existing body doc, OR existing is the same as
        queued, OR queued is newer than existing in bw history.
      - ``"stale_by_design"`` — an existing body doc has a SHA that is
        newer than ``sha_queued`` in bw history; the queued payload is
        stale-by-design and re-creating it would corrupt the
        one-body-doc invariant. Dead-letter.
      - ``"orphan_sha"`` — ``sha_queued`` is not in bw history at all
        (operator-side orphan-branch surgery, or ``bw delete --force``
        purged the ticket). Dead-letter immediately rather than
        thrashing for hours (N1 addendum on §D5.4a).
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import InMemoryDedupStore, PgDedupStore

    # Find any existing body doc for this ticket.
    existing_doc_id: str | None = None
    existing_sha: str | None = None

    def _lookup() -> tuple[str | None, str | None]:
        if isinstance(_dedup_store, InMemoryDedupStore):
            for doc in _dedup_store._documents.values():
                if doc.collection_id != slug:
                    continue
                if doc.document_id in _dedup_store._deletions:
                    continue
                meta = _dedup_store._doc_metadata.get(doc.document_id, {})
                if (
                    meta.get("ticket_id") == ticket_id
                    and meta.get("source_type") == "body"
                ):
                    return doc.document_id, meta.get("bw_commit_sha")
            return None, None
        if isinstance(_dedup_store, PgDedupStore):
            with _dedup_store._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.id::text,
                               d.metadata->>'bw_commit_sha'
                        FROM documents d
                        JOIN collections col ON d.collection_id = col.id
                        WHERE col.name = %(slug)s
                          AND d.metadata @> %(needle)s::jsonb
                          AND d.deleted_at IS NULL
                        ORDER BY d.created_at DESC
                        LIMIT 1
                        """,
                        {
                            "slug": slug,
                            "needle": json.dumps({
                                "ticket_id": ticket_id,
                                "source_type": "body",
                            }),
                        },
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None, None
                    return row[0], row[1]
        return None, None

    existing_doc_id, existing_sha = await asyncio.to_thread(_lookup)

    if existing_doc_id is None or existing_sha is None:
        return "ok"
    if existing_sha == sha_queued:
        # Already ingested (perhaps by a previous retry that succeeded
        # partway through). Dedup will short-circuit; just replay.
        return "ok"

    # Need to compare positions in bw history.
    from pipeline.api.bw_routes import _run_bw

    try:
        result = await _run_bw(
            slug, "history", ticket_id, "--json",
            json_output=True,
        )
    except HTTPException as e:
        # If bw history itself fails (e.g., ticket deleted, bw error),
        # treat as orphan-SHA and dead-letter rather than thrashing.
        logger.warning(
            "currency_check: bw history failed (slug=%s, ticket=%s): %s",
            slug, ticket_id, e.detail,
        )
        return "orphan_sha"

    items = result.get("items") if isinstance(result, dict) else None
    if not items or not isinstance(items, list):
        return "orphan_sha"

    hashes = [r.get("hash") for r in items if isinstance(r, dict)]
    # N1 addendum: if sha_queued is no longer in history (orphan-branch
    # surgery, force-delete), dead-letter immediately.
    if sha_queued not in hashes:
        return "orphan_sha"
    if existing_sha not in hashes:
        # Existing doc references a SHA not in current history — itself
        # an anomaly. Don't dead-letter on it; let dedup short-circuit
        # the replay and move on.
        return "ok"
    queued_idx = hashes.index(sha_queued)
    existing_idx = hashes.index(existing_sha)
    if queued_idx < existing_idx:
        # Queued is older than existing — stale by design.
        return "stale_by_design"
    return "ok"


async def _replay_ingest(payload: dict[str, Any]) -> None:
    """Re-run ``_ingest_bw_write``'s storage tail with the captured payload."""
    from pipeline.services import _process_single_document

    metadata = payload["metadata"]
    text = payload["text"]
    # ariadne--uuo.2: the retry-queue payload shape is UNCHANGED — `text`
    # and `metadata` are already separate keys, and both render functions
    # are pure. A row enqueued under pre-uuo code still carries the same
    # `text`+`metadata`; `_render_embed_content` simply finds no
    # `ticket_title`/`ticket_type` in an old metadata dict and degrades to
    # the bare body. So in-flight retry rows replay correctly under new
    # code — design §3.5 migration-safety property.
    payload_bytes = _render_payload(metadata, text)
    embed_bytes = _render_embed_content(metadata, text)

    result = await asyncio.to_thread(
        _process_single_document,
        uri=payload["uri"],
        store=True,
        collection=payload["slug"],
        tags=[],
        force=False,
        agent_id=payload["agent_id"],
        agent_type="bw_bridge",
        model=None,
        initiated_by="bw_routes",
        agent_notes=None,
        agent_metadata=metadata,
        chunking_config=None,
        ingest_config=None,
        action="ingest",
        inline_content=payload_bytes,
        inline_embed_content=embed_bytes,
    )
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result.get("message")))
    # documents.metadata is seeded at INSERT time inside
    # _process_single_document → store_document(agent_metadata=...) per
    # ariadne--5f2. The follow-up update_document_metadata call that
    # previously lived here has been removed.


async def _replay_patch_meta(payload: dict[str, Any]) -> None:
    """Re-run ``_patch_bw_body_metadata``'s storage tail with captured metadata.

    Per §D5.4: replay uses the metadata captured at enqueue time, NOT a
    fresh ``bw show`` re-read. If multiple PATCH-metas land in the queue
    for the same ticket they replay in ``enqueued_at`` order — the
    latest-interaction filter resolves to the most recent (which is the
    most recent bw mutation). Correct.
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import DocumentInteraction

    slug = payload["slug"]
    ticket_id = payload["ticket_id"]
    metadata = payload["metadata"]
    agent_id = payload["agent_id"]

    doc_id = await asyncio.to_thread(
        _resolve_body_doc_id, slug=slug, ticket_id=ticket_id,
    )
    if doc_id is None:
        # Body doc still doesn't exist. Re-raise so the row stays in the
        # queue for another retry — the body-create ingest may land on a
        # later poll and unblock this PATCH-meta then.
        raise RuntimeError(
            f"no body doc for (slug={slug}, ticket={ticket_id}) — "
            "deferred until body doc lands"
        )
    await asyncio.to_thread(
        _dedup_store.update_document_metadata,
        document_id=doc_id,
        agent_metadata=metadata,
    )
    await asyncio.to_thread(
        _dedup_store.record_interaction,
        DocumentInteraction(
            document_id=doc_id,
            collection_id=slug,
            agent_id=agent_id,
            agent_type="bw_bridge",
            initiated_by="bw_routes",
            agent_notes=None,
            agent_metadata=metadata,
            action="update",
            was_dedup_skip=False,
        ),
    )


# ── Retry worker (background task) ──────────────────────────────────────────


async def _bw_retry_worker_iteration() -> dict[str, int]:
    """One iteration: drain file fallbacks, pull due Postgres rows, replay.

    Returns a dict of counters useful for tests + observability.
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import PgDedupStore
    from pipeline.api.bw_routes import BW_REPOS_ROOT

    counts = {
        "file_drained": 0,
        "pg_replayed": 0,
        "pg_failed": 0,
        "dead_lettered": 0,
    }

    # Step 1: drain per-slug file fallbacks if any.
    if os.path.isdir(BW_REPOS_ROOT):
        for entry in os.listdir(BW_REPOS_ROOT):
            path = os.path.join(BW_REPOS_ROOT, entry, BW_FILE_FALLBACK_NAME)
            if os.path.isfile(path):
                counts["file_drained"] += _drain_file_fallback(entry)

    # Step 2: pull due rows from the queue (Postgres or in-memory).
    if isinstance(_dedup_store, PgDedupStore):
        rows = await asyncio.to_thread(_pull_due_rows_pg)
    else:
        rows = _pull_due_rows_in_memory()

    for row in rows:
        success, dl_reason = await _replay_one_row(row)
        if success:
            await asyncio.to_thread(_remove_row, row)
            counts["pg_replayed"] += 1
        elif dl_reason is not None:
            await asyncio.to_thread(_dead_letter_row, row, dl_reason)
            counts["dead_lettered"] += 1
        else:
            # ``_bump_attempt`` returns the NEW attempt_count (post-bump)
            # so the max-attempts check is path-agnostic. The Postgres
            # path issues an UPDATE while ``row`` stays a SELECT snapshot
            # (post-bump ``row["attempt_count"]`` would still be the OLD
            # value), and the in-memory path mutates ``row`` in place
            # (post-bump ``row["attempt_count"]`` would be the NEW value);
            # using the return value sidesteps that asymmetry. See
            # ``_bump_attempt`` below.
            new_attempt = await asyncio.to_thread(_bump_attempt, row)
            counts["pg_failed"] += 1
            if new_attempt >= BW_RETRY_MAX_ATTEMPTS:
                await asyncio.to_thread(_dead_letter_row, row, "max_attempts")
                counts["dead_lettered"] += 1
                counts["pg_failed"] -= 1  # was counted; replace with DL

    return counts


def _pull_due_rows_pg() -> list[dict[str, Any]]:
    from pipeline.services import _dedup_store

    with _dedup_store._pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, slug, source_type, ticket_id, comment_n,
                       bw_commit_sha, payload, attempt_count, next_attempt_at
                FROM bw_ingest_retry_queue
                WHERE next_attempt_at <= now()
                ORDER BY next_attempt_at
                LIMIT %(limit)s
                """,
                {"limit": BW_RETRY_BATCH_SIZE},
            )
            rows: list[dict[str, Any]] = []
            for r in cur.fetchall():
                rows.append({
                    "id": r[0],
                    "slug": r[1],
                    "source_type": r[2],
                    "ticket_id": r[3],
                    "comment_n": r[4],
                    "bw_commit_sha": r[5],
                    "payload": r[6],
                    "attempt_count": r[7] or 0,
                    "next_attempt_at": r[8],
                })
            return rows


def _pull_due_rows_in_memory() -> list[dict[str, Any]]:
    now = _now_utc_isoformat()
    due: list[dict[str, Any]] = []
    for r in list(_IN_MEMORY_RETRY_QUEUE):
        if r["next_attempt_at"] <= now:
            due.append(r)
        if len(due) >= BW_RETRY_BATCH_SIZE:
            break
    return due


def _remove_row(row: dict[str, Any]) -> None:
    from pipeline.services import _dedup_store
    from pipeline.dedup import PgDedupStore

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bw_ingest_retry_queue WHERE id = %(id)s::uuid",
                    {"id": row["id"]},
                )
            conn.commit()
        return
    # In-memory: identify by id.
    _IN_MEMORY_RETRY_QUEUE[:] = [
        r for r in _IN_MEMORY_RETRY_QUEUE if r["id"] != row["id"]
    ]


def _bump_attempt(row: dict[str, Any]) -> int:
    """Bump attempt_count + reschedule next_attempt_at via backoff.

    Returns the NEW attempt_count (post-bump). Callers should use this
    return value for max-attempts comparisons rather than re-reading
    ``row["attempt_count"]``: the Postgres path UPDATEs out-of-band so
    ``row`` (a SELECT snapshot) still holds the pre-bump value, while
    the in-memory path mutates ``row`` in place so the same field holds
    the post-bump value. Returning the value makes the check
    path-agnostic and pins the contract here.
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import PgDedupStore

    new_attempt = (row["attempt_count"] or 0) + 1
    backoff = _backoff_seconds(new_attempt)

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bw_ingest_retry_queue
                    SET attempt_count = %(c)s,
                        last_attempt_at = now(),
                        next_attempt_at = now() + (%(s)s || ' seconds')::interval
                    WHERE id = %(id)s::uuid
                    """,
                    {"c": new_attempt, "s": str(backoff), "id": row["id"]},
                )
            conn.commit()
        return new_attempt

    # In-memory bump.
    now_dt = datetime.now(timezone.utc)
    next_dt = now_dt.timestamp() + backoff
    next_iso = datetime.fromtimestamp(next_dt, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    for r in _IN_MEMORY_RETRY_QUEUE:
        if r["id"] == row["id"]:
            r["attempt_count"] = new_attempt
            r["last_attempt_at"] = _now_utc_isoformat()
            r["next_attempt_at"] = next_iso
            break
    return new_attempt


def _dead_letter_row(row: dict[str, Any], reason: str) -> None:
    """Move row from retry queue to dead-letter table with a reason."""
    from pipeline.services import _dedup_store
    from pipeline.dedup import PgDedupStore

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bw_ingest_retry_dead_letter (
                        slug, source_type, ticket_id, comment_n,
                        bw_commit_sha, payload, enqueued_at,
                        last_attempt_at, attempt_count, last_error,
                        gave_up_reason
                    )
                    SELECT slug, source_type, ticket_id, comment_n,
                           bw_commit_sha, payload, enqueued_at,
                           last_attempt_at, attempt_count, last_error,
                           %(reason)s
                    FROM bw_ingest_retry_queue
                    WHERE id = %(id)s::uuid
                    """,
                    {"id": row["id"], "reason": reason},
                )
                cur.execute(
                    "DELETE FROM bw_ingest_retry_queue WHERE id = %(id)s::uuid",
                    {"id": row["id"]},
                )
            conn.commit()
        return

    # In-memory.
    for r in list(_IN_MEMORY_RETRY_QUEUE):
        if r["id"] == row["id"]:
            r_copy = dict(r)
            r_copy["gave_up_reason"] = reason
            r_copy["gave_up_at"] = _now_utc_isoformat()
            _IN_MEMORY_DEAD_LETTER.append(r_copy)
            _IN_MEMORY_RETRY_QUEUE.remove(r)
            return


async def _bw_retry_worker() -> None:
    """Long-running background task: poll + drain.

    Started by ``app.py``'s lifespan; canceled on app shutdown. Each
    iteration is independently safe — an exception during one iteration
    is logged and the loop continues, so a transient DB blip never
    terminates the worker.
    """
    logger.info("bw_retry_worker started (poll=%.1fs)", BW_RETRY_POLL_SECONDS)
    try:
        while True:
            try:
                counts = await _bw_retry_worker_iteration()
                if any(counts.values()):
                    logger.info("bw_retry_worker: %s", counts)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("bw_retry_worker: iteration crashed: %s", e)
            await asyncio.sleep(BW_RETRY_POLL_SECONDS)
    except asyncio.CancelledError:
        logger.info("bw_retry_worker canceled")
        raise


# ── Observability surface ──────────────────────────────────────────────────


def get_retry_metrics() -> dict[str, Any]:
    """Return the current retry-queue depth + dead-letter count + per-slug breakdown.

    Used by the ``/api/bw/health`` route. Cheap query — the depth and
    per-slug counts hit the ``idx_bw_ingest_retry_slug`` index.
    """
    from pipeline.services import _dedup_store
    from pipeline.dedup import PgDedupStore

    if isinstance(_dedup_store, PgDedupStore):
        with _dedup_store._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM bw_ingest_retry_queue")
                depth = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM bw_ingest_retry_dead_letter")
                dead = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT slug, count(*) FROM bw_ingest_retry_queue
                    GROUP BY slug
                    """,
                )
                by_slug = {row[0]: row[1] for row in cur.fetchall()}
        return {
            "bw_ingest_retry_queue_depth": depth,
            "bw_ingest_retry_dead_letter_count": dead,
            "bw_ingest_retry_by_slug": by_slug,
            "bw_ingest_file_fallback_drain_count": _file_fallback_drain_count_metric(),
            "bw_ingest_file_fallback_pending_lines": _file_fallback_pending_lines(),
        }

    by_slug: dict[str, int] = {}
    for r in _IN_MEMORY_RETRY_QUEUE:
        by_slug[r["slug"]] = by_slug.get(r["slug"], 0) + 1
    return {
        "bw_ingest_retry_queue_depth": len(_IN_MEMORY_RETRY_QUEUE),
        "bw_ingest_retry_dead_letter_count": len(_IN_MEMORY_DEAD_LETTER),
        "bw_ingest_retry_by_slug": by_slug,
        "bw_ingest_file_fallback_drain_count": _file_fallback_drain_count_metric(),
        "bw_ingest_file_fallback_pending_lines": _file_fallback_pending_lines(),
    }
