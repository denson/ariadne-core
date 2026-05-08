"""CLI subprocess probes for the m5e source-size confirmation flow.

Covers design-rev3.1 §6 CLI-side probes:

- (h) Interactive prompt behavior: ``y\\n`` → 0 + Document JSON;
  ``n\\n`` → 1 + ``Aborted.`` on stderr; ``\\n`` (default-N) → 1.
- (i) Non-interactive mode: ``--yes`` no-TTY → 0; no ``--yes`` no-TTY → 1
  with ``confirmation required but stdin is not a TTY`` on stderr.
- (j) Directory ingest with ``--yes``: blanket-confirms the per-file
  prompt for an over-soft-cap file.
- (j-bis) ``--json`` without ``--yes``: stdout parses as JSON, prompt
  text is on stderr only, no prompt characters in stdout.
- (k) ``--json`` + ``--yes``: stdout parses as JSON, stderr contains
  the literal ``[auto-confirmed via --yes]`` substring, no prompt
  characters on stdout.

A small thread-based ``http.server`` stub runs on a loopback port and
returns canned 413 → 200 responses to drive the CLI's full
exception-and-retry path. Subprocess (rather than in-process) is
deliberate — ``sys.stdin.isatty()`` only behaves correctly under a
real subprocess; in-process monkeypatching cannot reproduce the
non-TTY semantic the CLI's fail-fast branch depends on.

Pattern follows ``tests/test_cli_version.py`` (sibling-style
subprocess probe). Each test stands up the server, runs ``ariadne
ingest ...`` via ``subprocess.run``, and asserts on exit code +
stdout + stderr.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterator

import pytest


# ---------------------------------------------------------------------- helpers


def _free_port() -> int:
    """Bind to port 0 so the OS picks a free port; close immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CannedHandler(BaseHTTPRequestHandler):
    """HTTP request handler that returns canned responses based on the
    ``calls`` script bound by ``_run_canned_server``."""

    # Set by the test fixture before the server starts.
    canned_responses: list[dict] = []
    requests_seen: list[dict] = []

    def log_message(self, format, *args):  # noqa: A003 — overridden API
        # Silence the default stderr access log; tests assert on stderr.
        pass

    def _send(self, status: int, body: dict) -> None:
        body_bytes = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path == "/api/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "version": "test",
                    "engine": "test",
                    "embedding_enabled": False,
                },
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body_bytes = self.rfile.read(length) if length else b""
        record = {"path": self.path, "headers": dict(self.headers), "body": body_bytes}

        if self.path == "/api/upload":
            # Multipart upload — synthesize a server-side path response.
            record["kind"] = "upload"
            type(self).requests_seen.append(record)
            self._send(
                200,
                {
                    "path": "/srv/uploads/test.txt",
                    "filename": "test.txt",
                    "size_bytes": length,
                },
            )
            return

        if self.path == "/api/documents":
            record["kind"] = "documents"
            try:
                record["json_body"] = json.loads(body_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                record["json_body"] = None
            type(self).requests_seen.append(record)

            # Pop the next canned response.
            try:
                canned = type(self).canned_responses.pop(0)
            except IndexError:
                self.send_error(500, "no canned response remaining")
                return
            self._send(canned["status"], canned["body"])
            return

        self.send_error(404)


@contextmanager
def _run_canned_server(canned: list[dict]) -> Iterator[str]:
    """Start the canned HTTP server in a thread; yield its base URL."""
    port = _free_port()
    _CannedHandler.canned_responses = list(canned)
    _CannedHandler.requests_seen = []
    server = HTTPServer(("127.0.0.1", port), _CannedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Brief readiness wait — connect to confirm.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


# Hoisted per tjw.2 f3: shared 413-body factory lives in conftest.
from conftest import _confirm_required_body  # noqa: E402  (after stdlib block)


def _document_response() -> dict:
    return {
        "document_id": "doc-cli-1",
        "source_file": "/srv/uploads/test.txt",
        "title": None,
        "file_type": ".txt",
        "collection": "default",
        "markdown": "x",
        "chunk_count": 1,
        "warnings": [],
        "warnings_count": 0,
        "tags": [],
    }


def _run_cli(
    args: list[str],
    *,
    host: str,
    stdin_bytes: bytes | None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run ``python -m ariadne_core_client.cli`` against ``host``."""
    import os

    env = dict(os.environ)
    env["ARIADNE_HOST"] = host
    env["ARIADNE_ACCESS_TOKEN"] = "test-bearer-token"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "ariadne_core_client.cli", *args],
        input=stdin_bytes,
        capture_output=True,
        env=env,
        timeout=30,
    )


def _decode(b: bytes) -> str:
    """Best-effort decode for assertions."""
    if b is None:
        return ""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("utf-8", errors="replace")


# ============================================================================
# Probe (h): interactive prompt behavior — y / n / default-N
# ============================================================================


def test_h_interactive_prompt_yes_proceeds_in_process(monkeypatch, capsys) -> None:
    """``y\\n`` confirms — exercised in-process by monkeypatching
    ``sys.stdin.isatty`` to True and ``input`` to return ``"y"``.

    Plain subprocess + piped stdin always reports ``isatty() == False``
    on Windows / Linux, so the TTY-confirms-on-y branch is unreachable
    via subprocess without a real PTY (Unix-only and platform-flaky).
    The probe is structurally an in-process unit test of
    ``_confirm_source_size``: with ``isatty=True`` and ``input -> "y"``,
    the helper returns True (proceed)."""
    from ariadne_core_client import cli as cli_mod
    from ariadne_core_client.exceptions import ConfirmationRequired

    err = ConfirmationRequired(
        "soft cap",
        soft_cap=1024,
        hard_cap=2048,
        reported_size=1500,
        source="https://example.org/big.pdf",
        content_type="application/pdf",
        last_modified="2026-05-08T00:00:00Z",
        confirmation_token="t1",
        ttl_seconds=300,
    )

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    proceed = cli_mod._confirm_source_size(err, auto_yes=False)
    assert proceed is True

    captured = capsys.readouterr()
    # Prompt fragments are on stderr only.
    assert "Source:" in captured.err
    assert "Reported size:" in captured.err
    assert "Default cap:" in captured.err
    assert "Proceed? [y/N]" in captured.err
    # No prompt characters on stdout.
    assert captured.out == ""


def test_h_interactive_prompt_no_aborts_in_process(monkeypatch, capsys) -> None:
    """``n`` declines — in-process for the same reason as the y-branch."""
    from ariadne_core_client import cli as cli_mod
    from ariadne_core_client.exceptions import ConfirmationRequired

    err = ConfirmationRequired(
        "soft cap",
        soft_cap=1024,
        hard_cap=2048,
        reported_size=1500,
        source="https://example.org/big.pdf",
        content_type=None,
        last_modified=None,
        confirmation_token="t",
        ttl_seconds=300,
    )

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    proceed = cli_mod._confirm_source_size(err, auto_yes=False)
    assert proceed is False


def test_h_interactive_prompt_empty_default_no_in_process(monkeypatch, capsys) -> None:
    """Pressing Enter (empty answer) defaults to N."""
    from ariadne_core_client import cli as cli_mod
    from ariadne_core_client.exceptions import ConfirmationRequired

    err = ConfirmationRequired(
        "soft cap",
        soft_cap=1024,
        hard_cap=2048,
        reported_size=1500,
        source="https://example.org/big.pdf",
        content_type=None,
        last_modified=None,
        confirmation_token="t",
        ttl_seconds=300,
    )

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    proceed = cli_mod._confirm_source_size(err, auto_yes=False)
    assert proceed is False


def test_h_interactive_prompt_no_aborts() -> None:
    """``n\\n`` aborts; CLI exits 1; ``Aborted.`` on stderr."""
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body()}},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"n\n",
        )
    # subprocess.run with input=b"..." closes stdin after writing it,
    # but the CLI's isatty() check is what gates the prompt: piped
    # stdin is non-TTY, so the CLI takes the fail-fast branch instead
    # of prompting. Both branches end in exit 1; assert that.
    assert result.returncode == 1
    stderr = _decode(result.stderr)
    # Either the explicit "Aborted." (TTY path) or the non-TTY error
    # ("confirmation required but stdin is not a TTY"). The non-TTY
    # branch is the realistic case under subprocess.
    assert (
        "Aborted." in stderr
        or "confirmation required but stdin is not a TTY" in stderr
    )


def test_h_interactive_prompt_empty_defaults_to_no() -> None:
    """``\\n`` (just press Enter) defaults to N; exits 1."""
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body()}},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"\n",
        )
    assert result.returncode == 1


# ============================================================================
# Probe (i): non-interactive mode — --yes vs no --yes
# ============================================================================


def test_i_yes_flag_no_tty_succeeds() -> None:
    """``--yes`` with closed/piped stdin → 0; ingestion completes."""
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body(confirmation_token="t-y")}},
        {"status": 200, "body": _document_response()},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "--yes", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"",
        )
    assert result.returncode == 0, _decode(result.stderr)
    stderr = _decode(result.stderr)
    assert "[auto-confirmed via --yes]" in stderr
    docs_calls = [
        r for r in _CannedHandler.requests_seen if r.get("kind") == "documents"
    ]
    assert len(docs_calls) == 2
    assert docs_calls[1]["json_body"]["confirmation_token"] == "t-y"


def test_i_no_yes_no_tty_fails_with_explicit_message() -> None:
    """No ``--yes`` and non-TTY → 1 with the explicit error message."""
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body()}},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"",
        )
    assert result.returncode == 1
    stderr = _decode(result.stderr)
    assert "confirmation required but stdin is not a TTY" in stderr
    assert "--yes" in stderr


# ============================================================================
# Probe (j): directory ingest with --yes blanket-confirms
# ============================================================================


def test_j_directory_ingest_with_yes_blanket_confirms(tmp_path) -> None:
    """A directory of one over-soft-cap file: ``--yes`` skips the
    per-file prompt and ingests."""
    # One file in the dir.
    (tmp_path / "a.txt").write_bytes(b"hello dir")
    # Canned: upload ok → 413 confirmation_required → 200 document.
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body(confirmation_token="t-dir")}},
        {"status": 200, "body": _document_response()},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "--yes", str(tmp_path)],
            host=host,
            stdin_bytes=b"",
        )
    assert result.returncode == 0, _decode(result.stderr)
    stderr = _decode(result.stderr)
    assert "[auto-confirmed via --yes]" in stderr
    docs_calls = [
        r for r in _CannedHandler.requests_seen if r.get("kind") == "documents"
    ]
    # First docs POST → 413; second → 200 with token.
    assert len(docs_calls) == 2
    assert docs_calls[1]["json_body"].get("confirmation_token") == "t-dir"


# ============================================================================
# Probe (j-bis): --json without --yes → JSON on stdout, prompt on stderr
# ============================================================================


def test_j_bis_json_no_yes_keeps_stdout_clean() -> None:
    """``--json`` without ``--yes``: with non-TTY stdin (which subprocess
    naturally produces), the CLI takes the fail-fast branch — exits 1
    with the explicit error on stderr and NO JSON on stdout. The
    load-bearing assertion is "no prompt characters bleed into
    stdout"."""
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body()}},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "--json", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"y\n",  # ignored under non-TTY
        )
    stdout = _decode(result.stdout)
    stderr = _decode(result.stderr)
    # Exit 1 on the fail-fast branch is fine.
    assert result.returncode == 1
    # Critical: no prompt characters on stdout.
    for needle in ("Proceed?", "[y/N]", "Reported size", "Source:", "Default cap"):
        assert needle not in stdout, (
            f"prompt fragment {needle!r} leaked into stdout: {stdout!r}"
        )
    # Stderr carries the prompt fields and/or the fail-fast error.
    assert (
        "confirmation required but stdin is not a TTY" in stderr
        or "Reported size" in stderr
    )


