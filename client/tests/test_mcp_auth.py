"""Hermetic CI tests for ``scripts/mcp_auth.py`` — the Claude Code MCP
``headersHelper`` script that turns a keyring-stored Ariadne credential
into an ``Authorization: Bearer <jwt>`` header on stdout.

Strategy
--------
We invoke the script as a subprocess (``subprocess.run([sys.executable,
script_path], env=..., capture_output=True)``) rather than importing it
in-process. The script is consumed by Claude Code via process exec, so
the CI test must exercise the same wire shape — exit code, stdout text,
stderr text — that Claude Code observes.

Hermeticity is achieved by:

- Pointing ``HOME`` / ``USERPROFILE`` at ``tmp_path`` so the script
  never reads the developer's real ``~/.config/ariadne/default``.
- Setting / unsetting ``ARIADNE_ACCESS_TOKEN`` and ``ARIADNE_HOST`` per
  case.
- Pre-seeding ``<tmp_path>/.config/ariadne/default`` for cases that
  exercise the file-fallback host-resolution path.
- For keyring-touching cases, monkeypatching is in-process; we drive the
  script's behavior by env-vars only and assume the keyring layer is
  covered by ``test_auth.py`` (Layer 1) at the unit level. Tests that
  need to simulate "keyring backend unavailable" inject a stub keyring
  via a tmp PYTHONPATH, demonstrated below.

What this suite does NOT cover (deferred to VERA's verification layers)
-----------------------------------------------------------------------
- A live OS keyring round-trip (Layer 6 in xft.5.5's methodology).
- The Claude Code MCP transport actually parsing our stdout
  (Denson manual smoke is the source of truth for that — see
  ``docs/smoke/xft5c_smoke.md``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# ----------------------------------------------------------- locate the script

# tests/test_mcp_auth.py -> tests/ -> client/ -> repo-root/ -> repo-root/scripts/mcp_auth.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "mcp_auth.py"


def _hermetic_env(tmp_home: Path, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal env dict that points HOME/USERPROFILE at ``tmp_home``.

    The script's only filesystem inputs (besides imports) are
    ``Path.home()`` (for ``DEFAULT_HOST_CONFIG_PATH``) and any keyring
    backend's per-OS storage path. By pointing both ``HOME`` (POSIX) and
    ``USERPROFILE`` (Windows) at ``tmp_home`` we get a guaranteed-empty
    config root.

    PATH and SYSTEMROOT (Windows) carry through so the subprocess can
    actually start — without SYSTEMROOT a CPython process on Windows
    cannot resolve required DLLs.
    """
    env = {
        "HOME": str(tmp_home),
        "USERPROFILE": str(tmp_home),
        "PATH": os.environ.get("PATH", ""),
    }
    # SYSTEMROOT / WINDIR / TEMP — Python on Windows needs these to start.
    for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    if extra:
        env.update(extra)
    return env


