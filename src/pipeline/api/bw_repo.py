"""Shared bw-repo enumeration helpers (ariadne--uuo.5).

The on-disk ``bw`` (beadwork) repo stores every ticket as a JSON file
under the orphan ``beadwork`` branch's ``issues/`` tree. Two callers need
to enumerate that tree without depending on the ``bw`` CLI being on the
caller's machine:

  • ``scripts/seed_bw_corpus.py`` — the bulk-seed adapter (the BAD path —
    it recreates tickets).
  • ``pipeline.api.bw_routes`` — the ``POST /reembed`` route (the GOOD
    path — it re-embeds existing tickets in place).

Before ariadne--uuo.5 this logic lived only in ``seed_bw_corpus.py``
(``_list_source_ticket_ids`` / ``_read_source_ticket`` / ``_git_show``).
Hoisting it here keeps the BAD-path script and the GOOD-path route
reading the repo the same way — a single source of truth for "what does
this bw repo contain" (design §6.6). The script keeps thin wrappers that
delegate here so its existing exception contract (``SeedConfigError`` /
``SeedError``) is preserved for its callers.

``git show beadwork:issues`` returns a tree listing; ``git show
beadwork:issues/<id>.json`` returns one ticket's JSON. Neither command
mutates anything — these are pure reads against the orphan branch.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

__all__ = [
    "BwRepoError",
    "BwRepoConfigError",
    "git_show",
    "list_ticket_ids",
    "read_ticket",
]


class BwRepoError(Exception):
    """Base class for bw-repo enumeration failures."""


class BwRepoConfigError(BwRepoError):
    """Configuration problem the caller can fix (missing repo / branch / git)."""


def git_show(repo: str, target: str, *, timeout: float | None = None) -> str:
    """Return stdout of ``git -C <repo> show <target>``.

    ``repo`` is a filesystem path (str or anything ``str()``-able — the
    route passes the resolved repo path; the script passes a ``Path``).
    ``target`` is a git revision/path spec, e.g. ``beadwork:issues`` or
    ``beadwork:issues/ariadne--uuo.json``.

    Raises ``BwRepoConfigError`` for a missing repo / missing branch / git
    not on PATH (the caller can fix the input); raises ``BwRepoError`` for
    an unexpected non-zero exit (likely an environment problem).

    A ``timeout`` (seconds) bounds the subprocess — the route passes one
    so a wedged git invocation cannot pin a request thread indefinitely;
    the script leaves it ``None`` (its run is operator-supervised).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "show", target],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BwRepoConfigError("git binary not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise BwRepoError(
            f"git show {target!r} timed out after {timeout}s"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        # Distinguish "no such repo / no such branch" (caller fix) from
        # other git failures (likely environment).
        lowered = stderr.lower()
        if (
            "not a git repository" in lowered
            or "unknown revision" in lowered
            or "bad revision" in lowered
        ):
            raise BwRepoConfigError(
                f"git show {target!r} failed: {stderr}. "
                f"Check that the repo path points at a bw-managed git repo "
                f"with a populated 'beadwork' branch."
            )
        raise BwRepoError(
            f"git show {target!r} failed (exit {proc.returncode}): {stderr}"
        )
    return proc.stdout


def list_ticket_ids(repo: str, *, timeout: float | None = None) -> list[str]:
    """Enumerate ticket IDs in the repo's ``beadwork`` branch.

    ``git show beadwork:issues`` returns a tree listing (one filename per
    line plus a header), e.g.::

        tree beadwork:issues

        .gitkeep
        ariadne--16a.json
        ariadne--1of.json
        ...

    We parse out the ``*.json`` filenames (dropping ``.gitkeep`` and the
    header) and strip the ``.json`` suffix to recover ticket IDs. Returns
    a sorted list so enumeration order is deterministic across machines
    and between an initial run and a resume.
    """
    raw = git_show(repo, "beadwork:issues", timeout=timeout)
    ids: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("tree "):
            continue
        if not line.endswith(".json"):
            continue
        ticket_id = line[: -len(".json")]
        if not ticket_id or ticket_id.startswith("."):
            continue
        ids.append(ticket_id)
    ids.sort()
    return ids


def read_ticket(
    repo: str, ticket_id: str, *, timeout: float | None = None
) -> dict[str, Any]:
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

    The ``issues/<id>.json`` on-disk shape is what ``bw show --json``
    surfaces (un-nested — unlike ``bw close --json``, which wraps the
    issue under ``"issue"``). The re-embed route reads this shape
    directly, so a closed ticket's close-reason comment is already in the
    top-level ``comments`` array exactly as the live ``close`` route
    originally ingested it (design §6.3, W-7 robustness note).
    """
    raw = git_show(repo, f"beadwork:issues/{ticket_id}.json", timeout=timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BwRepoError(
            f"failed to parse beadwork:issues/{ticket_id}.json: {exc}"
        ) from exc
