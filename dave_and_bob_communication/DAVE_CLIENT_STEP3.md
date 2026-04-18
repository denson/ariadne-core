# Step 3: AriadneClient class — all 15 methods

**For:** Dave  
**Context:** Read `DAVE_CLIENT_PACKAGE_PLAN.md` for the full plan. Steps 1-2 created the models, exceptions, credentials, and HTTP layer. This step builds the main `AriadneClient` class.

---

## File: `client/src/ariadne_core_client/client.py`

Create this file with the `AriadneClient` class. It uses the credentials and HTTP modules from step 2, and returns the model dataclasses from step 1.

### Constructor

```python
class AriadneClient:
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        agent_type: str | None = None,
        initiated_by: str | None = None,
        model: str | None = None,
        timeout: int = 60,
    ):
```

- Resolve `url` and `api_key` via `credentials.resolve_credentials(url, api_key)`
- Store `agent_type`, `initiated_by`, `model` as instance defaults
- Store `timeout`
- Build a base headers dict: `{"X-API-Key": api_key}` if api_key, else empty

### Helper: `_caller_metadata(**overrides) -> dict`

Merges instance defaults with per-call overrides. Returns a dict with keys `agent_type`, `agent_type`, `model`, `initiated_by` — only including keys that have non-None values. Per-call values override instance defaults.

### Helper: `_handle_source(source, agent_metadata) -> dict`

If `source` is provided, inject it into `agent_metadata["source_reference"]`. Returns the (possibly new) `agent_metadata` dict.

### 15 Methods

Implement all 15 methods from the spec. For each method:
- Build the request using `_http.json_request` or `_http.multipart_upload`
- Merge caller metadata into the request body
- Parse the response into the appropriate model dataclass
- Handle the `source` convenience parameter on ingest methods

Here are the signatures and key behaviors:

#### `health() -> Health`
- `GET /api/health` — no auth header needed
- Returns `Health` dataclass

#### `ingest_url(url, *, collection="default", tags=None, source=None, agent_notes=None, agent_metadata=None, chunking_config=None, force=False) -> Document`
- `POST /api/documents` with `uri=url`
- If `source` is not provided, auto-set `source` to the URL itself (spec says ingest_url auto-sets source)
- Handle `source` → `agent_metadata["source_reference"]`
- Returns `Document` dataclass

#### `ingest_file(path, *, collection="default", tags=None, source=None, agent_notes=None, agent_metadata=None, chunking_config=None, force=False) -> Document`
- Two-step: `POST /api/upload` (multipart) then `POST /api/documents` with returned path
- Does NOT auto-set source (spec says file path is not provenance)
- Returns `Document` dataclass

#### `ingest_bytes(content, filename, *, collection="default", tags=None, source=None, agent_notes=None, agent_metadata=None, chunking_config=None, force=False) -> Document`
- Write `content` (bytes) to a temp file, upload via `POST /api/upload`, then `POST /api/documents`
- Clean up temp file after upload
- Does NOT auto-set source
- Returns `Document` dataclass

#### `search(query, *, collection=None, top_k=5, filters=None, include_deleted=False, agent_notes=None, agent_metadata=None) -> SearchResponse`
- `POST /api/search`
- Parse each result into `SearchResult`, wrap in `SearchResponse`
- Parse `interactions` lists inside each result into `Interaction` dataclasses

#### `get_document(document_id, *, include_chunks=True, include_interactions=True) -> Document`
- `GET /api/documents/{id}?include_chunks=...&include_interactions=...`
- Map response to `Document` dataclass
- The response uses `content_markdown` for the markdown field — map it to `Document.markdown`

#### `list_documents(*, collection=None, file_type=None, limit=20, offset=0, include_deleted=False) -> list[Document]`
- `GET /api/documents?collection=...&limit=...&offset=...`
- Returns list of `Document` (metadata-only — no markdown content)

#### `list_collections() -> list[Collection]`
- `GET /api/collections`
- Returns list of `Collection`

#### `create_collection(name, *, description=None) -> Collection`
- `POST /api/collections`
- Returns `Collection`

#### `update_document(document_id, *, tags=None, collection=None, agent_metadata=None, agent_notes=None) -> dict`
- `PATCH /api/documents/{id}`
- Returns the raw response dict (has `updated_fields`)

#### `delete_document(document_id, *, agent_notes=None) -> dict`
- `DELETE /api/documents/{id}`
- Body is JSON with caller metadata + agent_notes
- Returns dict with `status`

#### `restore_document(document_id, *, agent_notes=None) -> dict`
- `POST /api/documents/{id}/restore`
- Returns dict with `status`

#### `delete_collection(name, *, agent_notes=None) -> dict`
- `DELETE /api/collections/{name}`
- Returns dict

#### `restore_collection(name, *, agent_notes=None) -> dict`
- `POST /api/collections/{name}/restore`
- Returns dict

#### `stats() -> Stats`
- `GET /api/stats`
- Returns `Stats` dataclass

### Response parsing helpers

Create private helpers to parse JSON dicts into dataclasses:

- `_parse_document(data: dict) -> Document` — handles field name mapping (e.g., `content_markdown` → `markdown`, server might use `collection` or `collection_id`), parses `interactions` list into `Interaction` objects
- `_parse_search_result(data: dict) -> SearchResult` — parses interactions
- `_parse_interaction(data: dict) -> Interaction`

These helpers should be tolerant of missing keys (use `.get()` with defaults) since different endpoints return different subsets of fields.

---

## Update `__init__.py`

Uncomment `AriadneClient` in the imports and `__all__`:

```python
from ariadne_core_client.client import AriadneClient
```

Add `"AriadneClient"` to `__all__`.

---

## Verify

```bash
python -c "
from ariadne_core_client import AriadneClient
c = AriadneClient(url='http://localhost:8000', api_key='test')
print(type(c))
print('Methods:', [m for m in dir(c) if not m.startswith('_')])
"
```

Should print the class type and list all 15 public methods (health, ingest_url, ingest_file, ingest_bytes, search, get_document, list_documents, list_collections, create_collection, update_document, delete_document, restore_document, delete_collection, restore_collection, stats).

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`.
