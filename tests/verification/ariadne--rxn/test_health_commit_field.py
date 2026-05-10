"""Probes for ariadne--rxn — /api/health surfaces a ``commit`` field.

Resolution-order probes:

  A) The response body has a ``commit`` key whose value is a string.
  B.1) ``RAILWAY_GIT_COMMIT_SHA`` wins when present.
  B.2) ``GIT_COMMIT`` is the secondary source.
  B.3) The resolved value is cached at module level (env flips after
       first resolve do not move the value within a process).
  B.4) When no env source and no ``.git/HEAD`` is reachable, the field
       is the literal string ``"unknown"``.
  C.1) ``.git`` directory layout (regular checkout) — when env vars
       are unset, the SHA is read from ``.git/HEAD`` walked through
       the loose ``refs/heads/<branch>`` file. (CATO Finding 2.)
  C.2) ``.git`` file layout (linked worktree) — when env vars are
       unset and ``.git`` is a *file* with ``gitdir: <path>``, the
       SHA is resolved via the linked git dir's HEAD plus the shared
       ``commondir``'s loose ref file. This is the case ``rxn``'s
       prior implementation silently failed in (CATO Finding 1).

Resolution-order pinning matters because the deploy-verification
routine relies on the field reflecting the *current* deploy. A silent
flip to a different env var name (or to a hardcoded value) would
make /api/health a corroborating-only signal again.

Probes C.1 and C.2 exercise ``_read_commit_from_dot_git`` directly
(via the ``start_dir=`` keyword) rather than going through
``TestClient`` + ``monkeypatch.chdir``. Three reasons:

* The function is the unit under test — driving it directly keeps the
  probe focused on what's actually being changed.
* It avoids ``chdir`` race / cleanup risk on Windows.
* It synthesizes both ``.git`` layouts inside ``tmp_path`` without
  having to assume anything about the test runner's cwd.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import routes as routes_module

from tests.verification._shared import build_app


def _reset_commit_cache(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "_COMMIT_SHA_CACHE", None)


def test_health_response_includes_commit_field(monkeypatch):
    """Probe A — the response body has a ``commit`` key with a string value.

    The exact value is not pinned (it's deploy-context-dependent); the
    field's *presence and type* are what callers depend on.
    """
    _reset_commit_cache(monkeypatch)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeefcafebabefacefeed00112233")
    client = TestClient(build_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "commit" in body, f"/api/health must surface a 'commit' field; body={body}"
    assert isinstance(body["commit"], str), (
        f"'commit' must be a string; got {type(body['commit']).__name__}"
    )
    assert body["commit"], "'commit' must be non-empty"


def test_health_commit_prefers_railway_env(monkeypatch):
    """Probe B.1 — RAILWAY_GIT_COMMIT_SHA wins when present.

    Verified against Railway docs (Variables Reference, 2026-05-09):
    Railway injects RAILWAY_GIT_COMMIT_SHA at build/runtime when the
    deploy was triggered from GitHub. Truncated to 7 chars for display.
    """
    _reset_commit_cache(monkeypatch)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc1234567890abcdef")
    monkeypatch.setenv("GIT_COMMIT", "ffffffffffff")
    client = TestClient(build_app())
    resp = client.get("/api/health")
    assert resp.json()["commit"] == "abc1234"


def test_health_commit_falls_back_to_git_commit_env(monkeypatch):
    """Probe B.2 — GIT_COMMIT is the secondary source."""
    _reset_commit_cache(monkeypatch)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("GIT_COMMIT", "1234567abcdef")
    client = TestClient(build_app())
    resp = client.get("/api/health")
    assert resp.json()["commit"] == "1234567"


def test_health_commit_value_is_cached_at_module_level(monkeypatch):
    """Probe B.3 — The SHA is read once and cached; subsequent env
    flips do not move the value within a single process. Pinned because
    re-reading per-request would add a syscall to a hot liveness path
    that is hit every few seconds by Railway's health check.
    """
    _reset_commit_cache(monkeypatch)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "aaaaaaaXXX")
    client = TestClient(build_app())
    first = client.get("/api/health").json()["commit"]
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "bbbbbbbYYY")
    second = client.get("/api/health").json()["commit"]
    assert first == second == "aaaaaaa", (
        f"commit value must be cached; got first={first!r} second={second!r}"
    )


def test_health_commit_is_unknown_when_no_sources_available(monkeypatch, tmp_path):
    """Probe B.4 — When no env source and no .git/HEAD is reachable,
    the field is the literal string ``"unknown"`` rather than empty or
    missing. Callers can branch on the literal sentinel.
    """
    _reset_commit_cache(monkeypatch)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    # Run from a directory with no .git so the local-dev fallback misses.
    monkeypatch.chdir(tmp_path)
    client = TestClient(build_app())
    resp = client.get("/api/health")
    assert resp.json()["commit"] == "unknown"


# ── Filesystem layout probes (CATO Findings 1 & 2) ──────────────────────────
#
# These two probes exercise ``_read_commit_from_dot_git`` directly with a
# synthesized ``.git`` under ``tmp_path``. Probe C.1 covers the regular
# ``.git`` directory layout; Probe C.2 covers the worktree ``.git``-file
# layout that the prior implementation silently failed to handle.


def _synthesize_git_dir(git_dir, branch: str, sha: str) -> None:
    """Populate a ``.git``-shaped directory tree at ``git_dir``.

    Writes a ``HEAD`` containing ``ref: refs/heads/<branch>`` and the
    matching ``refs/heads/<branch>`` file containing ``sha``.
    """
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    ref_path = git_dir / "refs" / "heads" / branch
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(f"{sha}\n", encoding="utf-8")


def test_read_commit_from_dot_git_directory_layout(monkeypatch, tmp_path):
    """Probe C.1 — regular checkout: ``<root>/.git`` is a directory.

    With env vars unset and a synthesized ``.git/`` directory plus
    ``refs/heads/<branch>`` loose ref, the helper returns the short
    SHA. This pins the happy-path that the existing env-var probes
    don't actually exercise — Finding 2.
    """
    _reset_commit_cache(monkeypatch)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    sha_full = "abcdef0123456789abcdef0123456789abcdef01"
    _synthesize_git_dir(tmp_path / ".git", branch="main", sha=sha_full)

    got = routes_module._read_commit_from_dot_git(start_dir=tmp_path)
    assert got == sha_full[:7], f"expected {sha_full[:7]!r}, got {got!r}"

    # Also confirm the public resolver picks it up when run with
    # cwd-equivalent semantics (no start_dir → uses cwd; chdir into
    # tmp_path so the env-fallback path lands here).
    _reset_commit_cache(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert routes_module._resolve_commit_sha() == sha_full[:7]


def test_read_commit_from_dot_git_worktree_layout(monkeypatch, tmp_path):
    """Probe C.2 — linked worktree: ``<root>/.git`` is a *file*.

    Pins the bug CATO empirically reproduced (Finding 1): inside a
    worktree, ``.git`` is a file containing ``gitdir: <path>``, refs
    live in the shared *commondir*, and the prior helper assumed
    ``.git`` was always a directory — so it returned ``None`` from
    every worktree on disk.

    Layout synthesized:

    * ``tmp_path/wt/.git``  (file)  →  ``gitdir: ../linked-gitdir``
    * ``tmp_path/linked-gitdir/HEAD``         → ``ref: refs/heads/feature``
    * ``tmp_path/linked-gitdir/commondir``    → ``../shared``
    * ``tmp_path/shared/refs/heads/feature``  → ``<sha>``
    """
    _reset_commit_cache(monkeypatch)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    sha_full = "fedcba9876543210fedcba9876543210fedcba98"
    branch = "feature"

    wt = tmp_path / "wt"
    linked = tmp_path / "linked-gitdir"
    shared = tmp_path / "shared"

    wt.mkdir()
    linked.mkdir()
    shared.mkdir()

    # ``.git`` file at the worktree root with a *relative* gitdir
    # pointer — the most common shape ``git worktree add`` produces.
    (wt / ".git").write_text(f"gitdir: ../linked-gitdir\n", encoding="utf-8")

    # Linked git dir holds per-worktree HEAD + a commondir back-pointer
    # to the shared dir (also relative — matches real git output).
    (linked / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    (linked / "commondir").write_text("../shared\n", encoding="utf-8")

    # Shared (common) git dir holds the loose ref file.
    ref_path = shared / "refs" / "heads" / branch
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(f"{sha_full}\n", encoding="utf-8")

    got = routes_module._read_commit_from_dot_git(start_dir=wt)
    assert got == sha_full[:7], f"expected {sha_full[:7]!r}, got {got!r}"

    # Public resolver must also surface it when cwd is the worktree.
    _reset_commit_cache(monkeypatch)
    monkeypatch.chdir(wt)
    assert routes_module._resolve_commit_sha() == sha_full[:7]
