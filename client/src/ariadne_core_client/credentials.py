"""Credential resolution for the Ariadne client.

Resolution order (per SPEC.md):
    1. Explicit params passed to resolve_credentials()
    2. ARIADNE_URL / ARIADNE_API_KEY environment variables
    3. .env file, walking up from cwd
    4. .mcp.json file, walking up from cwd (legacy ariadne MCP server config)

Never prints, logs, or exposes credentials.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ariadne_core_client.exceptions import AriadneClientError


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file as simple KEY=VALUE pairs. Ignores malformed lines."""
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _walk_up(start: Path | None) -> list[Path]:
    current = (start or Path.cwd()).resolve()
    return [current, *current.parents]


def _find_env_file(start: Path | None = None) -> Path | None:
    for candidate in _walk_up(start):
        env_path = candidate / ".env"
        if env_path.is_file():
            return env_path
    return None


def _load_mcp_json(start: Path | None = None) -> tuple[str | None, str | None]:
    """Walk up looking for .mcp.json; extract url + X-API-Key from an ariadne server entry."""
    for candidate in _walk_up(start):
        mcp_path = candidate / ".mcp.json"
        if not mcp_path.is_file():
            continue
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, None
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            return None, None

        chosen: dict | None = None
        for name, cfg in servers.items():
            if isinstance(cfg, dict) and isinstance(name, str) and name.lower().startswith("ariadne"):
                chosen = cfg
                break
        if chosen is None:
            for cfg in servers.values():
                if (
                    isinstance(cfg, dict)
                    and isinstance(cfg.get("url"), str)
                    and "ariadne" in cfg["url"].lower()
                ):
                    chosen = cfg
                    break
        if chosen is None:
            return None, None

        url = chosen.get("url") if isinstance(chosen.get("url"), str) else None
        api_key: str | None = None
        headers = chosen.get("headers")
        if isinstance(headers, dict):
            for key, value in headers.items():
                if isinstance(key, str) and key.lower() == "x-api-key" and isinstance(value, str):
                    api_key = value
                    break
        return url, api_key
    return None, None


def _normalize_url(url: str) -> str:
    u = url.strip()
    while u.endswith("/"):
        u = u[:-1]
    if u.endswith("/mcp"):
        u = u[: -len("/mcp")]
    while u.endswith("/"):
        u = u[:-1]
    return u


def resolve_credentials(
    url: str | None = None,
    api_key: str | None = None,
    *,
    search_from: Path | None = None,
) -> tuple[str, str | None]:
    """Resolve (url, api_key) from explicit params, env vars, .env, then .mcp.json.

    Returns (url, api_key). api_key may be None for unauthenticated endpoints
    such as /api/health.

    Raises AriadneClientError if no URL can be resolved.
    """
    resolved_url: str | None = url
    resolved_key: str | None = api_key

    if resolved_url is None:
        resolved_url = os.environ.get("ARIADNE_URL") or None
    if resolved_key is None:
        resolved_key = os.environ.get("ARIADNE_API_KEY") or None

    if resolved_url is None or resolved_key is None:
        env_path = _find_env_file(search_from)
        if env_path is not None:
            env_map = _parse_env_file(env_path)
            if resolved_url is None:
                resolved_url = env_map.get("ARIADNE_URL") or None
            if resolved_key is None:
                resolved_key = env_map.get("ARIADNE_API_KEY") or None

    if resolved_url is None or resolved_key is None:
        mcp_url, mcp_key = _load_mcp_json(search_from)
        if resolved_url is None and mcp_url:
            resolved_url = mcp_url
        if resolved_key is None and mcp_key:
            resolved_key = mcp_key

    if not resolved_url:
        raise AriadneClientError(
            "No Ariadne server URL found. Pass url=... explicitly, or set "
            "ARIADNE_URL in the environment, a .env file, or .mcp.json."
        )

    return _normalize_url(resolved_url), resolved_key
