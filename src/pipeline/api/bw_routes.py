"""HTTP surface for the ``bw`` (beadwork) CLI.

ariadne--8fd.2 (Phase 2). Wraps the ``bw`` binary so an agent (or a
human via the REST API) can drive beadwork repositories that live on
the Railway-mounted volume — without holding a shell on the host.

Design notes (locked by the Phase 2 plan; do NOT re-litigate here):

  • URL convention: path-prefix-per-project. Every endpoint hangs off
    ``/api/bw/projects/{slug}/...``. The slug identifies a beadwork
    repo on disk (one git working tree per slug, rooted at
    ``BW_REPOS_ROOT/{slug}``). Slug must match a strict allow-list
    pattern to prevent path traversal.

  • Method convention: action-endpoint pattern. ``POST .../close``,
    ``POST .../defer``, ``POST .../labels`` — each ``bw`` subcommand
    that mutates state maps to a POST against a sub-path named after
    the action. Read-only subcommands map to GET. Removal of an
    enumerable child (a label, a dep) maps to DELETE.

  • Auth: every endpoint takes the same ``require_user`` dependency
    used by ``/api/search`` and ``/api/documents``. v1 is single-user
    (no per-action ACL); a valid Auth0 Bearer JWT is sufficient.

  • Concurrency: per-slug in-process ``asyncio.Lock``. Acquired by
    write-shape endpoints; reads (``list``, ``show``, ``history``,
    ``ready``, ``blocked``, ``export``) skip the lock because git
    reads are concurrent-safe. This works because the FastAPI app
    runs as a single uvicorn process — multi-instance deploys would
    need distributed locking, but that is explicitly out of scope
    for v1 (see ariadne--8fd.5 / Phase 5 for the deploy shape).

  • bw invocation: subprocess. The ``-C <dir>`` global flag points
    ``bw`` at the per-slug repo; we pass ``--json`` to every
    subcommand that supports it and parse the resulting JSON. The
    few subcommands that don't (``sync``, ``onboard``, ``prime``,
    ``import``, ``export``) return their stdout verbatim in a
    documented ``output`` shape.

  • bw exit-code mapping: non-zero → HTTP 400 with bw's stderr in
    the response body's ``detail`` (caller error — bad ticket id,
    invalid date, missing required arg). Unexpected failures
    (binary missing, JSON parse fail on a --json subcommand,
    subprocess timeout) → HTTP 500.

  • Backup hook: real ``git push`` as of Phase 5 (ariadne--8fd.9).
    ``_backup_push(slug)`` looks up
    ``BW_BACKUP_REMOTE_{slug.upper().replace('-', '_')}`` — if unset,
    silent no-op (no remote configured); if set, runs
    ``git push <remote> beadwork:beadwork --force-with-lease`` and
    logs / increments a per-slug failure counter on any error.
    The hook MUST NOT raise on failure: the original bw write
    already succeeded, and the backup is a separate (eventually-
    consistent) durability layer. Phase 5's sub-task is replacing
    the per-slug counter with a Prometheus gauge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator

from pipeline.auth_oauth import Principal, require_user

logger = logging.getLogger("ariadne.bw")

# ── Configuration ───────────────────────────────────────────────────────────
#
# All bw-routes config flows through these module-level knobs. They are
# read at module import time from the environment because every value
# is process-stable (changing them requires a restart anyway). Tests
# override them via monkeypatch on this module.

# Base directory under which per-slug bw repos live. The expected
# layout on Railway is ``/data/bw-repos/{slug}/`` with a populated
# git working tree. Local dev / tests override via the env var or
# direct monkeypatch.
BW_REPOS_ROOT: str = os.environ.get("BW_REPOS_ROOT", "/data/bw-repos")

# Path to the bw binary. ``shutil.which("bw")`` at module import time
# gives the resolved path so we surface a clean 500 on first request
# rather than a cryptic FileNotFoundError mid-call. None is permitted
# (tests mock _run_bw and never invoke shutil.which).
BW_BINARY: Optional[str] = shutil.which("bw")

# Subprocess timeout per bw call. bw operations are local-git and
# normally sub-second; a 30s ceiling catches a hung child without
# making timeouts a common failure mode under load.
BW_SUBPROCESS_TIMEOUT_SECONDS: float = 30.0

# Backup-push subprocess timeout. ``_backup_push`` shells out to
# ``git push`` against a remote; network I/O can legitimately take
# tens of seconds (TLS handshake, pack negotiation, slow link) so the
# bw-call timeout (30s) is too tight. Default 60s; overridable via
# env. The push happens inside the per-slug lock, so an aggressive
# value would serialize writers behind a hung push — but the
# infallibility contract (push failure never raises) means a timeout
# is logged + counted, not surfaced to the caller.
BW_BACKUP_TIMEOUT_SECONDS: float = float(
    os.environ.get("BW_BACKUP_TIMEOUT_SECONDS", "60")
)

# Phase 5 (ariadne--8fd.9): toggle for the "is this slug initialized
# on disk" guard inside ``_resolve_repo_path``. Production wants
# this on (so the bw HTTP surface returns a clean 404 with operator
# guidance instead of a 400 carrying ``fatal: not a git repository``).
# Route-level tests that mock ``subprocess.run`` typically do NOT
# create a real ``.git`` directory under the temp repos root, so
# they monkey-patch this to False to skip the check. The default is
# True; tests opt out explicitly.
BW_REQUIRE_INITIALIZED_REPO: bool = True

# Slug allow-list. Matches the lowercase-letters/digits/dash/underscore
# convention used throughout the ariadne workspace and rejects anything
# that could path-traverse (``..``), shell-escape (``;``, ``|``, ``$``),
# or smuggle in a path separator (``/``, ``\``). Anchored at both ends.
_SLUG_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")

# Path-param NUL-byte guard. Percent-encoded ``%00`` survives Starlette
# routing and the decoded ``\x00`` reaches the handler — and then
# ``subprocess.run`` raises ``ValueError`` on argv with embedded NULs.
# Apply this pattern to every str path param that becomes an argv
# element (``ticket_id``, ``label``, ``target``) so the request 422s
# at validation time with a clean field-level error instead of cascading
# to a 500. (The ``slug`` path param has its own stricter allow-list.)
_PATH_PARAM_NO_NUL = r"^[^\x00]+$"


def _validate_slug(slug: str) -> None:
    """Raise 422 if ``slug`` is not in the allow-list.

    Slug is user-controllable via URL. The whole point of validating
    against an anchored character class (rather than blacklisting bad
    characters) is to keep this trivially auditable: if it isn't
    lowercase letters / digits / dash / underscore, it isn't allowed.
    """
    if not _SLUG_PATTERN.match(slug):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_slug",
                "message": (
                    "Slug must match ^[a-z0-9_-]{1,64}$. Got: "
                    f"{slug!r}"
                ),
            },
        )


def _resolve_repo_path(slug: str) -> str:
    """Return the absolute path of the per-slug bw repo.

    Re-validates the slug (defence in depth — the only callers are
    bw routes, which validate at the entry point, but the cost of a
    second check is one regex match).

    Phase 5 (ariadne--8fd.9): enforces "project initialized on this
    Ariadne instance" — if ``<BW_REPOS_ROOT>/<slug>/.git`` is missing,
    raises HTTPException(404) with an operator-actionable message
    pointing at ``bw init``. This catches the "deployed but operator
    forgot to run bw init for this slug" case with a clean error
    instead of letting ``bw -C <missing-dir>`` produce a cryptic
    fatal: not a git repository`` from the subprocess.
    """
    _validate_slug(slug)
    repo_path = os.path.join(BW_REPOS_ROOT, slug)
    if BW_REQUIRE_INITIALIZED_REPO and not os.path.isdir(
        os.path.join(repo_path, ".git")
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "bw_project_uninitialized",
                "slug": slug,
                "message": (
                    f"Project {slug!r} is not initialized on this "
                    f"Ariadne instance. Operator action: "
                    f"`mkdir -p {repo_path} && git init {repo_path}"
                    f" && cd {repo_path} && bw init --prefix {slug}`."
                ),
            },
        )
    return repo_path


# ── Per-slug write lock ─────────────────────────────────────────────────────
#
# bw mutations rewrite the git working tree of the underlying repo;
# concurrent writes against the same slug would race the orphan-branch
# commit. A per-slug ``asyncio.Lock`` serializes writes within this
# process. Reads skip the lock — bw's read subcommands (``list``,
# ``show``, ``history``, ``ready``, ``blocked``, ``export``) walk the
# git tree and do not commit, so concurrent reads are safe.

_slug_locks: dict[str, asyncio.Lock] = {}
_slug_locks_guard = asyncio.Lock()


async def _lock_for(slug: str) -> asyncio.Lock:
    """Return the lock for ``slug``, creating it on first request.

    ``_slug_locks_guard`` ensures the dict mutation is atomic across
    concurrent coroutines; without it two simultaneous writers for a
    brand-new slug could each create their own Lock and serialize
    against different objects, defeating the point.
    """
    async with _slug_locks_guard:
        lock = _slug_locks.get(slug)
        if lock is None:
            lock = asyncio.Lock()
            _slug_locks[slug] = lock
        return lock


# ── Backup hook (Phase 5: real git push with infallibility contract) ────────
#
# After a successful bw write, push the orphan branch to a remote so
# the on-disk state isn't the only copy. Configured per slug via
# ``BW_BACKUP_REMOTE_{SLUG}`` (slug uppercased, dashes mapped to
# underscores). No env var → silent no-op (slug has no configured
# backup, which is a legitimate operator choice for low-value repos).
#
# Infallibility contract: ``_backup_push`` MUST NOT raise. The original
# bw write already succeeded; backup is eventually-consistent durability,
# not a transaction member. Every failure path here logs + meters and
# returns normally so the request handler still completes 2xx.
#
# Per-slug counter of backup pushes that failed or were skipped due to
# error. Unbounded by design — the slug allow-list caps cardinality at
# the regex. Phase 5's sub-task swaps this for a Prometheus gauge; the
# counter stays as a fallback the operator can read via ``/health``.
_backup_skip_count: dict[str, int] = {}


def _backup_remote_env_key(slug: str) -> str:
    """Map a slug to the env-var name carrying its backup remote URL.

    ``my-project`` and ``my_project`` both map to ``BW_BACKUP_REMOTE_MY_PROJECT``
    because environment-variable names cannot contain dashes on most
    shells / systemd-style envs. The slug allow-list (``[a-z0-9_-]``)
    means upper + dash→underscore is unambiguous: two distinct slugs
    that collide in the env-key space (e.g. ``my-proj`` and ``my_proj``)
    would already be a deployment-time conflict the operator must
    resolve. We do not attempt to disambiguate at runtime.
    """
    return f"BW_BACKUP_REMOTE_{slug.upper().replace('-', '_')}"


def _mask_remote_url(remote_url: str) -> str:
    """Return ``remote_url`` with credentials masked if it looks
    token-bearing.

    Common shapes: ``https://x-access-token:<TOKEN>@host/path``,
    ``https://<TOKEN>@host/path``. A ``user:pass`` or ``token`` is
    everything between ``://`` and the next ``@``. We replace the
    pre-@ portion with ``***``. URLs without an ``@`` (SSH, plain
    https://host/path) pass through unchanged.
    """
    if "://" not in remote_url or "@" not in remote_url:
        return remote_url
    scheme_sep = remote_url.index("://") + 3
    at_pos = remote_url.index("@", scheme_sep)
    return remote_url[:scheme_sep] + "***" + remote_url[at_pos:]


async def _backup_push(slug: str) -> None:
    """Push the orphan beadwork branch to the configured backup remote.

    Resolution: env-var ``BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}``.
    If unset, the slug has no configured backup — silent no-op.

    Wire: ``git -C <repo> push <remote> beadwork:beadwork --force-with-lease``.
    The ``--force-with-lease`` flag is safer than ``--force``: bw is
    a single-writer-per-repo system (per-slug lock + single-instance
    deploy in v1), so the local beadwork ref is always ahead-of-or-equal
    to the remote — but ``--force-with-lease`` will refuse the push
    if the remote moved unexpectedly, catching the case where two
    operators accidentally point at the same backup remote (or where
    a future multi-instance deploy raced two writers).

    Infallibility contract: any failure (non-zero exit, timeout,
    unexpected exception) is logged + counted and swallowed. The
    bw write already succeeded; surfacing a backup failure would
    invert the durability hierarchy.

    Outer-timeout cancellation note: ``asyncio.to_thread`` does NOT
    propagate cancellation into the wrapped sync function (see the
    ``_run_bw`` outer-timeout guardrail for full context). If any
    future code wraps a write endpoint — including a call site that
    awaits ``_backup_push`` — in ``asyncio.wait_for``, the underlying
    ``subprocess.run`` will keep running after cancellation. The
    Phase 5 wiring deliberately does not introduce ``asyncio.wait_for``
    around the backup; the per-subprocess timeout
    (``BW_BACKUP_TIMEOUT_SECONDS``) is the cancellation seam.
    """
    env_key = _backup_remote_env_key(slug)
    remote_url = os.environ.get(env_key)
    if not remote_url:
        # Operator chose not to configure backup for this slug; the
        # bw write succeeded and that is the durability story for v1
        # on this slug. No bump — this is steady-state, not failure.
        return

    # Direct path construction (not ``_resolve_repo_path``): the bw
    # write that just completed proved the repo is initialized; the
    # initialized-repo guard would re-check and could raise
    # HTTPException, which would violate the infallibility contract.
    # Slug validation already happened at the route entry.
    repo_path = os.path.join(BW_REPOS_ROOT, slug)
    masked = _mask_remote_url(remote_url)
    push_cmd = [
        "git", "-C", repo_path, "push", remote_url,
        "beadwork:beadwork", "--force-with-lease",
    ]
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            push_cmd,
            capture_output=True,
            text=True,
            timeout=BW_BACKUP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _backup_skip_count[slug] = _backup_skip_count.get(slug, 0) + 1
        logger.warning(
            "bw backup push timed out: slug=%s remote=%s timeout=%.1fs "
            "skip_count=%d",
            slug, masked, BW_BACKUP_TIMEOUT_SECONDS, _backup_skip_count[slug],
        )
        return
    except Exception:
        # Unexpected (FileNotFoundError if git is missing from PATH,
        # OSError on a permissions issue, etc.). Log with traceback,
        # bump the counter, do NOT raise.
        _backup_skip_count[slug] = _backup_skip_count.get(slug, 0) + 1
        logger.exception(
            "bw backup push raised unexpectedly: slug=%s remote=%s "
            "skip_count=%d",
            slug, masked, _backup_skip_count[slug],
        )
        return

    if proc.returncode != 0:
        _backup_skip_count[slug] = _backup_skip_count.get(slug, 0) + 1
        stderr_snippet = (proc.stderr or "").strip()[:512]
        logger.warning(
            "bw backup push failed: slug=%s remote=%s exit=%d "
            "stderr=%r skip_count=%d",
            slug, masked, proc.returncode, stderr_snippet,
            _backup_skip_count[slug],
        )
        return

    # Success path. Counter is cumulative (lifetime) by design — Phase 5's
    # follow-up Prometheus gauge will replace this with a time-windowed
    # metric; until then the cumulative count is the operator-readable
    # signal that backup health is degraded. Logging includes the
    # remote-tip SHA (best-effort; if the rev-parse itself fails, the
    # push still succeeded — log the success without the SHA).
    tip_sha = ""
    try:
        tip_proc = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", repo_path, "rev-parse", "refs/heads/beadwork"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if tip_proc.returncode == 0:
            tip_sha = tip_proc.stdout.strip()[:12]
    except Exception:
        # Tip-resolution failure is irrelevant to backup success.
        tip_sha = ""
    logger.info(
        "bw backup push ok: slug=%s remote=%s tip=%s",
        slug, masked, tip_sha or "(unresolved)",
    )


# ── Subprocess seam ─────────────────────────────────────────────────────────


async def _run_bw(
    slug: str,
    *args: str,
    json_output: bool = True,
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """Invoke ``bw -C <repo> <args>`` and return a parsed result.

    Subprocess is a blocking syscall, and FastAPI runs ``async def``
    routes directly on the event loop — so we MUST NOT call
    ``subprocess.run`` synchronously from a route handler. The full
    bw call (which can run up to ``BW_SUBPROCESS_TIMEOUT_SECONDS``)
    would pause every other coroutine on the same worker for the
    duration. ``asyncio.to_thread`` offloads the blocking call to
    the default thread-pool executor and ``await``s the result, so
    the event loop stays responsive while the bw subprocess runs.

    Outer-timeout guardrail (Phase 5+ implementers — READ THIS):
    ``asyncio.to_thread`` does NOT propagate cancellation into the
    wrapped sync function. If any future caller wraps a bw call (or
    ``_backup_push``, which Phase 5 will also subprocess-out) in
    ``asyncio.wait_for(coro, timeout=...)``, the outer timeout will
    cancel the awaiting coroutine but the underlying
    ``subprocess.run`` continues running in the executor thread —
    the subprocess orphans, the thread stays busy, and the caller
    sees a ``TimeoutError`` while the child process is still alive.
    Two safe fixes for future code that wants real cancellation:
      (a) Switch the offending call to
          ``asyncio.create_subprocess_exec`` + ``await proc.communicate()``;
          this is native asyncio, and cancellation kills the child
          process via the OS as part of unwinding.
      (b) Wrap the to_thread call in ``try/except asyncio.CancelledError``
          that explicitly ``process.kill()``s the subprocess before
          re-raising. Harder to get right because the ``Popen`` handle
          is internal to ``subprocess.run`` — typically requires
          dropping to ``subprocess.Popen`` directly so the kill handle
          is reachable.
    The Phase 2/3/4 call chain does NOT wrap bw calls in
    ``asyncio.wait_for``, so this is not a live defect — it is a
    well-marked tripwire for the next implementer.

    The return shape is always a ``dict``. For ``--json`` subcommands
    the dict is bw's parsed JSON (which is itself either a dict or a
    list — lists get wrapped as ``{"items": [...]}`` so the caller
    sees a uniform shape). For non-JSON subcommands the dict is
    ``{"output": <stdout>, "stderr": <stderr>}``.

    Errors:

      • bw exit != 0 → HTTPException(400) with bw's stderr in detail.
        These are caller errors (bad id, invalid date, missing arg)
        and should surface to the API caller as 400.

      • bw binary missing → HTTPException(500). This is a deploy
        problem, not a caller problem.

      • Subprocess timeout → HTTPException(500). Same.

      • JSON parse failure on a ``--json`` subcommand → HTTPException(500).
        bw promised JSON and didn't deliver — that's a bw bug or a
        version mismatch, neither of which the caller can fix.

    Args:
        slug: Already-validated slug; resolves to the per-slug repo path.
        *args: bw subcommand + flags + positional args.
        json_output: True if ``--json`` is already in ``args`` (or
            implicit) and the caller wants the result parsed. False
            for subcommands that have no ``--json`` (sync, onboard,
            prime, export, import).
        timeout: Subprocess timeout override (defaults to
            ``BW_SUBPROCESS_TIMEOUT_SECONDS``). Tests override to
            assert the timeout path.
    """
    if BW_BINARY is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "bw_binary_missing",
                "message": (
                    "The bw binary was not found on PATH at app import. "
                    "Check the Dockerfile install step (Phase 5)."
                ),
            },
        )

    repo_path = _resolve_repo_path(slug)
    cmd = [BW_BINARY, "-C", repo_path, *args]
    effective_timeout = timeout if timeout is not None else BW_SUBPROCESS_TIMEOUT_SECONDS

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "bw_timeout",
                "message": (
                    f"bw call timed out after {effective_timeout}s "
                    f"(argv={cmd[2:]})"
                ),
            },
        ) from e
    except FileNotFoundError as e:
        # bw binary disappeared between import-time which() and now.
        # Surface as 500 — the operator needs to know the deploy is
        # broken, not the caller.
        raise HTTPException(
            status_code=500,
            detail={
                "error": "bw_binary_missing",
                "message": str(e),
            },
        ) from e

    if proc.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bw_exit_nonzero",
                "exit_code": proc.returncode,
                "stderr": (proc.stderr or "").strip(),
                "stdout": (proc.stdout or "").strip(),
            },
        )

    if not json_output:
        return {
            "output": proc.stdout,
            "stderr": proc.stderr,
        }

    # --json path: parse stdout. Empty stdout is treated as an empty
    # dict (some bw subcommands legitimately print nothing on success
    # — e.g. ``dep add`` with --json on certain versions). The caller
    # will see ``{}`` rather than a 500.
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "bw_json_parse",
                "message": str(e),
                "stdout": raw[:2000],
            },
        ) from e

    # Normalize list outputs to ``{"items": [...]}`` so every endpoint
    # returns a JSON object at the top level (matches the existing
    # /api/* convention and keeps OpenAPI declarations honest).
    if isinstance(parsed, list):
        return {"items": parsed}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


# ── Request models ─────────────────────────────────────────────────────────
#
# Pydantic v2 ``field_validator`` is used to reject null bytes (``\x00``)
# in user-text fields. ``subprocess.run`` raises ``ValueError`` when an
# argv element contains a NUL — that would cascade to the global 500
# handler with no helpful detail. Catching it at the request boundary
# turns the same bad input into a clean 422 with field-level pointer.


def _reject_null_byte(v: Optional[str]) -> Optional[str]:
    """Reject null bytes in user-text fields.

    Returns ``v`` unchanged for ``None`` (Optional fields) and for
    strings that don't contain ``\\x00``. Raises ``ValueError`` (which
    Pydantic surfaces as 422) otherwise.
    """
    if v is None:
        return v
    if "\x00" in v:
        raise ValueError("null byte not allowed in user-text fields")
    return v


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    description: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=4)
    type: Optional[str] = None
    defer: Optional[str] = None
    due: Optional[str] = None
    parent: Optional[str] = None

    # Every str/Optional[str] field on this model becomes an argv element
    # to ``bw create``; ``subprocess.run`` raises ValueError on embedded
    # NUL bytes, which would surface as an uncaught 500. Reject at the
    # request boundary so the client gets a clean 422.
    _strip_nul = field_validator(
        "title", "description", "type", "defer", "due", "parent"
    )(_reject_null_byte)


class TicketUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=512)
    description: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=4)
    assignee: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    defer: Optional[str] = None
    # ``due`` accepts the empty string to clear the field (matches
    # ``bw update --due ""`` semantics). None means "don't touch".
    due: Optional[str] = None
    parent: Optional[str] = None

    _strip_nul = field_validator(
        "title", "description", "assignee", "type", "status",
        "defer", "due", "parent",
    )(_reject_null_byte)


class TicketStart(BaseModel):
    assignee: Optional[str] = None

    _strip_nul = field_validator("assignee")(_reject_null_byte)


class TicketClose(BaseModel):
    reason: Optional[str] = None

    _strip_nul = field_validator("reason")(_reject_null_byte)


class CommentCreate(BaseModel):
    text: str = Field(..., min_length=1)
    author: Optional[str] = None

    _strip_nul = field_validator("text", "author")(_reject_null_byte)


class LabelAdd(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)

    _strip_nul = field_validator("label")(_reject_null_byte)


class DeferRequest(BaseModel):
    # bw accepts free-form date expressions ("tomorrow at 2pm", "in 15
    # minutes", "2 weeks", or YYYY-MM-DD / RFC3339). We pass through
    # as a single string; bw does the parsing.
    when: str = Field(..., min_length=1)

    _strip_nul = field_validator("when")(_reject_null_byte)


class DepAdd(BaseModel):
    blocks: str = Field(
        ...,
        min_length=1,
        description="The ticket ID that the current ticket blocks.",
    )

    _strip_nul = field_validator("blocks")(_reject_null_byte)


class ProjectCreate(BaseModel):
    """Body for ``POST /bw/projects`` (ariadne--9e7).

    Replaces the manual three-step operator sequence
    (``mkdir -p ... && git init ... && bw init --prefix ...``) with a
    single authenticated API call. The slug is validated against the
    same allow-list every other bw route uses (``_SLUG_PATTERN``).

    ``options`` is reserved for forward-compat: future per-project
    knobs (e.g., inline backup-remote configuration) will hang off
    here. v1 accepts the field for shape stability but does not
    consume it — per-slug backup remotes stay env-var-driven via the
    shipped ``BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}`` convention.
    """

    slug: str = Field(..., min_length=1, max_length=64)
    options: Optional[dict[str, Any]] = None


class ReembedRequest(BaseModel):
    """Body for ``POST /reembed`` (ariadne--uuo.5). Both fields optional.

    ``ticket_ids`` — restrict the re-embed to these tickets (uuo-6's
    20-ticket A/B and per-ticket recovery use this). Omitted / ``None`` →
    walk every ticket in the on-disk bw repo.

    ``dry_run`` — enumerate + count + run the orphaned-ticket detection,
    write nothing. Lets the operator see scope (including the orphaned
    set) before committing the embedding spend.
    """

    ticket_ids: Optional[list[str]] = None
    dry_run: bool = False

    @field_validator("ticket_ids")
    @classmethod
    def _strip_nul_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        for item in v:
            _reject_null_byte(item)
        return v


# ── Routers ────────────────────────────────────────────────────────────────
#
# Two routers share this module:
#
#   • ``router`` — prefix ``/bw/projects/{slug}``. The Phase 2 ticket-shaped
#     and repo-level surface; ``{slug}`` is the path-prefix-per-project
#     convention every endpoint hangs off.
#   • ``projects_router`` — prefix ``/bw/projects`` (NO slug). The
#     collection-level surface introduced by ariadne--9e7: ``POST`` to
#     create a new on-disk bw project. Because the path has no ``{slug}``,
#     it cannot share the ``router`` prefix (a route with the slug in
#     the prefix would force the URL to contain a slug segment).
#
# The app mounts both routers under ``/api`` (see app.py), giving the
# full paths ``/api/bw/projects/{slug}/...`` and ``/api/bw/projects``.

router = APIRouter(prefix="/bw/projects/{slug}", tags=["bw"])
projects_router = APIRouter(prefix="/bw/projects", tags=["bw"])


# ── Ticket-shaped endpoints ────────────────────────────────────────────────


@router.post("/tickets", status_code=201)
async def create_ticket(
    slug: str = Path(...),
    req: TicketCreate = Body(...),
    principal: Principal = Depends(require_user),
):
    """Create an issue. Maps to ``bw create``.

    Phase 3 (ariadne--8fd.5): inside the same per-slug lock and after
    the backup hook, ingest the new body into Ariadne as a `body`-type
    document. The ingest result is attached as ``ariadne_ingest`` on
    the response; bw's own result remains the load-bearing payload.
    """
    from pipeline.api.bw_ingest import _ingest_bw_write

    _validate_slug(slug)
    args: list[str] = ["create", req.title, "--json"]
    if req.priority is not None:
        args += ["--priority", str(req.priority)]
    if req.type is not None:
        args += ["--type", req.type]
    if req.description is not None:
        args += ["--description", req.description]
    if req.defer is not None:
        args += ["--defer", req.defer]
    if req.due is not None:
        args += ["--due", req.due]
    if req.parent is not None:
        args += ["--parent", req.parent]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        ticket_id = result.get("id")
        if ticket_id:
            # ariadne--uuo.2 (design §4): the body doc's text is just the
            # description. The title is no longer string-concatenated into
            # the body — it now reaches both the fingerprint salt (via
            # _build_agent_metadata.ticket_title → _render_payload) and the
            # embedded chunk text (via _render_embed_content's `# <title>`
            # header). This makes body and comment ingest symmetric: both
            # get the title once, via the header. A description-less
            # ticket yields an empty `text`, but the embed content still
            # carries the header, so extraction has non-empty input.
            text = req.description or ""
            ingest = await _ingest_bw_write(
                slug=slug,
                source_type="body",
                ticket_id=ticket_id,
                bw_show_snapshot=result,
                text=text,
                comment_n=None,
                principal=principal,
            )
            if isinstance(result, dict):
                result = dict(result)
                result["ariadne_ingest"] = ingest
    return result


@router.get("/tickets")
async def list_tickets(
    slug: str = Path(...),
    status: Optional[str] = Query(None, alias="status", pattern=_PATH_PARAM_NO_NUL),
    assignee: Optional[str] = Query(None, pattern=_PATH_PARAM_NO_NUL),
    priority: Optional[int] = Query(None, ge=0, le=4),
    type: Optional[str] = Query(None, pattern=_PATH_PARAM_NO_NUL),
    label: Optional[str] = Query(None, pattern=_PATH_PARAM_NO_NUL),
    grep: Optional[str] = Query(None, pattern=_PATH_PARAM_NO_NUL),
    parent: Optional[str] = Query(None, pattern=_PATH_PARAM_NO_NUL),
    limit: Optional[int] = Query(None, ge=1, le=10000),
    show_all: bool = Query(False, alias="all"),
    deferred: bool = Query(False),
    overdue: bool = Query(False),
    principal: Principal = Depends(require_user),
):
    """List issues. Maps to ``bw list`` with --json.

    Query params correspond 1:1 to ``bw list`` flags. ``all=true``
    bypasses the default open/in-progress + limit filter (matches
    ``bw list --all``). Note: ``status`` here is the filter; bw's
    own ``--status`` flag.
    """
    _validate_slug(slug)
    args: list[str] = ["list", "--json"]
    if status is not None:
        args += ["--status", status]
    if assignee is not None:
        args += ["--assignee", assignee]
    if priority is not None:
        args += ["--priority", str(priority)]
    if type is not None:
        args += ["--type", type]
    if label is not None:
        args += ["--label", label]
    if grep is not None:
        args += ["--grep", grep]
    if parent is not None:
        args += ["--parent", parent]
    if limit is not None:
        args += ["--limit", str(limit)]
    if show_all:
        args += ["--all"]
    if deferred:
        args += ["--deferred"]
    if overdue:
        args += ["--overdue"]
    # No lock — list is read-only.
    return await _run_bw(slug, *args, json_output=True)


@router.get("/tickets/{ticket_id}")
async def show_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    only: Optional[str] = Query(
        None,
        pattern=_PATH_PARAM_NO_NUL,
        description=(
            "Comma-separated section names: summary, description, "
            "children, blockedby, unblocks, comments."
        ),
    ),
    principal: Principal = Depends(require_user),
):
    """Show one issue. Maps to ``bw show <id> --json``."""
    _validate_slug(slug)
    args = ["show", ticket_id, "--json"]
    if only:
        args += ["--only", only]
    return await _run_bw(slug, *args, json_output=True)


@router.patch("/tickets/{ticket_id}")
async def update_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: TicketUpdate = Body(...),
    principal: Principal = Depends(require_user),
):
    """Patch fields on an issue. Maps to ``bw update``.

    Phase 3: per design §D4.1, branch on whether the body changed:

      • Fields-only PATCH (no ``title`` and no ``description``) →
        ``_patch_bw_body_metadata`` re-emits the full agent_metadata
        surface against the body doc.
      • Body-changing PATCH (``title`` or ``description`` non-None) →
        soft-delete the prior body doc(s), then ingest a new body doc.
    """
    from pipeline.api.bw_ingest import (
        _ingest_bw_write,
        _patch_bw_body_metadata,
        _soft_delete_body_docs,
    )

    _validate_slug(slug)
    args: list[str] = ["update", ticket_id, "--json"]
    if req.title is not None:
        args += ["--title", req.title]
    if req.description is not None:
        args += ["--description", req.description]
    if req.priority is not None:
        args += ["--priority", str(req.priority)]
    if req.assignee is not None:
        args += ["--assignee", req.assignee]
    if req.type is not None:
        args += ["--type", req.type]
    if req.status is not None:
        args += ["--status", req.status]
    if req.defer is not None:
        args += ["--defer", req.defer]
    if req.due is not None:
        args += ["--due", req.due]
    if req.parent is not None:
        args += ["--parent", req.parent]

    # If only --json is in the argv, the request body had no fields.
    if len(args) == 3:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_fields_to_update",
                "message": "PATCH body must include at least one field.",
            },
        )

    body_changed = req.title is not None or req.description is not None

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        if body_changed:
            deleted = await _soft_delete_body_docs(
                slug=slug, ticket_id=ticket_id,
            )
            # ariadne--uuo.2 (design §4): body text is the post-update
            # description only — same as the create path. The title is no
            # longer concatenated into the body; it reaches the fingerprint
            # salt and the embedded chunk text via metadata + the
            # _render_embed_content header. This keeps create-path and
            # patch-path body docs symmetric (both: `# <title>` header
            # once, then description) instead of patched bodies carrying a
            # double title.
            text = result.get("description") or ""
            ingest = await _ingest_bw_write(
                slug=slug,
                source_type="body",
                ticket_id=ticket_id,
                bw_show_snapshot=result,
                text=text,
                comment_n=None,
                principal=principal,
            )
            if isinstance(result, dict):
                result = dict(result)
                result["ariadne_ingest"] = ingest
                result["ariadne_soft_deleted_body_ids"] = deleted
        else:
            patch = await _patch_bw_body_metadata(
                slug=slug,
                ticket_id=ticket_id,
                bw_show_snapshot=result,
                principal=principal,
            )
            if isinstance(result, dict):
                result = dict(result)
                result["ariadne_ingest"] = patch
    return result


@router.delete("/tickets/{ticket_id}")
async def delete_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    force: bool = Query(
        False,
        description=(
            "If true, pass --force to bw delete (actually delete). "
            "If false, bw shows a preview only."
        ),
    ),
    principal: Principal = Depends(require_user),
):
    """Delete an issue. Maps to ``bw delete``.

    Without ``?force=true`` this is a preview (matches bw's default
    safety stance). The caller must pass ``?force=true`` to make the
    deletion stick.
    """
    from pipeline.api.bw_ingest import _soft_delete_ticket_docs

    _validate_slug(slug)
    args: list[str] = ["delete", ticket_id, "--json"]
    if force:
        args += ["--force"]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        if force:
            await _backup_push(slug)
            ingest = await _soft_delete_ticket_docs(
                slug=slug, ticket_id=ticket_id,
            )
            if isinstance(result, dict):
                result = dict(result)
                result["ariadne_ingest"] = ingest
    return result


@router.post("/tickets/{ticket_id}/start")
async def start_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: TicketStart = Body(default_factory=TicketStart),
    principal: Principal = Depends(require_user),
):
    """Move issue to in_progress + assign. Maps to ``bw start``."""
    from pipeline.api.bw_ingest import _patch_bw_body_metadata

    _validate_slug(slug)
    args: list[str] = ["start", ticket_id, "--json"]
    if req.assignee is not None:
        args += ["--assignee", req.assignee]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=result, principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
    return result


@router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: TicketClose = Body(default_factory=TicketClose),
    principal: Principal = Depends(require_user),
):
    """Close an issue. Maps to ``bw close``.

    Phase 3 per design §D3 matrix row for close-with-reason: when
    ``reason`` is non-None, the bw call records BOTH a status change
    AND a comment whose body is the reason. Both side-effects land in
    Ariadne — PATCH-meta on the body doc, plus a new comment doc.
    """
    from pipeline.api.bw_ingest import _ingest_bw_write, _patch_bw_body_metadata

    _validate_slug(slug)
    args: list[str] = ["close", ticket_id, "--json"]
    if req.reason is not None:
        args += ["--reason", req.reason]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        # ariadne--uuo.2 (r4): `bw close --json` nests the issue snapshot
        # under "issue" — its top-level shape is
        # ``{"issue": {...}, "unblocked": [...]}`` — UNLIKE create / comment
        # / update, whose --json IS the issue dict directly. The ingest
        # helpers expect a `bw show`-shaped snapshot (top-level `title` /
        # `type` / `status` / `labels` / `comments` / ...), so unwrap here.
        # `result` itself stays the load-bearing API response payload.
        # Without this unwrap the close path's snapshot metadata —
        # status / assignee / labels / title / type / comment_n — was all
        # silently None/empty; this is a pre-existing shipped bug surfaced
        # by the uuo-2 r4 verification task, fixed in the same seam.
        snapshot = result.get("issue") if isinstance(result, dict) else None
        if not isinstance(snapshot, dict):
            # Defensive: a bw version that does NOT nest still works —
            # fall back to treating `result` as the snapshot directly.
            snapshot = result if isinstance(result, dict) else {}
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=snapshot, principal=principal,
        )
        comment_ingest = None
        if req.reason is not None:
            # The close-reason becomes a real bw comment — its
            # ``comment_n`` is the length of the resulting comments
            # array (same shape rule as the comment-add path uses).
            comments = snapshot.get("comments")
            comment_n = len(comments) if comments else None
            comment_ingest = await _ingest_bw_write(
                slug=slug,
                source_type="comment",
                ticket_id=ticket_id,
                bw_show_snapshot=snapshot,
                text=req.reason,
                comment_n=comment_n,
                principal=principal,
            )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
            if comment_ingest is not None:
                result["ariadne_comment_ingest"] = comment_ingest
    return result


@router.post("/tickets/{ticket_id}/reopen")
async def reopen_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    principal: Principal = Depends(require_user),
):
    """Reopen a closed/in-progress issue. Maps to ``bw reopen``."""
    from pipeline.api.bw_ingest import _patch_bw_body_metadata

    _validate_slug(slug)
    args = ["reopen", ticket_id, "--json"]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=result, principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
    return result


@router.post("/tickets/{ticket_id}/comments", status_code=201)
async def add_comment(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: CommentCreate = Body(...),
    principal: Principal = Depends(require_user),
):
    """Add a comment. Maps to ``bw comment``.

    Phase 3: ingest the new comment as a ``comment``-type document.
    ``comment_n`` is the 1-indexed length of the comments array in the
    bw response (verified shape — bw comment --json returns the full
    ticket view including the just-added comment).
    """
    from pipeline.api.bw_ingest import _ingest_bw_write

    _validate_slug(slug)
    args: list[str] = ["comment", ticket_id, req.text, "--json"]
    if req.author is not None:
        args += ["--author", req.author]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        comments = result.get("comments") if isinstance(result, dict) else None
        comment_n = len(comments) if comments else None
        ingest = await _ingest_bw_write(
            slug=slug,
            source_type="comment",
            ticket_id=ticket_id,
            bw_show_snapshot=result,
            text=req.text,
            comment_n=comment_n,
            principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = ingest
    return result


@router.post("/tickets/{ticket_id}/labels", status_code=201)
async def add_label(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: LabelAdd = Body(...),
    principal: Principal = Depends(require_user),
):
    """Add a label. Maps to ``bw label <id> +<label>``.

    bw's CLI uses a ``+`` prefix to add and ``-`` prefix to remove
    labels on a single shared subcommand. We expose those as two
    HTTP endpoints (POST to add, DELETE to remove) — the prefix is
    composed server-side.
    """
    _validate_slug(slug)
    # Reject any caller that prepends + or - themselves to keep the
    # semantics single-purpose. The DELETE endpoint is how you remove.
    if req.label.startswith("+") or req.label.startswith("-"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_label",
                "message": (
                    "Label must not start with + or -. Use the "
                    "DELETE endpoint to remove a label."
                ),
            },
        )
    args = ["label", ticket_id, f"+{req.label}", "--json"]

    from pipeline.api.bw_ingest import _patch_bw_body_metadata

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=result, principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
    return result


@router.delete("/tickets/{ticket_id}/labels/{label}")
async def remove_label(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    label: str = Path(
        ..., min_length=1, max_length=128, pattern=_PATH_PARAM_NO_NUL
    ),
    principal: Principal = Depends(require_user),
):
    """Remove a label. Maps to ``bw label <id> -<label>``."""
    _validate_slug(slug)
    if label.startswith("+") or label.startswith("-"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_label",
                "message": "Label path segment must not start with + or -.",
            },
        )
    args = ["label", ticket_id, f"-{label}", "--json"]

    from pipeline.api.bw_ingest import _patch_bw_body_metadata

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=result, principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
    return result


@router.post("/tickets/{ticket_id}/defer")
async def defer_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: DeferRequest = Body(...),
    principal: Principal = Depends(require_user),
):
    """Defer an issue until a target date. Maps to ``bw defer``."""
    from pipeline.api.bw_ingest import _patch_bw_body_metadata

    _validate_slug(slug)
    args = ["defer", ticket_id, req.when, "--json"]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=result, principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
    return result


@router.post("/tickets/{ticket_id}/undefer")
async def undefer_ticket(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    principal: Principal = Depends(require_user),
):
    """Restore a deferred issue. Maps to ``bw undefer``."""
    from pipeline.api.bw_ingest import _patch_bw_body_metadata

    _validate_slug(slug)
    args = ["undefer", ticket_id, "--json"]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
        patch = await _patch_bw_body_metadata(
            slug=slug, ticket_id=ticket_id,
            bw_show_snapshot=result, principal=principal,
        )
        if isinstance(result, dict):
            result = dict(result)
            result["ariadne_ingest"] = patch
    return result


@router.post("/tickets/{ticket_id}/deps", status_code=201)
async def add_dep(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    req: DepAdd = Body(...),
    principal: Principal = Depends(require_user),
):
    """Add a dependency: ``ticket_id`` blocks ``req.blocks``.

    Maps to ``bw dep add <ticket_id> blocks <target>``. The literal
    word ``blocks`` is bw's positional separator, not a flag — it is
    part of the argv we construct here, not a value the caller
    controls. The caller controls only the two ticket IDs.
    """
    _validate_slug(slug)
    args = ["dep", "add", ticket_id, "blocks", req.blocks, "--json"]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
    return result


@router.delete("/tickets/{ticket_id}/deps/{target}")
async def remove_dep(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    target: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    principal: Principal = Depends(require_user),
):
    """Remove the ``ticket_id blocks target`` dependency.

    Maps to ``bw dep remove <ticket_id> blocks <target>``.
    """
    _validate_slug(slug)
    args = ["dep", "remove", ticket_id, "blocks", target, "--json"]

    lock = await _lock_for(slug)
    async with lock:
        result = await _run_bw(slug, *args, json_output=True)
        await _backup_push(slug)
    return result


@router.get("/tickets/{ticket_id}/history")
async def ticket_history(
    slug: str = Path(...),
    ticket_id: str = Path(..., pattern=_PATH_PARAM_NO_NUL),
    limit: Optional[int] = Query(None, ge=1, le=10000),
    principal: Principal = Depends(require_user),
):
    """Show git commit history for an issue. Maps to ``bw history``."""
    _validate_slug(slug)
    args = ["history", ticket_id, "--json"]
    if limit is not None:
        args += ["--limit", str(limit)]
    return await _run_bw(slug, *args, json_output=True)


# ── Repo-level endpoints ───────────────────────────────────────────────────


@router.get("/ready")
async def list_ready(
    slug: str = Path(...),
    principal: Principal = Depends(require_user),
):
    """List unblocked issues. Maps to ``bw ready``."""
    _validate_slug(slug)
    return await _run_bw(slug, "ready", "--json", json_output=True)


@router.get("/blocked")
async def list_blocked(
    slug: str = Path(...),
    principal: Principal = Depends(require_user),
):
    """List blocked issues. Maps to ``bw blocked``."""
    _validate_slug(slug)
    return await _run_bw(slug, "blocked", "--json", json_output=True)


@router.post("/sync")
async def sync_repo(
    slug: str = Path(...),
    principal: Principal = Depends(require_user),
):
    """Fetch + rebase + push the beadwork branch. Maps to ``bw sync``.

    No ``--json`` support on this subcommand — stdout is captured
    verbatim. Held under the per-slug lock because sync rewrites
    history (rebase) and would race a concurrent write.
    """
    _validate_slug(slug)
    lock = await _lock_for(slug)
    async with lock:
        return await _run_bw(slug, "sync", json_output=False)


@router.get("/onboard")
async def onboard(
    slug: str = Path(...),
    principal: Principal = Depends(require_user),
):
    """Return the agent onboarding snippet. Maps to ``bw onboard``."""
    _validate_slug(slug)
    return await _run_bw(slug, "onboard", json_output=False)


@router.get("/prime")
async def prime(
    slug: str = Path(...),
    principal: Principal = Depends(require_user),
):
    """Return the workflow-context snippet. Maps to ``bw prime``."""
    _validate_slug(slug)
    return await _run_bw(slug, "prime", json_output=False)


@router.get("/health")
async def bw_health(
    slug: str = Path(...),
    principal: Principal = Depends(require_user),
):
    """Phase 3 observability: ingest-retry depth + file-fallback metrics.

    The slug is required by the path but not used for the metrics body —
    the queue depth is global by design (one Postgres table for all
    slugs; per-slug breakdown returned as a dict). Returning under
    ``/api/bw/projects/{slug}/health`` keeps the URL convention
    consistent; an operator hitting any slug's health endpoint gets the
    same view, with the per-slug breakdown surfacing how the depth is
    distributed.
    """
    from pipeline.api.bw_ingest import get_retry_metrics

    _validate_slug(slug)
    return get_retry_metrics()


@router.get("/export")
async def export_jsonl(
    slug: str = Path(...),
    status: Optional[str] = Query(None, pattern=_PATH_PARAM_NO_NUL),
    principal: Principal = Depends(require_user),
):
    """Export issues as JSONL. Maps to ``bw export``.

    Output is JSONL (one JSON object per line), not JSON — bw does
    not honor ``--json`` here. We return the raw stdout under
    ``output`` for the caller to split on newlines as needed.
    """
    _validate_slug(slug)
    args: list[str] = ["export"]
    if status is not None:
        args += ["--status", status]
    return await _run_bw(slug, *args, json_output=False)


# ── In-place re-embed (ariadne--uuo.5) ─────────────────────────────────────


@router.post("/reembed")
async def reembed_project(
    slug: str = Path(...),
    req: ReembedRequest = Body(default_factory=ReembedRequest),
    principal: Principal = Depends(require_user),
):
    """Re-embed bw tickets in place — the GOOD migration path (uuo-5).

    ariadne--uuo.5 (design §6). Walks the on-disk bw repo for ``slug``
    and, for every ticket (or the ``ticket_ids`` subset), re-ingests the
    body + every comment via the snapshot-driven ingest core with
    ``force=True`` and the resolved existing ``documents.id`` per slot —
    so the new clean (uuo-2) embed-content lands on the *same* document
    rows, the old polluted chunks are deleted, and the bw repo itself is
    only read, never written.

    This does NOT recreate bw tickets (that is ``seed_bw_corpus.py`` — the
    BAD path). It is the reusable operational capability for every future
    ingest-logic change, and the migration path for the existing
    ~1020-doc ``aresense`` corpus (uuo-6 runs that migration against this
    route).

    Body (both fields optional — see ``ReembedRequest``):
      ``{"ticket_ids": [...], "dry_run": false}``

    Per-ticket lock scope: the orchestrator acquires/releases the shipped
    per-slug ``_lock_for(slug)`` at the per-ticket boundary — held
    atomically across one ticket's body + entire comments loop, released
    between tickets (design §6.8).

    Summary response:
      ``{reembedded, fresh_inserted, orphaned_tickets, errors, dry_run,
         tickets_enumerated}`` — plus ``docs_would_reembed`` on a dry run.
    """
    from pipeline.api.bw_ingest import _reembed_tickets

    _validate_slug(slug)
    # _resolve_repo_path (called inside _reembed_tickets) enforces the
    # initialized-repo guard and raises 404 for an uninitialized slug,
    # consistent with every other bw route.
    return await _reembed_tickets(
        slug=slug,
        ticket_ids=req.ticket_ids,
        dry_run=req.dry_run,
        agent_id=principal.user_id,
    )


# ── Project bootstrap (ariadne--9e7) ───────────────────────────────────────
#
# ``POST /api/bw/projects`` lets an authenticated caller initialize a brand-
# new bw project without holding an SSH shell on the host. Closes the gap
# left by Phase 5 (8fd.9), whose "Operator setup checklist" hard-coded a
# three-step manual sequence:
#
#   mkdir -p {BW_REPOS_ROOT}/{slug}
#   git init {BW_REPOS_ROOT}/{slug}
#   bw -C {BW_REPOS_ROOT}/{slug} init --prefix {slug}
#
# The handler runs the same three steps under the per-slug write lock,
# rolls back on partial failure, and returns 409 if the slug already
# exists on disk (idempotent re-init would silently destroy the orphan
# beadwork branch — operator surface this rather than swallow it).


@projects_router.post("", status_code=201)
async def create_project(
    req: ProjectCreate = Body(...),
    principal: Principal = Depends(require_user),
):
    """Initialize a new bw project on disk.

    Sequence (all under the per-slug lock):

      1. ``os.makedirs(<repo_path>, exist_ok=False)`` — if the slug dir
         already exists, return **409** ``slug_already_exists`` without
         touching it.
      2. ``git init <repo_path>`` via subprocess. On failure, roll back
         the directory and return **500** ``init_failed`` with step set
         to ``git_init`` and bw's stderr (sanitized) in the body.
      3. ``bw -C <repo_path> init --prefix <slug>`` via subprocess. Same
         rollback + 500 semantics on failure, with step set to
         ``bw_init``.

    Rollback uses ``shutil.rmtree(..., ignore_errors=True)`` so the next
    operator attempt starts clean. The slug-dir creation, the git init,
    and the bw init are NOT atomic at the filesystem level — but the
    rollback restores the pre-call state for any failure on steps 2 or
    3, and step 1's ``exist_ok=False`` makes step 1's failure
    distinguishable (409, not 500). The whole sequence is held under
    the per-slug lock so a concurrent create against the same slug
    serializes — the second attempt will see step 1's ``exist_ok=False``
    failure and return 409 even if the first attempt is still mid-flight.

    Returns **201** with ``{"slug": <slug>, "status": "created",
    "repo_path": <absolute path>}`` on success.

    The ``options`` field on the request body is accepted for forward-
    compat but ignored in v1 — per-slug knobs (e.g., inline backup-remote
    config) stay env-var-driven via ``BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}``.
    """
    _validate_slug(req.slug)

    if BW_BINARY is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "bw_binary_missing",
                "message": (
                    "The bw binary was not found on PATH at app import. "
                    "Check the Dockerfile install step (Phase 5)."
                ),
            },
        )

    repo_path = os.path.join(BW_REPOS_ROOT, req.slug)
    lock = await _lock_for(req.slug)
    async with lock:
        # Step 1: create the slug directory. ``exist_ok=False`` is the
        # 409 trigger — a pre-existing directory means the slug is
        # already in some prior state (initialized, half-initialized,
        # or holding unrelated content), and silently re-initing would
        # destroy it.
        try:
            os.makedirs(repo_path, exist_ok=False)
        except FileExistsError:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "slug_already_exists",
                    "slug": req.slug,
                    "repo_path": repo_path,
                    "message": (
                        f"Project {req.slug!r} already exists at "
                        f"{repo_path}. Refusing to re-initialize "
                        f"(would destroy any existing orphan beadwork "
                        f"branch). Operator action: choose a different "
                        f"slug, or remove the existing directory after "
                        f"manual inspection."
                    ),
                },
            )
        except OSError as e:
            # Permission / mount-unavailable / disk-full / etc.
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "init_failed",
                    "step": "makedirs",
                    "slug": req.slug,
                    "stderr": str(e),
                },
            ) from e

        # Step 2: git init. Rolls back on failure.
        try:
            git_proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "init", repo_path],
                capture_output=True,
                text=True,
                timeout=BW_SUBPROCESS_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            shutil.rmtree(repo_path, ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "init_failed",
                    "step": "git_init",
                    "slug": req.slug,
                    "stderr": str(e),
                },
            ) from e
        if git_proc.returncode != 0:
            shutil.rmtree(repo_path, ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "init_failed",
                    "step": "git_init",
                    "slug": req.slug,
                    "exit_code": git_proc.returncode,
                    "stderr": (git_proc.stderr or "").strip()[:2000],
                },
            )

        # Step 3: bw init --prefix <slug>. Rolls back on failure.
        # ``bw 0.12.3 init`` runs in CWD and does NOT accept a path
        # argument — but ``bw -C <dir>`` sets the working directory
        # for the subprocess. Same pattern as every other bw call.
        try:
            bw_proc = await asyncio.to_thread(
                subprocess.run,
                [BW_BINARY, "-C", repo_path, "init", "--prefix", req.slug],
                capture_output=True,
                text=True,
                timeout=BW_SUBPROCESS_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            shutil.rmtree(repo_path, ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "init_failed",
                    "step": "bw_init",
                    "slug": req.slug,
                    "stderr": str(e),
                },
            ) from e
        if bw_proc.returncode != 0:
            shutil.rmtree(repo_path, ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "init_failed",
                    "step": "bw_init",
                    "slug": req.slug,
                    "exit_code": bw_proc.returncode,
                    "stderr": (bw_proc.stderr or "").strip()[:2000],
                },
            )

    logger.info(
        "bw project initialized: slug=%s repo_path=%s actor=%s",
        req.slug, repo_path, principal.user_id,
    )
    return {
        "slug": req.slug,
        "status": "created",
        "repo_path": repo_path,
    }


# ── Deferred surface (out of v1 scope) ─────────────────────────────────────
#
# These subcommands exist in bw 0.12.3 but don't have a clear v1 HTTP
# shape, so we explicitly do NOT scaffold them. Surfaced here so a
# future ticket can pick them up.
#
#   • bw upgrade     — admin / manual ops; not an agent-facing call.
#   • bw config      — admin surface. Defer until a real ACL story
#                       exists; until then config changes happen on
#                       the host directly.
#   • bw registry    — host-local registry; per-process state, not
#                       per-repo. Not relevant to the slug-routed API.
#   • bw attach      — needs multipart upload semantics (caller hands
#                       the API a file blob, not a path on the server
#                       filesystem). Defer until Phase 3 / Phase 4
#                       since the answer shape interacts with the
#                       broader "API accepts file content" question
#                       that Phase 3 (inline ingest) settles.
#   • bw import      — same as attach: needs file upload. Defer.
#
# TODO(ariadne--8fd.<future>): scaffold attach + import with multipart
# handlers once Phase 3's inline-ingest upload surface lands.
# TODO(ariadne--8fd.<future>): expose bw config GET (read-only) — the
# mutation surface stays internal until the ACL story exists.
