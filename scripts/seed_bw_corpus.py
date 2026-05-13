#!/usr/bin/env python3
"""Bulk-seed a source ``bw`` (beadwork) repo into Ariadne via the
Phase 2 HTTP surface + Phase 3 inline ingest.

Reads tickets from the source repo's orphan ``beadwork`` branch via
``git show`` (no ``bw`` CLI dependency on the caller's machine), POSTs
each ticket and its comments via the Phase 2 endpoints, and lets
Phase 3's ``_ingest_bw_write`` push them into the Ariadne search index
inline. The script itself is generic — any beadwork corpus on the
caller's machine is just a value of ``--bw-repo``.

Usage::

    python scripts/seed_bw_corpus.py \\
        --bw-repo /path/to/source-bw-repo \\
        --project target-slug \\
        --limit 10

CLI contract (locked by the ariadne--8fd.6 brief)
-------------------------------------------------

``--bw-repo PATH``      Required. Path to the source bw repo. The script
                        reads tickets from this repo's orphan
                        ``beadwork`` branch via ``git show``; the repo
                        must have that branch populated (every bw-managed
                        repo does).

``--project SLUG``      Required. Target Ariadne project slug. Tickets
                        are POSTed to ``/api/bw/projects/{SLUG}/...``.
                        The slug must match the server's allow-list
                        ``^[a-z0-9_-]{1,64}$`` or the first POST fails
                        with a 422.

``--limit N``           Optional. Cap the number of source tickets
                        seeded this run. Primarily for small-fire
                        validation against a fresh slug; omit for full
                        corpus seeds.

``--ariadne-host URL``  Optional. Ariadne base URL (no trailing slash).
                        Defaults to the same resolution chain the
                        ariadne CLI uses (``ARIADNE_HOST`` env, then
                        ``~/.config/ariadne/default``).

``--dry-run``           Optional. Enumerate + parse source tickets and
                        log what would be POSTed; make no HTTP calls.

``--start-after ID``    Optional. Resume from a specific source ticket.
                        Sorted enumeration order is asc(ticket-id);
                        ``--start-after`` skips every source ticket
                        with id <= the supplied value. Useful when the
                        state file is unavailable (fresh machine).

``--state-file PATH``   Optional. Override the seed-state JSON path.
                        Defaults to ``<bw-repo>/.ariadne_seed_state.json``.
                        The state file maps source ticket IDs to target
                        ticket IDs and is the script's idempotency
                        anchor — re-running against the same source
                        repo + state file skips already-seeded tickets.

``--rate-limit-sleep S``  Optional. Sleep this many seconds between
                        ticket POSTs to ride under a Gemini rate limit.
                        Default 0 (no sleep); the small-fire uses 0.

Auth
----

Production Ariadne requires ``Authorization: Bearer <jwt>`` on every
``/api/*`` endpoint. The script delegates to
:mod:`ariadne_core_client.auth` (the same module ``ariadne login`` /
``mcp_auth.py`` use), which honours ``ARIADNE_ACCESS_TOKEN`` env first,
then the OS keyring (populated by ``ariadne login``). No new auth
surface is invented here.

Idempotency
-----------

Two complementary mechanisms:

1. **Script-level state file.** The script writes
   ``<bw-repo>/.ariadne_seed_state.json`` mapping
   ``{source_ticket_id: {"target_id": <new>, "target_comments": <int>,
   "seeded_at": <ts>}}``. On restart the script reads this and skips
   every source ticket whose id is already a key. Comments are
   re-emitted only if the source has more comments than the state
   file recorded.

2. **Ariadne content_fingerprint dedup.** Phase 3 fingerprints the
   ingest payload and returns ``was_dedup_skip=true`` on a re-ingest
   of identical content. The script counts these separately
   (``dedup_skipped``) for the small-fire validation contract; they
   should be 0 on a first run and > 0 on a second run if the script's
   state file was deleted but content matches.

Both layers cooperate: the state file is the fast path (skip without
HTTP), the fingerprint dedup is the safety net.

Generic by design
-----------------

The script knows nothing about any specific corpus name or identity.
It accepts ``--bw-repo`` and ``--project`` and operates uniformly over
whatever lives in the source's orphan ``beadwork`` branch. The Phase 4
brief's audit guarantee — that this file is free of any per-corpus
naming in product code — is the load-bearing property of "generic".
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx


# ── Constants ───────────────────────────────────────────────────────────────

# Slug allow-list — must match the server's ``_SLUG_PATTERN`` in
# ``src/pipeline/api/bw_routes.py``. We validate client-side too so a
# bad slug fails fast (before the first HTTP round-trip) with a clear
# diagnostic, rather than surfacing as a 422 deep in the run.
_SLUG_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")

# Default state-file basename, written into the bw repo's working tree
# (alongside the orphan branch's source). Operators who want a different
# location can override via ``--state-file``.
_DEFAULT_STATE_FILENAME = ".ariadne_seed_state.json"

# HTTP request timeout. Phase 3 ingest does an embedding round-trip per
# POST, which can run 5-10s under typical Gemini throughput. 60s ceiling
# catches a hung embed without making timeouts a common failure mode.
_HTTP_TIMEOUT_SECONDS = 60.0

# Retry budget per POST. Phase 3 has its own retry queue for embedding
# failures, but a 5xx from the server itself (or a transient network
# blip) is worth one client-side retry before we count the call as
# failed and move on.
_HTTP_MAX_RETRIES = 1
_HTTP_RETRY_BACKOFF_SECONDS = 5.0


# ── Custom exceptions ──────────────────────────────────────────────────────


class SeedError(Exception):
    """Base class for seed-script-specific failures."""


class SeedConfigError(SeedError):
    """Configuration / argument problem the user can fix."""


# ── Auth resolution (delegates to ariadne_core_client.auth) ────────────────


def _bootstrap_client_path() -> None:
    """Inject ``client/src`` onto sys.path so ariadne_core_client is importable.

    This script lives at ``<repo-root>/scripts/seed_bw_corpus.py``; the
    Bearer-JWT auth helper lives at
    ``<repo-root>/client/src/ariadne_core_client/auth.py``. When the
    client package is editable-installed the import works without path
    manipulation. Mirror the pattern from ``scripts/mcp_auth.py`` so
    the script runs in an operator's cwd without ``pip install -e
    client/`` having been done first.
    """
    here = Path(__file__).resolve().parent
    candidate = here.parent / "client" / "src"
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _resolve_auth(
    explicit_host: Optional[str],
) -> tuple[str, str]:
    """Return ``(base_url, bearer_token)``.

    Precedence on the host:
      1. ``--ariadne-host`` (explicit_host parameter)
      2. ``ARIADNE_HOST`` env var (via auth.resolve_host)
      3. ``~/.config/ariadne/default`` (via auth.resolve_host)

    Token: ``auth.get_access_token`` walks ``ARIADNE_ACCESS_TOKEN`` env,
    cached keyring access token, then refreshes silently. Any failure
    raises ``SeedConfigError`` so the caller exits with a user-actionable
    message ("run ariadne login").
    """
    _bootstrap_client_path()
    try:
        from ariadne_core_client import auth as _auth
    except ImportError as exc:
        raise SeedConfigError(
            "ariadne_core_client.auth is not importable. Run "
            "`pip install -e client/` from the ariadne-core repo, or "
            "set ARIADNE_ACCESS_TOKEN and pass --ariadne-host."
        ) from exc

    try:
        host = _auth.resolve_host(explicit_host)
    except _auth.AuthError as exc:
        raise SeedConfigError(str(exc)) from exc

    try:
        token = _auth.get_access_token(host)
    except (_auth.AuthError, _auth.KeyringBackendUnavailable) as exc:
        raise SeedConfigError(str(exc)) from exc

    return host, token


# ── bw source enumeration (git show, no bw CLI dep) ────────────────────────


def _git_show(repo: Path, target: str) -> str:
    """Return stdout of ``git -C <repo> show <target>``.

    Raises ``SeedConfigError`` for missing repo / missing branch / git
    not on PATH; raises ``SeedError`` for unexpected non-zero exits.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "show", target],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SeedConfigError(
            "git binary not found on PATH"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        # Distinguish "no such repo / no such branch" (caller fix) from
        # other git failures (likely environment).
        if "not a git repository" in stderr.lower() or \
                "unknown revision" in stderr.lower() or \
                "bad revision" in stderr.lower():
            raise SeedConfigError(
                f"git show {target!r} failed: {stderr}. "
                f"Check that --bw-repo points at a bw-managed git repo "
                f"with a populated 'beadwork' branch."
            )
        raise SeedError(
            f"git show {target!r} failed (exit {proc.returncode}): "
            f"{stderr}"
        )
    return proc.stdout


def _list_source_ticket_ids(repo: Path) -> list[str]:
    """Enumerate ticket IDs in the source repo's beadwork branch.

    ``git show beadwork:issues`` returns a tree listing (one filename
    per line plus a header), e.g.::

        tree beadwork:issues

        .gitkeep
        ariadne--16a.json
        ariadne--1of.json
        ...

    We parse out the ``*.json`` filenames (dropping ``.gitkeep`` and
    the header) and strip the ``.json`` suffix to recover ticket IDs.
    Returns a sorted list so enumeration order is deterministic across
    machines and between the initial run and a resume.
    """
    raw = _git_show(repo, "beadwork:issues")
    ids: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "tree beadwork:issues" or line.startswith("tree "):
            continue
        if not line.endswith(".json"):
            continue
        ticket_id = line[: -len(".json")]
        if not ticket_id or ticket_id.startswith("."):
            continue
        ids.append(ticket_id)
    ids.sort()
    return ids


def _read_source_ticket(repo: Path, ticket_id: str) -> dict[str, Any]:
    """Return the parsed JSON for one source ticket.

    Schema (verified against ``bw 0.12.3`` on-disk format)::

        {
          "id": "<ticket-id>",
          "title": "<str>",
          "description": "<str>",
          "type": "task|bug|feature|...",
          "priority": 0..4,
          "status": "open|in_progress|closed|deferred",
          "labels": ["<str>", ...],
          "parent": "<ticket-id>" | "",
          "assignee": "<str>" | "",
          "blocked_by": [...],
          "blocks": [...],
          "created": "<iso8601>",
          "updated_at": "<iso8601>",
          "comments": [
            {"text": "<str>", "timestamp": "<iso8601>", "author": "<str>?"},
            ...
          ]
        }
    """
    raw = _git_show(repo, f"beadwork:issues/{ticket_id}.json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeedError(
            f"failed to parse beadwork:issues/{ticket_id}.json: {exc}"
        ) from exc


# ── State file (script-level idempotency anchor) ───────────────────────────


def _state_path(bw_repo: Path, override: Optional[Path]) -> Path:
    if override is not None:
        return override
    return bw_repo / _DEFAULT_STATE_FILENAME


def _state_file_inside_repo_and_untracked(
    bw_repo: Path, state_file: Path,
) -> bool:
    """True iff ``state_file`` lives inside ``bw_repo``'s working tree
    AND the source repo's ``.gitignore`` does not already exclude it.

    Cheap operator-safety check: a state file that lives inside the
    source repo and is NOT ignored will get silently staged by an
    accidental ``git add .`` in the source repo. We warn the operator
    so they can add it to ``.gitignore`` (or move it elsewhere via
    ``--state-file``) before that happens.

    Best-effort: false-negatives (no warning when one might help) are
    acceptable — this is a hygiene nudge, not a guard. We do not run
    git here to avoid surprising the operator with subprocess calls
    against the source repo just to compute a log line.
    """
    try:
        state_resolved = state_file.resolve()
        bw_resolved = bw_repo.resolve()
    except OSError:
        return False
    try:
        state_resolved.relative_to(bw_resolved)
    except ValueError:
        # state file is outside the bw repo — no risk of accidental staging.
        return False

    # State file IS inside the repo. Now check if .gitignore (root or any
    # directory between the state file and the repo root) lists the
    # state file's basename or the default basename. This is a literal
    # substring check — gitignore globbing would be more correct, but
    # the cost of a false-negative is just a redundant warning, which
    # is fine for a hygiene nudge.
    target_names = {state_resolved.name, _DEFAULT_STATE_FILENAME}
    gitignore = bw_repo / ".gitignore"
    if gitignore.exists():
        try:
            content = gitignore.read_text(encoding="utf-8")
        except OSError:
            content = ""
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # crude but sufficient: the basename appears anywhere in
            # the gitignore as its own line content (a bare name, a
            # glob, or with a leading ``/``).
            if any(name in stripped for name in target_names):
                return False
    return True


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    """Load the state file, or return an empty dict if missing/empty.

    Schema::

        {
          "<source-id>": {
            "target_id": "<new-id>",
            "target_comments": <int>,        # comments POSTed so far
            "seeded_at": "<iso8601>"
          },
          ...
        }
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedConfigError(
            f"state file {path} is unreadable or malformed: {exc}. "
            f"Move it aside or pass a different --state-file."
        ) from exc
    if not isinstance(data, dict):
        raise SeedConfigError(
            f"state file {path} must contain a JSON object at top level"
        )
    return data


def _save_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    """Persist state atomically (write-temp + os.replace).

    The atomic-rename pattern keeps the file readable at all times — a
    crash during write leaves the prior on-disk copy intact rather than
    leaving a half-written JSON the next run can't parse.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


# ── HTTP client (httpx, Bearer JWT) ────────────────────────────────────────


class _SeedHttp:
    """Thin httpx wrapper that adds Bearer auth + one-retry-with-backoff.

    Holds a single ``httpx.Client`` so the underlying connection pool is
    reused across the full run — important when POSTing thousands of
    tickets against a TLS-terminated Railway endpoint.

    Exposed as a class (rather than free functions on a module) so the
    unit tests can inject a fake (``DummyHttp``) at the same seam the
    real run uses.
    """

    def __init__(self, base_url: str, token: str, timeout: float = _HTTP_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "_SeedHttp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def post(self, path: str, json_body: dict[str, Any]) -> httpx.Response:
        """POST with one retry on transient (5xx / network) failure.

        Returns the final ``httpx.Response`` so callers can branch on
        status code + JSON body. Does not raise on 4xx / 5xx — caller
        decides how to interpret them. Raises ``SeedError`` only on
        a network failure that exceeds the retry budget.
        """
        attempt = 0
        while True:
            try:
                resp = self._client.post(path, json=json_body)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt < _HTTP_MAX_RETRIES:
                    time.sleep(_HTTP_RETRY_BACKOFF_SECONDS)
                    attempt += 1
                    continue
                raise SeedError(
                    f"POST {path} network failure after "
                    f"{attempt + 1} attempt(s): {exc}"
                ) from exc

            # Retry once on 5xx (transient server / gateway hiccup).
            if 500 <= resp.status_code < 600 and attempt < _HTTP_MAX_RETRIES:
                time.sleep(_HTTP_RETRY_BACKOFF_SECONDS)
                attempt += 1
                continue
            return resp

    def delete(self, path: str) -> httpx.Response:
        """DELETE — used by the small-fire cleanup to drop the test slug."""
        return self._client.delete(path)


# ── Per-ticket POST shape ──────────────────────────────────────────────────


def _ticket_create_body(
    source: dict[str, Any],
    parent_override: Optional[str] = None,
) -> dict[str, Any]:
    """Translate an on-disk bw ticket into a ``TicketCreate`` request body.

    ``TicketCreate`` (from ``src/pipeline/api/bw_routes.py``) accepts:
    ``title`` (required), ``description``, ``priority``, ``type``,
    ``defer``, ``due``, ``parent``. We omit any field that's not on
    the source (or is empty), so the server's defaults / unset
    semantics apply uniformly.

    Note: ``status``, ``assignee``, and ``labels`` are NOT propagated
    by this Phase 4 deliverable. ``bw create`` (and the Phase 2
    ``POST /tickets`` body) does not accept those fields at
    create-time, and the per-ticket loop below does NOT emit
    follow-up PATCHes. Seeded tickets land on the target with
    ``status: open``, no ``labels``, and no ``assignee``, regardless
    of the source values. Operators who need fidelity on those
    fields must extend this script post-seed (e.g., ``bw status`` /
    ``bw label`` / ``bw start --assignee`` against each target
    ticket) or wait on a follow-up enhancement (filed as follow-up).
    Documented as a Phase 4 limitation.

    Parent remap (ariadne--8fd.13)
    ------------------------------

    Source-side parent IDs do not survive into the destination corpus:
    bw allocates fresh 3-char suffixes per-repo, so source ``parent``
    references must be translated to the destination-side IDs the
    state file already records for previously-seeded tickets.

    ``parent_override`` carries that translation:

      * ``None`` (default) — top-level ticket. Source ``parent`` is
        ignored even if present; we never POST the source-side ID
        to the destination (it would 400 with "no issue found
        matching").
      * non-empty string — destination-side parent ID (the
        ``target_id`` recorded in the state file for the parent's
        source ID). Emitted as ``body["parent"]`` so the server
        creates the parent edge.

    The caller (``run`` /``_post_ticket_and_comments``) is responsible
    for resolving the source ``parent`` via the state map BEFORE
    calling this function. If the parent is not yet in the state map
    (would mean parents are out-of-dependency-order in the source
    enumeration), the caller skips the ticket entirely rather than
    falling back to the source-side ID — the 400 from bw is silent
    cascade-failure for every descendant, so we surface the gap
    early as a single ``errors`` count instead.
    """
    body: dict[str, Any] = {"title": source.get("title") or "(untitled)"}
    desc = source.get("description")
    if desc:
        body["description"] = desc
    pri = source.get("priority")
    if isinstance(pri, int):
        body["priority"] = pri
    ttype = source.get("type")
    if ttype:
        body["type"] = ttype
    if parent_override:
        body["parent"] = parent_override
    return body


def _comment_create_body(comment: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Translate an on-disk bw comment into a ``CommentCreate`` body.

    Skips empty/whitespace-only comments (rare but possible — the
    server's ``CommentCreate`` rejects empty text with 422).
    """
    text = (comment.get("text") or "").rstrip()
    if not text:
        return None
    body: dict[str, Any] = {"text": text}
    author = comment.get("author")
    if author:
        body["author"] = author
    return body


# ── Parent remap (ariadne--8fd.13) ─────────────────────────────────────────


def _resolve_parent_override(
    source: dict[str, Any],
    state: dict[str, dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    """Translate a source ticket's ``parent`` field to a destination-side ID.

    Returns ``(destination_parent_id, gap_reason)``:

      * ``("tg-...", None)`` — source has a parent and the parent has
        already been seeded; emit ``parent=tg-...`` on the POST.
      * ``(None, None)`` — top-level ticket (source ``parent`` is empty);
        emit no ``parent`` field.
      * ``(None, "<reason>")`` — source has a parent BUT the parent is
        not in the state map (or has no ``target_id`` recorded yet).
        Caller should treat this as a hard error and skip the ticket
        rather than fall back to the source-side ID — the cost of the
        skip is one logged error per orphaned subtree; the cost of
        falling back is a silent cascade where every descendant 400s
        on the source-side parent ID (the very bug this remap fixes).

    The state schema here matches ``_load_state``:
    ``{source_id: {"target_id": str, "target_comments": int, "seeded_at": str}}``.
    """
    source_parent = source.get("parent")
    if not source_parent:
        return None, None

    entry = state.get(source_parent)
    if entry is None:
        return None, (
            f"parent {source_parent!r} not yet in state map "
            f"(out-of-dependency-order enumeration?)"
        )

    target_id = entry.get("target_id")
    if not target_id:
        return None, (
            f"parent {source_parent!r} is in state map but has no "
            f"target_id recorded (partial-write or corrupted state)"
        )

    return target_id, None


# ── Counters ────────────────────────────────────────────────────────────────


class _Counters:
    """Per-run tallies the script reports at end of run."""

    def __init__(self) -> None:
        self.tickets_seeded = 0
        self.tickets_skipped_state = 0    # already in state file
        self.comments_seeded = 0
        self.comments_skipped_state = 0   # comment[i] already POSTed prior run
        self.dedup_skipped = 0            # ariadne_ingest.was_dedup_skip=true
        self.errors = 0                   # POST failures after retry

    def to_dict(self) -> dict[str, int]:
        return {
            "tickets_seeded": self.tickets_seeded,
            "tickets_skipped_state": self.tickets_skipped_state,
            "comments_seeded": self.comments_seeded,
            "comments_skipped_state": self.comments_skipped_state,
            "dedup_skipped": self.dedup_skipped,
            "errors": self.errors,
        }


# ── Main loop ───────────────────────────────────────────────────────────────


def _post_ticket_and_comments(
    http: _SeedHttp,
    project: str,
    source: dict[str, Any],
    state_entry: Optional[dict[str, Any]],
    counters: _Counters,
    rate_limit_sleep: float,
    log: callable,
    parent_override: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """POST a single ticket + its comments. Returns the updated state entry.

    If ``state_entry`` is not None, the ticket has been seeded on a
    prior run — re-uses the recorded ``target_id`` and only POSTs
    comments beyond ``target_comments``. Otherwise POSTs the ticket
    fresh and then every comment.

    ``parent_override`` (ariadne--8fd.13) is the destination-side
    parent ticket ID, already resolved by the caller via the state
    map. ``None`` means top-level — source ``parent`` is ignored.

    Returns ``None`` on a hard failure (ticket POST failed after
    retry); caller skips the ticket and increments ``counters.errors``.
    """
    source_id = source["id"]

    # ── Ticket POST (skipped if state entry exists)
    if state_entry is None:
        body = _ticket_create_body(source, parent_override=parent_override)
        path = f"/api/bw/projects/{project}/tickets"
        try:
            resp = http.post(path, body)
        except SeedError as exc:
            log(f"  ! {source_id}: {exc}")
            counters.errors += 1
            return None

        if resp.status_code >= 400:
            log(
                f"  ! {source_id}: POST {path} -> {resp.status_code}: "
                f"{resp.text[:300]}"
            )
            counters.errors += 1
            return None

        result = resp.json() if resp.content else {}
        target_id = result.get("id")
        if not target_id:
            log(
                f"  ! {source_id}: POST {path} returned no 'id' "
                f"(response: {str(result)[:300]})"
            )
            counters.errors += 1
            return None

        # Phase 3 augments the response with ariadne_ingest.was_dedup_skip
        # when the content_fingerprint matched an existing document.
        ingest = result.get("ariadne_ingest") or {}
        if isinstance(ingest, dict) and ingest.get("was_dedup_skip"):
            counters.dedup_skipped += 1

        counters.tickets_seeded += 1
        state_entry = {
            "target_id": target_id,
            "target_comments": 0,
            "seeded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        log(f"  + {source_id} -> {target_id} (ticket)")
    else:
        target_id = state_entry["target_id"]

    # ── Comment POSTs (only those beyond what state already records)
    comments = source.get("comments") or []
    already = int(state_entry.get("target_comments", 0))
    for idx, comment in enumerate(comments):
        if idx < already:
            counters.comments_skipped_state += 1
            continue
        body = _comment_create_body(comment)
        if body is None:
            # Empty comment — count as "seeded" (we processed it) but
            # don't actually POST. Advance the state pointer so a
            # restart doesn't re-process it.
            state_entry["target_comments"] = idx + 1
            continue

        path = f"/api/bw/projects/{project}/tickets/{target_id}/comments"
        try:
            resp = http.post(path, body)
        except SeedError as exc:
            log(f"  ! {source_id}#{idx}: {exc}")
            counters.errors += 1
            # Persist progress up to this point so a restart resumes
            # cleanly (target_comments is unchanged → idx will retry).
            return state_entry

        if resp.status_code >= 400:
            log(
                f"  ! {source_id}#{idx}: POST {path} -> "
                f"{resp.status_code}: {resp.text[:300]}"
            )
            counters.errors += 1
            return state_entry

        comment_result = resp.json() if resp.content else {}
        ingest = comment_result.get("ariadne_ingest") or {}
        if isinstance(ingest, dict) and ingest.get("was_dedup_skip"):
            counters.dedup_skipped += 1

        counters.comments_seeded += 1
        state_entry["target_comments"] = idx + 1

        if rate_limit_sleep > 0:
            time.sleep(rate_limit_sleep)

    return state_entry


def run(args: argparse.Namespace, http_factory=None, log=None) -> int:
    """Top-level entry. Returns the process exit code.

    ``http_factory`` and ``log`` are seams for the unit tests:

    * ``http_factory(base_url, token)`` returns a context-managed object
      that behaves like ``_SeedHttp``. Defaults to the real one.
    * ``log(msg)`` writes one line of status; defaults to stderr print.
    """
    if log is None:
        def log(msg: str) -> None:  # type: ignore[no-redef]
            print(msg, file=sys.stderr)

    if not _SLUG_PATTERN.match(args.project):
        raise SeedConfigError(
            f"--project must match ^[a-z0-9_-]{{1,64}}$, got: {args.project!r}"
        )

    bw_repo = Path(args.bw_repo).resolve()
    if not bw_repo.exists():
        raise SeedConfigError(f"--bw-repo path does not exist: {bw_repo}")
    if not bw_repo.is_dir():
        raise SeedConfigError(f"--bw-repo is not a directory: {bw_repo}")

    state_file = _state_path(bw_repo, Path(args.state_file) if args.state_file else None)
    state = _load_state(state_file)

    source_ids = _list_source_ticket_ids(bw_repo)
    if args.start_after:
        source_ids = [tid for tid in source_ids if tid > args.start_after]

    log(f"seed_bw_corpus: source={bw_repo}")
    log(f"seed_bw_corpus: project={args.project}")
    log(f"seed_bw_corpus: state_file={state_file}")
    log(f"seed_bw_corpus: source_tickets={len(source_ids)}")
    log(f"seed_bw_corpus: state_existing_entries={len(state)}")

    if _state_file_inside_repo_and_untracked(bw_repo, state_file):
        log(
            "seed_bw_corpus: WARNING — state file lives inside the "
            "source bw repo's working tree and is not listed in its "
            ".gitignore. Add the file's name to .gitignore in the "
            "source repo if you don't want it tracked by an "
            "accidental `git add .`."
        )

    if args.dry_run:
        log("seed_bw_corpus: --dry-run; enumerating without POSTing")
        # Simulate the state map so cascading parents resolve to
        # hypothetical destination IDs (ariadne--8fd.13). Real seeds
        # build this map as POSTs return; dry-run synthesizes one with
        # ``dry-<source-id>`` stand-ins so the output shows what the
        # destination ``parent`` field WOULD be on a live run.
        simulated_state: dict[str, dict[str, Any]] = dict(state)
        for tid in source_ids[: args.limit] if args.limit else source_ids:
            ticket = _read_source_ticket(bw_repo, tid)
            n_comments = len(ticket.get("comments") or [])
            state_entry = state.get(tid)
            marker = "skip(state)" if state_entry else "post"
            destination_parent, gap = _resolve_parent_override(
                ticket, simulated_state,
            )
            if gap:
                parent_note = f" [parent gap: {gap}]"
            elif destination_parent:
                parent_note = f" [parent: {destination_parent}]"
            else:
                parent_note = ""
            log(f"  - {tid} ({n_comments} comments) [{marker}]{parent_note}")
            # Add a simulated target_id so the next child can resolve.
            if state_entry is not None:
                continue
            simulated_state[tid] = {
                "target_id": f"dry-{tid}",
                "target_comments": 0,
                "seeded_at": "dry-run",
            }
        return 0

    # Resolve auth once. http_factory may not actually need it (tests),
    # but the production factory does, and resolving up-front gives the
    # cleanest error surface if auth is misconfigured.
    if http_factory is None:
        host, token = _resolve_auth(args.ariadne_host)

        def _make_http(*_args, **_kwargs):  # type: ignore[no-redef]
            return _SeedHttp(host, token)

        http_factory = _make_http

    counters = _Counters()
    started_at = time.monotonic()

    with http_factory(args.ariadne_host, None) as http:
        processed = 0
        for source_id in source_ids:
            if args.limit is not None and processed >= args.limit:
                log(f"seed_bw_corpus: reached --limit={args.limit}, stopping")
                break
            processed += 1

            existing = state.get(source_id)
            if existing is not None:
                # Has the source grown comments since we last touched it?
                # If not, this is a pure skip; if yes, fall through to
                # the POST loop which will only emit the new comments.
                source = _read_source_ticket(bw_repo, source_id)
                source_n_comments = len(source.get("comments") or [])
                already = int(existing.get("target_comments", 0))
                if source_n_comments <= already:
                    counters.tickets_skipped_state += 1
                    continue
                # Resume path: ticket already exists destination-side,
                # so parent_override is unused for the ticket POST (the
                # POST is skipped) — we still pass None for clarity.
                updated = _post_ticket_and_comments(
                    http, args.project, source, existing, counters,
                    args.rate_limit_sleep, log, parent_override=None,
                )
            else:
                source = _read_source_ticket(bw_repo, source_id)
                # Translate source-side parent → destination-side parent
                # via the state map (ariadne--8fd.13). On a gap (parent
                # not yet seeded, or partial state entry), log + skip;
                # do NOT fall back to the source-side ID — that's the
                # bug this remap fixes.
                destination_parent, gap = _resolve_parent_override(
                    source, state,
                )
                if gap is not None:
                    log(f"  ! {source_id}: {gap}; skipping")
                    counters.errors += 1
                    continue
                updated = _post_ticket_and_comments(
                    http, args.project, source, None, counters,
                    args.rate_limit_sleep, log,
                    parent_override=destination_parent,
                )

            if updated is not None:
                state[source_id] = updated
                # Persist after every ticket so a crash mid-run leaves
                # state coherent up to the last fully-processed ticket.
                _save_state(state_file, state)

    elapsed = time.monotonic() - started_at
    log("")
    log("seed_bw_corpus: done.")
    for k, v in counters.to_dict().items():
        log(f"  {k}: {v}")
    log(f"  elapsed_seconds: {elapsed:.1f}")

    return 0 if counters.errors == 0 else 1


# ── CLI plumbing ────────────────────────────────────────────────────────────


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="seed_bw_corpus",
        description=(
            "Bulk-seed a source bw (beadwork) repo into Ariadne via the "
            "Phase 2 HTTP surface."
        ),
    )
    p.add_argument(
        "--bw-repo",
        required=True,
        help="Path to the source bw repo (must have an orphan 'beadwork' branch).",
    )
    p.add_argument(
        "--project",
        required=True,
        help="Target Ariadne project slug ([a-z0-9_-]{1,64}).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of source tickets seeded this run.",
    )
    p.add_argument(
        "--ariadne-host",
        default=None,
        help="Ariadne base URL (defaults to ARIADNE_HOST / ~/.config/ariadne/default).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate + parse source tickets without POSTing.",
    )
    p.add_argument(
        "--start-after",
        default=None,
        help="Skip source tickets with id <= this value (resume hint).",
    )
    p.add_argument(
        "--state-file",
        default=None,
        help="Path to the seed-state JSON (default: <bw-repo>/.ariadne_seed_state.json).",
    )
    p.add_argument(
        "--rate-limit-sleep",
        type=float,
        default=0.0,
        help="Sleep N seconds between POSTs (default 0).",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return run(args)
    except SeedConfigError as exc:
        print(f"seed_bw_corpus: config error: {exc}", file=sys.stderr)
        return 2
    except SeedError as exc:
        print(f"seed_bw_corpus: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
