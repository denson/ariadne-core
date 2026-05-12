"""Tests for the bw HTTP surface (``/api/bw/projects/{slug}/...``).

ariadne--8fd.2 / Phase 2.

All tests mock ``subprocess.run`` so no real bw binary is invoked and
no real beadwork repo is touched on disk. The seam being tested is
the URL/method → bw argv translation plus the slug validation, lock
acquisition, and response shape.

Why mock at ``subprocess.run`` rather than at ``_run_bw``:
mocking ``subprocess.run`` exercises the full ``_run_bw`` body —
including the bw-binary check, the ``--json`` parse, the exit-code
mapping, and the timeout path. Mocking ``_run_bw`` directly would
skip all four. The tests here that drive specific failure paths
(missing binary, timeout, JSON parse fail, exit-code != 0) need
the real ``_run_bw`` in the call chain to surface those branches.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.api import bw_routes
from pipeline.api.bw_routes import router

from tests.conftest import override_auth


# ── Test infrastructure ─────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    app = FastAPI()
    # Mount under /api to match production. bw_router already carries
    # its own /bw/projects/{slug} prefix, so the full mount is
    # /api/bw/projects/{slug}/... — same as app.py wires it.
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


def _fake_completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    """Build a CompletedProcess with stdout/stderr/returncode set."""
    return subprocess.CompletedProcess(
        args=["bw"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@pytest.fixture
def app_with_bw_binary(monkeypatch):
    """App fixture that pretends bw is installed.

    bw_routes.BW_BINARY is resolved at module-import time via
    shutil.which. On CI hosts without bw on PATH the module imports
    successfully with BW_BINARY=None, but every endpoint would 500
    on the "bw_binary_missing" check. Override here so the happy-path
    tests proceed to the subprocess.run mock.
    """
    monkeypatch.setattr(bw_routes, "BW_BINARY", "/usr/local/bin/bw")
    monkeypatch.setattr(bw_routes, "BW_REPOS_ROOT", "/tmp/test-bw-repos")
    app = _build_app()
    return app


@pytest.fixture
def client(app_with_bw_binary):
    return TestClient(app_with_bw_binary)


# ── Slug validation (security-critical: path-traversal surface) ─────────────


@pytest.mark.parametrize(
    "bad_slug",
    [
        # Slugs that survive URL normalization as a single path segment
        # and must hit our regex validator → 422.
        "foo;rm",
        "$PATH",
        "FOO",            # uppercase
        "a" * 65,         # over max length
        ".hidden",        # leading dot
        "foo.bar",        # dots not in allow-list
        "foo@bar",
    ],
)
def test_invalid_slug_rejected_422(client, bad_slug):
    """Bad slugs that survive URL normalization must 422 before any
    subprocess call happens.

    Note: slugs containing ``/`` or ``\\`` (e.g. ``foo/../bar``) get
    URL-normalized by the client and/or rewritten by FastAPI's router
    before reaching our validator — those are handled by routing
    (404 / unmatched route), not by the regex. We test the inputs
    that DO reach the validator. Path-traversal via ``..`` in the
    slug is structurally impossible because the slug must match
    ``^[a-z0-9_-]{1,64}$`` which excludes ``.`` and ``/``.
    """
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get(f"/api/bw/projects/{bad_slug}/tickets")
        assert response.status_code == 422, (
            f"Bad slug {bad_slug!r} should be rejected with 422; got "
            f"{response.status_code}: {response.text}"
        )
        mock_run.assert_not_called()


@pytest.mark.parametrize(
    "bad_slug_with_slash",
    [
        # Bare ``..`` — httpx routes it as no-slug; routing 404s before
        # the slug regex runs.
        "..",
        # Percent-encoded slash + ``..``. ``%2F`` decodes to ``/`` and
        # the resulting URL no longer matches the route pattern
        # ``/api/bw/projects/{slug}/...`` as a single segment, so
        # Starlette routing returns 404 before the slug regex runs.
        # The slug regex is defence-in-depth for this input, not the
        # load-bearing protection.
        "foo%2F..%2Fbar",
        # Percent-encoded ``..`` (``%2E%2E``). No slash, so routing
        # accepts the slug as a single segment and the slug regex
        # rejects with 422 — the regex is the load-bearing protection
        # here.
        "%2E%2E",
        # Mixed-encoding ``..`` (``.%2E``). Same surface as ``%2E%2E``
        # — no slash, regex rejects with 422.
        ".%2E",
    ],
)
def test_path_traversal_slug_rejected(client, bad_slug_with_slash):
    """Slugs that try to smuggle a path separator or ``..`` past the
    URL normalizer must never reach ``subprocess.run`` — either
    Starlette routing rejects them (404, unmatched route) or the slug
    regex rejects them (422).

    Two distinct protection layers, two distinct failure modes:

    - **Slash-bearing inputs** (``foo%2F..%2Fbar``, bare ``..``): after
      ``%2F`` decode, the URL contains a ``/`` that the route pattern
      doesn't allow inside a single ``{slug}`` segment. Starlette's
      router fails to match and returns **404** — the slug regex never
      runs. Routing is the protection; the regex is defence-in-depth.
    - **Non-slash traversal patterns** (``%2E%2E``, ``.%2E``): these
      decode to ``..`` *within* a single path segment, so Starlette
      routes them successfully and they reach the slug-validator
      handler. The slug regex then rejects with **422**. The regex is
      the load-bearing protection here.

    Note: HTTP-spec URL normalization collapses literal segments like
    ``foo/../bar`` to ``bar`` *before* routing, so those inputs hit
    the route with a clean ``bar`` slug (covered separately in
    ``test_url_normalization_collapses_traversal_to_valid_slug``).
    That is not a path traversal — it is the URL normalizer producing
    a different (legitimate) request.

    The assertion accepts either 404 or 422 because the two layers
    catch different inputs.
    """
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get(f"/api/bw/projects/{bad_slug_with_slash}/tickets")
        assert response.status_code in (404, 422), (
            f"Path-traversal slug {bad_slug_with_slash!r} returned "
            f"{response.status_code} (expected 404 or 422): {response.text}"
        )
        mock_run.assert_not_called()


def test_url_normalization_collapses_traversal_to_valid_slug(client):
    """HTTP-spec URL normalization collapses ``foo/../bar`` to ``bar``
    *before* the request reaches the route, so the route sees a clean
    ``bar`` slug — not ``foo/../bar``. The resulting subprocess call
    uses the legitimate ``bar`` repo path with no ``..`` component.

    This is a property test for the normalizer, not a security
    failure — it pins that the on-the-wire URL transform behaves as
    expected so a regression in the test harness (or in starlette /
    httpx) gets caught here rather than in a security review.
    """
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get("/api/bw/projects/foo/../bar/tickets")
    # URL normalization collapses to /api/bw/projects/bar/tickets.
    assert response.status_code == 200
    argv = list(mock_run.call_args[0][0])
    repo_arg = argv[argv.index("-C") + 1]
    # Must NOT contain a `..` segment in the resolved repo path.
    assert ".." not in repo_arg, (
        f"Resolved repo path contains '..': {repo_arg!r}"
    )
    # The normalized slug should be exactly `bar` (last segment after collapse).
    expected_repo = os.path.join("/tmp/test-bw-repos", "bar")
    assert repo_arg == expected_repo, (
        f"Expected normalized slug 'bar' resolving to {expected_repo!r}, "
        f"got {repo_arg!r}"
    )


def test_valid_slug_accepted(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}', returncode=0)
        response = client.get("/api/bw/projects/ariadne-core/tickets")
        assert response.status_code == 200
        mock_run.assert_called_once()


# ── Argv shape — one assertion per endpoint ─────────────────────────────────


def _argv_from_call(mock_run) -> list[str]:
    """Extract the argv from the mocked subprocess.run call."""
    args, _kwargs = mock_run.call_args
    return list(args[0])


def test_create_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(
            stdout='{"id": "bw-a3f8", "title": "Test"}',
        )
        response = client.post(
            "/api/bw/projects/myproj/tickets",
            json={
                "title": "Fix login bug",
                "priority": 1,
                "type": "bug",
                "description": "Login button is broken",
            },
        )
        assert response.status_code == 201
        assert response.json() == {"id": "bw-a3f8", "title": "Test"}

    argv = _argv_from_call(mock_run)
    assert argv[0] == "/usr/local/bin/bw"
    # Use os.path.join so the test passes on both Linux and Windows
    # (os.path.join inside bw_routes uses the platform separator).
    expected_repo = os.path.join("/tmp/test-bw-repos", "myproj")
    assert argv[1:5] == ["-C", expected_repo, "create", "Fix login bug"]
    assert "--json" in argv
    assert "--priority" in argv and argv[argv.index("--priority") + 1] == "1"
    assert "--type" in argv and argv[argv.index("--type") + 1] == "bug"
    assert "--description" in argv


def test_list_tickets_argv_no_filters(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get("/api/bw/projects/myproj/tickets")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["list", "--json"]


def test_list_tickets_argv_with_filters(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="[]")
        # Empty stdout list wraps to {"items": [...]}, but here we
        # return "[]" so the wrapper sees the array and rewrites it.
        response = client.get(
            "/api/bw/projects/myproj/tickets"
            "?status=open&assignee=alice&priority=1"
            "&type=bug&label=urgent&grep=login&limit=5&all=true&deferred=true"
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert "list" in argv
    assert "--json" in argv
    assert "--status" in argv and argv[argv.index("--status") + 1] == "open"
    assert "--assignee" in argv and argv[argv.index("--assignee") + 1] == "alice"
    assert "--priority" in argv and argv[argv.index("--priority") + 1] == "1"
    assert "--type" in argv and argv[argv.index("--type") + 1] == "bug"
    assert "--label" in argv and argv[argv.index("--label") + 1] == "urgent"
    assert "--grep" in argv and argv[argv.index("--grep") + 1] == "login"
    assert "--limit" in argv and argv[argv.index("--limit") + 1] == "5"
    assert "--all" in argv
    assert "--deferred" in argv


def test_show_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.get(
            "/api/bw/projects/myproj/tickets/bw-a3f8?only=summary,comments"
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["show", "bw-a3f8", "--json", "--only", "summary,comments"]


def test_update_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.patch(
            "/api/bw/projects/myproj/tickets/bw-a3f8",
            json={"priority": 2, "assignee": "bob", "status": "in_progress"},
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert "update" in argv and "bw-a3f8" in argv
    assert "--priority" in argv and argv[argv.index("--priority") + 1] == "2"
    assert "--assignee" in argv and argv[argv.index("--assignee") + 1] == "bob"
    assert "--status" in argv and argv[argv.index("--status") + 1] == "in_progress"


def test_update_ticket_empty_body_400(client):
    """PATCH with no fields = 400 (no_fields_to_update)."""
    with patch.object(subprocess, "run") as mock_run:
        response = client.patch(
            "/api/bw/projects/myproj/tickets/bw-a3f8",
            json={},
        )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "no_fields_to_update"
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    "endpoint, method, payload",
    [
        # TicketCreate.title and .description
        (
            "/api/bw/projects/myproj/tickets",
            "POST",
            {"title": "bad\x00title"},
        ),
        (
            "/api/bw/projects/myproj/tickets",
            "POST",
            {"title": "ok", "description": "bad\x00desc"},
        ),
        # TicketCreate identifier fields (type, parent) — these reach
        # subprocess.run argv as ``--type`` / ``--parent`` and raise
        # ValueError on NUL exactly like the user-text fields.
        (
            "/api/bw/projects/myproj/tickets",
            "POST",
            {"title": "ok", "type": "bug\x00type"},
        ),
        (
            "/api/bw/projects/myproj/tickets",
            "POST",
            {"title": "ok", "parent": "bw-a3f8\x00x"},
        ),
        # TicketUpdate.title and .description
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8",
            "PATCH",
            {"title": "bad\x00title"},
        ),
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8",
            "PATCH",
            {"description": "bad\x00desc"},
        ),
        # TicketUpdate identifier fields (assignee, type, status)
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8",
            "PATCH",
            {"assignee": "alice\x00bob"},
        ),
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8",
            "PATCH",
            {"status": "open\x00closed"},
        ),
        # TicketStart.assignee
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/start",
            "POST",
            {"assignee": "alice\x00bob"},
        ),
        # CommentCreate.text
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/comments",
            "POST",
            {"text": "bad\x00text"},
        ),
        # CommentCreate.author
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/comments",
            "POST",
            {"text": "ok", "author": "alice\x00bob"},
        ),
        # TicketClose.reason
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/close",
            "POST",
            {"reason": "bad\x00reason"},
        ),
        # DeferRequest.when
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/defer",
            "POST",
            {"when": "bad\x00when"},
        ),
        # LabelAdd.label
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/labels",
            "POST",
            {"label": "urgent\x00x"},
        ),
        # DepAdd.blocks
        (
            "/api/bw/projects/myproj/tickets/bw-a3f8/deps",
            "POST",
            {"blocks": "bw-b1c2\x00x"},
        ),
    ],
)
def test_null_byte_in_user_text_rejected_422(client, endpoint, method, payload):
    """Null bytes in any argv-bound string field must be rejected at the
    request boundary with a clean 422, not cascade to ``subprocess.run``
    and surface as a 500. ``subprocess.run`` raises ``ValueError`` when
    an argv element contains ``\\x00``; the global exception handler
    then masks the real reason. Pydantic validators turn the same bad
    input into a field-level 422 with a helpful detail.

    Coverage is over every user-controllable string field on every
    request model that reaches ``subprocess.run`` argv — not just the
    free-form text fields (title/description/text/reason/when) but the
    identifier fields too (type, parent, assignee, status, author,
    label, blocks). The boundary protection is uniform.
    """
    with patch.object(subprocess, "run") as mock_run:
        response = client.request(method, endpoint, json=payload)
    assert response.status_code == 422, (
        f"{method} {endpoint} with null-byte payload {payload!r} returned "
        f"{response.status_code}: {response.text}"
    )
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    "method, endpoint",
    [
        # ticket_id path param — read endpoint exercises the constraint
        # most cheaply.
        ("GET", "/api/bw/projects/myproj/tickets/x%00y"),
        # label path param on DELETE labels.
        ("DELETE", "/api/bw/projects/myproj/tickets/bw-a3f8/labels/urgent%00x"),
        # target path param on DELETE deps.
        ("DELETE", "/api/bw/projects/myproj/tickets/bw-a3f8/deps/bw-b1c2%00x"),
    ],
)
def test_null_byte_in_path_param_rejected_422(client, method, endpoint):
    """Percent-encoded ``%00`` in a path-param survives Starlette
    routing (it is decoded *after* the route matches), so without an
    explicit ``Path(pattern=...)`` constraint the decoded ``\\x00`` would
    reach the handler and propagate into ``subprocess.run`` argv —
    which raises ``ValueError`` and surfaces as a 500.

    A literal ``\\x00`` byte in the URL is rejected earlier by the HTTP
    client (httpx ``InvalidURL``), so we only test the
    percent-encoded form here. That is the form an attacker controls.

    The ``slug`` path param is already protected by its own stricter
    allow-list regex (``^[a-z0-9_-]{1,64}$``) and has its own tests
    above; this test covers the remaining str path params.
    """
    with patch.object(subprocess, "run") as mock_run:
        response = client.request(method, endpoint)
    assert response.status_code == 422, (
        f"{method} {endpoint} with NUL in path param returned "
        f"{response.status_code}: {response.text}"
    )
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    "method, endpoint",
    [
        # list_tickets query params (six Optional[str] fields).
        ("GET", "/api/bw/projects/myproj/tickets?status=open%00closed"),
        ("GET", "/api/bw/projects/myproj/tickets?assignee=alice%00bob"),
        ("GET", "/api/bw/projects/myproj/tickets?type=task%00bug"),
        ("GET", "/api/bw/projects/myproj/tickets?label=p1%00p2"),
        ("GET", "/api/bw/projects/myproj/tickets?grep=foo%00bar"),
        ("GET", "/api/bw/projects/myproj/tickets?parent=bw-a3f8%00x"),
        # show_ticket ?only=
        ("GET", "/api/bw/projects/myproj/tickets/bw-a3f8?only=summary%00body"),
        # export_jsonl ?status=
        ("GET", "/api/bw/projects/myproj/export?status=open%00closed"),
    ],
)
def test_null_byte_in_query_param_rejected_422(client, method, endpoint):
    """Same defect class as ``test_null_byte_in_path_param_rejected_422``:
    percent-encoded ``%00`` in an ``Optional[str]`` query param decodes
    to ``\\x00`` after parsing and propagates into ``subprocess.run`` argv
    without an explicit ``Query(pattern=...)`` constraint, surfacing as
    a 500 ValueError.

    Coverage matches the eight unguarded query params on ``list_tickets``,
    ``show_ticket``, and ``export_jsonl``. Integer/bool query params
    (priority, limit, show_all, deferred, overdue) cannot carry NULs.
    """
    with patch.object(subprocess, "run") as mock_run:
        response = client.request(method, endpoint)
    assert response.status_code == 422, (
        f"{method} {endpoint} with NUL in query param returned "
        f"{response.status_code}: {response.text}"
    )
    mock_run.assert_not_called()


def test_delete_ticket_preview_argv(client):
    """DELETE without ?force=true is a preview (no --force flag)."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"preview": true}')
        response = client.delete("/api/bw/projects/myproj/tickets/bw-a3f8")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert "delete" in argv and "bw-a3f8" in argv
    assert "--json" in argv
    assert "--force" not in argv


