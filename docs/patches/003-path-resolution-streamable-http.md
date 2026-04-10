# Patch 003: Path Resolution for Streamable HTTP Clients (Cowork, etc.)

**Status:** Implementation specification

**Resolves:** Local file paths fail when Cowork/Claude Desktop connects via Streamable HTTP (port 8080)

**References:** Patch 002 (documented the behavior without fixing the underlying issue)

---

## Problem Statement

### Symptom

When a client (Cowork, Claude Code, Cursor) connects to Ariadne Core via Streamable HTTP on port 8080 and calls `convert_document` with a local file path like `C:\Users\denso\...\file.pdf`, the call fails:

```
error: "No such file or directory"
```

### Root Cause

The architecture has three transports:

```
┌─────────────────────────────────────────────────────────┐
│  CLIENT (Cowork, Claude Code, Cursor, etc.)             │
│  Sends: uri = "C:\Users\denso\...\report.pdf"          │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
    STDIO transport            Streamable HTTP (8080)
           │                          │
           ▼                          ▼
┌──────────────────────┐   ┌──────────────────────┐
│  mcp_stdio_proxy.py  │   │  mcp_server.py       │
│  Runs on HOST        │   │  Runs in CONTAINER   │
│  ✅ Can see C:\Users\│   │  ❌ Cannot see       │
│  ✅ Has path res     │   │     C:\Users\ paths  │
│  Uploads to REST API │   │  Passes uri straight │
│  (8000)              │   │  to MarkItDown       │
└──────────────────────┘   └──────────────────────┘
```

**Why this happens:**

1. **STDIO proxy** (`mcp_stdio_proxy.py`, lines 34–69) runs on the host machine and has access to the local filesystem. When it receives a local file path, it:
   - Detects the path is local (line 34, `_is_local_file()`)
   - Uploads it to the REST API (line 49, `_upload_file()`)
   - Rewrites the URI to the container path (line 131)
   - Forwards the modified request to the REST API

2. **Streamable HTTP server** (`mcp_server.py`) runs inside the Docker container and has NO access to the host filesystem. When it receives a local path, it passes it directly to MarkItDown (line 78 of `extraction/markitdown.py`), which attempts to open the file and fails because the path doesn't exist in the container.

**The fundamental issue:** A process inside Docker cannot access host paths like `C:\Users\denso\...`. There is no code change inside the container that can fix this. The solution must intercept the request before it enters the container.

### Why the obvious fix doesn't work

**Can we copy `_is_local_file()` and `_upload_file()` into `mcp_server.py`?**

No. Both functions rely on accessing the host filesystem:
- `_is_local_file()` (line 34 of `mcp_stdio_proxy.py`) calls `os.path.exists(uri)` — this checks the host filesystem, not the container's.
- `_upload_file()` (line 49) opens `local_path` with `open(local_path, "rb")` — this reads from the host, which the container can't see.

---

## Solution: MCP HTTP Proxy

The fix is to add a lightweight local proxy that runs on the host machine (not in Docker). This proxy:

1. **Intercepts Streamable HTTP requests** from the client before they reach the container
2. **Detects local file paths** using the same `_is_local_file()` logic from `mcp_stdio_proxy.py`
3. **Uploads local files** to the REST API on the host using `_upload_file()`
4. **Rewrites URIs** to container paths
5. **Forwards the modified request** to the Streamable HTTP server on port 8080

This approach:
- Reuses proven code from `mcp_stdio_proxy.py`
- Makes path resolution transparent to all Streamable HTTP clients
- Doesn't require changes to the container or REST API
- Is completely optional — clients can continue using port 8080 directly if they prefer

---

## Implementation

### Step 1: Extract Shared Path Resolution Module

**File to create:** `src/pipeline/path_resolution.py`

This module is used by both `mcp_stdio_proxy.py` and the new `mcp_http_proxy.py`.

