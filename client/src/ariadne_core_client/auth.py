"""OAuth 2.1 + PKCE authentication for the Ariadne Core client.

Stdlib-only transport (urllib); the only third-party runtime dep is
``keyring`` for OS credential storage. No httpx, no requests — the
rest of the client package is urllib-based and this module matches.

Public surface
--------------
- :func:`discover_config(host)` — GET ``{host}/.well-known/ariadne-config``.
- :class:`KeyringStore` — thin wrapper over ``keyring`` so tests can
  inject a fake backend (see ``InMemoryKeyringStore`` below).
- :class:`InMemoryKeyringStore` — hermetic fake for tests; also works
  as an emergency in-process fallback (never used by production code).
- :func:`login(host, store=None)` — opens the browser, runs the PKCE
  loopback flow, stores refresh + access tokens in the keyring.
- :func:`logout(host, store=None)` — clears all keyring entries for
  this host.
- :func:`get_access_token(host, store=None)` — returns a cached
  access token; proactively refreshes when inside the 60s threshold.
- :func:`whoami(host, store=None)` — decodes the stored JWT and
  returns ``{host, user_email, user_sub, access_expiry, expires_in_seconds}``.
- :func:`format_keyring_error(exc, platform=...)` — platform-aware
  error text for macOS / Windows / Linux with recovery guidance.
- :func:`resolve_host(flag_value)` — precedence
  ``--host`` > ``ARIADNE_HOST`` > ``~/.config/ariadne/default`` > error.
- :func:`write_default_host(host)` — unconditionally overwrites
  ``~/.config/ariadne/default``. Called by ``login`` on success.

Design decisions (Denson-approved 2026-04-21, see ticket ariadne--xft.5.1):
- **PKCE:** loopback redirect per RFC 8252; multi-port allow-list
  8765-8769 tried in order; first bindable port wins.
- **Storage:** ``service="ariadne-core"``, ``username="{host}:{slot}"``
  where slot ∈ ``{refresh_token, access_token, access_expiry}``.
- **Refresh:** proactive — if ``access_expiry - now() <= 60s``, refresh
  before returning. No reactive 401-retry in this ticket.
- **ARIADNE_ACCESS_TOKEN env var:** always honored first in
  :func:`get_access_token`; keyring is never touched when it is set.
- **No plaintext-file fallback.** Keyring failures surface platform-
  aware error messages and exit nonzero.
- **discover_config shape:** returns the inner ``auth`` dict from the
  server response —
  ``{"issuer", "client_id", "audience", "scope"}``. The server emits
  ``{"auth": {...}}`` per SPEC.md § "Discovery endpoint"; we unwrap
  one level.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

# --------------------------------------------------------------------- constants

#: Loopback ports tried in order; first bindable port wins.
LOOPBACK_PORT_CANDIDATES: tuple[int, ...] = (8765, 8766, 8767, 8768, 8769)

#: Keyring service name — all Ariadne credentials live under this service.
KEYRING_SERVICE: str = "ariadne-core"

#: Refresh-threshold: if an access token's remaining lifetime is <= this
#: many seconds, :func:`get_access_token` refreshes before returning.
REFRESH_THRESHOLD_SECONDS: int = 60

#: Slot names for per-host credential storage.
SLOT_REFRESH_TOKEN = "refresh_token"
SLOT_ACCESS_TOKEN = "access_token"
SLOT_ACCESS_EXPIRY = "access_expiry"

#: Default location for the resolved host fallback.
DEFAULT_HOST_CONFIG_PATH = Path.home() / ".config" / "ariadne" / "default"

#: ``GET /.well-known/ariadne-config`` path (mounted at app root, not under /api).
DISCOVERY_PATH = "/.well-known/ariadne-config"


# --------------------------------------------------------------------- exceptions

class KeyringBackendUnavailable(Exception):
    """Raised when the OS keyring is unreachable (or the package is missing).

    Carries a preformatted, platform-aware error message that callers
    (notably the CLI) can print verbatim. The original exception is
    available on ``.__cause__`` for Google/search purposes.
    """


class AuthError(Exception):
    """Generic auth-flow failure (PKCE callback, token exchange, discovery)."""


# -------------------------------------------------------- keyring store abstraction

class KeyringStoreProtocol(Protocol):  # pragma: no cover - typing only
    def get(self, host: str, slot: str) -> Optional[str]: ...
    def set(self, host: str, slot: str, value: str) -> None: ...
    def delete(self, host: str, slot: str) -> None: ...


class KeyringStore:
    """Thin wrapper over the ``keyring`` package.

    Import of the ``keyring`` package is lazy (inside ``__init__``) so
    that importing this module on a system without the package installed
    does not fail at import time — tests that use an injected fake do
    not need the real package to exist.

    All errors are wrapped as :class:`KeyringBackendUnavailable` with a
    platform-aware message via :func:`format_keyring_error`.
    """

    def __init__(self) -> None:
        try:
            import keyring  # type: ignore[import-not-found]
            import keyring.errors  # type: ignore[import-not-found]
        except ImportError as exc:
            raise KeyringBackendUnavailable(format_keyring_error(exc)) from exc
        self._keyring = keyring
        # Store the error classes we know how to wrap. Anything else
        # propagates unchanged — we do not want to swallow unexpected
        # backend bugs.
        self._known_errors: tuple[type[BaseException], ...] = (
            keyring.errors.KeyringError,
        )

    @staticmethod
    def _username(host: str, slot: str) -> str:
        return f"{host}:{slot}"

    def get(self, host: str, slot: str) -> Optional[str]:
        try:
            return self._keyring.get_password(KEYRING_SERVICE, self._username(host, slot))
        except self._known_errors as exc:  # pragma: no cover - passthrough
            raise KeyringBackendUnavailable(format_keyring_error(exc)) from exc

    def set(self, host: str, slot: str, value: str) -> None:
        try:
            self._keyring.set_password(KEYRING_SERVICE, self._username(host, slot), value)
        except self._known_errors as exc:  # pragma: no cover - passthrough
            raise KeyringBackendUnavailable(format_keyring_error(exc)) from exc

    def delete(self, host: str, slot: str) -> None:
        try:
            self._keyring.delete_password(KEYRING_SERVICE, self._username(host, slot))
        except self._known_errors as exc:
            # Missing entry is a subclass (PasswordDeleteError) and is
            # not an error for logout — we just want to make sure the
            # slot ends up absent. Re-raise anything else.
            name = exc.__class__.__name__
            if name == "PasswordDeleteError":
                return
            raise KeyringBackendUnavailable(format_keyring_error(exc)) from exc


class InMemoryKeyringStore:
    """Hermetic in-memory fake implementing :class:`KeyringStoreProtocol`.

    Used by tests. Also safe to hand to :func:`login` in non-interactive
    contexts where you want the tokens to live only in process memory
    (rare; the production path uses :class:`KeyringStore`).
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], str] = {}

    def get(self, host: str, slot: str) -> Optional[str]:
        return self._data.get((host, slot))

    def set(self, host: str, slot: str, value: str) -> None:
        self._data[(host, slot)] = value

    def delete(self, host: str, slot: str) -> None:
        self._data.pop((host, slot), None)


