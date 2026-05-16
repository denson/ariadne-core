"""Tests for ``POST /api/bw/projects`` — bw project bootstrap (ariadne--9e7).

Covers the new collection-level endpoint that replaces the manual
``mkdir + git init + bw init`` operator sequence with a single
authenticated API call.

Strategy:

  • Slug validation, auth, and 409 (slug-already-exists) are covered
    with the existing ``patch.object(subprocess, "run")`` pattern from
    ``test_api_bw_routes.py`` — no real bw is invoked.
  • The happy path uses a tmp ``BW_REPOS_ROOT`` and patches
    ``subprocess.run`` so we can assert the on-disk dir is created
    AND the git_init + bw_init argv list matches the brief's spec.
  • Rollback is tested by making ``subprocess.run`` return non-zero
    on the bw_init call; the partial slug dir must NOT survive.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.api import bw_routes
from pipeline.api.bw_routes import projects_router, router

from tests.conftest import override_auth


# ── Test infrastructure ─────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    """Build a fresh FastAPI with BOTH bw routers mounted.

    The 9e7 ticket adds a second router (``projects_router``) for the
    collection-level surface (``POST /bw/projects``); the existing
    per-slug ``router`` is included too because one of the happy-path
    assertions hits ``GET /bw/projects/{slug}/tickets`` to confirm
    end-to-end init worked (the new init populated a real .git, so
    the slug-scoped routes are now reachable for that slug).
    """
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    override_auth(app)
    return app


def _fake_completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["bw"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@pytest.fixture
def tmp_bw_root(tmp_path, monkeypatch):
    """Point bw_routes at a writable tmp dir for the duration of one test.

    Also overrides ``BW_BINARY`` so the bw-binary-missing 500 path is
    not hit. Tests that specifically exercise the bw-binary-missing
    branch override ``BW_BINARY`` back to ``None`` themselves.
    """
    monkeypatch.setattr(bw_routes, "BW_BINARY", "/usr/local/bin/bw")
    monkeypatch.setattr(bw_routes, "BW_REPOS_ROOT", str(tmp_path))
    # The initialized-repo guard is for the slug-scoped routes; the
    # collection-level POST creates the .git tree itself, so the guard
    # only matters for the post-init smoke-test GET. We leave it as the
    # production default (True) so the GET correctly fails before init
    # and succeeds after.
    return tmp_path


@pytest.fixture
def client(tmp_bw_root):
    return TestClient(_build_app())


# ── Happy path ──────────────────────────────────────────────────────────────


def test_post_create_project_happy_path(client, tmp_bw_root):
    """A valid slug returns 201 + repo_path; the slug dir + .git exist on
    disk; the subprocess argv matches the documented bw init sequence;
    and the slug becomes reachable via the slug-scoped GET (end-to-end).
    """
    slug = "test-project"
    expected_repo_path = os.path.join(str(tmp_bw_root), slug)

    captured_calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        captured_calls.append(list(argv))
        # Materialize ``.git`` on the first call (git init) so the
        # post-init smoke-test GET below sees an initialized repo and
        # the initialized-repo guard does not 404.
        if argv[:2] == ["git", "init"]:
            os.makedirs(os.path.join(argv[2], ".git"), exist_ok=True)
        return _fake_completed(stdout="ok", returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        resp = client.post(
            "/api/bw/projects",
            json={"slug": slug},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {
        "slug": slug,
        "status": "created",
        "repo_path": expected_repo_path,
    }

    # Slug dir exists on disk.
    assert os.path.isdir(expected_repo_path)

    # Two subprocess calls in this order: git init, then bw init --prefix.
    assert len(captured_calls) == 2
    assert captured_calls[0] == ["git", "init", expected_repo_path]
    assert captured_calls[1] == [
        "/usr/local/bin/bw",
        "-C", expected_repo_path,
        "init", "--prefix", slug,
    ]

    # End-to-end: the slug-scoped GET now resolves the repo (initialized-
    # repo guard does NOT 404). It will then call ``bw list --json`` via
    # subprocess; we mock that one too to assert the round-trip works.
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        resp2 = client.get(f"/api/bw/projects/{slug}/tickets?limit=1")
        assert resp2.status_code == 200, resp2.text


# ── 409 — slug directory already exists ─────────────────────────────────────


def test_post_create_project_existing_slug_returns_409(
    client, tmp_bw_root,
):
    """A POST against a slug whose dir already exists returns 409 and
    does NOT touch the existing contents (no subprocess call).
    """
    slug = "already-here"
    existing_dir = os.path.join(str(tmp_bw_root), slug)
    os.makedirs(existing_dir)
    # Drop a sentinel so we can verify the existing contents survive.
    sentinel = os.path.join(existing_dir, "PRE_EXISTING_FILE")
    with open(sentinel, "w", encoding="utf-8") as f:
        f.write("operator put this here before the API call")

    with patch.object(subprocess, "run") as mock_run:
        resp = client.post(
            "/api/bw/projects",
            json={"slug": slug},
        )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "slug_already_exists"
    assert body["detail"]["slug"] == slug
    # No subprocess work happened.
    mock_run.assert_not_called()
    # Sentinel survives — we did not touch the existing dir.
    assert os.path.exists(sentinel)
    with open(sentinel, encoding="utf-8") as f:
        assert "operator put this here" in f.read()


# ── 422 — invalid slug ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_slug",
    [
        "FOO",            # uppercase
        "foo.bar",        # dots
        "foo/bar",        # slash (would path-traverse)
        "a" * 65,         # over max length
        "foo@bar",        # @
    ],
)
def test_post_create_project_invalid_slug_returns_422(
    client, tmp_bw_root, bad_slug,
):
    """Any slug that fails the regex is rejected at 422 before any
    subprocess call or filesystem mutation.
    """
    with patch.object(subprocess, "run") as mock_run:
        resp = client.post(
            "/api/bw/projects",
            json={"slug": bad_slug},
        )

    assert resp.status_code == 422, (
        f"Bad slug {bad_slug!r} should be 422; got {resp.status_code}: "
        f"{resp.text}"
    )
    # No subprocess work, no on-disk dir.
    mock_run.assert_not_called()
    # Pydantic-level rejections (max_length, etc.) and our
    # ``_validate_slug`` rejections both 422 — assert the structured
    # error appears when we got past pydantic's own length/type check.
    body = resp.json()
    detail = body["detail"]
    # Either our slug allow-list message, or pydantic's field error
    # (both legitimate 422s — the regex catches different inputs than
    # ``max_length`` does).
    assert detail is not None


def test_post_create_project_missing_slug_returns_422(client, tmp_bw_root):
    """Request body without the required ``slug`` field is a 422."""
    with patch.object(subprocess, "run") as mock_run:
        resp = client.post(
            "/api/bw/projects",
            json={},  # no slug
        )

    assert resp.status_code == 422, resp.text
    mock_run.assert_not_called()


def test_post_create_project_empty_body_returns_422(client, tmp_bw_root):
    """Wholly missing body is also 422 (slug is required)."""
    with patch.object(subprocess, "run") as mock_run:
        resp = client.post("/api/bw/projects")

    assert resp.status_code == 422, resp.text
    mock_run.assert_not_called()


# ── 401 — unauthenticated ───────────────────────────────────────────────────


def test_post_create_project_no_auth_returns_401(tmp_bw_root):
    """A POST without a Bearer JWT returns 401.

    Build the app WITHOUT ``override_auth`` so the real ``require_user``
    is in the dependency chain. With no Authorization header it raises
    401 before the handler runs.
    """
    app = FastAPI()
    app.include_router(projects_router, prefix="/api")
    # NB: deliberately not calling override_auth(app).
    no_auth_client = TestClient(app)

    with patch.object(subprocess, "run") as mock_run:
        resp = no_auth_client.post(
            "/api/bw/projects",
            json={"slug": "any-slug"},
        )

    assert resp.status_code == 401, resp.text
    mock_run.assert_not_called()


# ── Rollback — bw init subprocess fails ─────────────────────────────────────


def test_post_create_project_bw_init_failure_rolls_back(
    client, tmp_bw_root,
):
    """If ``bw init`` exits non-zero, the partial slug dir is removed
    and the response is 500 ``init_failed`` with step=bw_init.
    """
    slug = "rollback-me"
    expected_repo_path = os.path.join(str(tmp_bw_root), slug)

    def fake_run(argv, **kwargs):
        # git init succeeds (creates a real .git so rollback is observable);
        # bw init fails.
        if argv[:2] == ["git", "init"]:
            os.makedirs(os.path.join(argv[2], ".git"), exist_ok=True)
            return _fake_completed(stdout="ok", returncode=0)
        # bw init path
        return _fake_completed(
            stderr="fatal: not a git repository (bw init complained)",
            returncode=128,
        )

    with patch.object(subprocess, "run", side_effect=fake_run):
        resp = client.post(
            "/api/bw/projects",
            json={"slug": slug},
        )

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "init_failed"
    assert body["detail"]["step"] == "bw_init"
    assert body["detail"]["slug"] == slug
    assert body["detail"]["exit_code"] == 128
    assert "bw init complained" in body["detail"]["stderr"]
    # Rollback: the slug dir is gone.
    assert not os.path.exists(expected_repo_path), (
        f"Rollback failed — slug dir {expected_repo_path!r} survived "
        f"a failed bw init."
    )


def test_post_create_project_git_init_failure_rolls_back(
    client, tmp_bw_root,
):
    """If ``git init`` exits non-zero, the slug dir is removed and the
    response is 500 ``init_failed`` with step=git_init. ``bw init`` is
    never invoked (we never reach step 3).
    """
    slug = "git-init-fails"
    expected_repo_path = os.path.join(str(tmp_bw_root), slug)

    captured_calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        captured_calls.append(list(argv))
        # git init fails. bw init should never be called.
        return _fake_completed(
            stderr="git: command not found-ish",
            returncode=127,
        )

    with patch.object(subprocess, "run", side_effect=fake_run):
        resp = client.post(
            "/api/bw/projects",
            json={"slug": slug},
        )

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "init_failed"
    assert body["detail"]["step"] == "git_init"
    assert body["detail"]["exit_code"] == 127
    # Only one subprocess call attempted (git init); bw init never ran.
    assert len(captured_calls) == 1
    assert captured_calls[0][:2] == ["git", "init"]
    # Rollback.
    assert not os.path.exists(expected_repo_path)


# ── Reserved-for-future ``options`` field ─────────────────────────────────


def test_post_create_project_options_field_accepted_and_ignored(
    client, tmp_bw_root,
):
    """The ``options`` field is accepted (shape stability for v2) but
    has no observable side-effect in v1.
    """
    slug = "with-options"

    def fake_run(argv, **kwargs):
        if argv[:2] == ["git", "init"]:
            os.makedirs(os.path.join(argv[2], ".git"), exist_ok=True)
        return _fake_completed(stdout="ok", returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        resp = client.post(
            "/api/bw/projects",
            json={
                "slug": slug,
                "options": {
                    "backup_remote": "https://example.com/repo.git",
                    "future_knob": True,
                },
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == slug
    # Response shape is the same — options is not echoed back.
    assert set(body.keys()) == {"slug", "status", "repo_path"}


# ── Per-slug lock acquisition ───────────────────────────────────────────────


def test_post_create_project_acquires_per_slug_lock(client, tmp_bw_root):
    """The handler must hold the per-slug ``_lock_for(slug)`` lock for
    the duration of init. We can't easily probe contention from a
    sync TestClient, but we CAN confirm the lock dict gains the slug
    after the call — the lock object survives in
    ``bw_routes._slug_locks``.
    """
    slug = "lockcheck"

    def fake_run(argv, **kwargs):
        if argv[:2] == ["git", "init"]:
            os.makedirs(os.path.join(argv[2], ".git"), exist_ok=True)
        return _fake_completed(stdout="ok", returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        resp = client.post("/api/bw/projects", json={"slug": slug})
    assert resp.status_code == 201, resp.text
    # The lock for this slug was created during the call.
    assert slug in bw_routes._slug_locks