```python
"""Shared path resolution logic for local file uploads.

Both the STDIO proxy and HTTP proxy use this to detect local file paths
and upload them to the REST API before forwarding the request.
"""

import os
from typing import Any, Optional
from pathlib import Path, PurePosixPath, PureWindowsPath

API_BASE = "http://localhost:8000/api"
TIMEOUT = 60


def is_local_file(uri: str) -> bool:
    """Check if a URI is a local file path (not a URL or container path).

    Args:
        uri: The URI to check.

    Returns:
        True if uri is a local file path on the calling system (host or container).
    """
    # URLs — not local
    if uri.startswith(("http://", "https://")):
        return False
    # Already a container path — not local
    if uri.startswith("/data/"):
        return False
    # file:// URI — extract path and check
    if uri.startswith("file://"):
        uri = uri[7:]  # strip scheme
    # If it exists on the host filesystem, it's local
    return os.path.exists(uri)


def upload_file(local_path: str) -> str:
    """Upload a local file to the container via POST /api/upload.

    Args:
        local_path: Path to the file on the host machine.

    Returns:
        The container-internal path to the uploaded file.

    Raises:
        RuntimeError: If the upload fails.
    """
    import requests

    if local_path.startswith("file://"):
        local_path = local_path[7:]

    filename = os.path.basename(local_path)

    with open(local_path, "rb") as f:
        resp = requests.post(
            f"{API_BASE}/upload",
            files={"file": (filename, f)},
            timeout=TIMEOUT,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:500]}")

    return resp.json()["path"]
```

### Step 2: Create MCP HTTP Proxy

**File to create:** `src/pipeline/mcp_http_proxy.py`

This is a Streamable HTTP MCP server that intercepts convert_document calls, resolves local paths, and forwards to the real server on port 8080.