def test_delete_ticket_force_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"deleted": true}')
        response = client.delete(
            "/api/bw/projects/myproj/tickets/bw-a3f8?force=true"
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert "--force" in argv


def test_start_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-a3f8/start",
            json={"assignee": "alice"},
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["start", "bw-a3f8", "--json", "--assignee", "alice"]


def test_start_ticket_no_assignee_argv(client):
    """No body / empty body → bw uses git user.name default."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post("/api/bw/projects/myproj/tickets/bw-a3f8/start")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["start", "bw-a3f8", "--json"]


def test_close_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-a3f8/close",
            json={"reason": "duplicate"},
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert "close" in argv
    assert "--reason" in argv and argv[argv.index("--reason") + 1] == "duplicate"


def test_reopen_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post("/api/bw/projects/myproj/tickets/bw-a3f8/reopen")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["reopen", "bw-a3f8", "--json"]


def test_add_comment_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "c1"}')
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-a3f8/comments",
            json={"text": "Fixed in latest deploy", "author": "alice"},
        )
        assert response.status_code == 201

    argv = _argv_from_call(mock_run)
    assert argv[3:7] == ["comment", "bw-a3f8", "Fixed in latest deploy", "--json"]
    assert "--author" in argv and argv[argv.index("--author") + 1] == "alice"


def test_add_label_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"labels": ["urgent"]}')
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-a3f8/labels",
            json={"label": "urgent"},
        )
        assert response.status_code == 201

    argv = _argv_from_call(mock_run)
    # The label is composed with a leading + server-side.
    assert argv[3:] == ["label", "bw-a3f8", "+urgent", "--json"]


def test_add_label_rejects_caller_prefix(client):
    """Caller cannot bypass server-composed prefix by sending +foo or -foo."""
    with patch.object(subprocess, "run") as mock_run:
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-a3f8/labels",
            json={"label": "+urgent"},
        )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_label"
    mock_run.assert_not_called()


def test_remove_label_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"labels": []}')
        response = client.delete(
            "/api/bw/projects/myproj/tickets/bw-a3f8/labels/urgent"
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["label", "bw-a3f8", "-urgent", "--json"]


def test_defer_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-a3f8/defer",
            json={"when": "tomorrow at 2pm"},
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["defer", "bw-a3f8", "tomorrow at 2pm", "--json"]


def test_undefer_ticket_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post("/api/bw/projects/myproj/tickets/bw-a3f8/undefer")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["undefer", "bw-a3f8", "--json"]


def test_add_dep_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"ok": true}')
        response = client.post(
            "/api/bw/projects/myproj/tickets/bw-1234/deps",
            json={"blocks": "bw-5678"},
        )
        assert response.status_code == 201

    argv = _argv_from_call(mock_run)
    # bw dep add <id> blocks <target> --json
    assert argv[3:] == ["dep", "add", "bw-1234", "blocks", "bw-5678", "--json"]


def test_remove_dep_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"ok": true}')
        response = client.delete(
            "/api/bw/projects/myproj/tickets/bw-1234/deps/bw-5678"
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["dep", "remove", "bw-1234", "blocks", "bw-5678", "--json"]


def test_history_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get(
            "/api/bw/projects/myproj/tickets/bw-a3f8/history?limit=5"
        )
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["history", "bw-a3f8", "--json", "--limit", "5"]


# ── Repo-level endpoints ────────────────────────────────────────────────────


def test_ready_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get("/api/bw/projects/myproj/ready")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["ready", "--json"]


def test_blocked_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"items": []}')
        response = client.get("/api/bw/projects/myproj/blocked")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["blocked", "--json"]


def test_sync_argv_no_json(client):
    """sync has no --json flag; output returned verbatim."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="Synced. 3 changes pushed.\n")
        response = client.post("/api/bw/projects/myproj/sync")
        assert response.status_code == 200
        body = response.json()
        assert body["output"] == "Synced. 3 changes pushed.\n"

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["sync"]
    assert "--json" not in argv


def test_onboard_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="instructions...")
        response = client.get("/api/bw/projects/myproj/onboard")
        assert response.status_code == 200
        assert response.json()["output"] == "instructions..."

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["onboard"]


