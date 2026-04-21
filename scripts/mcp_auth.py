#!/usr/bin/env python3
"""MCP authentication helper for Claude Code.

Called by Claude Code via headersHelper at connection time. Reads
ARIADNE_ACCESS_TOKEN from the environment (or from .env in the current
working directory / a few parents) and emits the auth header as JSON
on stdout. The agent never sees this script's output — Claude Code
injects the header at the transport level.

The server accepts OAuth 2.1 Bearer JWTs issued by Auth0 (see
`src/pipeline/auth_oauth.py`). Until the `ariadne login` CLI lands
in ticket `ariadne--xft.5` (which will cache an OS-keyring-backed
refresh token and mint access tokens automatically),
ARIADNE_ACCESS_TOKEN is the env-var escape hatch: obtain a test JWT
from Auth0 dashboard → Applications → your app → Test tab → copy the
access token, and paste it into ARIADNE_ACCESS_TOKEN in your .env.

Usage in .mcp.json:
  "headersHelper": "python ariadne-core/scripts/mcp_auth.py"

Contract (do NOT change — Claude Code relies on it):
  - On success: exit 0 and print a JSON object with the header dict
    `{"Authorization": "Bearer <jwt>"}` to stdout.
  - On no token found: exit 1 and print `{}` to stdout. Claude Code
    interprets this as "skip the auth injection" — useful for local
    dev against a server with auth disabled.
"""
import json
import os
import sys
from pathlib import Path


def find_env_file() -> Path | None:
    """Search for .env starting from cwd, then up."""
    if Path(".env").exists():
        return Path(".env")
    current = Path.cwd()
    for _ in range(3):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        current = current.parent
    return None


def read_token(env_path: Path) -> str:
    """Read ARIADNE_ACCESS_TOKEN from a .env file."""
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == "ARIADNE_ACCESS_TOKEN":
                return v.strip()
    return ""


def main():
    token = os.environ.get("ARIADNE_ACCESS_TOKEN", "")

    if not token:
        env_path = find_env_file()
        if env_path:
            token = read_token(env_path)

    if not token:
        print(json.dumps({}))
        sys.exit(1)

    print(json.dumps({"Authorization": f"Bearer {token}"}))


if __name__ == "__main__":
    main()