```python
"""MCP HTTP proxy — intercepts convert_document calls to resolve local file paths.

When Streamable HTTP clients (Cowork, Claude Code, Cursor) connect to port 8081,
this proxy:
1. Intercepts convert_document and ingest calls
2. Detects local file paths and uploads them to the REST API
3. Rewrites URIs to container paths
4. Forwards the modified request to the real MCP server on port 8080

All other tool calls (search, get_document, list_documents, list_collections)
pass through unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from mcp.server import FastMCP

from pipeline.path_resolution import is_local_file, upload_file

# Copy the instructions from the main MCP server
from pipeline.mcp_server import app as _original_app

app = FastMCP(
    "ariadne-core",
    instructions=_original_app.instructions,
)

UPSTREAM_URL = "http://localhost:8080/mcp"
TIMEOUT = 120

logger = logging.getLogger("ariadne.http_proxy")


async def _forward_tool_call(tool_name: str, arguments: dict[str, Any]) -> str:
    """Forward a tool call to the upstream Streamable HTTP server.

    Args:
        tool_name: Name of the tool (e.g., "convert_document", "search")
        arguments: Tool arguments as a dict

    Returns:
        JSON string with the tool result
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            UPSTREAM_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        )

    if resp.status_code != 200:
        return json.dumps({
            "error": True,
            "message": f"Upstream proxy error ({resp.status_code}): {resp.text[:500]}"
        }, indent=2)

    result = resp.json()
    if "result" in result:
        return result["result"][0].get("text", json.dumps(result))
    return json.dumps(result, indent=2)


@app.tool()
async def convert_document(
    uri: str,
    store: bool = True,
    collection: str = "default",
    tags: list[str] = [],
    force: bool = False,
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    model: Optional[str] = None,
    initiated_by: Optional[str] = None,
    agent_notes: Optional[str] = None,
    agent_metadata: Optional[dict] = None,
    chunking_config: Optional[dict] = None,
) -> str:
    """Convert a document to clean Markdown optimized for LLM consumption.

    Supports over 20 formats including PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, and more.

    Args:
        uri: file://, http://, https://, or local file path
        store: If true, also chunk, embed, and store in vector DB
        collection: Collection to store in (default: "default")
        tags: Tags to apply to the document
        force: If true, re-process even if fingerprint matches existing document
        agent_id: Caller's identity (e.g., "cowork-session-abc", "ob1-agent-daily")
        agent_type: Client type: "claude-cowork", "claude-code", "ob1", "api", etc.
        model: The LLM model the caller is running (e.g., "claude-sonnet-4-6")
        initiated_by: Human or system identity (e.g., "user:denson")
        agent_notes: Free-text description of context (e.g., "Eval run: testing PDF extraction")
        agent_metadata: Structured JSON metadata from the caller (e.g., eval run details)
        chunking_config: Optional override for chunking parameters (strategy, max_characters, etc.)

    Returns:
        JSON string with extracted Markdown content plus metadata.
    """
    # Resolve local file paths by uploading to the REST API
    if is_local_file(uri):
        try:
            uri = upload_file(uri)
        except RuntimeError as e:
            return json.dumps({
                "error": True,
                "message": f"Failed to upload file: {e}"
            }, indent=2)

    # Forward to upstream server
    arguments: dict[str, Any] = {
        "uri": uri,
        "store": store,
        "collection": collection,
        "tags": tags,
        "force": force,
    }
    if agent_id is not None:
        arguments["agent_id"] = agent_id
    if agent_type is not None:
        arguments["agent_type"] = agent_type
    if model is not None:
        arguments["model"] = model
    if initiated_by is not None:
        arguments["initiated_by"] = initiated_by
    if agent_notes is not None:
        arguments["agent_notes"] = agent_notes
    if agent_metadata is not None:
        arguments["agent_metadata"] = agent_metadata
    if chunking_config is not None:
        arguments["chunking_config"] = chunking_config

    return await _forward_tool_call("convert_document", arguments)


@app.tool()
async def ingest(
    path: str,
    collection: str = "default",
    recursive: bool = True,
    file_types: Optional[list[str]] = None,
    force: bool = False,
    tags: list[str] = [],
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    model: Optional[str] = None,
    initiated_by: Optional[str] = None,
    agent_notes: Optional[str] = None,
    agent_metadata: Optional[dict] = None,
) -> str:
    """Batch-ingest a directory of documents. Processes all supported files and returns a summary.

    Note: The path must be accessible from inside the container. Local host directories
    are NOT auto-mounted. Use a bind mount or /data/ path. See documentation for details.

    Args:
        path: Directory path to scan for documents.
        collection: Collection to store all documents in (default: "default").
        recursive: Recurse into subdirectories (default: true).
        file_types: Filter to specific extensions (e.g., ["pdf", "docx"]). If null, process all supported types.
        force: Re-process documents even if they already exist (dedup override).
        tags: Tags to apply to all documents.
        agent_id: Caller's identity.
        agent_type: Client type.
        model: The LLM model the caller is running.
        initiated_by: Human or system identity.
        agent_notes: Free-text description of context.
        agent_metadata: Structured JSON metadata from the caller.

    Returns:
        JSON string with ingestion summary and per-file results.
    """
    # Note: We do NOT auto-upload directories because:
    # 1. Recursive directory traversal happens inside the container
    # 2. We can't enumerate the host filesystem from the proxy
    # 3. Users should bind mount directories or copy them into /data/

    # Forward to upstream server
    arguments: dict[str, Any] = {
        "path": path,
        "collection": collection,
        "recursive": recursive,
        "force": force,
        "tags": tags,
    }
    if file_types is not None:
        arguments["file_types"] = file_types
    if agent_id is not None:
        arguments["agent_id"] = agent_id
    if agent_type is not None:
        arguments["agent_type"] = agent_type
    if model is not None:
        arguments["model"] = model
    if initiated_by is not None:
        arguments["initiated_by"] = initiated_by
    if agent_notes is not None:
        arguments["agent_notes"] = agent_notes
    if agent_metadata is not None:
        arguments["agent_metadata"] = agent_metadata

    return await _forward_tool_call("ingest", arguments)


@app.tool()
async def search(
    query: str,
    top_k: int = 5,
    collection: Optional[str] = None,
    filters: Optional[dict] = None,
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    model: Optional[str] = None,
    initiated_by: Optional[str] = None,
    agent_notes: Optional[str] = None,
    agent_metadata: Optional[dict] = None,
) -> str:
    """Semantic search over the document knowledge store.

    Args:
        query: Natural language query.
        top_k: Number of results (default 5, max 20).
        collection: Limit search to a collection (default: search all).
        filters: Optional filters (source_file, file_type, etc.).
        agent_id: Caller's identity.
        agent_type: Client type.
        model: The LLM model the caller is running.
        initiated_by: Human or system identity.
        agent_notes: Free-text description of context.
        agent_metadata: Structured JSON metadata from the caller.

    Returns:
        JSON with search results and interaction history.
    """
    arguments: dict[str, Any] = {
        "query": query,
        "top_k": min(top_k, 20),
    }
    if collection is not None:
        arguments["collection"] = collection
    if filters is not None:
        arguments["filters"] = filters
    if agent_id is not None:
        arguments["agent_id"] = agent_id
    if agent_type is not None:
        arguments["agent_type"] = agent_type
    if model is not None:
        arguments["model"] = model
    if initiated_by is not None:
        arguments["initiated_by"] = initiated_by
    if agent_notes is not None:
        arguments["agent_notes"] = agent_notes
    if agent_metadata is not None:
        arguments["agent_metadata"] = agent_metadata

    return await _forward_tool_call("search", arguments)


@app.tool()
async def get_document(
    document_id: str,
    include_chunks: bool = True,
    include_interactions: bool = True,
) -> str:
    """Retrieve the full stored document by ID."""
    arguments: dict[str, Any] = {
        "document_id": document_id,
        "include_chunks": include_chunks,
        "include_interactions": include_interactions,
    }
    return await _forward_tool_call("get_document", arguments)


@app.tool()
async def list_documents(
    collection: Optional[str] = None,
    file_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List documents in the knowledge store."""
    arguments: dict[str, Any] = {
        "limit": min(limit, 100),
        "offset": offset,
    }
    if collection is not None:
        arguments["collection"] = collection
    if file_type is not None:
        arguments["file_type"] = file_type

    return await _forward_tool_call("list_documents", arguments)


@app.tool()
async def list_collections() -> str:
    """List all collections with document counts."""
    return await _forward_tool_call("list_collections", {})
```