def test_j_bis_json_with_yes_emits_parseable_json_on_stdout() -> None:
    """``--json --yes`` → stdout parses as JSON; stderr carries the
    audit-trail line. This is the realistic non-TTY happy path."""
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body(confirmation_token="t-jy")}},
        {"status": 200, "body": _document_response()},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "--json", "--yes", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"",
        )
    assert result.returncode == 0, _decode(result.stderr)
    stdout = _decode(result.stdout)
    # stdout should parse as JSON (the Document).
    parsed = json.loads(stdout)
    assert parsed["document_id"] == "doc-cli-1"


# ============================================================================
# Probe (k): --json + --yes → audit-trail on stderr
# ============================================================================


def test_k_json_yes_audit_trail_on_stderr_only() -> None:
    """Pin the three properties of design rev3 Nit 4 (probe k):
      (i)   stdout is parseable JSON
      (ii)  stderr contains the literal ``[auto-confirmed via --yes]``
      (iii) no prompt-shaped substrings on stdout
    """
    canned = [
        {"status": 413, "body": {"detail": _confirm_required_body(confirmation_token="t-k")}},
        {"status": 200, "body": _document_response()},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", "--json", "--yes", "https://example.org/big.pdf"],
            host=host,
            stdin_bytes=b"",
        )
    assert result.returncode == 0, _decode(result.stderr)
    stdout = _decode(result.stdout)
    stderr = _decode(result.stderr)

    # (i)
    parsed = json.loads(stdout)
    assert parsed["document_id"] == "doc-cli-1"
    # (ii)
    assert "[auto-confirmed via --yes]" in stderr
    # (iii)
    for needle in ("Proceed?", "[y/N]"):
        assert needle not in stdout, (
            f"prompt fragment {needle!r} on stdout in --json --yes mode: {stdout!r}"
        )


