# Client Package Build — Step Plan

**Goal:** Build `ariadne-core-client`, a pip-installable Python package that wraps the REST API. Lives at `ariadne-core/client/`. Zero dependencies beyond stdlib. Provides both a Python API (`AriadneClient`) and a CLI (`ariadne` command).

**Source of truth:** `SPEC.md` → "Client package" section (lines 531-649) and "REST API" section (lines 192-528).

## Package layout

```
client/
├── pyproject.toml              # package metadata, [project.scripts] for CLI
├── README.md                   # short usage doc
└── src/
    └── ariadne_core_client/
        ├── __init__.py         # re-exports AriadneClient + exceptions + dataclasses
        ├── client.py           # AriadneClient class — all methods
        ├── models.py           # dataclasses: Document, SearchResult, Collection, Stats, Health, etc.
        ├── exceptions.py       # AriadneClientError, AriadneAuthError, AriadneNotFoundError, AriadneServerError
        ├── credentials.py      # credential resolution (env vars, .env, .mcp.json)
        ├── _http.py            # low-level HTTP using urllib.request (no deps)
        └── cli.py              # CLI entry point: `ariadne` command
```

Uses `src/` layout so the package is properly isolated during development. Import: `from ariadne_core_client import AriadneClient`.

## Steps (one Dave instruction per step, Bob review after each)

### Step 1 — Scaffolding + `pyproject.toml` + exceptions + models

Create the directory structure and these files:

**`client/pyproject.toml`:**
- `name = "ariadne-core-client"`
- `version = "0.1.0"`
- `requires-python = ">=3.10"`
- `dependencies = []` (zero deps)
- `[project.scripts]` → `ariadne = "ariadne_core_client.cli:main"`
- Author: Denson Smith
- License: Apache-2.0
- Build backend: hatchling with `src/` layout

**`client/src/ariadne_core_client/exceptions.py`:**
- `AriadneClientError(Exception)` — base, has `status_code`, `message`, `request_info`
- `AriadneAuthError(AriadneClientError)` — 401/403
- `AriadneNotFoundError(AriadneClientError)` — 404
- `AriadneServerError(AriadneClientError)` — 5xx

**`client/src/ariadne_core_client/models.py`:**
- Dataclasses: `Document`, `SearchResult`, `SearchResponse`, `Collection`, `Stats`, `Health`, `UploadResult`, `IngestSummary`
- Each with `__repr__` that doesn't dump huge content (truncate markdown to ~100 chars)
- `Document` fields match `POST /api/documents` response: `document_id`, `source_file`, `title`, `file_type`, `engine`, `content_fingerprint`, `collection`, `chunks_count`, `was_dedup_skip`, `markdown`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `token_savings`, `embedding_model`, `store_status`, `interactions`, `provenance`
- `SearchResult` fields match each item in search results array: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, `interactions`
- `Health` fields: `status`, `version`, `engine`, `embedding_enabled`
- `Stats` fields: `total_documents`, `total_chunks`, `total_collections`, `embedding_enabled`, `collections`
- `Collection` fields: `name`, `description`, `document_count`

**`client/src/ariadne_core_client/__init__.py`:**
- Re-export `AriadneClient` (will be added in step 3), all exceptions, all model classes

**Test:** `pip install -e client/` then `python -c "from ariadne_core_client import AriadneClientError, Document, Health"` — should work.

---

### Step 2 — Credential resolution + HTTP layer

**`client/src/ariadne_core_client/credentials.py`:**
- `resolve_credentials(url=None, api_key=None) -> tuple[str, str | None]`
- Resolution order per spec:
  1. Explicit params (passed in)
  2. `ARIADNE_URL` and `ARIADNE_API_KEY` env vars
  3. `.env` file — walk up from cwd looking for `.env`, parse `KEY=VALUE` lines
  4. `.mcp.json` — extract URL from ariadne server config (legacy)
- Raises `AriadneClientError` if no URL can be resolved
- Never prints/logs/exposes credentials

**`client/src/ariadne_core_client/_http.py`:**
- Uses only `urllib.request` — zero external deps
- `request(method, url, headers, body=None, timeout=60) -> HTTPResponse` wrapper
- `json_request(method, url, headers, json_body, timeout) -> dict` — serializes JSON, parses response
- `multipart_upload(url, headers, filepath, field_name="file", timeout=120) -> dict` — builds multipart/form-data by hand
- Maps HTTP errors to the right exception class:
  - 401/403 → `AriadneAuthError`
  - 404 → `AriadneNotFoundError`
  - 5xx → `AriadneServerError`
  - Other errors → `AriadneClientError`
- Parses the server's error format: `{"detail": {"message": "..."}}`

**Test:** `python -c "from ariadne_core_client.credentials import resolve_credentials; from ariadne_core_client._http import json_request"` — should import clean.

---

### Step 3 — `AriadneClient` class (all 15 methods)

**`client/src/ariadne_core_client/client.py`:**