def _run_script(env: dict[str, str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Invoke ``mcp_auth.py`` as a subprocess and return the completed process."""
    return subprocess.run(  # noqa: S603 — controlled args
        [sys.executable, str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ============================================================== happy-path tests

class TestEnvTokenHappyPath:
    """ARIADNE_ACCESS_TOKEN env var bypasses the keyring entirely."""

    def test_emits_bearer_json_on_stdout(self, tmp_path: Path) -> None:
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "https://example.test",
                "ARIADNE_ACCESS_TOKEN": "tk-happy-path",
            },
        )
        result = _run_script(env)
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stderr == "", f"unexpected stderr: {result.stderr!r}"
        # Must parse as JSON and have exactly the Authorization header.
        payload = json.loads(result.stdout)
        assert payload == {"Authorization": "Bearer tk-happy-path"}

    def test_stdout_is_pure_json_no_trailing_noise(self, tmp_path: Path) -> None:
        """Claude Code parses stdout strictly as JSON. Any trailing text fails."""
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "https://example.test",
                "ARIADNE_ACCESS_TOKEN": "tk-purity",
            },
        )
        result = _run_script(env)
        assert result.returncode == 0
        # No trailing newline, no debug print, no log line.
        assert result.stdout == '{"Authorization": "Bearer tk-purity"}', (
            f"stdout was not pure JSON: {result.stdout!r}"
        )
        # And: it parses, and the dict has exactly one key.
        parsed = json.loads(result.stdout)
        assert list(parsed.keys()) == ["Authorization"]

    def test_host_resolved_from_default_file_when_env_unset(
        self, tmp_path: Path
    ) -> None:
        """If ARIADNE_HOST is unset, ``~/.config/ariadne/default`` wins."""
        # Pre-seed the file.
        cfg_dir = tmp_path / ".config" / "ariadne"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "default").write_text("https://from-default-file.test\n")

        env = _hermetic_env(
            tmp_path,
            extra={"ARIADNE_ACCESS_TOKEN": "tk-from-default"},
        )
        # ARIADNE_HOST intentionally absent.
        result = _run_script(env)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert json.loads(result.stdout) == {
            "Authorization": "Bearer tk-from-default"
        }


# ============================================================ fail-closed tests

class TestFailClosed:
    """No silent fallback — missing creds produce a non-zero exit + stderr."""

    def test_no_credentials_fails_closed_with_diagnostic(
        self, tmp_path: Path
    ) -> None:
        """No env-token, no keyring entry, no host file → exit 2, empty stdout."""
        env = _hermetic_env(
            tmp_path,
            extra={"ARIADNE_HOST": "https://no-creds.test"},
        )
        result = _run_script(env)
        # Fail-closed contract: non-zero (specifically 2 for auth class).
        assert result.returncode == 2, (
            f"expected exit 2 (auth-class), got {result.returncode}\n"
            f"stderr={result.stderr!r}"
        )
        # Stdout is EMPTY — no legacy {} fail-open emission.
        assert result.stdout == "", (
            f"stdout must be empty on fail-closed; got {result.stdout!r}"
        )
        # Stderr names the failure and the user action.
        assert "ariadne mcp_auth" in result.stderr
        assert "ariadne login" in result.stderr

    def test_no_host_resolvable_fails_closed(self, tmp_path: Path) -> None:
        """No ARIADNE_HOST, no default file → exit 2 with host-resolution stderr."""
        env = _hermetic_env(tmp_path)
        # ARIADNE_HOST and ARIADNE_ACCESS_TOKEN both unset; tmp_path has
        # no .config/ariadne/default.
        result = _run_script(env)
        assert result.returncode == 2
        assert result.stdout == ""
        # The diagnostic should explicitly name host resolution.
        assert "host" in result.stderr.lower() or "ARIADNE_HOST" in result.stderr
        # And it should point at the recovery action.
        assert "ariadne login" in result.stderr

    def test_legacy_empty_dict_emission_is_gone(self, tmp_path: Path) -> None:
        """Regression guard: the legacy ``{}`` fail-open shape is REMOVED.

        The previous mcp_auth.py would print ``{}`` and exit 1 when no
        token was found. Pass 3 fail-closed posture removes both halves
        of that contract: stdout is empty, exit is non-1 (we use 2).
        """
        env = _hermetic_env(
            tmp_path,
            extra={"ARIADNE_HOST": "https://no-creds.test"},
        )
        result = _run_script(env)
        assert result.stdout != "{}", (
            "fail-open `{}` shape must not be re-introduced"
        )
        assert result.returncode != 1, (
            "legacy exit code 1 must not be re-used; new contract is exit 2"
        )


# =========================================================== token-leak guard

class TestTokenNeverLeaks:
    """Tokens MUST NOT appear in stderr (or anywhere besides the JSON payload)."""

    def test_token_never_appears_in_stderr_on_success(self, tmp_path: Path) -> None:
        sentinel = "never-log-me-zzz-9f3d2c1b"
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "https://leak-check.test",
                "ARIADNE_ACCESS_TOKEN": sentinel,
            },
        )
        result = _run_script(env)
        assert result.returncode == 0
        assert sentinel not in result.stderr, (
            f"token leaked to stderr: {result.stderr!r}"
        )
        # The token IS in stdout — that's the contract — but only there.
        assert sentinel in result.stdout

    def test_token_never_appears_in_stderr_on_failure(self, tmp_path: Path) -> None:
        """Even on a (synthetic) host-validation failure, no token in stderr."""
        sentinel = "another-secret-aaa-bbb-ccc"
        # Use a deliberately-malformed host so resolve_host raises; the
        # token is set but irrelevant because resolve_host fails first.
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "ftp://wrong-scheme.test",
                "ARIADNE_ACCESS_TOKEN": sentinel,
            },
        )
        result = _run_script(env)
        assert result.returncode != 0
        assert sentinel not in result.stderr
        assert sentinel not in result.stdout


# ====================================================== keyring-unavailable case

class TestKeyringUnavailable:
    """When the keyring backend itself is broken, we must:

    - Use ARIADNE_ACCESS_TOKEN if set (env hatch wins).
    - Otherwise, exit 2 with a stderr hint pointing at ARIADNE_ACCESS_TOKEN.
    """

    def _stub_keyring_dir(self, tmp_path: Path) -> Path:
        """Write a stub ``keyring`` package under tmp_path/stubs/ that raises.

        We then prepend that dir to PYTHONPATH so the subprocess imports
        OUR ``keyring``, which simulates "backend unavailable" on every
        operation. This exercises the real
        ``KeyringStore.__init__`` → ``KeyringBackendUnavailable`` path.
        """
        stub_root = tmp_path / "stubs"
        stub_pkg = stub_root / "keyring"
        stub_pkg.mkdir(parents=True)
        (stub_pkg / "__init__.py").write_text(
            textwrap.dedent(
                """\
                # Stub keyring that always raises — simulates a broken backend.
                from . import errors


                def get_password(service, username):
                    raise errors.KeyringError("stub backend: get_password unavailable")


                def set_password(service, username, value):
                    raise errors.KeyringError("stub backend: set_password unavailable")


                def delete_password(service, username):
                    raise errors.KeyringError("stub backend: delete_password unavailable")
                """
            )
        )
        (stub_pkg / "errors.py").write_text(
            textwrap.dedent(
                """\
                class KeyringError(Exception):
                    pass


                class PasswordDeleteError(KeyringError):
                    pass
                """
            )
        )
        return stub_root

    def test_env_token_wins_even_when_keyring_broken(self, tmp_path: Path) -> None:
        """ARIADNE_ACCESS_TOKEN is the always-first hatch: keyring never queried."""
        stub_root = self._stub_keyring_dir(tmp_path)
        # Make our stub win over any installed `keyring` package.
        pythonpath = str(stub_root) + os.pathsep + os.environ.get("PYTHONPATH", "")
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "https://broken-keyring.test",
                "ARIADNE_ACCESS_TOKEN": "tk-bypass-keyring",
                "PYTHONPATH": pythonpath,
            },
        )
        result = _run_script(env)
        assert result.returncode == 0, (
            f"env-token must bypass keyring; "
            f"got exit={result.returncode} stderr={result.stderr!r}"
        )
        assert json.loads(result.stdout) == {
            "Authorization": "Bearer tk-bypass-keyring"
        }

    def test_keyring_broken_no_env_token_fails_closed_with_hint(
        self, tmp_path: Path
    ) -> None:
        """Without env-token, broken keyring → exit 2, stderr names env hatch."""
        stub_root = self._stub_keyring_dir(tmp_path)
        pythonpath = str(stub_root) + os.pathsep + os.environ.get("PYTHONPATH", "")
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "https://broken-keyring.test",
                "PYTHONPATH": pythonpath,
            },
        )
        result = _run_script(env)
        assert result.returncode == 2, (
            f"expected exit 2; got {result.returncode}\nstderr={result.stderr!r}"
        )
        assert result.stdout == ""
        # The platform-aware message mentions ARIADNE_ACCESS_TOKEN.
        assert "ARIADNE_ACCESS_TOKEN" in result.stderr, (
            f"stderr should hint at the env-var hatch; got {result.stderr!r}"
        )


# ================================================================ shape sanity

class TestShape:
    """Lock the wire-shape contract a future maintainer might naively change."""

    def test_success_stdout_has_exactly_one_authorization_key(
        self, tmp_path: Path
    ) -> None:
        env = _hermetic_env(
            tmp_path,
            extra={
                "ARIADNE_HOST": "https://shape.test",
                "ARIADNE_ACCESS_TOKEN": "tk-shape",
            },
        )
        result = _run_script(env)
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == {"Authorization"}
        # Bearer scheme exactly — case-sensitive per RFC 6750.
        assert re.fullmatch(r"Bearer \S+", parsed["Authorization"])

    def test_script_is_executable_with_python_interpreter(self) -> None:
        """The script must be importable as a top-level module (no relative imports)."""
        # Sanity: file exists, parses as a Python module.
        assert _SCRIPT.is_file(), f"{_SCRIPT} not found"
        compile(_SCRIPT.read_text(encoding="utf-8"), str(_SCRIPT), "exec")