### Step 3: Update mcp_stdio_proxy.py

**File to modify:** `src/pipeline/mcp_stdio_proxy.py`

Replace lines 34–69 with imports from the shared module.

**Before (lines 34–69):**
```python
def _is_local_file(uri: str) -> bool:
    """Check if a URI is a local file path (not a URL or container path)."""
    # URLs — not local
    if uri.startswith(("http://", "https://")):
        return False
    # Already a container path — not local
    if uri.startswith("/data/"):
        return False
    # file:// URI — extract path and check
    if uri.startswith("file://"):
        uri = uri[7:]  # strip scheme
    # If it exists on the host filesystem, it's local
    return os.path.exists(uri)


def _upload_file(local_path: str) -> str:
    """Upload a local file to the container via POST /api/upload.

    Returns the container-internal path.
    """
    if local_path.startswith("file://"):
        local_path = local_path[7:]

    filename = os.path.basename(local_path)

    with open(local_path, "rb") as f:
        resp = requests.post(
            f"{API_BASE}/upload",
            files={"file": (filename, f)},
            timeout=TIMEOUT,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:500]}")

    return resp.json()["path"]
```

**After:**
```python
from pipeline.path_resolution import is_local_file, upload_file
```

Then replace all calls to `_is_local_file()` with `is_local_file()` and `_upload_file()` with `upload_file()` in the file (lines 130, 131).

### Step 4: Update __main__.py

**File to modify:** `src/pipeline/__main__.py`

Add a new subcommand `mcp-proxy`.