# ---------------------------------------------------------- platform error messages

_MACOS_TEMPLATE = (
    "Could not access the macOS Keychain.\n"
    "\n"
    "Ariadne stores its OAuth tokens in the system keychain so that they are\n"
    "encrypted at rest and scoped to your user account. This operation failed.\n"
    "\n"
    "To recover:\n"
    "  1. Open 'Keychain Access' (Applications > Utilities).\n"
    "  2. If the 'login' keychain is locked, double-click it and unlock it\n"
    "     with your macOS account password.\n"
    "  3. Try the Ariadne command again.\n"
    "\n"
    "If the problem persists, set ARIADNE_ACCESS_TOKEN in your environment\n"
    "to supply a token directly (bypasses the keychain entirely).\n"
    "\n"
    "Details: {detail}"
)

_WINDOWS_TEMPLATE = (
    "Could not access Windows Credential Manager.\n"
    "\n"
    "Ariadne stores its OAuth tokens in the Windows Credential Manager so\n"
    "that they are encrypted at rest and scoped to your user account. This\n"
    "operation failed.\n"
    "\n"
    "Common causes:\n"
    "  - Running under a service account (LOCAL SYSTEM, NETWORK SERVICE)\n"
    "    that has no interactive user profile to attach credentials to.\n"
    "  - Group Policy blocking access to the user's credential store.\n"
    "  - The 'Credential Manager' service (VaultSvc) being disabled.\n"
    "\n"
    "To recover:\n"
    "  1. Run 'services.msc'. Make sure 'Credential Manager' is running.\n"
    "  2. Run this command from an interactive user session (not a\n"
    "     background service).\n"
    "  3. If you are inside a locked-down corporate profile, set\n"
    "     ARIADNE_ACCESS_TOKEN in your environment to supply a token\n"
    "     directly (bypasses Credential Manager entirely).\n"
    "\n"
    "Details: {detail}"
)