def test_prime_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="workflow context...")
        response = client.get("/api/bw/projects/myproj/prime")
        assert response.status_code == 200

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["prime"]


def test_export_argv(client):
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id":"x"}\n{"id":"y"}\n')
        response = client.get("/api/bw/projects/myproj/export?status=open")
        assert response.status_code == 200
        body = response.json()
        # No --json on export — output returned verbatim under "output".
        assert "id" in body["output"]

    argv = _argv_from_call(mock_run)
    assert argv[3:] == ["export", "--status", "open"]


# ── bw exit-code mapping ────────────────────────────────────────────────────


def test_bw_exit_nonzero_returns_400(client):
    """bw exits non-zero (bad id, invalid date, etc.) → HTTP 400."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(
            stdout="",
            stderr="error: issue bw-bogus not found",
            returncode=1,
        )
        response = client.get("/api/bw/projects/myproj/tickets/bw-bogus")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "bw_exit_nonzero"
    assert detail["exit_code"] == 1
    assert "bw-bogus not found" in detail["stderr"]


def test_bw_binary_missing_returns_500(monkeypatch):
    """If BW_BINARY is None at request time, every endpoint should 500."""
    # Build a separate app where BW_BINARY is None.
    monkeypatch.setattr(bw_routes, "BW_BINARY", None)
    monkeypatch.setattr(bw_routes, "BW_REPOS_ROOT", "/tmp/test-bw-repos")
    app = _build_app()
    c = TestClient(app)
    response = c.get("/api/bw/projects/myproj/tickets")
    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "bw_binary_missing"


def test_bw_timeout_returns_500(client):
    """A subprocess timeout surfaces as HTTP 500, not 200."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["bw"], timeout=30.0)
        response = client.get("/api/bw/projects/myproj/tickets")
    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "bw_timeout"