**Replace the main() function (lines 14–26):**

**Before:**
```python
def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "mcp"

    if command == "api":
        _run_api()
    elif command == "worker":
        _run_worker()
    elif command == "mcp":
        _run_mcp()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m pipeline [api|worker|mcp]")
        sys.exit(1)
```

**After:**
```python
def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "mcp"

    if command == "api":
        _run_api()
    elif command == "worker":
        _run_worker()
    elif command == "mcp":
        _run_mcp()
    elif command == "mcp-proxy":
        _run_http_proxy()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m pipeline [api|worker|mcp|mcp-proxy]")
        sys.exit(1)
```

**Add the new _run_http_proxy() function after _run_mcp() (after line 124):**

```python
def _run_http_proxy() -> None:
    """Start the MCP HTTP proxy with Streamable HTTP transport.

    This proxy runs on the host machine and intercepts convert_document calls
    to resolve local file paths by uploading them to the REST API on port 8000.

    Clients connect to localhost:8081 instead of the container's port 8080.
    All other tool calls (search, get_document, etc.) pass through unchanged.

    Usage:
        python -m pipeline mcp-proxy
    """
    import asyncio
    import logging
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("ariadne.http_proxy")
    logger.info(
        "Starting MCP HTTP proxy on port 8081 "
        "(forwards to Streamable HTTP on port 8080, resolves local paths)"
    )

    from pipeline.mcp_http_proxy import app as http_proxy_app
    import uvicorn

    # Create Streamable HTTP app from FastMCP
    starlette_app = http_proxy_app.streamable_http_app()

    # Run on port 8081 (or from env var)
    import os
    listen_port = int(os.environ.get("MCP_PROXY_PORT", "8081"))

    config = uvicorn.Config(
        starlette_app,
        host="127.0.0.1",
        port=listen_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        logger.info("Proxy stopped")
```

### Step 5: Update Documentation

#### `SPEC.md`

**Add a new section after the existing "Path Resolution" section (after line 304):**

```markdown
### Transport & Path Resolution Matrix

Three transport options, each with different path resolution capabilities:

| Transport | Port | Location | Path Resolution | When to Use |
|-----------|------|----------|-----------------|------------|
| **STDIO proxy** | N/A | Host process | ✅ Auto-uploads local paths | Local development, Claude Desktop |
| **HTTP proxy** | 8081 | Host process | ✅ Auto-uploads local paths | Cowork, recommended for desktop clients |
| **Streamable HTTP (direct)** | 8080 | Container | ❌ URLs and `/data/` paths only | REST API clients, scripting |
| **REST API (direct)** | 8000 | Container | ❌ URLs and `/data/` paths only (or manual upload) | Remote clients, programmatic access |

**Recommendation:** For interactive use (Cowork, Claude Desktop, Cursor), use either STDIO or the HTTP proxy (port 8081). Both auto-resolve local file paths. For scripting or remote access, use the REST API with manual upload or bind mounts.
```

#### `SKILL.md` (OB1 repo)

**Replace the "Path resolution" callout (lines 179–198) with:**