_LINUX_TEMPLATE = (
    "No OS keyring backend available.\n"
    "\n"
    "Ariadne stores its OAuth tokens in the system keyring so that they are\n"
    "encrypted at rest and scoped to your user account. No usable keyring\n"
    "backend was found.\n"
    "\n"
    "To install a keyring backend:\n"
    "  - Debian / Ubuntu:     sudo apt install gnome-keyring python3-secretstorage\n"
    "  - Fedora / RHEL:       sudo dnf install gnome-keyring python3-secretstorage\n"
    "  - Arch:                sudo pacman -S gnome-keyring python-secretstorage\n"
    "\n"
    "Then, in a session without a display manager (SSH, tmux, systemd\n"
    "service), start the daemon manually before running Ariadne:\n"
    "\n"
    "    eval $(gnome-keyring-daemon --start)\n"
    "    export GNOME_KEYRING_CONTROL GNOME_KEYRING_PID SSH_AUTH_SOCK\n"
    "\n"
    "Alternative: set ARIADNE_ACCESS_TOKEN in your environment to supply a\n"
    "token directly (bypasses the keyring entirely).\n"
    "\n"
    "Details: {detail}"
)


def format_keyring_error(exc: BaseException, platform: Optional[str] = None) -> str:
    """Return a platform-aware error message for a keyring failure.

    :param exc: the underlying exception. Its ``str()`` is appended
        under a "Details:" tail so users can Google the verbatim text.
    :param platform: ``sys.platform`` value, overridable for tests.
        Dispatch rules: starts with ``darwin`` → macOS template;
        starts with ``win`` → Windows template; everything else → Linux
        template (covers Linux proper, *BSD, WSL-without-keyring).
    """
    plat = (platform if platform is not None else sys.platform).lower()
    detail = str(exc) if str(exc) else exc.__class__.__name__
    if plat.startswith("darwin"):
        tpl = _MACOS_TEMPLATE
    elif plat.startswith("win"):
        tpl = _WINDOWS_TEMPLATE
    else:
        tpl = _LINUX_TEMPLATE
    return tpl.format(detail=detail)


# ------------------------------------------------------------------ host resolution

def _read_default_host_file(path: Optional[Path] = None) -> Optional[str]:
    p = path if path is not None else DEFAULT_HOST_CONFIG_PATH
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return raw or None


def resolve_host(
    flag_value: Optional[str],
    *,
    env: Optional[dict[str, str]] = None,
    config_path: Optional[Path] = None,
) -> str:
    """Resolve the Ariadne server host per CLI precedence.

    Order (first hit wins):

    1. ``flag_value`` (i.e. ``--host <url>``).
    2. ``ARIADNE_HOST`` environment variable.
    3. Contents of ``~/.config/ariadne/default`` (or ``config_path`` if
       injected for tests).

    Raises :class:`AuthError` with a friendly message if none are set.
    The returned host is stripped of trailing slashes so callers can
    always build URLs by simple string concatenation.
    """
    environ = env if env is not None else os.environ

    if flag_value:
        return _normalize_host(flag_value)

    env_val = environ.get("ARIADNE_HOST")
    if env_val:
        return _normalize_host(env_val)

    file_val = _read_default_host_file(config_path)
    if file_val:
        return _normalize_host(file_val)

    raise AuthError(
        "No Ariadne server host configured.\n"
        "  - Pass it explicitly: --host https://your-deployment.example\n"
        "  - Or set ARIADNE_HOST in your environment\n"
        "  - Or run 'ariadne login --host <url>' to make it the default"
    )


def _normalize_host(raw: str) -> str:
    """Strip whitespace and trailing slashes from a host URL, then validate scheme.

    Security: the host we are about to hit for ``/.well-known/ariadne-config``
    determines which IdP the PKCE flow redirects to. A poisoned
    ``ARIADNE_HOST`` / default-host file with ``http://attacker.example``
    (or ``file://``, ``javascript:``, ``ftp://``, ``data:``, or a bare
    hostname) would let an attacker-controlled discovery payload pick
    the ``issuer`` for authorize. PKCE protects the code→token exchange,
    not the "which IdP do we even go to" step — so this predicate is
    the chokepoint that enforces the IdP-selection is trustworthy.

    Rule: accept ``https://<any-host>``; allow ``http://`` **only** for
    loopback (``localhost`` or ``127.0.0.1``), which is where the local
    dev server runs. Everything else raises :class:`AuthError`.
    """
    out = raw.strip()
    while out.endswith("/"):
        out = out[:-1]
    parsed = urllib.parse.urlparse(out)
    scheme = parsed.scheme
    hostname = parsed.hostname  # lowercased, stripped of port
    if scheme == "https" and hostname:
        return out
    if scheme == "http" and hostname in ("localhost", "127.0.0.1"):
        return out
    raise AuthError(
        f"Host {raw!r} is not a valid Ariadne server URL — "
        "must be https://... or http://localhost[:port] / "
        "http://127.0.0.1[:port] for local development."
    )


