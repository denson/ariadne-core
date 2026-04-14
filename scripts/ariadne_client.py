"""Shared HTTP client for Ariadne Core bulk CLI scripts.

Library module — imported by bulk_ingest.py, bulk_export.py, etc.
Auto-discovers the server URL from the nearest .mcp.json and the API
key from the nearest .env. No CLI in this file.
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT = 120
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF = (5, 10, 20, 40, 60)
SEARCH_PARENTS = 3


class AriadneClientError(Exception):
    """Raised for non-retryable HTTP errors or config failures."""


def _search_upward(filename: str) -> Path | None:
    if Path(filename).exists():
        return Path(filename).resolve()
    current = Path.cwd().resolve()
    for _ in range(SEARCH_PARENTS + 1):
        candidate = current / filename
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _read_base_url_from_mcp_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    for entry in servers.values():
        url = entry.get("url")
        if url:
            if url.endswith("/mcp"):
                url = url[: -len("/mcp")]
            return url.rstrip("/")
    raise AriadneClientError(
        f"No mcpServers.*.url found in {path}"
    )


def _read_api_key_from_env(path: Path) -> str:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "ARIADNE_API_KEY":
            return v.strip().strip('"').strip("'")
    raise AriadneClientError(
        f"ARIADNE_API_KEY not found in {path}"
    )


def discover_config() -> tuple[str, str]:
    """Return (base_url, api_key) by searching for .mcp.json and .env."""
    mcp_path = _search_upward(".mcp.json")
    if not mcp_path:
        raise AriadneClientError(
            "Could not find .mcp.json in cwd or up to 3 parent directories. "
            "Run this from a project directory with .mcp.json present."
        )
    env_path = _search_upward(".env")
    if not env_path:
        raise AriadneClientError(
            "Could not find .env in cwd or up to 3 parent directories. "
            "Ariadne's API key must live in .env alongside .mcp.json."
        )
    base_url = _read_base_url_from_mcp_json(mcp_path)
    api_key = _read_api_key_from_env(env_path)
    return base_url, api_key


class AriadneClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_schedule: tuple[int, ...] = DEFAULT_BACKOFF,
    ):
        if base_url is None or api_key is None:
            discovered_url, discovered_key = discover_config()
            base_url = base_url or discovered_url
            api_key = api_key or discovered_key
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_schedule = backoff_schedule

    # ---------- low-level request ----------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict:
        url = self.base_url + path
        if query:
            url = url + "?" + urllib.parse.urlencode(
                {k: v for k, v in query.items() if v is not None}
            )

        attempt = 0
        while True:
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("X-API-Key", self.api_key)
            req.add_header("Accept", "application/json")
            if content_type:
                req.add_header("Content-Type", content_type)

            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if not raw:
                        return {}
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                status = e.code
                raw = e.read() if hasattr(e, "read") else b""
                body_text = raw.decode("utf-8", errors="replace") if raw else ""

                if status in (429, 503) and attempt < self.max_retries:
                    delay = self._parse_retry_delay(body_text)
                    if delay is None:
                        idx = min(attempt, len(self.backoff_schedule) - 1)
                        delay = self.backoff_schedule[idx]
                    print(
                        f"[ariadne_client] {method} {path} -> {status}, "
                        f"retrying in {delay}s "
                        f"(attempt {attempt + 1}/{self.max_retries})",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue

                raise AriadneClientError(
                    f"{method} {path} failed: HTTP {status} — {body_text[:500]}"
                ) from None
            except urllib.error.URLError as e:
                raise AriadneClientError(
                    f"{method} {path} failed: {e.reason}"
                ) from None

    @staticmethod
    def _parse_retry_delay(body_text: str) -> int | None:
        if not body_text:
            return None
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError:
            return None
        for key in ("retryDelay", "retry_delay", "retry_after"):
            val = data.get(key) if isinstance(data, dict) else None
            if isinstance(val, (int, float)):
                return int(val)
            if isinstance(val, str) and val.isdigit():
                return int(val)
        return None

    # ---------- multipart builder ----------

    @staticmethod
    def _build_multipart(
        local_path: Path,
    ) -> tuple[bytes, str]:
        boundary = "----ariadne" + uuid.uuid4().hex
        mime = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        filename = local_path.name.encode("utf-8")
        file_bytes = local_path.read_bytes()

        preamble = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="'
        ).encode("utf-8") + filename + (
            f'"\r\nContent-Type: {mime}\r\n\r\n'
        ).encode("utf-8")
        trailer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = preamble + file_bytes + trailer
        return body, f"multipart/form-data; boundary={boundary}"

    # ---------- high-level methods ----------

    def upload_file(self, local_path: Path) -> str:
        """POST /api/upload — returns the server-side path string."""
        local_path = Path(local_path)
        if not local_path.exists():
            raise AriadneClientError(f"File not found: {local_path}")
        body, content_type = self._build_multipart(local_path)
        resp = self._request(
            "POST", "/api/upload",
            body=body, content_type=content_type,
        )
        path = resp.get("path") or resp.get("server_path")
        if not path:
            raise AriadneClientError(
                f"/api/upload response missing 'path': {resp}"
            )
        return path

    def convert_document(
        self,
        uri: str,
        store: bool = True,
        collection: str = "default",
        tags: list[str] | None = None,
        agent_metadata: dict | None = None,
        agent_notes: str | None = None,
    ) -> dict:
        """POST /api/documents — convert and (optionally) store a document."""
        payload: dict[str, Any] = {
            "uri": uri,
            "store": store,
            "collection": collection,
        }
        if tags is not None:
            payload["tags"] = tags
        if agent_metadata is not None:
            payload["agent_metadata"] = agent_metadata
        if agent_notes is not None:
            payload["agent_notes"] = agent_notes
        body = json.dumps(payload).encode("utf-8")
        return self._request(
            "POST", "/api/documents",
            body=body, content_type="application/json",
        )

    def list_collections(self) -> list[dict]:
        resp = self._request("GET", "/api/collections")
        if isinstance(resp, list):
            return resp
        return resp.get("collections", [])

    def delete_document(self, document_id: str) -> dict:
        return self._request("DELETE", f"/api/documents/{document_id}")

    def get_stats(self) -> dict:
        return self._request("GET", "/api/stats")


if __name__ == "__main__":
    # Tiny smoke test: discover config and hit /api/stats.
    try:
        client = AriadneClient()
        print(f"base_url: {client.base_url}")
        print(json.dumps(client.get_stats(), indent=2))
    except AriadneClientError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