def test_bw_json_parse_failure_returns_500(client):
    """If --json subcommand returns non-JSON stdout, surface as 500."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="not json {{{")
        response = client.get("/api/bw/projects/myproj/tickets/bw-a3f8")
    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "bw_json_parse"


def test_bw_empty_stdout_returns_empty_dict(client):
    """An empty --json stdout (legitimate for some bw versions) → {} not 500."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="")
        response = client.get("/api/bw/projects/myproj/tickets/bw-a3f8")
    assert response.status_code == 200
    assert response.json() == {}


# ── Auth (existing override removed for this test) ──────────────────────────


@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", "/api/bw/projects/myproj/tickets"),
        ("GET", "/api/bw/projects/myproj/tickets"),
        ("DELETE", "/api/bw/projects/myproj/tickets/bw-a3f8"),
        ("PATCH", "/api/bw/projects/myproj/tickets/bw-a3f8"),
        ("POST", "/api/bw/projects/myproj/sync"),
        ("GET", "/api/bw/projects/myproj/ready"),
    ],
)
def test_missing_jwt_returns_401(monkeypatch, method, path):
    """No Authorization header → 401 on every endpoint. Parametrized
    across a representative sample of all 22 routes so a future
    regression that copies a route and forgets ``Depends(require_user)``
    is caught here — not in a security review or production. The 1-of-22
    smoke-test pattern would silently let a missing-auth endpoint ship.
    """
    monkeypatch.setattr(bw_routes, "BW_BINARY", "/usr/local/bin/bw")
    monkeypatch.setattr(bw_routes, "BW_REPOS_ROOT", "/tmp/test-bw-repos")
    # Set the env vars require_user reads so it doesn't short-circuit
    # with a config error (we want the "no token" branch).
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://test/api")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    # NOTE: deliberately NOT calling override_auth here.
    c = TestClient(app)
    response = c.request(method, path, json={} if method in {"POST", "PATCH"} else None)
    assert response.status_code == 401, (
        f"{method} {path} did not require auth: got {response.status_code} "
        f"{response.text}"
    )


