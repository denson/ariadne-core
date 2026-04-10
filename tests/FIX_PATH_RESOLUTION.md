# FIX: Local File Path Resolution

## ROLE
You are a developer. You will implement local file path resolution so that MCP clients can pass host filesystem paths (e.g., `C:\Users\denso\Documents\report.pdf`) and the container can access the files.

## PROBLEM
When a caller passes a local file path to `convert_document` or `ingest`, the code inside the Docker container tries to open that path — but it doesn't exist inside the container. The container only sees `/data/` (a Docker-managed volume) and `/config/`. HTTP/HTTPS URLs work fine because the container downloads them directly. Local paths fail silently or error.

## SOLUTION: File Upload Endpoint + STDIO Proxy Interception

Two changes:

1. **New REST endpoint** `POST /api/upload` — accepts a multipart file upload, saves it to `/data/incoming/<filename>`, returns the container-internal path.
2. **STDIO proxy intercepts local paths** — before forwarding `convert_document` or `ingest` calls to the REST API, detects local file paths (not `http://`, `https://`, or paths already under `/data/`), uploads the file via `POST /api/upload`, and rewrites the `uri` to the returned container path.

This avoids Docker bind mounts entirely. The STDIO proxy runs on the host, so it can read host files. The REST API runs in the container, so it saves to `/data/incoming/` where the extraction code can reach it.

## IMPLEMENTATION

### Step 1: Add upload endpoint to `src/pipeline/api/routes.py`

Add at the top of the file:
```python
from fastapi import UploadFile, File
import os
import uuid
```

Add a new endpoint BEFORE the document endpoints section:

```python
# ── File upload ─────────────────────────────────────────────────────────────

INCOMING_DIR = "/data/incoming"

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Accept a file upload and save to /data/incoming/.

    Returns the container-internal path for use in subsequent API calls.
    Used by the STDIO proxy to bridge host filesystem to container.
    """
    os.makedirs(INCOMING_DIR, exist_ok=True)

    # Prefix with UUID to avoid collisions
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest = os.path.join(INCOMING_DIR, safe_name)

    contents = await file.read()
    with open(dest, "wb") as f:
        f.write(contents)

    return {"path": dest, "filename": file.filename, "size": len(contents)}
```

### Step 2: Add path detection and upload to `src/pipeline/mcp_stdio_proxy.py`

Add these imports at the top:
```python
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
```

Add a helper function after `API_BASE` / `TIMEOUT` constants:

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

### Step 3: Wire upload into `convert_document` in the STDIO proxy

In the `convert_document` function, BEFORE building the payload, add path resolution:

```python
    # Resolve local file paths by uploading to container
    if _is_local_file(uri):
        uri = _upload_file(uri)
```

This goes right after the docstring and before `payload: dict[str, Any] = {`.

### Step 4: Wire upload into `ingest` in the STDIO proxy

The `ingest` tool currently does NOT exist in the STDIO proxy. Check if it does — if not, add it. The `ingest` tool accepts a `path` parameter (a directory). For directories, the proxy needs to:

1. Walk the directory on the host
2. Upload each file individually
3. Since files are now in `/data/incoming/`, call `convert_document` for each one (or call the REST ingest endpoint with the container path)

**Simpler approach for ingest:** Instead of uploading every file, add a note to the ingest tool's docstring that batch ingest of local directories requires a bind mount (documented separately). For Phase 1, focus on `convert_document` single-file path resolution only.

If `ingest` already exists in the proxy, add a comment noting this limitation. If it doesn't exist, skip it for now.

### Step 5: Update SPEC.md

Add a new section under the existing architecture sections:

```markdown
## Path Resolution

When clients connect via STDIO proxy, local file paths are automatically resolved:

1. Proxy detects that `uri` is a local file path (not http/https, not already a `/data/` path)
2. Proxy uploads the file to `POST /api/upload`
3. Upload endpoint saves to `/data/incoming/<uuid>_<filename>` and returns the container path
4. Proxy rewrites the `uri` to the container path before forwarding to the REST API

HTTP/HTTPS URLs pass through unchanged — the container downloads them directly.

The HTTP MCP server (port 8080) and direct REST API calls do NOT get automatic path resolution.
Callers using those transports must either:
- Pass HTTP/HTTPS URLs
- Use the upload endpoint manually
- Use a bind mount (configure in docker-compose.yml)
```

## VERIFICATION

Run these checks in order:

### 1. Upload endpoint works
```bash
# Create a test file
echo "Hello from host" > /tmp/test_upload.txt

# Upload it
curl -s -F "file=@/tmp/test_upload.txt" http://localhost:8000/api/upload | python3 -m json.tool
```
Expected: `{"path": "/data/incoming/<uuid>_test_upload.txt", "filename": "test_upload.txt", "size": 16}`

### 2. Uploaded file exists in container
```bash
# Get the path from the upload response and check it exists
docker compose exec api ls -la /data/incoming/
```
Expected: the uploaded file is present.

### 3. convert_document works with uploaded path
```bash
# Use the container path from step 1
curl -s -X POST http://localhost:8000/api/documents \
  -H "Content-Type: application/json" \
  -d '{"uri": "/data/incoming/<uuid>_test_upload.txt", "store": false}' | python3 -m json.tool
```
Expected: successful conversion with markdown output.

### 4. STDIO proxy resolves local paths
Use the MCP `convert_document` tool via STDIO with a local file path. The proxy should upload the file automatically and return a successful result. Verify by checking that `/data/incoming/` has a new file.

### 5. HTTP URLs still work
```bash
curl -s -X POST http://localhost:8000/api/documents \
  -H "Content-Type: application/json" \
  -d '{"uri": "https://raw.githubusercontent.com/microsoft/markitdown/main/README.md", "store": false}' | python3 -m json.tool
```
Expected: successful conversion (no regression).

## CONSTRAINTS

- Do NOT add Docker bind mounts to docker-compose.yml
- Do NOT modify the extraction code (markitdown.py) — it already handles local paths fine once the file is accessible
- Upload endpoint requires NO authentication (same as health check) — it's only reachable inside the Docker network or from localhost
- The `_is_local_file` check must not break on Windows paths (backslashes) or file:// URIs
- UUID prefix on filenames prevents collisions when two agents upload files with the same name
- `/data/incoming/` cleanup is a future concern — do not implement cleanup in this fix

## RESULTS

Write results to `tests/FIX_PATH_RESOLUTION_RESULTS.md` with:
- Which files were modified
- Whether each verification step passed
- Any issues encountered
