# Step 1: Shared helper module — scripts/ariadne_client.py

**Context:** Read `DAVE_BULK_SCOPE.md` for the full plan. This is step 1 of 3.

## What to build

A Python module that CLI scripts can import to talk to Ariadne Core's REST API. Handles auth, URL resolution, rate limit retries, and error handling in one place so individual scripts stay small.

**File:** `ariadne-core/scripts/ariadne_client.py` (new)

## Required capabilities

### 1. Config resolution

Read the API key and server URL without requiring env vars to be pre-set:

- **Server URL**: read from the nearest `.mcp.json`. Search cwd, then parent directories up to 3 levels. Parse the JSON, find the first `mcpServers.*.url`, strip `/mcp` suffix to get the base URL.
- **API key**: read from the nearest `.env`. Same search path. Look for `ARIADNE_API_KEY`.

Both must be found or the script exits with a clear error message. No fallback to environment variables — the .env is the source of truth.

### 2. HTTP client

A class `AriadneClient` with methods:

- `upload_file(local_path: Path) -> str` — POSTs to `/api/upload`, returns the server-side path. Uses multipart/form-data.
- `convert_document(uri, store=True, collection="default", tags=None, agent_metadata=None, agent_notes=None) -> dict` — POSTs to `/api/documents`. Returns the full response dict.
- `list_collections() -> list[dict]` — GET `/api/collections`
- `delete_document(document_id: str) -> dict` — DELETE `/api/documents/{id}`
- `get_stats() -> dict` — GET `/api/stats`

All methods include the `X-API-Key` header automatically.

### 3. Retry logic

For HTTP 429 (rate limit) and 503 (overloaded):
- Up to 5 retries (more than the embedder's 3, since bulk ops can afford to wait)
- Exponential backoff: 5s, 10s, 20s, 40s, 60s
- Parse the `retryDelay` hint from response bodies when available
- Log each retry to stderr so the user sees progress

For other errors (400, 401, 404, 5xx):
- Raise an exception with the status code and response body

### 4. Timeout handling

Default timeout of 120 seconds per request. Override via constructor parameter.

## Interface

```python
from ariadne_client import AriadneClient

client = AriadneClient()  # auto-discovers URL and key from .mcp.json + .env
# Or explicit:
client = AriadneClient(base_url="https://...", api_key="...")

server_path = client.upload_file(Path("document.pdf"))
result = client.convert_document(
    uri=server_path,
    collection="initial_batch",
    tags=["type:report"],
    agent_metadata={"source_reference": "doi:..."},
)
print(result["document_id"])
```

## Don't do

- Don't use the `requests` library if it's not already a dependency — use `urllib` from the stdlib. Check existing scripts to see what they use. Keep dependencies minimal.
- Don't build a CLI in this file. This is a library module, imported by other scripts. No `if __name__ == "__main__"` block except maybe a tiny smoke test.
- Don't hardcode retry counts or timeouts. Make them constructor parameters with sensible defaults.
- Don't cache the client, the URL, or the key at module level. Instantiate fresh in each script.

## Do not commit

Report when done. Leave for Bob.