The main class. Constructor:
```python
AriadneClient(
    url=None,           # resolved via credentials.py
    api_key=None,       # resolved via credentials.py
    agent_type=None,    # default caller metadata
    initiated_by=None,
    model=None,
    timeout=60,
)
```

15 methods matching the spec's method summary table:

| Method | HTTP | Notes |
|--------|------|-------|
| `health()` | `GET /api/health` | Returns `Health` dataclass. No auth. |
| `ingest_url(url, collection, tags, source, agent_notes, agent_metadata, chunking_config, force)` | `POST /api/documents` | Sets `uri=url`. Auto-sets `source_reference` from URL if `source` not given. Returns `Document`. |
| `ingest_file(path, collection, tags, source, agent_notes, agent_metadata, chunking_config, force)` | `POST /api/upload` then `POST /api/documents` | Uploads file, then converts. Does NOT auto-set source. Returns `Document`. |
| `ingest_bytes(content, filename, collection, tags, source, agent_notes, agent_metadata, chunking_config, force)` | `POST /api/upload` then `POST /api/documents` | Writes content to temp file, uploads, converts. Does NOT auto-set source. Returns `Document`. |
| `search(query, collection, top_k, filters, include_deleted, agent_notes, agent_metadata)` | `POST /api/search` | Returns `SearchResponse` (has `.results` list of `SearchResult`). |
| `get_document(document_id, include_chunks, include_interactions)` | `GET /api/documents/{id}` | Returns `Document`. |
| `list_documents(collection, file_type, limit, offset, include_deleted)` | `GET /api/documents` | Returns list of `Document` (metadata only). |
| `list_collections()` | `GET /api/collections` | Returns list of `Collection`. |
| `create_collection(name, description)` | `POST /api/collections` | Returns `Collection`. |
| `update_document(document_id, tags, collection, agent_metadata, agent_notes)` | `PATCH /api/documents/{id}` | Returns dict with `updated_fields`. |
| `delete_document(document_id, agent_notes)` | `DELETE /api/documents/{id}` | Returns dict with status. |
| `restore_document(document_id, agent_notes)` | `POST /api/documents/{id}/restore` | Returns dict with status. |
| `delete_collection(name, agent_notes)` | `DELETE /api/collections/{name}` | Returns dict. |
| `restore_collection(name, agent_notes)` | `POST /api/collections/{name}/restore` | Returns dict. |
| `stats()` | `GET /api/stats` | Returns `Stats`. |

All methods that accept caller metadata should merge the instance defaults (`agent_type`, `initiated_by`, `model`) with per-call overrides.

The `source` convenience parameter: if provided, inject into `agent_metadata["source_reference"]`.

Update `__init__.py` to re-export `AriadneClient`.

**Test:** `python -c "from ariadne_core_client import AriadneClient; c = AriadneClient(url='http://localhost:8000', api_key='test'); print(c)"` — should construct without error (no server call).

---

### Step 4 — CLI

**`client/src/ariadne_core_client/cli.py`:**

Uses only `argparse` (stdlib). Entry point: `ariadne` command.

Subcommands per spec:
- `ariadne ingest <path-or-url> --collection --tags --recursive --manifest --source --dry-run`
  - If path is a URL (starts with http), use `client.ingest_url()`
  - If path is a directory, iterate files (with `--recursive`) calling `client.ingest_file()` for each, with progress output
  - If path is a file, use `client.ingest_file()`
  - `--manifest` reads a JSONL file for per-file metadata (basic implementation — read lines, match by filename)
- `ariadne search <query> --collection --top-k --filters`
- `ariadne list-documents --collection --file-type --limit`
- `ariadne list-collections`
- `ariadne stats`
- `ariadne health`

Output: human-readable by default, `--json` flag for raw JSON.

**Test:** `ariadne health --help` should show usage. `ariadne health` against a running server should print status.

---

### Step 5 — Monorepo housekeeping + README

1. **`client/README.md`** — Short usage doc (installation, quick start, method list). Author: Denson Smith.

2. **`client/.gitignore`** — Standard Python ignores (`__pycache__`, `*.egg-info`, `dist/`, `build/`)

3. **Root `.gitignore`** — Add `client/dist/`, `client/build/`, `client/*.egg-info` if not already covered.

4. **Root `CLAUDE.md`** — Add a note under "Running locally" that the client package is at `client/` and can be installed with `pip install -e client/`.

5. **Verify full round-trip** (if server is available): install client, run `ariadne health`, ingest a test file, search for it, delete it.

---

## Constraints for every step

- **Zero external dependencies.** Only Python stdlib. `urllib.request` for HTTP, `json` for parsing, `argparse` for CLI, `dataclasses` for models. No `requests`, no `httpx`, no `click`.
- **Author is Denson Smith** in `pyproject.toml` and README. Not anyone else.
- **Import path:** `from ariadne_core_client import AriadneClient` — underscores in Python, hyphens in pip.
- **All behavior matches SPEC.md.** If there's ambiguity, the spec wins.
