#!/usr/bin/env python3
"""MCP authentication helper for Claude Code.

Called by Claude Code via headersHelper at connection time.
Reads ARIADNE_API_KEY from .env and outputs the auth header as JSON.
The agent never sees this script's output — Claude Code injects
the header at the transport level.

Usage in .mcp.json:
  "headersHelper": "python ariadne-core/scripts/mcp_auth.py"
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


def read_key(env_path: Path) -> str:
    """Read ARIADNE_API_KEY from a .env file."""
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == "ARIADNE_API_KEY":
                return v.strip()
    return ""


def main():
    key = os.environ.get("ARIADNE_API_KEY", "")

    if not key:
        env_path = find_env_file()
        if env_path:
            key = read_key(env_path)

    if not key:
        print(json.dumps({}))
        sys.exit(1)

    print(json.dumps({"X-API-Key": key}))


if __name__ == "__main__":
    main()