# ── Per-slug lock — same-slug writes serialize ──────────────────────────────


def test_same_slug_writes_serialize(app_with_bw_binary):
    """Two concurrent writes against the same slug must serialize.

    Uses an asyncio.Event to assert that the second writer can only
    proceed after the first releases the lock. If the lock weren't
    held, the second writer would finish before the first ever
    released its inner barrier — the test would deadlock under that
    failure mode (we add a timeout to bail out cleanly).
    """
    import asyncio
    import threading

    # We can't trivially test asyncio.Lock semantics through the sync
    # TestClient. Drive the locked code path directly instead.
    slug = "concurrency_test"

    started = asyncio.Event()
    inside_first = asyncio.Event()
    release_first = asyncio.Event()
    second_finished = asyncio.Event()
    order: list[str] = []

    async def first_writer():
        lock = await bw_routes._lock_for(slug)
        async with lock:
            order.append("first_enter")
            inside_first.set()
            await release_first.wait()
            order.append("first_exit")

    async def second_writer():
        # Wait until first_writer has the lock.
        await inside_first.wait()
        lock = await bw_routes._lock_for(slug)
        async with lock:
            order.append("second_enter")
            order.append("second_exit")
            second_finished.set()

    async def driver():
        # Start both, then poke the events to release.
        t1 = asyncio.create_task(first_writer())
        t2 = asyncio.create_task(second_writer())
        # Give the scheduler a tick to let first_writer enter the lock.
        await asyncio.sleep(0)
        await inside_first.wait()
        # second_writer is now blocked waiting on the lock.
        # Release first; second should immediately follow.
        release_first.set()
        await asyncio.wait_for(second_finished.wait(), timeout=2.0)
        await asyncio.gather(t1, t2)

    asyncio.run(driver())

    # The lock works iff first fully exited before second entered.
    assert order == ["first_enter", "first_exit", "second_enter", "second_exit"], (
        f"Lock did not serialize same-slug writers; got order={order}"
    )


