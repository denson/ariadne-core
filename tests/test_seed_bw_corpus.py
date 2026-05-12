"""Tests for scripts/seed_bw_corpus.py (ariadne--8fd.6 / Phase 4).

The script under test is a stand-alone CLI tool, not part of the
``pipeline`` package — it lives at ``<repo-root>/scripts/seed_bw_corpus.py``
and depends only on ``httpx`` plus stdlib. The tests import it via a
``sys.path`` insert because the ``scripts/`` directory is not on the
default Python path (intentional — these are end-user scripts, not
library code).

Coverage targets (per ariadne--8fd.6 brief):

  * Mock the HTTP client. Assert correct URL/method/body for each
    ticket + comment.
  * Assert ``--limit`` is respected.
  * Assert dedup-skip handling (mock create endpoint to return Phase 3's
    ``was_dedup_skip=true`` augmentation; script should count + continue).
  * Assert restart-idempotency at the script level (run twice against
    same fixture; second run skips all).
  * Assert clean exit codes (0 on success, 1 on errors, 2 on config).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


# ── Module loader (script lives outside the pipeline package) ──────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import seed_bw_corpus as sbc  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_source_ticket(
    ticket_id: str,
    *,
    title: str = "test ticket",
    description: str = "",
    priority: int = 2,
    type_: str = "task",
    parent: str = "",
    comments: list[dict[str, Any]] | None = None,
    status: str = "open",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "title": title,
        "description": description,
        "priority": priority,
        "type": type_,
        "parent": parent,
        "assignee": "",
        "blocked_by": [],
        "blocks": [],
        "labels": labels or [],
        "status": status,
        "created": "2026-05-12T00:00:00Z",
        "updated_at": "2026-05-12T00:00:00Z",
        "comments": comments or [],
    }


@pytest.fixture
def synthetic_bw_repo(tmp_path: Path) -> Path:
    """Build a fake bw repo with an orphan 'beadwork' branch via real git.

    Uses real git (not a mock) so the script's ``git show`` enumeration
    is exercised end-to-end. The orphan branch carries an ``issues/``
    directory with one JSON file per ticket — matching the bw 0.12.3
    on-disk format the script depends on.
    """
    repo = tmp_path / "synthetic-bw"
    repo.mkdir()
    # Configure git to not require a user committed by default; tests
    # may run in CI sandboxes without a global git identity.
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            env=env,
            capture_output=True,
        )

    _git("init", "--initial-branch=master", "-q")
    # First commit on master so the repo is well-formed; never touched
    # by the script (script reads orphan ``beadwork`` branch only).
    (repo / "README.md").write_text("synthetic", encoding="utf-8")
    _git("add", "README.md")
    _git("commit", "-q", "-m", "init")

    # Build the orphan ``beadwork`` branch via plumbing
    # (``mktree`` + ``commit-tree`` + ``update-ref``) so the test does
    # not depend on ``git worktree add --orphan``, which was added in
    # git 2.42 — older Windows installs (2.40) hit ``ambiguous option:
    # orphan`` and crash the fixture. The plumbing path works on every
    # git that ships ``mktree`` (which is every modern release).

    tickets = [
        _make_source_ticket("aa-001", title="alpha", description="first ticket"),
        _make_source_ticket(
            "aa-002",
            title="beta",
            description="second ticket with comments",
            comments=[
                {"text": "first comment", "timestamp": "2026-05-12T01:00:00Z"},
                {"text": "second comment", "timestamp": "2026-05-12T02:00:00Z"},
            ],
        ),
        _make_source_ticket(
            "aa-003",
            title="gamma",
            description="",
            parent="aa-001",
            priority=3,
        ),
    ]

    # Hash-object each ticket JSON, then build a ``mktree`` listing for
    # the ``issues`` directory, then assemble the root tree containing
    # only ``issues/``.
    #
    # IMPORTANT: pass ``input`` and parse ``stdout`` as bytes
    # (``text=False``) rather than as text. Python's text-mode
    # subprocess translates ``\n`` to the platform line-ending on write
    # — on Windows this means ``\r\n`` lands in git's stdin, and
    # ``git mktree`` treats the trailing ``\r`` as part of the filename
    # (the resulting tree has entries like ``.gitkeep\r`` and the
    # script's ``git show beadwork:issues/aa-002.json`` then can't
    # resolve them). Binary I/O bypasses universal-newlines translation.

    def _stdin_call(input_bytes: bytes, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            input=input_bytes, check=True, env=env, capture_output=True,
        ).stdout.strip()

    issues_entries: list[str] = []
    # ``.gitkeep`` parity with the workspace's real beadwork layout —
    # the parser must filter it out, so include it in the fixture.
    gitkeep_hash = _stdin_call(b"", "hash-object", "-w", "--stdin").decode()
    issues_entries.append(f"100644 blob {gitkeep_hash}\t.gitkeep")

    for t in tickets:
        body = json.dumps(t, indent=2).encode("utf-8")
        obj_hash = _stdin_call(body, "hash-object", "-w", "--stdin").decode()
        issues_entries.append(f"100644 blob {obj_hash}\t{t['id']}.json")

    issues_tree_input = ("\n".join(issues_entries) + "\n").encode("utf-8")
    issues_tree_hash = _stdin_call(issues_tree_input, "mktree").decode()

    root_tree_input = (
        f"040000 tree {issues_tree_hash}\tissues\n"
    ).encode("utf-8")
    root_tree_hash = _stdin_call(root_tree_input, "mktree").decode()

    commit_hash = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", root_tree_hash, "-m", "seed"],
        check=True, env=env, capture_output=True,
    ).stdout.strip().decode()

    _git("update-ref", "refs/heads/beadwork", commit_hash)
    return repo


# ── Fake HTTP layer (the seam tests inject) ────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any] | None = None):
        self.status_code = status_code
        self._body = body or {}
        self.content = json.dumps(self._body).encode("utf-8") if body else b""
        self.text = json.dumps(self._body) if body else ""

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeHttp:
    """Stand-in for ``_SeedHttp`` that records all calls.

    Behaviour controlled by ``next_id_seq`` (yields a fresh ``id``
    string per ticket POST) and ``dedup_on_create`` / ``dedup_on_comment``
    (toggle Phase 3's ``ariadne_ingest.was_dedup_skip`` in the
    response). Comment POSTs return ``201`` with a body that doesn't
    matter for the script's bookkeeping beyond ``ariadne_ingest``.
    """

    def __init__(
        self,
        *,
        dedup_on_create: bool = False,
        dedup_on_comment: bool = False,
        fail_on_create: bool = False,
        fail_on_comment_idx: int | None = None,
    ):
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._next_target = 0
        self.dedup_on_create = dedup_on_create
        self.dedup_on_comment = dedup_on_comment
        self.fail_on_create = fail_on_create
        self.fail_on_comment_idx = fail_on_comment_idx
        self._comment_calls = 0
        self.deletes: list[str] = []

    def __enter__(self) -> "_FakeHttp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, path: str, json_body: dict[str, Any]) -> _FakeResponse:
        self.calls.append(("POST", path, json_body))

        if path.endswith("/tickets"):
            if self.fail_on_create:
                return _FakeResponse(400, {"detail": "synthetic create failure"})
            self._next_target += 1
            target_id = f"tg-{self._next_target:03d}"
            return _FakeResponse(
                201,
                {
                    "id": target_id,
                    "title": json_body.get("title", ""),
                    "ariadne_ingest": {
                        "document_id": f"doc-{target_id}",
                        "was_dedup_skip": self.dedup_on_create,
                    },
                },
            )

        if "/comments" in path:
            self._comment_calls += 1
            if (
                self.fail_on_comment_idx is not None
                and self._comment_calls - 1 == self.fail_on_comment_idx
            ):
                return _FakeResponse(500, {"detail": "synthetic 5xx"})
            return _FakeResponse(
                201,
                {
                    "comments": [{"text": json_body["text"]}],
                    "ariadne_ingest": {
                        "document_id": "doc-comment",
                        "was_dedup_skip": self.dedup_on_comment,
                    },
                },
            )

        return _FakeResponse(404, {"detail": f"unmocked path {path}"})

    def delete(self, path: str) -> _FakeResponse:
        self.deletes.append(path)
        return _FakeResponse(200, {})


def _args(
    bw_repo: Path,
    *,
    project: str = "phase4-validation",
    limit: int | None = None,
    dry_run: bool = False,
    start_after: str | None = None,
    state_file: str | None = None,
    rate_limit_sleep: float = 0.0,
    ariadne_host: str | None = "https://example.invalid",
) -> argparse.Namespace:
    return argparse.Namespace(
        bw_repo=str(bw_repo),
        project=project,
        limit=limit,
        ariadne_host=ariadne_host,
        dry_run=dry_run,
        start_after=start_after,
        state_file=state_file,
        rate_limit_sleep=rate_limit_sleep,
    )


# ── Tests: happy path ──────────────────────────────────────────────────────


def test_seed_three_tickets_with_comments(synthetic_bw_repo: Path) -> None:
    """Full happy path: 3 tickets, 2 comments on the middle one.

    Asserts:
      * Each ticket triggers one ``POST /api/bw/projects/{slug}/tickets``.
      * Comments POST to ``/tickets/{target_id}/comments``.
      * Body shapes (title, description, priority, type, parent) match
        the source.
      * Counters: 3 seeded, 2 comments, 0 errors → exit 0.
      * State file is written under the bw repo.
    """
    http = _FakeHttp()
    args = _args(synthetic_bw_repo)
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 0
    # 3 ticket creates + 2 comment creates = 5 POSTs.
    assert len(http.calls) == 5

    # POST 1: aa-001 → tickets endpoint.
    method, path, body = http.calls[0]
    assert method == "POST"
    assert path == "/api/bw/projects/phase4-validation/tickets"
    assert body["title"] == "alpha"
    assert body["description"] == "first ticket"
    assert body["priority"] == 2
    assert body["type"] == "task"
    assert "parent" not in body  # source parent was ""

    # POST 2: aa-002 → ticket
    method, path, body = http.calls[1]
    assert path == "/api/bw/projects/phase4-validation/tickets"
    assert body["title"] == "beta"

    # POST 3 + 4: aa-002 comments
    for idx, expected_text in enumerate(["first comment", "second comment"]):
        method, path, body = http.calls[2 + idx]
        assert method == "POST"
        # tg-002 because aa-002 is the 2nd ticket POSTed.
        assert path == "/api/bw/projects/phase4-validation/tickets/tg-002/comments"
        assert body["text"] == expected_text

    # POST 5: aa-003 (with parent)
    method, path, body = http.calls[4]
    assert path == "/api/bw/projects/phase4-validation/tickets"
    assert body["title"] == "gamma"
    assert body["parent"] == "aa-001"
    assert body["priority"] == 3

    # State file written with all 3 source IDs mapped.
    state_path = synthetic_bw_repo / ".ariadne_seed_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state) == {"aa-001", "aa-002", "aa-003"}
    assert state["aa-001"]["target_id"] == "tg-001"
    assert state["aa-002"]["target_id"] == "tg-002"
    assert state["aa-002"]["target_comments"] == 2
    assert state["aa-003"]["target_id"] == "tg-003"


def test_limit_respected(synthetic_bw_repo: Path) -> None:
    """``--limit 1`` processes only the first ticket, no later POSTs."""
    http = _FakeHttp()
    args = _args(synthetic_bw_repo, limit=1)
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 0
    # 1 ticket, 0 comments (aa-001 has no comments).
    assert len(http.calls) == 1
    _, path, _ = http.calls[0]
    assert path.endswith("/tickets")


def test_dry_run_makes_no_http_calls(synthetic_bw_repo: Path) -> None:
    """``--dry-run`` enumerates but emits no POSTs and no state file."""
    http = _FakeHttp()
    args = _args(synthetic_bw_repo, dry_run=True)
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 0
    assert http.calls == []
    assert not (synthetic_bw_repo / ".ariadne_seed_state.json").exists()


# ── Tests: idempotency / restart ────────────────────────────────────────────


def test_restart_skips_already_seeded_tickets(synthetic_bw_repo: Path) -> None:
    """Run twice; second run skips every ticket via the state file.

    First run POSTs everything and writes state. Second run reads state,
    finds every source id present with matching comment count, and
    skips — emitting zero HTTP calls.
    """
    http1 = _FakeHttp()
    args = _args(synthetic_bw_repo)
    sbc.run(args, http_factory=lambda *_a, **_kw: http1, log=lambda _m: None)
    assert len(http1.calls) == 5  # 3 tickets + 2 comments

    http2 = _FakeHttp()
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http2, log=lambda _m: None)
    assert rc == 0
    assert http2.calls == [], (
        "second run should skip all tickets via state file; got "
        f"{http2.calls}"
    )


def test_restart_emits_new_comments_only(
    synthetic_bw_repo: Path, tmp_path: Path
) -> None:
    """If the source grew a comment after the first run, the second run
    POSTs only the new comment, not the ticket itself.

    Manually rewrite the state file to simulate "one comment was already
    seeded last run; the source now has two." The script must POST one
    comment (the new one) and zero tickets.
    """
    # Pre-populate state with the second ticket having only 1 comment
    # POSTed previously; the source has 2.
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "aa-001": {"target_id": "tg-001", "target_comments": 0},
                "aa-002": {"target_id": "tg-002", "target_comments": 1},
                "aa-003": {"target_id": "tg-003", "target_comments": 0},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    http = _FakeHttp()
    args = _args(synthetic_bw_repo, state_file=str(state_path))
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 0
    # One POST: the second comment on aa-002.
    assert len(http.calls) == 1
    method, path, body = http.calls[0]
    assert method == "POST"
    assert path == "/api/bw/projects/phase4-validation/tickets/tg-002/comments"
    assert body["text"] == "second comment"


def test_start_after_skips_lower_ids(synthetic_bw_repo: Path) -> None:
    """``--start-after aa-001`` skips aa-001, processes aa-002 and aa-003."""
    http = _FakeHttp()
    args = _args(synthetic_bw_repo, start_after="aa-001")
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 0
    ticket_titles = [
        body["title"]
        for (_method, path, body) in http.calls
        if path.endswith("/tickets")
    ]
    assert ticket_titles == ["beta", "gamma"]


# ── Tests: dedup tracking ──────────────────────────────────────────────────


def test_dedup_skip_counted(synthetic_bw_repo: Path, tmp_path: Path) -> None:
    """When Phase 3 reports ``was_dedup_skip=true`` the counter increments.

    Run against a synthetic repo with three tickets where the create
    endpoint always returns ``ariadne_ingest.was_dedup_skip=true``.
    The script should still record every ticket in state (the bw
    write succeeded — only the Ariadne ingest was a noop), and the
    ``dedup_skipped`` counter should equal the number of tickets
    + comments (3 tickets + 2 comments = 5).
    """
    # Use a fresh state file (separate from the default) so the run
    # is a true first-run — otherwise restart-idempotency skips the
    # POSTs and the dedup counter stays 0.
    state_file = tmp_path / "dedup-state.json"
    log_lines: list[str] = []
    rc = sbc.run(
        _args(synthetic_bw_repo, state_file=str(state_file)),
        http_factory=lambda *_a, **_kw: _FakeHttp(
            dedup_on_create=True, dedup_on_comment=True,
        ),
        log=log_lines.append,
    )
    assert rc == 0
    dedup_line = [
        line for line in log_lines if line.strip().startswith("dedup_skipped:")
    ]
    assert dedup_line, f"no dedup_skipped line in {log_lines}"
    assert dedup_line[0].strip() == "dedup_skipped: 5"


# ── Tests: error handling ──────────────────────────────────────────────────


def test_ticket_create_failure_counted_and_run_continues(
    synthetic_bw_repo: Path,
) -> None:
    """A 4xx on ticket POST increments ``errors`` and the run continues.

    ``_FakeHttp(fail_on_create=True)`` returns 400 for every ticket
    POST. The script should log + count + return exit 1, but it should
    NOT raise.
    """
    http = _FakeHttp(fail_on_create=True)
    args = _args(synthetic_bw_repo)
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 1, "errors > 0 should yield exit code 1"
    # No ticket got an id back, so nothing is persisted in state.
    state_path = synthetic_bw_repo / ".ariadne_seed_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state == {}


def test_comment_failure_persists_partial_progress(
    synthetic_bw_repo: Path,
) -> None:
    """A failure mid-comment-loop leaves the state file at the last
    successfully-seeded comment so a restart can resume cleanly.

    ``aa-002`` has two comments. We fail on the first (idx 0); the
    ticket itself created OK, and the script should:
      * record the ticket's ``target_id`` in state
      * leave ``target_comments`` at 0 (the failed comment is NOT
        recorded as done; a restart will retry it)
      * increment ``errors`` (exit 1)
    """
    http = _FakeHttp(fail_on_comment_idx=0)
    args = _args(synthetic_bw_repo)
    rc = sbc.run(args, http_factory=lambda *_a, **_kw: http, log=lambda _m: None)
    assert rc == 1
    state_path = synthetic_bw_repo / ".ariadne_seed_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "aa-002" in state
    assert state["aa-002"]["target_comments"] == 0


# ── Tests: argument / config validation ────────────────────────────────────


def test_invalid_slug_rejected(synthetic_bw_repo: Path) -> None:
    """A bad ``--project`` slug fails fast before any HTTP call."""
    args = _args(synthetic_bw_repo, project="HAS_UPPERCASE")
    with pytest.raises(sbc.SeedConfigError):
        sbc.run(args, http_factory=lambda *_a, **_kw: _FakeHttp(),
                log=lambda _m: None)


def test_missing_repo_path_rejected(tmp_path: Path) -> None:
    """``--bw-repo`` pointing nowhere is a config error."""
    args = _args(tmp_path / "no-such")
    with pytest.raises(sbc.SeedConfigError):
        sbc.run(args, http_factory=lambda *_a, **_kw: _FakeHttp(),
                log=lambda _m: None)


def test_main_returns_2_on_config_error(tmp_path: Path) -> None:
    """``main()`` catches SeedConfigError and returns exit code 2."""
    rc = sbc.main(
        ["--bw-repo", str(tmp_path / "no-such"),
         "--project", "phase4-validation"]
    )
    assert rc == 2


# ── Tests: source-enumeration parser ────────────────────────────────────────


def test_list_source_ticket_ids_parses_tree_output(synthetic_bw_repo: Path) -> None:
    """The git-show parser strips the header line + .gitkeep + .json suffix."""
    ids = sbc._list_source_ticket_ids(synthetic_bw_repo)
    assert ids == ["aa-001", "aa-002", "aa-003"]


def test_read_source_ticket_round_trip(synthetic_bw_repo: Path) -> None:
    """Each on-disk JSON parses back to a dict matching the source."""
    t = sbc._read_source_ticket(synthetic_bw_repo, "aa-002")
    assert t["id"] == "aa-002"
    assert t["title"] == "beta"
    assert len(t["comments"]) == 2
    assert t["comments"][0]["text"] == "first comment"


# ── Tests: state-file atomicity ────────────────────────────────────────────


def test_state_file_atomic_write(tmp_path: Path) -> None:
    """``_save_state`` overwrites via temp-then-rename; no half-written file."""
    path = tmp_path / "state.json"
    sbc._save_state(path, {"a": {"target_id": "x", "target_comments": 0}})
    sbc._save_state(path, {"a": {"target_id": "y", "target_comments": 1}})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"a": {"target_id": "y", "target_comments": 1}}
    # No .tmp left behind.
    assert not (tmp_path / "state.json.tmp").exists()


def test_load_state_missing_returns_empty(tmp_path: Path) -> None:
    assert sbc._load_state(tmp_path / "absent.json") == {}


def test_load_state_malformed_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(sbc.SeedConfigError):
        sbc._load_state(path)


# ── Tests: state-file location hygiene warning (R5) ────────────────────────


def test_state_file_inside_repo_warning_fires(
    synthetic_bw_repo: Path,
) -> None:
    """When the (default) state file lives inside the bw repo's working
    tree AND the source repo has no ``.gitignore`` excluding it, the
    script logs a WARNING line nudging the operator to add it.
    """
    log_lines: list[str] = []
    args = _args(synthetic_bw_repo, dry_run=True)  # dry-run = no HTTP
    rc = sbc.run(
        args,
        http_factory=lambda *_a, **_kw: _FakeHttp(),
        log=log_lines.append,
    )
    assert rc == 0
    warning_lines = [
        line for line in log_lines if "WARNING" in line and "state file" in line
    ]
    assert warning_lines, (
        f"expected a state-file location warning; log was:\n"
        + "\n".join(log_lines)
    )


def test_state_file_outside_repo_no_warning(
    synthetic_bw_repo: Path, tmp_path: Path,
) -> None:
    """State file outside the bw repo emits no warning."""
    state_path = tmp_path / "outside-state.json"
    log_lines: list[str] = []
    args = _args(synthetic_bw_repo, dry_run=True, state_file=str(state_path))
    rc = sbc.run(
        args,
        http_factory=lambda *_a, **_kw: _FakeHttp(),
        log=log_lines.append,
    )
    assert rc == 0
    warning_lines = [
        line for line in log_lines if "WARNING" in line and "state file" in line
    ]
    assert not warning_lines, (
        f"unexpected warning when state file is outside the repo:\n"
        + "\n".join(log_lines)
    )


def test_state_file_inside_repo_but_gitignored_no_warning(
    synthetic_bw_repo: Path,
) -> None:
    """If the source repo's ``.gitignore`` already lists the state-file
    basename, the warning does NOT fire.
    """
    # Add an entry for the default state file basename.
    gitignore = synthetic_bw_repo / ".gitignore"
    gitignore.write_text(
        ".ariadne_seed_state.json\n", encoding="utf-8",
    )
    log_lines: list[str] = []
    args = _args(synthetic_bw_repo, dry_run=True)
    rc = sbc.run(
        args,
        http_factory=lambda *_a, **_kw: _FakeHttp(),
        log=log_lines.append,
    )
    assert rc == 0
    warning_lines = [
        line for line in log_lines if "WARNING" in line and "state file" in line
    ]
    assert not warning_lines, (
        f"unexpected warning when state file is gitignored:\n"
        + "\n".join(log_lines)
    )