```markdown
   **Path resolution — how file paths work across transports:**

   Ariadne Core runs in a Docker container, so there are three ways to pass documents:

   1. **Local paths with STDIO proxy** (recommended for local agents):
      - Local file paths like `/Users/denson/report.pdf` or `C:\Users\denso\report.pdf`
      - `file://` URIs
      - The STDIO proxy (running on your machine) automatically uploads local files to the container before forwarding the call.
      - **Just pass the path — it works.**

   2. **Local paths with HTTP proxy** (recommended for Cowork, Claude Desktop):
      - If you're using Cowork or Claude Desktop over HTTP MCP, connect to `http://localhost:8081/mcp` instead of `localhost:8080/mcp`.
      - This runs the MCP HTTP proxy on your machine, which auto-resolves local paths like the STDIO proxy does.
      - **Just pass the path — it works.**

   3. **Direct to HTTP MCP or REST API** (container cannot see local paths):
      - If you connect directly to port 8080 or 8000, the container cannot access local file paths (it's isolated inside Docker).
      - Your options:
        - Pass an HTTP/HTTPS URL the container can fetch
        - Upload the file first via `POST /api/upload`, then use the returned path
        - Use a bind mount: configure a directory in `docker-compose.yml` so it's visible inside the container as `/data/shared/`

   **Quick test:** If your `convert_document` calls with local paths work without errors, you're on STDIO or the HTTP proxy. If they fail with "file not found", you're on direct HTTP and need to upload first or use URLs.
```

#### `docs/mcp-setup.md`

**Add a new section on the HTTP proxy after the STDIO section:**

```markdown
## Streamable HTTP with Path Resolution (HTTP Proxy)

### For Cowork and Desktop Clients

If you're using Cowork, Claude Desktop, or another desktop client that connects via HTTP MCP, you can get automatic local file path resolution by running the MCP HTTP proxy.

### Setup

1. **Ensure Ariadne Core is running:**
   ```bash
   docker compose up -d
   ```
   This starts the REST API (port 8000) and Streamable HTTP server (port 8080).

2. **In a second terminal, start the HTTP proxy:**
   ```bash
   python -m pipeline mcp-proxy
   ```
   This starts the proxy on `http://127.0.0.1:8081`.

3. **Configure your client to connect to the proxy:**
   - **Cowork:** Add a custom connector to `http://127.0.0.1:8081/mcp`
   - **Claude Desktop:** Update `claude_desktop_config.json`:
     ```json
     "ariadne-core": {
       "url": "http://127.0.0.1:8081/mcp"
     }
     ```

4. **Test the connection:**
   Call `convert_document` with a local file path on your machine. The proxy will upload it automatically.

### How It Works

The HTTP proxy:
- Runs on your machine (not in Docker)
- Intercepts `convert_document` calls
- Detects local file paths (using the same logic as the STDIO proxy)
- Uploads them to the REST API on port 8000
- Rewrites the URI to the container path
- Forwards the modified call to the Streamable HTTP server on port 8080

This is transparent to the client — it looks like a normal MCP server, but local paths "just work".

### Environment Variables

- `MCP_PROXY_PORT`: Port to listen on (default: 8081)

### Troubleshooting

**Connection refused:**
- Ensure the REST API is running on port 8000: `docker compose ps`
- Ensure the Streamable HTTP server is running on port 8080
- Ensure the proxy is running: `python -m pipeline mcp-proxy`

**Upload fails ("Permission denied"):**
- The proxy runs as the current user. Ensure the file is readable by that user.

**Path resolution not working:**
- Confirm you're connecting to port 8081, not 8080
- Check the proxy logs for upload errors
```

### Step 6: Update docker-compose.yml (Optional)

**Note:** The proxy runs on the host, NOT in Docker. You can optionally add a service definition for convenience, but it's not necessary. Include a comment explaining this.

**Append to the services section (after redis block, before volumes):**

```yaml
  # NOTE: The MCP HTTP proxy runs on the HOST, not in this container.
  # Start it separately with: python -m pipeline mcp-proxy
  # (It's listed here as documentation only.)
  #
  # mcp-proxy:
  #   (Not a service — runs directly on host)
  #   Run with: python -m pipeline mcp-proxy
  #   Listens on: http://127.0.0.1:8081/mcp
```

---

## Verification Steps

### Unit Tests

Add tests for the new path resolution module:

**File:** `tests/test_path_resolution.py`

```python
import tempfile
import os
from pathlib import Path
from pipeline.path_resolution import is_local_file


def test_is_local_file():
    """Test path detection."""
    # HTTP URLs
    assert not is_local_file("https://example.com/file.pdf")
    assert not is_local_file("http://example.com/file.pdf")

    # Container paths
    assert not is_local_file("/data/incoming/file.pdf")

    # Local paths
    with tempfile.NamedTemporaryFile(delete=False) as f:
        local_path = f.name
    try:
        assert is_local_file(local_path)
    finally:
        os.unlink(local_path)

    # Non-existent paths
    assert not is_local_file("/nonexistent/path/file.pdf")

    # file:// URIs
    with tempfile.NamedTemporaryFile(delete=False) as f:
        local_path = f.name
    try:
        assert is_local_file(f"file://{local_path}")
    finally:
        os.unlink(local_path)
```

### Integration Tests

**Test the complete flow:**

1. **Start Ariadne Core:**
   ```bash
   docker compose up -d
   ```

2. **Start the HTTP proxy:**
   ```bash
   python -m pipeline mcp-proxy
   ```

3. **Test via curl:**
   ```bash
   # Call convert_document with a local file path
   curl -X POST http://127.0.0.1:8081/mcp \
     -H "Content-Type: application/json" \
     -d '{
       "jsonrpc": "2.0",
       "id": 1,
       "method": "tools/call",
       "params": {
         "name": "convert_document",
         "arguments": {
           "uri": "/path/to/local/document.pdf",
           "store": true,
           "collection": "default"
         }
       }
     }'
   ```

4. **Expect:** The proxy detects the local path, uploads it to `/api/upload`, rewrites the URI, and forwards to port 8080. The document is extracted successfully.

### Manual Testing with Cowork

1. **Start Docker and the proxy (as above)**
2. **Connect Cowork to `http://localhost:8081/mcp`**
3. **Call convert_document with a Windows path:**
   ```
   uri: C:\Users\denso\claude_projects\docs\report.pdf
   ```
