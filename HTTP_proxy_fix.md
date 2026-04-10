# HTTP Proxy Fix — Path Resolution for Streamable HTTP Clients

**Date:** 2026-04-05
**Patch:** 003 (Path Resolution for Streamable HTTP)

---

## Problem

When any MCP client sends `convert_document` with a local file path like `C:\Users\denso\...\report.pdf`, the call fails with "No such file or directory" — because the MCP server runs inside a Docker container that can't see the host filesystem.

### Why the STDIO proxy doesn't help

The Patch 003 spec assumed the STDIO proxy (`mcp_stdio_proxy.py`) runs on the host and has access to local files. In reality, Claude Desktop's config launches it **inside the container** via `docker exec`:

```json
"ariadne-core": {
  "command": "docker",
  "args": ["exec", "-i", "ariadne-core-api-1", "python", "-m", "pipeline", "mcp"]
}
```

The proxy's `is_local_file()` calls `os.path.exists()` — but inside the container, `C:\Users\denso\...` doesn't exist. The check returns `False`, the path passes through unchanged, and MarkItDown fails.

**Bottom line:** Neither STDIO (via `docker exec`) nor Streamable HTTP (port 8080) can resolve local paths. Both run inside Docker.

### The transport diagram

```
CLIENT (Cowork, Claude Code, Cursor)
  Sends: uri = "C:\Users\denso\...\report.pdf"
          │
    ┌─────┴─────────────────────────────────┐
    │                                       │
  STDIO via docker exec              Streamable HTTP (8080)
    │                                       │
    ▼                                       ▼
┌──────────────────────┐         ┌──────────────────────┐
│  mcp_stdio_proxy.py  │         │  mcp_server.py       │
│  Runs IN CONTAINER   │         │  Runs IN CONTAINER   │
│  ❌ Can't see C:\    │         │  ❌ Can't see C:\    │
│  os.path.exists()    │         │  Passes uri straight │
│  returns False       │         │  to MarkItDown       │
└──────────────────────┘         └──────────────────────┘
```

---

## Solution: MCP HTTP Proxy on the Host (Port 8081)

A new Streamable HTTP MCP server that runs **on the host machine** (not in Docker). It:

1. Accepts MCP tool calls from clients on port 8081
2. Detects local file paths with `is_local_file()` (which works because it runs on the host)
3. Uploads local files to the REST API via `POST /api/upload` on port 8000
4. Rewrites the URI to the container path returned by the upload
5. Forwards the request to the REST API on port 8000

### Key design decision: Forward to REST API, not MCP

The original Patch 003 spec had the proxy forwarding to the Streamable HTTP MCP server on port 8080 via JSON-RPC. This doesn't work because:

- Streamable HTTP MCP requires a full session handshake (initialize → notifications/initialized → tool calls)
- Each forwarded call would need its own session management
- The `Accept: application/json, text/event-stream` header requirement adds complexity

The fix: forward to the **REST API on port 8000** instead — the same approach the STDIO proxy uses. The REST API is a simple HTTP POST, no session management needed.

---

## Files Created

### `src/pipeline/path_resolution.py`
Shared module extracted from `mcp_stdio_proxy.py`:
- `is_local_file(uri)` — detects local file paths (not URLs, not `/data/` container paths)
- `upload_file(local_path)` — uploads to `POST /api/upload`, returns container path

### `src/pipeline/mcp_http_proxy.py`
Streamable HTTP MCP server that delegates to the REST API with path resolution. Near-clone of `mcp_stdio_proxy.py` but served over HTTP instead of STDIO.

**Important:** Uses `from typing import Dict, List, Optional` instead of `list[str]`, `dict[str, Any]`, etc. The local MCP SDK (v1.12.2) on Python 3.11 throws `TypeError: issubclass() arg 1 must be a class` when it encounters generic type aliases (like `list[str]`) in `@app.tool()` decorated function signatures. The container's environment handles this fine, but the host's doesn't. Using `typing` imports fixes it.

### `tests/test_path_resolution.py`
Unit tests for `is_local_file()` covering HTTP URLs, container paths, local files, non-existent paths, and `file://` URIs.

## Files Modified

### `src/pipeline/mcp_stdio_proxy.py`
- Removed inline `_is_local_file()` and `_upload_file()` functions
- Added `from pipeline.path_resolution import is_local_file, upload_file`
- Updated call sites: `_is_local_file()` → `is_local_file()`, `_upload_file()` → `upload_file()`
- Cleaned up unused imports (`os`, `sys`, `Path`, `PurePosixPath`, `PureWindowsPath`)