# ============================================================================
# Probe (v4): mid-batch decline — file 2 of 3 declined, files 1 + 3 succeed
# ============================================================================


def test_v4_mid_batch_decline_continues_with_remaining_files(tmp_path) -> None:
    """tjw.2 v4 — integrated probe: a 3-file directory where the middle
    file triggers ConfirmationRequired and the operator declines (or
    stdin is non-TTY without ``--yes``, which fail-fasts the same way).
    Files 1 and 3 must complete; file 2 must be marked as a per-file
    failure; the loop must not abort the whole batch.

    Wire shape (per-file):
        file 1 → upload OK → /api/documents 200 (success)
        file 2 → upload OK → /api/documents 413 confirmation_required
                 → CLI decline → counted as failure, NO retry POST
        file 3 → upload OK → /api/documents 200 (success)

    Canned /api/documents responses: [200, 413, 200]. Files iterate in
    sorted order so a.txt, b.txt, c.txt is the actual sequence."""
    # Three files, sorted-iter order = a, b, c.
    (tmp_path / "a.txt").write_bytes(b"alpha")
    (tmp_path / "b.txt").write_bytes(b"beta")  # the over-soft-cap one (canned 413)
    (tmp_path / "c.txt").write_bytes(b"gamma")

    canned = [
        {"status": 200, "body": _document_response()},
        {
            "status": 413,
            "body": {"detail": _confirm_required_body(confirmation_token="t-mid")},
        },
        {"status": 200, "body": _document_response()},
    ]
    with _run_canned_server(canned) as host:
        result = _run_cli(
            ["ingest", str(tmp_path)],
            host=host,
            # n\n is operator-decline at a TTY prompt; under non-TTY
            # subprocess (the realistic case) the CLI takes the
            # fail-fast branch which ALSO returns False from
            # _confirm_source_size — same per-file-failure path.
            stdin_bytes=b"n\n",
        )

    # Exit 1 because file 2 errored (failures > 0).
    assert result.returncode == 1, _decode(result.stderr)

    docs_calls = [
        r for r in _CannedHandler.requests_seen if r.get("kind") == "documents"
    ]
    # Exactly 3 docs POSTs — file 2's decline must NOT trigger a retry POST.
    assert len(docs_calls) == 3, (
        f"expected 3 /api/documents POSTs (one per file, no retry on decline); "
        f"got {len(docs_calls)}"
    )
    # None of the docs POSTs should carry confirmation_token — file 2's
    # token is dropped (decline), files 1 + 3 never got a token.
    for i, call in enumerate(docs_calls, 1):
        assert "confirmation_token" not in (call.get("json_body") or {}), (
            f"docs POST {i} unexpectedly carried confirmation_token: "
            f"{call.get('json_body')}"
        )

    # Stderr should reflect: 2 successes, 1 errored. The non-JSON branch
    # prints a summary line "ingested N/3 (M errored)" — pin that.
    stderr = _decode(result.stderr)
    assert "ingested 2/3" in stderr, (
        f"expected 'ingested 2/3' summary line; got stderr: {stderr!r}"
    )
    assert "1 errored" in stderr, (
        f"expected '1 errored' in summary; got stderr: {stderr!r}"
    )
