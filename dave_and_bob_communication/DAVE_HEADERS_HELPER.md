# Fix: Use headersHelper for MCP auth — agent never sees the API key

## The problem

`${VARIABLE}` substitution in `.mcp.json` headers is broken (Claude Code issue #6204, closed NOT_PLANNED). We can't put the literal key in `.mcp.json` because agents can read it and leak it (happened twice). We need a third option.

## The solution

Claude Code supports `headersHelper` — a script that runs at connection time and outputs auth headers as JSON to stdout. The agent never sees the key. Claude Code injects the headers at the transport level before the agent touches the request.

## Implementation

### 1. Create the auth helper script

**File:** `ariadne-core/scripts/mcp_auth.py` (new)

```python
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
    # Check cwd first (project root)
    if Path(".env").exists():
        return Path(".env")
    # Check parent directories up to 3 levels
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
    # First check shell environment
    key = os.environ.get("ARIADNE_API_KEY", "")

    # Fall back to .env file
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
```

### 2. Update the setup script to use headersHelper

**File:** `scripts/setup.py`

Find where `.mcp.json` is written. Change from:

```json
{
  "mcpServers": {
    "ariadne-ree": {
      "type": "http",
      "url": "https://..../mcp",
      "headers": {
        "X-API-Key": "${ARIADNE_API_KEY}"
      }
    }
  }
}
```

To:

```json
{
  "mcpServers": {
    "ariadne-ree": {
      "type": "http",
      "url": "https://..../mcp",
      "headersHelper": "python ariadne-core/scripts/mcp_auth.py"
    }
  }
}
```

The `headers` key is removed entirely. The `headersHelper` runs the script which reads from `.env`.

**Important:** The path in `headersHelper` is relative to the project root (where Claude Code is started from), not relative to `.mcp.json`. Since the user starts Claude Code from the project root and the script is at `ariadne-core/scripts/mcp_auth.py`, this path is correct.

### 3. Update .mcp.json.template

**File:** `.mcp.json.template`

```json
{
  "mcpServers": {
    "ariadne-core": {
      "type": "http",
      "url": "https://YOUR-DEPLOYMENT.up.railway.app/mcp",
      "headersHelper": "python ariadne-core/scripts/mcp_auth.py"
    }
  }
}
```

### 4. Remove the ${ARIADNE_API_KEY} approach

Search `setup.py` for any remaining `${ARIADNE_API_KEY}` references in MCP config writing and replace with the `headersHelper` pattern.

## Do not touch

- `src/pipeline/` (server code unchanged — it still validates X-API-Key header)
- SPEC.md, skills, docs

## Do not commit

Report when done. Leave for Bob.