### `src/pipeline/__main__.py`
- Added `mcp-proxy` subcommand
- Added `_run_http_proxy()` function that starts the proxy on port 8081 (configurable via `MCP_PROXY_PORT` env var)
- Updated usage string: `[api|worker|mcp|mcp-proxy]`

### `SPEC.md`
- Added "Transport & Path Resolution Matrix" table after the existing Path Resolution section
- Documents all four transports: STDIO proxy, HTTP proxy (8081), Streamable HTTP direct (8080), REST API (8000)

### `docs/mcp-setup.md`
- Added "Streamable HTTP with Path Resolution (HTTP Proxy)" section
- Setup instructions, how it works, environment variables, troubleshooting

### `docker-compose.yml`
- Added documentation comment explaining the proxy runs on the host, not as a Docker service

### `skills/ariadne-document-intelligence/SKILL.md` (OB1 repo)
- Updated path resolution callout to document three transport options including the HTTP proxy on port 8081

---

## How to Use

### Start the proxy
```bash
cd C:\Users\denso\claude_projects\nate_skills\ariadne-core
python -m pipeline mcp-proxy
```

The proxy listens on `http://127.0.0.1:8081/mcp`.

### Configure Cowork / Claude Desktop
Change the MCP server config from STDIO to Streamable HTTP:

```json
"ariadne-core": {
  "url": "http://localhost:8081/mcp"
}
```

Config file locations:
- **Standard:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Microsoft Store:** `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`

### Requires
- Docker containers running (`docker compose up -d`) — the proxy forwards to port 8000
- Python environment with `mcp`, `requests`, `uvicorn` installed (same deps as the project)

---

## Test Results

### Test 1: STDIO proxy with local path (FAILS)
```
mcp__ariadne-core__convert_document(
  uri="C:\Users\denso\...\sample.txt"
)
→ ERROR: "No such file or directory"
```
The STDIO proxy runs inside Docker via `docker exec`. `os.path.exists()` checks the container filesystem, not the host. The Windows path doesn't exist in the Linux container.

### Test 2: HTTP proxy with local path (SUCCEEDS)
```bash
# Full MCP handshake → convert_document via port 8081
curl -s -X POST http://127.0.0.1:8081/mcp \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
    "name":"convert_document",
    "arguments":{"uri":"C:/Users/denso/.../sample.txt","collection":"test-http-proxy"}
  }}'
```

Result:
```json
{
  "document_id": "b2718949-da5d-4746-a87b-5280dce43e0d",
  "source_file": "32bc6bfd_sample.txt",
  "file_type": "txt",
  "engine": "markitdown",
  "processing_time_ms": 8,
  "collection": "test-http-proxy",
  "was_dedup_skip": false,
  "chunks_count": 2,
  "embedding_model": "text-embedding-3-small",
  "store_status": "stored"
}
```

The proxy detected the local path, uploaded it to the REST API, received the container path (`32bc6bfd_sample.txt`), and forwarded the request. Full pipeline completed: extraction (8ms) → image enrichment (0 images) → embedding (2 chunks, 1.4s) → stored.

---

## Bugs Found & Fixed During Implementation

### 1. `from __future__ import annotations` breaks MCP SDK tool registration

**Symptom:** `TypeError: issubclass() arg 1 must be a class` when the proxy starts.

**Cause:** MCP SDK v1.12.2 inspects function parameter annotations at decoration time. `from __future__ import annotations` (PEP 563) makes all annotations strings. When the SDK evaluates them, `list[str]` becomes a `types.GenericAlias`, not a class, and `issubclass()` chokes.

**Fix:** Removed `from __future__ import annotations` from `mcp_http_proxy.py`. Used `from typing import Dict, List, Optional` with `List[str]`, `Dict[str, Any]` etc. instead of Python 3.10+ generic syntax.

### 2. Forwarding to MCP Streamable HTTP (port 8080) requires session management

**Symptom:** `406 Not Acceptable` and `Missing session ID` errors when the proxy tried to forward tool calls to port 8080.

**Cause:** The original design forwarded via JSON-RPC to the Streamable HTTP MCP server on port 8080. But Streamable HTTP requires: (1) `Accept: application/json, text/event-stream` header, (2) full initialize → notifications/initialized handshake, (3) session ID on every subsequent request.

**Fix:** Changed the proxy to forward to the **REST API on port 8000** instead — simple HTTP POST, no session management. This is the same approach the STDIO proxy uses and is far simpler.

### 3. `_run_mcp()` lost its `main()` call during editing

**Symptom:** The `mcp` subcommand would silently do nothing.

**Cause:** When inserting `_run_http_proxy()` after `_run_mcp()`, the `main()` call at the end of `_run_mcp()` was accidentally removed.

**Fix:** Restored the `main()` call inside `_run_mcp()`.