4. **Expect:** Extraction succeeds. Path resolution was automatic.

5. **Test with HTTP URLs:**
   ```
   uri: https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf
   ```
6. **Expect:** URL passes through unchanged. Extraction succeeds.

7. **Test with container paths:**
   ```
   uri: /data/test/sample.txt
   ```
8. **Expect:** Path passes through unchanged. Extraction succeeds (if file exists in container).

---

## What This Patch Changes

### Files Created
- `src/pipeline/path_resolution.py` — Shared module for path detection and upload
- `src/pipeline/mcp_http_proxy.py` — Streamable HTTP proxy with path resolution
- Tests in `tests/test_path_resolution.py`

### Files Modified
- `src/pipeline/mcp_stdio_proxy.py` — Imports path resolution from shared module
- `src/pipeline/__main__.py` — Adds `mcp-proxy` subcommand
- `SPEC.md` — Documents transport & path resolution matrix
- `docs/mcp-setup.md` — Documents how to run the HTTP proxy
- `skills/ariadne-document-intelligence/SKILL.md` (OB1 repo) — Updated path resolution callout
- `docker-compose.yml` — Adds documentation comment (no functional changes)

### Files NOT Changed
- `src/pipeline/mcp_server.py` — Stays as-is, runs in container without path resolution
- `src/pipeline/api/routes.py` — Upload endpoint already works
- `src/pipeline/extraction/markitdown.py` — No changes needed
- Database schema or migrations
- Dockerfile

---

## Backward Compatibility

- All existing clients continue to work unchanged
- STDIO proxy behavior is identical (same code, just refactored into a shared module)
- Direct HTTP MCP (port 8080) and REST API (port 8000) require no changes
- The HTTP proxy is completely optional — clients can continue using port 8080 if they prefer

---

## Related Issues and Patches

- **Patch 001:** Documented search response fields (unrelated to path resolution)
- **Patch 002:** Documented path resolution behavior in SKILL.md (this patch implements the actual fix)

---

## Future Enhancements

1. **Auto-discovery:** Clients could query `/health` to discover available proxies and ports
2. **Proxy chaining:** Multiple proxies could sit in a chain for security/load balancing
3. **Directory watch:** Watch local directories and auto-upload changes (not recommended, complex)
4. **Config file:** Allow proxy to read `.env` for custom ports/endpoints

