#!/usr/bin/env python3
"""MCP authentication helper for Claude Code — keyring-backed Bearer JWT.

Called by Claude Code via ``headersHelper`` at connection time. Resolves
the Ariadne server host (``--host``-equivalent precedence:
``ARIADNE_HOST`` env > ``~/.config/ariadne/default``), then mints an
``Authorization: Bearer <jwt>`` header by calling
:func:`ariadne_core_client.auth.get_access_token`. Tokens come from the
OS keyring after a one-time ``ariadne login``; ``ARIADNE_ACCESS_TOKEN``
is honored as the always-first env-var escape hatch (CI / scheduled
tasks / locked-down workstations / keyring-broken recovery).

Wire shape — Claude Code consumes stdout as a JSON header dict:

  Success → exit 0, stdout = ``{"Authorization": "Bearer <jwt>"}``,
            stderr empty.

  Failure → exit 2 (auth-acquisition) or exit 3 (defensive / unexpected),
            stdout EMPTY (no ``{}``), stderr a single human-readable
            diagnostic with an actionable remediation. The diagnostic
            never contains token material.

Fail-closed-on-IdP — security posture (Pass 3 of epic ariadne--xft).
The legacy ``exit 1 + stdout {}`` shape from the X-API-Key era
(introduced when the server tolerated unauthenticated requests on
some endpoints) is REMOVED. The server now requires Bearer JWT on
every protected endpoint and 401s on missing / invalid bearer; emitting
``{}`` on the absence of credentials would mean Claude Code sends an
unauthenticated request and surfaces an opaque 401 instead of a
diagnostic that names the user action ("run ariadne login"). Exit 2
distinguishes this fail-closed posture from the legacy ``exit 1``
contract for any reader inspecting process output.

Usage in ``.mcp.json``::

    {
      "mcpServers": {
        "ariadne": {
          "type": "http",
          "url": "https://YOUR-DEPLOYMENT.up.railway.app/mcp",
          "headersHelper": "python ariadne-core/scripts/mcp_auth.py"
        }
      }
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# --- import path bootstrapping --------------------------------------------
#
# This script lives at <repo-root>/scripts/mcp_auth.py and depends on
# ``ariadne_core_client.auth``, which lives at
# <repo-root>/client/src/ariadne_core_client/auth.py. When the client
# package is editable-installed (``pip install -e client/``), the import
# below works without ``sys.path`` manipulation. When it is not — for
# example, an operator clones the repo and points Claude Code at this
# script before running ``pip install`` — we fall back to a path append.
#
# The append is unconditional (rather than gated on an ImportError catch)
# because Claude Code's ``headersHelper`` invocation may run in any cwd
# with any PYTHONPATH; injecting this entry costs nothing and removes a
# class of "works on my machine" failure modes. If the dev had editable-
# installed the package, ``ariadne_core_client`` is already importable
# and the appended path is harmless.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLIENT_SRC = _REPO_ROOT / "client" / "src"
if str(_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(_CLIENT_SRC))

from ariadne_core_client import auth  # noqa: E402 — load-bearing path bootstrap above

# Exit codes (documented contract — read by operators tailing process
# output; do not renumber without updating the docstring above).
EXIT_OK = 0
EXIT_AUTH = 2
EXIT_UNEXPECTED = 3


def main() -> int:
    """Resolve host, mint Bearer header, emit JSON to stdout. Fail closed.

    Returns the integer exit code rather than calling :func:`sys.exit`
    directly so the entry point and tests share one path.
    """
    # --- step 1: resolve host -------------------------------------------------
    # ``auth.resolve_host(None)`` walks ``ARIADNE_HOST`` env then
    # ``~/.config/ariadne/default`` (written by ``ariadne login``). Any
    # validation failure (empty file, non-https/non-loopback scheme) raises
    # ``AuthError`` with a message that names the recovery action.
    try:
        host = auth.resolve_host(None)
    except auth.AuthError as exc:
        # ``resolve_host``'s ``AuthError`` message already enumerates the
        # three remediations (--host flag, ARIADNE_HOST env, ariadne
        # login). Pass it through verbatim under the ``ariadne mcp_auth``
        # prefix; do not append a second hint.
        print(f"ariadne mcp_auth: {exc}", file=sys.stderr)
        return EXIT_AUTH

    # --- step 2: acquire access token ----------------------------------------
    # ``auth.get_access_token`` precedence:
    #   1. ``ARIADNE_ACCESS_TOKEN`` env var (always wins; keyring untouched).
    #   2. cached access token with > 60s remaining lifetime.
    #   3. silent refresh via the stored refresh token.
    # Any failure surfaces as ``AuthError`` (no cached refresh / refresh
    # rejected by Auth0 / discovery unreachable) or
    # ``KeyringBackendUnavailable`` (locked / disabled keychain).
    try:
        token = auth.get_access_token(host)
    except auth.KeyringBackendUnavailable as exc:
        # The platform-aware message from ``format_keyring_error`` already
        # ends with the ``ARIADNE_ACCESS_TOKEN`` env-var hatch hint, so we
        # print it verbatim and add the ``ariadne login`` reminder above.
        print(
            f"ariadne mcp_auth: keyring is unreachable for host={host}.\n"
            f"{exc}",
            file=sys.stderr,
        )
        return EXIT_AUTH
    except auth.AuthError as exc:
        # ``AuthError`` from ``get_access_token`` already includes
        # "Run 'ariadne login --host <host>'" when the cause is a missing
        # refresh token, and otherwise names the refresh failure. Pass
        # through verbatim and prefix with the script name for log
        # readability.
        print(
            f"ariadne mcp_auth: {exc}",
            file=sys.stderr,
        )
        return EXIT_AUTH
    except Exception as exc:  # noqa: BLE001 — defensive last-resort
        # ImportError from a broken editable-install, OSError from a
        # disk-full ~/.config write, etc. We name the class so a user can
        # Google it; we deliberately do NOT print the full traceback here
        # because Claude Code surfaces stderr inline and a stack trace
        # adds noise without actionable signal.
        print(
            f"ariadne mcp_auth: unexpected error ({exc.__class__.__name__}): {exc}",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED

    # --- step 3: emit the headersHelper contract on stdout -------------------
    # Claude Code parses stdout as a JSON dict of header name → value.
    # Stdout MUST contain only this JSON object — no trailing log lines,
    # no token material, no reassuring "got it!" prints. The token itself
    # is in the payload, but the payload IS the contract; it never lands
    # in stderr or anywhere else this script writes.
    sys.stdout.write(json.dumps({"Authorization": f"Bearer {token}"}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