def write_default_host(host: str, *, config_path: Optional[Path] = None) -> None:
    """Unconditionally (over)write ``~/.config/ariadne/default`` with ``host``.

    Called by :func:`login` on success. Simple-is-better: the user just
    logged in to this host, so we want that to be the default; if they
    want a different default they log in to a different host.

    Creates the parent directory with user-only permissions
    (``0o700``) and writes the file with ``0o600``. On Windows
    ``chmod`` modes are advisory but we set them anyway for cross-
    platform consistency.
    """
    target = config_path if config_path is not None else DEFAULT_HOST_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:  # pragma: no cover - permissions on Windows are best-effort
        pass
    target.write_text(host, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:  # pragma: no cover
        pass


# -------------------------------------------------------------- discovery transport

def _http_get_json(url: str, *, timeout: float = 30.0) -> Any:
    """Minimal stdlib JSON GET helper scoped to this module.

    We keep this separate from ``ariadne_core_client._http`` because
    :mod:`_http` raises ``AriadneClientError`` — we want auth-layer
    errors to surface as :class:`AuthError` so callers can distinguish
    "couldn't log in" from "API call failed".
    """
    req = urllib_request.Request(url=url, method="GET")
    req.add_header("Accept", "application/json")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib_error.HTTPError as err:
        try:
            body = err.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise AuthError(f"HTTP {err.code} from {url}: {body[:300] or err.reason}") from err
    except urllib_error.URLError as err:
        raise AuthError(f"Could not reach {url}: {err.reason}") from err
    except TimeoutError as err:
        raise AuthError(f"Request to {url} timed out after {timeout}s") from err
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise AuthError(f"Non-JSON response from {url}") from err


def _http_post_form(
    url: str,
    form: dict[str, str],
    *,
    timeout: float = 30.0,
) -> Any:
    """POST ``application/x-www-form-urlencoded`` and parse JSON response."""
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib_request.Request(url=url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib_error.HTTPError as err:
        try:
            text = err.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        # Try to parse Auth0's structured error envelope (it returns
        # {"error": "...", "error_description": "..."} on 400/401).
        detail = text[:500] or err.reason or f"HTTP {err.code}"
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            err_code = payload.get("error")
            err_desc = payload.get("error_description")
            if err_code and err_desc:
                detail = f"{err_code}: {err_desc}"
            elif err_code:
                detail = str(err_code)
        raise AuthError(f"Token endpoint returned HTTP {err.code}: {detail}") from err
    except urllib_error.URLError as err:
        raise AuthError(f"Could not reach {url}: {err.reason}") from err
    except TimeoutError as err:
        raise AuthError(f"Request to {url} timed out after {timeout}s") from err
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise AuthError(f"Non-JSON response from {url}") from err


def discover_config(host: str, *, timeout: float = 30.0) -> dict[str, str]:
    """GET ``{host}/.well-known/ariadne-config`` and return the inner ``auth`` dict.

    The server returns ``{"auth": {"issuer": ..., "client_id": ...,
    "audience": ..., "scope": ...}}`` — we return the unwrapped inner
    object so callers just see ``{"issuer", "client_id", "audience",
    "scope"}``.

    ``issuer`` is expected to carry the Auth0 trailing slash
    (``https://<tenant>/``), which matches Auth0's convention for
    ``/authorize`` and ``/oauth/token`` path construction
    (``{issuer}authorize`` and ``{issuer}oauth/token`` — no double
    slash).

    Raises :class:`AuthError` if the endpoint returns a non-2xx, a
    non-JSON body, or a payload missing the required keys.
    """
    url = f"{_normalize_host(host)}{DISCOVERY_PATH}"
    payload = _http_get_json(url, timeout=timeout)
    if not isinstance(payload, dict):
        raise AuthError(f"Unexpected discovery payload type: {type(payload).__name__}")
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        raise AuthError("Discovery payload missing 'auth' object")
    required = ("issuer", "client_id", "audience", "scope")
    missing = [k for k in required if not isinstance(auth.get(k), str) or not auth[k]]
    if missing:
        raise AuthError(f"Discovery payload missing fields: {', '.join(missing)}")
    return {k: auth[k] for k in required}


# --------------------------------------------------------------------------- PKCE

def _generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636 § 4.

    - ``code_verifier`` is 43 chars of URL-safe base64 (from 32 random
      bytes); well within the RFC's 43–128 range.
    - ``code_challenge`` = BASE64URL(SHA256(verifier)), padding stripped.
    """
    verifier = secrets.token_urlsafe(32)  # 32 bytes -> 43 chars (no padding)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _generate_state() -> str:
    """Return a URL-safe random string with >= 128 bits of entropy."""
    return secrets.token_urlsafe(32)  # 32 bytes = 256 bits


# -------------------------------------------------------- loopback callback server

def _find_free_loopback_port(
    candidates: Iterable[int] = LOOPBACK_PORT_CANDIDATES,
) -> int:
    """Return the first port in ``candidates`` that binds on 127.0.0.1.

    Raises :class:`AuthError` (with the tried list and OS guidance) if
    all candidates are in use. We bind and immediately close the probe
    socket — the actual server re-binds the same port a moment later.
    There is a tiny TOCTOU window; 5 candidates make the retry
    statistically trivial.
    """
    tried: list[int] = []
    last_exc: Optional[OSError] = None
    for port in candidates:
        tried.append(port)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as err:
            last_exc = err
            probe.close()
            continue
        probe.close()
        return port
    tried_s = ", ".join(str(p) for p in tried)
    detail = f" (last error: {last_exc})" if last_exc is not None else ""
    raise AuthError(
        f"Could not bind any loopback callback port. Tried: {tried_s}.{detail}\n"
        f"\n"
        f"The OAuth login flow needs to listen on one of these ports to\n"
        f"receive the callback from your browser. They are all currently\n"
        f"in use by another process. Free one of them and try again.\n"
        f"\n"
        f"On Unix:   lsof -i :8765   (replace with whichever port)\n"
        f"On macOS:  lsof -nP -iTCP:8765 -sTCP:LISTEN\n"
        f"On Windows: netstat -ano | findstr :8765"
    )


class _CallbackResult:
    """Thread-safe shared state between the callback handler and the main thread."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.code: Optional[str] = None
        self.state: Optional[str] = None
        self.error: Optional[str] = None
        self.error_description: Optional[str] = None

    def set_success(self, code: str, state: str) -> None:
        self.code = code
        self.state = state
        self._event.set()

    def set_error(self, error: str, description: Optional[str]) -> None:
        self.error = error
        self.error_description = description
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout=timeout)


def _make_callback_handler(
    result: _CallbackResult,
    expected_state: str,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Factory returning a BaseHTTPRequestHandler subclass closed over state."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Silence the default stderr access log — CLI UX is quieter
            # without "127.0.0.1 - - [...] GET /callback HTTP/1.1 200 -".
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in ("/callback", "/"):
                self.send_response(404)
                self.end_headers()
                return
            params = urllib.parse.parse_qs(parsed.query)
            err = (params.get("error") or [None])[0]
            if err:
                desc = (params.get("error_description") or [None])[0]
                result.set_error(err, desc)
                self._reply_html(
                    400,
                    "Ariadne login failed",
                    f"<p>Auth0 returned an error: <code>{err}</code></p>"
                    + (f"<p>{desc}</p>" if desc else "")
                    + "<p>You can close this window and try again.</p>",
                )
                return
            code = (params.get("code") or [None])[0]
            state = (params.get("state") or [None])[0]
            if not code or not state:
                result.set_error("missing_params", "Missing 'code' or 'state'.")
                self._reply_html(
                    400,
                    "Ariadne login failed",
                    "<p>The callback from Auth0 was missing required parameters.</p>"
                    "<p>You can close this window and try again.</p>",
                )
                return
            if not secrets.compare_digest(state, expected_state):
                result.set_error("state_mismatch", "CSRF state did not match.")
                self._reply_html(
                    400,
                    "Ariadne login failed",
                    "<p>The callback state did not match the one we sent to Auth0.</p>"
                    "<p>This is a security check. You can close this window and try again.</p>",
                )
                return
            result.set_success(code, state)
            self._reply_html(
                200,
                "Ariadne login complete",
                "<p>Sign-in succeeded. You can close this window and return to your terminal.</p>",
            )

        def _reply_html(self, status: int, title: str, body_html: str) -> None:
            payload = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title>"
                "<style>body{font-family:system-ui,sans-serif;padding:2em;max-width:40em;}"
                "code{background:#eee;padding:0 .2em;border-radius:3px;}</style>"
                f"</head><body><h1>{title}</h1>{body_html}</body></html>"
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return _Handler


def _run_loopback_callback(
    port: int,
    expected_state: str,
    *,
    timeout: int = 120,
) -> tuple[str, str]:
    """Block until the callback arrives; return ``(code, state)``.

    Spins up a single-request ``HTTPServer`` on ``127.0.0.1:port`` in a
    daemon thread, waits at most ``timeout`` seconds for the callback,
    then shuts the server down. Raises :class:`AuthError` on any error,
    state mismatch, or timeout.
    """
    result = _CallbackResult()
    handler_cls = _make_callback_handler(result, expected_state)
    server = http.server.HTTPServer(("127.0.0.1", port), handler_cls)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not result.wait(timeout=timeout):
            raise AuthError(
                f"Login timed out after {timeout}s waiting for the browser to complete\n"
                f"the sign-in flow. Re-run 'ariadne login' to try again."
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    if result.error is not None:
        desc = f": {result.error_description}" if result.error_description else ""
        raise AuthError(f"Login failed ({result.error}{desc})")
    # mypy/typing: the success path guarantees these are set.
    assert result.code is not None and result.state is not None
    return result.code, result.state


# --------------------------------------------------------------- JWT (id_token) decode

def _b64url_decode(data: str) -> bytes:
    """Decode a base64url segment, padding as necessary."""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def decode_jwt_unverified(token: str) -> dict[str, Any]:
    """Decode the payload segment of a JWT without signature verification.

    We **only** use this for UX — reading ``email`` out of the Auth0
    id_token at login time, and reading ``sub`` / ``email`` / ``exp``
    for the ``whoami`` display. We never trust an unverified JWT for
    authorization; the server does the verification against Auth0's
    JWKS.

    Raises :class:`AuthError` on a malformed token.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Token is not a well-formed JWT (expected three segments)")
    try:
        payload = _b64url_decode(parts[1])
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise AuthError(f"Could not decode JWT payload: {err}") from err


# -------------------------------------------------------------- token exchange flow

def _exchange_authorization_code(
    issuer: str,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST ``{issuer}oauth/token`` to exchange an authorization code.

    ``issuer`` has a trailing slash per Auth0 convention, so the URL is
    built by plain concatenation.
    """
    return _http_post_form(
        f"{issuer}oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
        timeout=timeout,
    )


def _exchange_refresh_token(
    issuer: str,
    client_id: str,
    refresh_token: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST ``{issuer}oauth/token`` to refresh an access token."""
    return _http_post_form(
        f"{issuer}oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
        timeout=timeout,
    )


def _compute_expiry_iso(expires_in_seconds: int) -> str:
    """Return an ISO-8601 UTC timestamp ``expires_in_seconds`` in the future."""
    expires_at = datetime.now(timezone.utc).timestamp() + float(expires_in_seconds)
    dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    return dt.isoformat()


def _parse_expiry_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp produced by :func:`_compute_expiry_iso`."""
    # ``datetime.fromisoformat`` accepts our output shape directly.
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------- public entry points

def login(
    host: str,
    *,
    store: Optional[KeyringStoreProtocol] = None,
    open_browser: bool = True,
    port_candidates: Iterable[int] = LOOPBACK_PORT_CANDIDATES,
    timeout: int = 120,
    write_default: bool = True,
) -> dict[str, Any]:
    """Run the PKCE loopback login flow; store tokens in the keyring.

    Returns a small dict with UX-relevant fields
    (``{"email": ..., "sub": ..., "host": ...}``) so the CLI can print
    the success message without a second keyring round-trip.

    Parameters other than ``host`` / ``store`` are for testability:

    - ``open_browser=False`` skips ``webbrowser.open`` — tests drive the
      callback directly.
    - ``port_candidates`` is injectable so tests can use random
      high-port numbers without touching 8765-8769.
    - ``write_default=False`` suppresses the unconditional default-host
      write — tests avoid scribbling into ``~/.config/ariadne/default``.
    """
    store = store if store is not None else KeyringStore()
    host = _normalize_host(host)

    config = discover_config(host)
    issuer = config["issuer"]
    client_id = config["client_id"]
    audience = config["audience"]
    scope = config["scope"]

    verifier, challenge = _generate_pkce()
    state = _generate_state()
    port = _find_free_loopback_port(port_candidates)
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    authorize_url = f"{issuer}authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "audience": audience,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    if open_browser:
        # Best effort — on headless systems webbrowser.open returns
        # False; we still print the URL so the user can paste it.
        try:
            webbrowser.open(authorize_url, new=1, autoraise=True)
        except webbrowser.Error:  # pragma: no cover - platform-specific
            pass

    code, _returned_state = _run_loopback_callback(port, state, timeout=timeout)
    token_response = _exchange_authorization_code(
        issuer, client_id, code, verifier, redirect_uri
    )

    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in")
    id_token = token_response.get("id_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise AuthError(
            "Token response missing access_token or refresh_token — the Auth0\n"
            "application may not be configured for refresh tokens. Make sure\n"
            "'offline_access' is in the scope and that the Auth0 app has\n"
            "refresh-token grants enabled."
        )
    if not isinstance(expires_in, int):
        raise AuthError("Token response missing numeric 'expires_in'")

    expiry_iso = _compute_expiry_iso(expires_in)

    store.set(host, SLOT_REFRESH_TOKEN, refresh_token)
    store.set(host, SLOT_ACCESS_TOKEN, access_token)
    store.set(host, SLOT_ACCESS_EXPIRY, expiry_iso)

    # Pull email + sub from the id_token if present — it's optional
    # on the Auth0 side but we ask for ``openid profile email`` so it
    # should always be there.
    email: Optional[str] = None
    sub: Optional[str] = None
    if isinstance(id_token, str):
        try:
            claims = decode_jwt_unverified(id_token)
        except AuthError:
            claims = {}
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        sub = claims.get("sub") if isinstance(claims.get("sub"), str) else None

    if write_default:
        try:
            write_default_host(host)
        except OSError:  # pragma: no cover - best-effort write
            pass

    return {"host": host, "email": email, "sub": sub, "expires": expiry_iso}


def logout(
    host: str,
    *,
    store: Optional[KeyringStoreProtocol] = None,
) -> None:
    """Remove all keyring entries for ``host``. Idempotent."""
    store = store if store is not None else KeyringStore()
    host = _normalize_host(host)
    for slot in (SLOT_REFRESH_TOKEN, SLOT_ACCESS_TOKEN, SLOT_ACCESS_EXPIRY):
        store.delete(host, slot)


def get_access_token(
    host: str,
    *,
    store: Optional[KeyringStoreProtocol] = None,
    env: Optional[dict[str, str]] = None,
) -> str:
    """Return a valid access token for ``host``.

    Resolution order:

    1. ``ARIADNE_ACCESS_TOKEN`` env var — always wins, keyring untouched.
       This is the CI/ci-scheduled-task escape hatch and the last-line
       recovery when keyring is broken.
    2. Cached access token with remaining lifetime ``>
       REFRESH_THRESHOLD_SECONDS``.
    3. Refresh using the stored refresh token; on success, store the
       fresh access token + expiry (and the new refresh token if Auth0
       rotated it) and return the fresh access token.

    Raises :class:`AuthError` if no refresh token is stored (user must
    run ``ariadne login``) or if the refresh call fails.
    """
    environ = env if env is not None else os.environ
    override = environ.get("ARIADNE_ACCESS_TOKEN")
    if override:
        return override

    store = store if store is not None else KeyringStore()
    host = _normalize_host(host)

    access_token = store.get(host, SLOT_ACCESS_TOKEN)
    expiry_iso = store.get(host, SLOT_ACCESS_EXPIRY)

    if access_token and expiry_iso:
        try:
            expiry = _parse_expiry_iso(expiry_iso)
        except ValueError:
            expiry = None
        if expiry is not None:
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            if remaining > REFRESH_THRESHOLD_SECONDS:
                return access_token

    refresh_token = store.get(host, SLOT_REFRESH_TOKEN)
    if not refresh_token:
        raise AuthError(
            f"Not logged in to {host}. Run:\n"
            f"    ariadne login --host {host}"
        )

    config = discover_config(host)
    issuer = config["issuer"]
    client_id = config["client_id"]

    response = _exchange_refresh_token(issuer, client_id, refresh_token)
    new_access = response.get("access_token")
    new_expires_in = response.get("expires_in")
    new_refresh = response.get("refresh_token")  # may be None if rotation is off
    if not isinstance(new_access, str) or not isinstance(new_expires_in, int):
        raise AuthError(
            "Refresh response missing access_token or expires_in. Your refresh\n"
            f"token may have been revoked. Run 'ariadne login --host {host}' to\n"
            f"sign in again."
        )
    expiry_iso = _compute_expiry_iso(new_expires_in)
    store.set(host, SLOT_ACCESS_TOKEN, new_access)
    store.set(host, SLOT_ACCESS_EXPIRY, expiry_iso)
    if isinstance(new_refresh, str) and new_refresh:
        store.set(host, SLOT_REFRESH_TOKEN, new_refresh)
    return new_access


def whoami(
    host: str,
    *,
    store: Optional[KeyringStoreProtocol] = None,
) -> dict[str, Any]:
    """Return identity info for the currently logged-in user at ``host``.

    Shape::

        {
          "host": "https://...",
          "user_email": "you@example.com" | None,
          "user_sub":   "auth0|abc..."    | None,
          "access_expiry": "2026-04-21T14:23:15+00:00" | None,
          "expires_in_seconds": 2532   # may be negative if expired
        }

    Raises :class:`AuthError` if no access token is stored. Does NOT
    perform a token refresh — ``whoami`` is a pure "what's in my
    keyring" query. If the token is expired the caller (CLI) renders
    that explicitly.
    """
    store = store if store is not None else KeyringStore()
    host = _normalize_host(host)

    access_token = store.get(host, SLOT_ACCESS_TOKEN)
    expiry_iso = store.get(host, SLOT_ACCESS_EXPIRY)
    if not access_token:
        raise AuthError(
            f"Not logged in to {host}. Run:\n"
            f"    ariadne login --host {host}"
        )

    claims: dict[str, Any] = {}
    try:
        claims = decode_jwt_unverified(access_token)
    except AuthError:
        # Access token isn't decodable for some reason; whoami still
        # reports host + expiry if those are available.
        claims = {}

    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    sub = claims.get("sub") if isinstance(claims.get("sub"), str) else None

    expires_in_seconds: Optional[int] = None
    if expiry_iso:
        try:
            expiry_dt = _parse_expiry_iso(expiry_iso)
            expires_in_seconds = int(
                (expiry_dt - datetime.now(timezone.utc)).total_seconds()
            )
        except ValueError:
            expires_in_seconds = None

    return {
        "host": host,
        "user_email": email,
        "user_sub": sub,
        "access_expiry": expiry_iso,
        "expires_in_seconds": expires_in_seconds,
    }


# --------------------------------------------------------------- whoami formatters
#
# These live in auth.py rather than cli.py so that programmatic callers
# (e.g. agents embedding the client) can reuse them, and so they stay
# covered by the hermetic unit tests.

def format_relative_time(seconds: int) -> str:
    """Human-readable relative-time string.

    Examples
    --------
    ``format_relative_time(2520) -> '42 minutes from now'``
    ``format_relative_time(-300) -> '5 minutes ago'``
    ``format_relative_time(10800) -> 'in 3 hours'``

    Rules:

    - Past / future is expressed with " ago" / " from now" respectively
      for the minute band; "in X hours" for the hours-and-up band
      because the phrasing reads naturally.
    - Granularity: seconds up to 90s, then minutes up to 90 min, then
      hours up to 48h, then days.
    """
    abs_s = abs(seconds)
    if abs_s < 90:
        unit = "second" if abs_s == 1 else "seconds"
        value = abs_s
    elif abs_s < 90 * 60:
        value = int(round(abs_s / 60))
        unit = "minute" if value == 1 else "minutes"
    elif abs_s < 48 * 3600:
        value = int(round(abs_s / 3600))
        unit = "hour" if value == 1 else "hours"
    else:
        value = int(round(abs_s / 86400))
        unit = "day" if value == 1 else "days"

    if seconds < 0:
        return f"{value} {unit} ago"
    # Use "in X hours/days" phrasing for larger intervals; "X minutes
    # from now" for the tight-near-future band. Both sound natural.
    if abs_s < 90 * 60:
        return f"{value} {unit} from now"
    return f"in {value} {unit}"


def format_whoami_human(info: dict[str, Any]) -> str:
    """Render a :func:`whoami` dict as the three-line human format.

    Labels padded to align values at column 10 (``Host:    ``,
    ``User:    ``, ``Expires: ``).
    """
    host = info.get("host", "")
    email = info.get("user_email") or "(unknown)"
    sub = info.get("user_sub") or "(unknown)"
    expiry_iso = info.get("access_expiry")
    expires_in = info.get("expires_in_seconds")

    if expiry_iso:
        try:
            expiry_dt = _parse_expiry_iso(expiry_iso)
            expiry_abs = expiry_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            expiry_abs = expiry_iso
    else:
        expiry_abs = "(unknown)"

    if isinstance(expires_in, int):
        rel = format_relative_time(expires_in)
        if expires_in <= 0:
            expires_line = f"{expiry_abs} ({rel}, EXPIRED)"
        else:
            expires_line = f"{expiry_abs} ({rel})"
    else:
        expires_line = expiry_abs

    return (
        f"Host:    {host}\n"
        f"User:    {email} ({sub})\n"
        f"Expires: {expires_line}"
    )


def format_whoami_json(info: dict[str, Any]) -> str:
    """Render a :func:`whoami` dict as the ``--json`` output shape.

    Shape: ``{"host", "user", "sub", "expires"}`` (flattened for
    scripting convenience; matches the brief).
    """
    payload = {
        "host": info.get("host"),
        "user": info.get("user_email"),
        "sub": info.get("user_sub"),
        "expires": info.get("access_expiry"),
        "expires_in_seconds": info.get("expires_in_seconds"),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


__all__ = [
    # exceptions
    "AuthError",
    "KeyringBackendUnavailable",
    # stores
    "KeyringStore",
    "KeyringStoreProtocol",
    "InMemoryKeyringStore",
    # main operations
    "discover_config",
    "login",
    "logout",
    "get_access_token",
    "whoami",
    # helpers
    "resolve_host",
    "write_default_host",
    "format_keyring_error",
    "format_relative_time",
    "format_whoami_human",
    "format_whoami_json",
    "decode_jwt_unverified",
    # constants
    "KEYRING_SERVICE",
    "LOOPBACK_PORT_CANDIDATES",
    "REFRESH_THRESHOLD_SECONDS",
    "SLOT_REFRESH_TOKEN",
    "SLOT_ACCESS_TOKEN",
    "SLOT_ACCESS_EXPIRY",
    "DEFAULT_HOST_CONFIG_PATH",
]