def test_different_slugs_do_not_block(app_with_bw_binary):
    """Two writers against different slugs must NOT serialize."""
    import asyncio

    inside_a = asyncio.Event()
    release_a = asyncio.Event()
    b_finished = asyncio.Event()
    order: list[str] = []

    async def writer_a():
        lock = await bw_routes._lock_for("slug_a")
        async with lock:
            order.append("a_enter")
            inside_a.set()
            await release_a.wait()
            order.append("a_exit")

    async def writer_b():
        await inside_a.wait()
        lock = await bw_routes._lock_for("slug_b")
        async with lock:
            order.append("b_enter")
            order.append("b_exit")
            b_finished.set()

    async def driver():
        t_a = asyncio.create_task(writer_a())
        t_b = asyncio.create_task(writer_b())
        await asyncio.sleep(0)
        # writer_b should finish even though A still holds A's lock,
        # because they're keyed on different slugs.
        await asyncio.wait_for(b_finished.wait(), timeout=2.0)
        # Now release A so the test can clean up.
        release_a.set()
        await asyncio.gather(t_a, t_b)

    asyncio.run(driver())

    # b_enter must happen while a is still holding its lock.
    assert order.index("b_enter") < order.index("a_exit"), (
        f"Different-slug writers should not block each other; got order={order}"
    )


# ── Backup hook stub increments the counter ─────────────────────────────────


def test_write_invokes_backup_stub(client, monkeypatch):
    # Reset the counter for a clean assertion.
    monkeypatch.setattr(bw_routes, "_backup_skip_count", {})
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "Test"},
        )
        assert response.status_code == 201
    # The backup stub bumps the per-slug counter once per write.
    assert bw_routes._backup_skip_count.get("myproj") == 1


def test_read_does_not_invoke_backup_stub(client, monkeypatch):
    monkeypatch.setattr(bw_routes, "_backup_skip_count", {})
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(stdout='{"id": "bw-a3f8"}')
        response = client.get("/api/bw/projects/myproj/tickets/bw-a3f8")
        assert response.status_code == 200
    # Reads must NOT trigger the backup hook.
    assert bw_routes._backup_skip_count.get("myproj") is None


def test_backup_skipped_on_bw_failure(client, monkeypatch):
    """If the bw write itself fails (exit ≠ 0), backup MUST NOT be
    called. The invariant is: backup is a post-write durability layer
    — pushing a failed write would push nothing useful, and could
    mask a real error by pretending state was preserved.

    The current implementation gets this for free because
    ``_backup_push`` is only called inside the ``async with lock``
    block *after* ``await _run_bw(...)`` returns; a non-zero exit
    code raises ``HTTPException(400)`` and the function exits before
    ``_backup_push`` runs. This test pins the invariant so a future
    refactor (e.g. wrapping backup in a try/except) cannot silently
    invert the order.
    """
    monkeypatch.setattr(bw_routes, "_backup_skip_count", {})
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(
            stdout="",
            stderr="error: title required",
            returncode=1,
        )
        response = client.post(
            "/api/bw/projects/myproj/tickets",
            json={"title": "Test"},
        )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "bw_exit_nonzero"
    # The bw write failed; backup must NOT have been called.
    assert bw_routes._backup_skip_count.get("myproj") is None


# ── List wrapping (bw --json returning bare array) ──────────────────────────


def test_list_output_array_is_wrapped(client):
    """bw --json that returns a JSON array gets wrapped as {"items": [...]}."""
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = _fake_completed(
            stdout=json.dumps([
                {"id": "bw-a3f8", "title": "T1"},
                {"id": "bw-b1c2", "title": "T2"},
            ]),
        )
        response = client.get("/api/bw/projects/myproj/tickets")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == "bw-a3f8"
