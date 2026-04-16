# Ariadne Core — Specification

This document describes how Ariadne Core works. It is the source of truth for the README, skills, client package, and all agent instructions. If the code doesn't match this doc, the code is wrong.

---

## What it is

Ariadne Core is an open source document extraction and retrieval pipeline. It takes documents in 20+ formats, produces clean Markdown and vector embeddings, and exposes them via a REST API. Agents and scripts interact with it through the `ariadne-core-client` Python package, which wraps the REST API.

The core value: a 100-page PDF that would consume 50,000-100,000 tokens as raw content becomes 5,000 tokens of clean, searchable Markdown. Documents are chunked, embedded, and stored with full provenance metadata so any agent can find them later.

## Supported formats

Over 20 formats: PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV, HTML, TXT, Markdown, JSON, XML, RTF, EPUB, EML, MSG, ZIP (recursive extraction), Jupyter notebooks (.ipynb), RST, ORG, WAV, MP3, M4A.

Images (JPG, PNG, GIF, JPEG, WEBP) are supported but require a vision API key (`ARIADNE_IMAGE_ENRICHMENT_API_KEY`) for content extraction. Without it, image files are accepted but produce empty output with a warning.

Not supported: scanned PDFs (no text layer), legacy Office (.doc, .ppt), complex layouts with merged cells, BMP, TIFF, HEIC.

## Architecture

Ariadne Core has two components:

1. **Server** — a REST API backed by Postgres + pgvector. Runs on Railway, Fly.io, any Docker host, or any VPS. Handles extraction, chunking, embedding, storage, search, and document lifecycle.

2. **Client** (`ariadne-core-client`) — a pip-installable Python package that wraps the REST API. Agents, scripts, and CI pipelines use this. Zero dependencies beyond stdlib. Provides both a Python API and a CLI (`ariadne` command).

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core server    │
│  ├── REST API            │
│  ├── Postgres + pgvector │
│  ├── MarkItDown          │
│  └── Chunking/Embedding  │
└─────────────────────────┘
         ▲
         │  HTTPS + X-API-Key
         │
┌────────┴─────────────────┐
│  Clients                 │
│  ├── ariadne-core-client │  pip install ariadne-core-client
│  │   ├── Python API      │  from ariadne_core_client import AriadneClient
│  │   └── CLI             │  ariadne ingest, ariadne search, ...
│  ├── Any HTTP client     │  curl, requests, urllib
│  └── Any LLM agent      │  via client package or direct REST
└──────────────────────────┘
```

The server and client live in the same monorepo (`denson/ariadne-core`) as separate Python packages. They never import each other — the REST API is the contract between them.

### Connecting clients

All clients connect to the same HTTPS endpoint. The URL depends on where you deploy (e.g., `https://ariadne-core.up.railway.app`).

All endpoints except `/api/health` require authentication via `X-API-Key` header.

**LLM agents (Claude Code, Cursor, etc.):** Install the client package and use the Python API. The client reads server URL and API key from environment variables or `.env` file.

```bash
pip install ariadne-core-client
# or
uv add ariadne-core-client
```

**Scripts and CI:** Use the client package or call the REST API directly.

**Any HTTP client:** Call the REST API endpoints with `X-API-Key` header. See the REST API section for full endpoint documentation.

### Document input — three paths

The server runs remotely. Local file bytes must be sent over HTTP. There are three ingestion paths, in order of preference:

| Priority | Method | Token cost | When to use |
|----------|--------|-----------|-------------|
| 1st | URL | Zero — server fetches directly | Document is at an HTTP/HTTPS URL |
| 2nd | File path | Zero — client uploads via HTTP | Document is a local file |
| 3rd | Bytes from context | Already paid | File was dropped in chat UI, content already in LLM context |

**Via the client package:**
```python
client = AriadneClient()

# From URL (preferred — server fetches, zero tokens)
doc = client.ingest_url("https://example.com/report.pdf", collection="reports")

# From local file (client uploads, zero tokens)
doc = client.ingest_file("path/to/report.pdf", collection="reports")

# From bytes already in context (tokens already spent)
doc = client.ingest_bytes(content, filename="report.pdf", collection="reports")
```

**Via REST directly** (two-step — prefer the client package which handles this in one call):
1. Upload: `POST /api/upload` with multipart form data, get back a server-side path
2. Convert: `POST /api/documents` with the server-side path as `uri`

**Via CLI:**
```bash
ariadne ingest report.pdf --collection reports
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
```

Never pass raw file bytes through an LLM's context window when you can avoid it. A 6 MB PDF as base64 is ~8 MB, roughly 1.5-2M tokens of payload before any processing. Use `ingest_url` or `ingest_file` instead.

### Self-hosting

Deploy with Docker or any container platform:

```bash
# Railway (recommended)
railway up

# Or any Docker host
docker compose up -d
```

The `docker-compose.yml` runs the application and Postgres together. Environment variables configure API keys and database credentials.

### Authentication

All deployments should enable API key auth:

```yaml
# config/ariadne.yaml
api:
  require_auth: true
```

API keys are stored as SHA-256 hashes on the server. `/api/health` is the only unauthenticated endpoint — all other endpoints require an `X-API-Key` header when auth is enabled.

**Client-side authentication:** The client package resolves credentials in this order:

1. Explicit parameters: `AriadneClient(url="...", api_key="...")`
2. Environment variables: `ARIADNE_URL`, `ARIADNE_API_KEY`
3. `.env` file in current directory or parent directories
4. `.mcp.json` file (extracts URL from ariadne server config — legacy support)

Agents and scripts should set `ARIADNE_URL` and `ARIADNE_API_KEY` in their environment or `.env` file. The client never prints, logs, or exposes credentials.

## Configuration

All configuration is controlled via environment variables. The config file (`config/ariadne.yaml`) interpolates them.

```
DB_PASSWORD=xxxxxxxxxxxx

VISION_API_KEY=sk-proj-your-key-here
VISION_MODEL=gpt-4o-mini
VISION_BASE_URL=https://api.openai.com/v1

EMBEDDING_API_KEY=sk-proj-your-key-here
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_BASE_URL=https://api.openai.com/v1
```

Both API keys can use the same OpenAI key, or you can use different ones to track usage with finer granularity. You can also use any OpenAI-compatible endpoint, including open models — just change the `BASE_URL` and `MODEL` values to match your provider.

### Port Configuration

- **`PORT`** — REST API port (default: `8000`). On Railway, this is set automatically.
- **`MCP_PORT`** — MCP server port (default: `8081`). When `MCP_PORT` equals `PORT`, the server runs in **single-port mode**: MCP is mounted at `/mcp` inside the REST API server, one listener handles everything. When they differ, the server runs in **dual-port mode**: separate listeners on each port.
- **Production (Railway/hosted):** `MCP_PORT` defaults to `PORT` automatically — single-port mode works out of the box. Do not set `MCP_PORT` unless you need dual-port mode. Railway injects `DATABASE_URL_PRIVATE` (internal network, no egress fees) and `DATABASE_URL` (public); the app prefers `DATABASE_URL_PRIVATE` when available.
- **Local development:** Leave defaults (`PORT=8000`, `MCP_PORT=8081`) for dual-port mode. This lets you restart the MCP server independently without bouncing the REST API.

---

## REST API

The REST API is the server's only interface. All endpoints are under `/api/`. All processing is synchronous — the endpoint returns the full result when it completes.

When `require_auth` is enabled, all endpoints except `/api/health` require an `X-API-Key` header. API keys are stored as SHA-256 hashes.

### Endpoint summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check (no auth) |
| `POST` | `/api/upload` | Upload a file, returns server-side path |
| `POST` | `/api/documents` | Convert and store a document |
| `GET` | `/api/documents` | List documents (paginated) |
| `GET` | `/api/documents/{id}` | Get full document by ID |
| `PATCH` | `/api/documents/{id}` | Update document metadata (tags, collection) |
| `DELETE` | `/api/documents/{id}` | Soft-delete a document (48h recovery window) |
| `POST` | `/api/documents/{id}/restore` | Restore a soft-deleted document |
| `POST` | `/api/search` | Semantic search over stored chunks |
| `POST` | `/api/ingest` | Batch directory ingestion (server-side paths) |
| `GET` | `/api/collections` | List all collections |
| `POST` | `/api/collections` | Create a new collection |
| `DELETE` | `/api/collections/{name}` | Soft-delete all documents in a collection |
| `POST` | `/api/collections/{name}/restore` | Restore a soft-deleted collection |
| `GET` | `/api/stats` | System statistics |

---

### Error responses

All endpoints return errors as JSON with this structure:

```json
{"detail": {"message": "Human-readable error description", "document_id": "uuid-if-applicable"}}
```

Common HTTP status codes:
- `400` — Invalid request (missing required fields, malformed JSON)
- `401` — Missing API key
- `403` — Invalid API key
- `404` — Document or collection not found
- `410` — Soft-delete window expired (restore too late)
- `413` — File too large
- `422` — Extraction failed (encoding error, unsupported format, corrupt file)
- `503` — Embedding not configured (search endpoint only)

---

### `GET /api/health`

Health check. No authentication required.

**Response:**
```json
{"status": "healthy", "version": "0.1.0", "engine": "markitdown", "embedding_enabled": true}
```

**Client method:** `client.health()`

---

### `POST /api/upload`

Upload a local file to the server. Returns a server-side path for use with `POST /api/documents`.

**Request:** Multipart form data with `file` field.

```bash
curl -s -X POST "$ARIADNE_URL/api/upload" \
  -H "X-API-Key:$ARIADNE_API_KEY" \
  -F "file=@path/to/document.pdf"
```

**Response:**
```json
{"path": "data/uploads/document.pdf", "filename": "document.pdf", "size_bytes": 38560}
```

Use the `path` value as `uri` in `POST /api/documents`.

---

### `POST /api/documents`

Convert a document to clean Markdown. By default, also chunks, embeds, and stores the result for future search.

**Request body (JSON):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `uri` | string | (required) | HTTP/HTTPS URL or server-side path from `/api/upload` |
| `store` | bool | `true` | Chunk, embed, and store in vector DB. `false` for one-time extraction |
| `collection` | string | `"default"` | Logical namespace. Dedup is scoped per collection |
| `tags` | list[str] | `[]` | Tags applied to the document. Searchable via the `tags` filter |
| `force` | bool | `false` | Re-process even if fingerprint already exists in this collection |
| `chunking_config` | dict | `null` | Override chunking. Keys: `strategy` (`"by_title"`, `"by_page"`, `"fixed_size"`), `max_characters`, `overlap` |
| `agent_id` | string | `null` | Caller identity |
| `agent_type` | string | `null` | Client type (e.g. `"claude-code"`, `"script"`) |
| `model` | string | `null` | LLM model the caller is running |
| `initiated_by` | string | `null` | Human or system identity (e.g. `"user:denson"`) |
| `agent_notes` | string | `null` | Why this action is being taken |
| `agent_metadata` | dict | `null` | Structured metadata (source_url, intent, findings, etc.) |

**Response:** JSON with `document_id`, `source_file`, `title`, `markdown`, `file_type`, `engine`, `content_fingerprint`, `collection`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `embedding_model`, `store_status` (`"stored"` / `"not_stored"` / `"skipped"`), `interactions`.

**Dedup behavior:** If a document with the same content fingerprint already exists in the target collection, extraction/chunking/embedding are skipped. The existing document is returned, and a new `document_interactions` row is recorded. Use `force: true` to re-process.

**Chunking auto-selection:** If no `chunking_config` is provided, the strategy is chosen by file type: `.pptx` -> `by_page`, `.csv`/`.xlsx` -> `fixed_size`, `.txt` with no headings -> `fixed_size` with high overlap, everything else -> `by_title`.

**Image handling:** If the file is an image format and no vision API key is configured, a warning is returned explaining that a vision API key is needed for image content extraction.

---

### `GET /api/documents`

List stored documents. Returns metadata only — use `GET /api/documents/{id}` for full content.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `collection` | string | `null` | Filter to a specific collection |
| `file_type` | string | `null` | Filter by extension (e.g. `pdf`, `docx`) |
| `limit` | int | `20` | Results per page (max 100) |
| `offset` | int | `0` | Pagination offset |
| `include_deleted` | bool | `false` | Include soft-deleted documents |

**Response:** JSON with `total_count`, `documents` array (each: `document_id`, `collection`, `source_file`, `file_type`, `title`, `chunk_count`, `interaction_count`, `created_at`).

---

### `GET /api/documents/{id}`

Retrieve the full stored document by ID. Use after search to get complete content, or to inspect chunks and interaction history.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_chunks` | bool | `true` | Return all chunks with text, section, page info |
| `include_interactions` | bool | `true` | Return all interaction records |

**Response:** JSON with `document_id`, `source_file`, `title`, `file_type`, `engine`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `content_fingerprint`, `collection`, `tags`, `processing_chain`, `content_markdown`, `chunks` array (each: `chunk_id`, `text`, `section`, `page`, `token_count`, `embedding_model`), `interactions` array (each: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`, `action`, `was_dedup_skip`, `created_at`).

---

### `PATCH /api/documents/{id}`

Update metadata on an existing document.

**Request body (JSON):**

| Field | Type | Description |
|-------|------|-------------|
| `tags` | list[str] | Replaces existing tags |
| `collection` | string | Moves document to a different collection |
| `agent_id` | string | Caller identity (recorded in interaction) |
| `agent_type` | string | Client type |
| `initiated_by` | string | Human or system identity |
| `model` | string | LLM model the caller is running |
| `agent_metadata` | dict | Structured metadata |
| `agent_notes` | string | Why this update is being made |

**Response:** JSON with `document_id`, `collection`, `tags`, `agent_metadata` (dict, shallow-merged), `updated_fields` (list of field names that were changed, e.g. `["tags", "collection"]`).

**Client method:** `client.update_document(document_id, tags=None, collection=None)`

---

### `DELETE /api/documents/{id}`

Soft-delete a document. The document is hidden immediately but can be restored within 48 hours. After 48 hours, it is permanently purged (chunks, interactions, and all data cascade-deleted).

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `document_id`, `status: "scheduled_for_deletion"`, `deletion_scheduled_at`.

**Client method:** `client.delete_document(document_id)`

---

### `POST /api/documents/{id}/restore`

Restore a soft-deleted document within the 48-hour window. Returns 410 if the window has passed.

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `document_id`, `status: "restored"`.

**Client method:** `client.restore_document(document_id)`

---

### `POST /api/search`

Semantic search over all stored document chunks. Returns ranked results with source metadata and interaction history.

**Request body (JSON):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | (required) | Natural language search query |
| `top_k` | int | `5` | Number of results (max 20) |
| `collection` | string | `null` | Scope to a specific collection |
| `filters` | dict | `null` | Additional filters (see below) |
| `include_deleted` | bool | `false` | Include soft-deleted documents in results |
| `agent_id` | string | `null` | Caller identity |
| `agent_type` | string | `null` | Client type |
| `model` | string | `null` | LLM model the caller is running |
| `initiated_by` | string | `null` | Human or system identity |
| `agent_notes` | string | `null` | Why this search is being performed |
| `agent_metadata` | dict | `null` | Structured metadata |

**Current filters:**

| Filter key | Type | Behavior |
|------------|------|----------|
| `collection` | string | Match chunks in this collection. Same as the top-level `collection` parameter — either works. If both are provided, the filter value takes precedence. |
| `document_id` | string | Match chunks from a specific document |
| `source_file` | string | Substring match (case-insensitive) against filename |
| `file_type` | string | Exact match against extension. Both `.pdf` and `pdf` accepted |
| `tags` | list[str] | Match documents with any of these tags (OR logic) |

Unknown filter keys are silently ignored.

**Planned metadata filters** (not yet implemented):

| Filter key | Type | Behavior |
|------------|------|----------|
| `metadata` | dict | JSONB containment match — find documents where `agent_metadata` contains these key-value pairs. Works for nested keys too: `{"nested": {"field": "value"}}` matches documents where `agent_metadata.nested.field == "value"`. |
| `metadata_exists` | list[str] | Find documents that have these keys in `agent_metadata` (regardless of value) |

These will enable queries like "find all documents from project P176874" or "find all documents that have a wb_doc_type field."

**Response:** JSON with `query`, `top_k`, `collection`, `results_count`, `results` array. Each result: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, `interactions` array.

**Requires embedding:** Search only works when an embedding API key is configured. Returns 503 if not.

**Search is approximate (ANN):** Results may vary slightly between identical queries due to HNSW index traversal. For reproducible results, pin document/chunk IDs rather than re-querying.

---

### `POST /api/ingest`

Batch ingestion of files already on the server. Processes all supported files in a server-side directory and returns a summary.

**Request body (JSON):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | (required) | Server-side directory path |
| `collection` | string | `"default"` | Collection for all documents |
| `recursive` | bool | `true` | Recurse into subdirectories |
| `file_types` | list[str] | `null` | Filter to extensions (e.g. `["pdf", "docx"]`). Null = all supported |
| `force` | bool | `false` | Re-process even if fingerprint exists (dedup override) |
| `tags` | list[str] | `[]` | Tags applied to all documents |
| `agent_id` | string | `null` | Caller identity |
| `agent_type` | string | `null` | Client type |
| `model` | string | `null` | LLM model |
| `initiated_by` | string | `null` | Human or system identity |
| `agent_notes` | string | `null` | Why this ingestion is being done |
| `agent_metadata` | dict | `null` | Structured metadata |

**Response:** JSON with `files_found`, `files_processed`, `files_skipped` (dedup), `files_errored`, `results` array (each: `document_id`, `source_file`, `was_dedup_skip`, `error`).

Processing is synchronous. Files are processed concurrently (up to 4 at a time). For large directories this may take minutes. The endpoint returns the full summary when done.

**Note:** This endpoint only works with server-side paths. For local files, use the client package (`client.ingest_file()`) or the CLI (`ariadne ingest`), which handle upload + conversion automatically.

---

### `GET /api/collections`

List all collections with document counts.

**Response:**
```json
{"collections": [{"name": "world-bank-ree", "description": null, "document_count": 502}]}
```

---

### `POST /api/collections`

Create a new named collection.

**Request body (JSON):**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Collection name |
| `description` | string | Optional description |
| `initiated_by` | string | Who created this collection |

**Response:** JSON with `name`, `description`, `status: "created"`. Returns 409 if collection already exists.

**Client method:** `client.create_collection(name, description=None)`

---

### `DELETE /api/collections/{name}`

Soft-delete all documents in a collection. Each document keeps its own 48-hour recovery window.

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `collection`, `documents_marked` (int — count of documents soft-deleted), `message`.

**Client method:** `client.delete_collection(name)`

---

### `POST /api/collections/{name}/restore`

Restore soft-deleted documents in a collection. Only restores documents within their 48-hour window.

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `collection`, `documents_restored` (int — count of documents restored).

**Client method:** `client.restore_collection(name)`

---

### `GET /api/stats`

System statistics.

**Response:**
```json
{"total_documents": 502, "total_chunks": 124000, "total_collections": 3, "embedding_enabled": true, "collections": {"world-bank-ree": 502, "default": 0}}
```

**Client method:** `client.stats()`

---

## Client package

`ariadne-core-client` is a pip-installable Python package that wraps the REST API. Agents, scripts, and CI pipelines use this to talk to an Ariadne Core server. It lives in the same monorepo as the server (`ariadne-core/client/`).

- **PyPI package:** `ariadne-core-client`
- **Python import:** `from ariadne_core_client import AriadneClient`
- **Zero dependencies** beyond Python stdlib (uses `urllib.request`)
- **Provides both** a Python API and a CLI (`ariadne` command)

### Installation

```bash
pip install ariadne-core-client
# or
uv add ariadne-core-client
# or from the monorepo
pip install git+https://github.com/denson/ariadne-core.git#subdirectory=client
```

### Credential resolution

The client resolves server URL and API key in this order:

1. Explicit params: `AriadneClient(url="...", api_key="...")`
2. Environment variables: `ARIADNE_URL`, `ARIADNE_API_KEY`
3. `.env` file in current directory or parent directories
4. `.mcp.json` file (legacy — extracts URL from ariadne server config)

Never prints, logs, or exposes credentials.

### Default caller metadata

The constructor accepts `agent_type`, `initiated_by`, `model` — applied to every call automatically. Individual calls can override.

```python
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

### Ingestion methods (preference order)

| Priority | Method | Token cost | When to use |
|----------|--------|-----------|-------------|
| 1st | `ingest_url(url)` | Zero — server fetches | Document at an HTTP/HTTPS URL |
| 2nd | `ingest_file(path)` | Zero — client uploads via HTTP | Local file |
| 3rd | `ingest_bytes(content, filename)` | Already paid | File dropped in chat UI |

- `ingest_url()` auto-sets `source` to the URL if not explicitly provided
- `ingest_file()` and `ingest_bytes()` do NOT auto-set source — the file path is not provenance
- After using `ingest_bytes()`, the agent should tell the user: "Next time, give me the file path instead of dropping it — I'll ingest it directly without loading it into our conversation."

### Source convenience parameter

All ingest methods accept an optional `source` string — shortcut for `agent_metadata["source_reference"]`.

```python
client.ingest_file("report.pdf", source="https://documents.worldbank.org/...")
client.ingest_bytes(content, filename="report.pdf", source="gdrive:1BxiMVs...")
```

Provenance hierarchy: DOI > URL > database/API ref > file path > "unknown".

### Method summary

| Method | REST endpoint | Description |
|--------|--------------|-------------|
| `ingest_url(url, ...)` | `POST /api/documents` | Ingest from URL (server fetches) |
| `ingest_file(path, ...)` | `POST /api/upload` + `POST /api/documents` | Upload + convert in one call |
| `ingest_bytes(content, filename, ...)` | `POST /api/upload` + `POST /api/documents` | Store content already in context |
| `search(query, ...)` | `POST /api/search` | Semantic search |
| `get_document(document_id, ...)` | `GET /api/documents/{id}` | Full document retrieval |
| `list_documents(...)` | `GET /api/documents` | Browse documents |
| `list_collections()` | `GET /api/collections` | List collections |
| `create_collection(name, ...)` | `POST /api/collections` | Create a collection |
| `update_document(document_id, ...)` | `PATCH /api/documents/{id}` | Update metadata |
| `delete_document(document_id)` | `DELETE /api/documents/{id}` | Soft-delete |
| `restore_document(document_id)` | `POST /api/documents/{id}/restore` | Undo soft-delete |
| `delete_collection(name)` | `DELETE /api/collections/{name}` | Soft-delete collection |
| `restore_collection(name)` | `POST /api/collections/{name}/restore` | Restore collection |
| `stats()` | `GET /api/stats` | System statistics |
| `health()` | `GET /api/health` | Health check |

### Return types

Return types are dataclasses, not dicts: `Document`, `SearchResult`, `Collection`, `Stats`, `Health`. Sensible `__repr__` that doesn't dump 50KB of markdown.

### Error handling

Errors are exceptions, not error dicts:

- `AriadneClientError` — base exception
- `AriadneAuthError` — 401/403
- `AriadneNotFoundError` — 404
- `AriadneServerError` — 5xx

Each includes the HTTP status code, the server's error message, and the request that caused it.

### CLI

```bash
ariadne ingest report.pdf --collection reports
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
ariadne search "rare earth mining" --collection world-bank-ree --top-k 10
ariadne list-documents --collection world-bank-ree
ariadne list-collections
ariadne stats
ariadne health
```

### Manifest-based ingestion

For corpora with existing metadata (World Bank reports, academic papers, regulatory documents), the CLI's `--manifest` flag attaches per-file provenance during ingestion. Each file is matched to its manifest entry and ingested with the entry's metadata as `agent_metadata`.

Manifest format is adapter-based — each corpus type has its own adapter that reads the native format and produces per-file metadata. The client doesn't enforce a fixed schema on the metadata dict.

---

## Ingesting local files

The MCP `convert_document` tool accepts URIs — HTTP/HTTPS URLs and server-side file paths. For files on the user's local machine:

1. Upload the file via the REST endpoint: `POST /api/upload` (multipart form data, requires `X-API-Key` header).
2. The response includes a `path` field with the server-side location.
3. Pass that path to `convert_document` via MCP (or REST).

Never base64-encode file content into an MCP tool call. The bytes would pass through the LLM's context, which defeats the entire point of the pipeline — a 6 MB PDF becomes ~8 MB of base64, roughly 1.5–2 M tokens of tool-call payload before the server has done any work. Use REST `POST /api/upload` instead.

For batch ingestion of a local directory, the normal pattern is: script the upload of each file against `POST /api/upload`, then call `ingest` on the resulting server-side directory, or call `convert_document` per returned path. A reference helper script is included in the project-specific skills.

---

## Caller metadata

`convert_document`, `search`, and `ingest` accept these optional fields for provenance tracking. `convert_document` and `ingest` create a `document_interactions` row on every call, even dedup skips. `search` creates a `search_log` row on every call.

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Caller's session or workflow identifier (e.g., `"cowork-session-abc"`) |
| `agent_type` | string | Client type: `"claude-cowork"`, `"claude-code"`, `"ob1"`, `"api"`, etc. |
| `model` | string | LLM model powering this session (e.g., `"claude-sonnet-4-6"`) |
| `initiated_by` | string | Human or system identity (e.g., `"user:denson"`) |
| `agent_notes` | string | Free-text context (e.g., the user's prompt that triggered the call) |
| `agent_metadata` | dict | Structured JSON for any additional context (project ID, eval run details, etc.) |

## Metadata Conventions

The caller metadata fields (`agent_notes`, `agent_metadata`, `collection`, `tags`) are intentionally flexible — any agent can write any value. But flexibility without convention produces unsearchable noise. These conventions exist so that metadata written by one agent, in one session, is discoverable and meaningful to a different agent, in a different session, weeks later.

None of these conventions are enforced by the system. They are recommendations. Agents that follow them produce metadata that composes well with search, filtering, and provenance queries. Agents that ignore them still work — their metadata is just harder to use.

### When to use `collection` vs `tags` vs `agent_metadata`

These three fields serve different purposes. Using the wrong one doesn't break anything, but it makes filtering harder.

| Field | Scope | Purpose | Example |
|-------|-------|---------|---------|
| `collection` | Per-document | Broad namespace for a corpus. Dedup is scoped per collection. Search can be scoped to one. | `"quarterly-reports"`, `"legal-contracts"`, `"project-atlas"` |
| `tags` | Per-document | Cross-cutting labels that span collections. Searchable via the `tags` filter (OR logic). | `["pricing", "q1-2026", "reviewed"]` |
| `agent_metadata` | Per-interaction | Structured facts about this specific processing event. JSON with known keys. | `{"intent": "research", "project": "atlas", "status": "extracted"}` |

**`collection`** answers: *what corpus does this document belong to?*
**`tags`** answer: *what cross-cutting categories apply to this document?*
**`agent_metadata`** answers: *why did this agent process this document right now, and what did it find?*

Every document should have a collection. A document in the `"default"` collection is a signal that the agent didn't think about organization — which means future search and filtering are degraded. If you don't know what collection to use, name it after the project, topic, or task.

### Recommended `agent_metadata` keys

`agent_metadata` accepts arbitrary JSON. These conventional keys make metadata written by different agents interoperable:

| Key | Type | Description |
|-----|------|-------------|
| `project` | string | Project name or identifier (e.g., `"atlas"`, `"q4-review"`) |
| `source_url` | string | Where the document was downloaded from, if applicable. Still valid; `source_reference` is preferred going forward. |
| `source_reference` | string | Most authoritative reference to the document's origin: DOI, URL, database/API reference, local file path, or the literal `"unknown"`. See "Source provenance" below. |
| `source_notes` | string | Free-text context about provenance — especially when the source is unknown, ambiguous, or required interpretation. |
| `intent` | string | Why the agent processed this document: `"research"`, `"compliance-review"`, `"onboarding"`, `"reference"`, `"archival"` |
| `findings` | string | Brief summary of what the agent learned from the document |
| `status` | string | Processing state: `"extracted"`, `"reviewed"`, `"needs-follow-up"`, `"superseded"` |
| `related_documents` | list[str] | Document IDs of related items the agent found or was working with |

These keys are recommendations, not a schema. Agents can add any additional keys that make sense for their workflow. The value of following the convention is that another agent can filter or search `agent_metadata` for `intent: "research"` and find documents across sessions and agent types.

### Source provenance

Every document should carry a `source_reference`. This is the most important metadata field for corpus integrity: a document with no recorded origin is unverifiable and uncitable, and a corpus full of unsourced documents quickly becomes noise.

**Default hierarchy** (most authoritative first):

1. **DOI** — for research papers, format as `"doi:10.xxxx/..."`
2. **URL** — the original URL the document was downloaded from (not the server upload path)
3. **Database / API reference** — the query, endpoint, or record ID the document came from
4. **Local file path** — the original filesystem path, when no upstream source exists
5. **`"unknown"`** — explicit, when the agent considered provenance and could not determine it

**Explicit unknown is better than missing.** Setting `"source_reference": "unknown"` (with a `source_notes` explanation) signals that an agent considered provenance and couldn't determine it. A missing field signals that no one tried.

**Backward compatibility.** `source_url` remains valid and readers should accept either key. New code should write `source_reference`; both keys may coexist on the same document.

**Project-specific override.** Project skills (e.g., a cannabis research skill) may override this hierarchy with stricter, domain-specific rules — for example, requiring a DOI for research papers and tagging missing-DOI papers `provenance:no-doi` and `status:needs-review`.

**Worked examples:**

```json
{
  "agent_metadata": {
    "source_reference": "doi:10.1038/s41586-024-07123-4",
    "intent": "research",
    "project": "atlas"
  }
}
```

```json
{
  "agent_metadata": {
    "source_reference": "unknown",
    "source_notes": "User pasted PDF contents into chat with no filename or URL. Asked but they didn't recall where it came from.",
    "intent": "reference"
  }
}
```

### How to write useful `agent_notes`

`agent_notes` is a free-text string. It should help the next agent (or the same agent in a future session) decide whether to re-read this document or skip it.

**Bad:**
```
"processed this file"
```

**Good:**
```
"Extracted for Q1 pricing review. Found 3 tables on revenue projections.
Section 4.2 has the margin breakdown the user asked about."
```

**Good:**
```
"User uploaded during contract negotiation. Key clauses: termination (Section 8),
IP assignment (Section 12), non-compete (Section 15). No unusual terms flagged."
```

The test: if a different agent searches and finds this document six months from now, will the note tell them enough to decide whether it's relevant without re-reading the full content?

### Tag conventions

Tags are free-form strings, but following these conventions makes them composable with search filters:

- **Lowercase, hyphenated:** `"q1-2026"` not `"Q1 2026"`
- **Namespace prefixes for categories:** `"project:atlas"`, `"status:reviewed"`, `"source:email"`, `"dept:legal"`
- **Keep tags searchable:** they compose with the `tags` filter in `search` (OR logic). A tag like `"reviewed"` is useful; a tag like `"reviewed-by-jane-on-tuesday"` is too specific to filter on

Common tag patterns:

| Pattern | Examples | Use case |
|---------|----------|----------|
| Time period | `"q1-2026"`, `"fy-2025"` | Filter documents by business period |
| Status | `"status:reviewed"`, `"status:needs-follow-up"` | Track review workflow |
| Source | `"source:email"`, `"source:slack"`, `"source:upload"` | Filter by how the document arrived |
| Domain | `"legal"`, `"financial"`, `"technical"` | Cross-collection topic filtering |
| Project | `"project:atlas"`, `"project:onboarding"` | When documents span multiple collections but share a project |

### Worked examples

#### 1. Single document extraction — user drags a PDF into chat

The user says: *"Can you look at this quarterly report and tell me about the revenue trends?"*

The agent uploads the file, then calls `convert_document`:

```json
{
  "uri": "/uploads/acme-q1-2026-report.pdf",
  "collection": "acme-financials",
  "tags": ["financial", "q1-2026"],
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-sonnet-4-6",
  "agent_notes": "User asked about revenue trends in Acme Q1 2026 quarterly report. Extracting for analysis.",
  "agent_metadata": {
    "intent": "research",
    "project": "acme-review"
  }
}
```

After extraction, the agent reads the Markdown and answers the user's question. The document is now searchable — if the user asks about Acme financials next week, `search` with `collection: "acme-financials"` will find it.

#### 2. Batch project ingest — agent processes a folder of contracts

The user says: *"Process everything in /data/contracts/ — these are the vendor agreements for Project Atlas."*

The agent calls `list_collections` first to see if a relevant collection exists, then calls `ingest`:

```json
{
  "path": "/data/contracts/",
  "collection": "atlas-vendor-contracts",
  "tags": ["legal", "project:atlas", "vendor"],
  "recursive": true,
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-sonnet-4-6",
  "agent_notes": "Batch ingest of vendor agreements for Project Atlas. User wants all contracts searchable for upcoming negotiation review.",
  "agent_metadata": {
    "intent": "archival",
    "project": "atlas",
    "status": "extracted"
  }
}
```

After ingest completes, the agent reports: *"Processed 23 files (2 skipped as duplicates, 1 failed — password-protected). All are now searchable in the `atlas-vendor-contracts` collection."*

#### 3. Research session — agent searches, reads, and annotates across multiple docs

The user says: *"What do our contracts say about termination clauses? I need to compare across vendors."*

**Step 1 — Search:**

```json
{
  "query": "termination clause early exit penalty",
  "top_k": 10,
  "collection": "atlas-vendor-contracts",
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-sonnet-4-6",
  "agent_notes": "User comparing termination clauses across vendor contracts for Project Atlas.",
  "agent_metadata": {
    "intent": "research",
    "project": "atlas"
  }
}
```

**Step 2 — Deep read:** The agent calls `get_document` on the top results to read full content, then synthesizes a comparison.

**Step 3 — Follow-up search** (narrowing):

```json
{
  "query": "early termination penalty fee 30 days notice",
  "top_k": 5,
  "collection": "atlas-vendor-contracts",
  "filters": { "tags": ["vendor"] },
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-sonnet-4-6",
  "agent_notes": "Narrowing to specific penalty terms after initial comparison. 4 of 10 results had relevant termination clauses; looking for penalty amounts and notice periods.",
  "agent_metadata": {
    "intent": "research",
    "project": "atlas",
    "findings": "Initial search found termination clauses in Vendor A (Section 8), Vendor C (Section 12), Vendor D (Section 6.3), Vendor F (Section 9). Vendor B contract has no termination clause."
  }
}
```

Note how the `agent_notes` and `agent_metadata.findings` evolve across calls — the second search's metadata captures what was learned from the first. A future agent reviewing the search log can reconstruct the research trajectory.

#### 4. Multi-agent handoff — agent A ingests, agent B reviews, agent C answers

This pattern spans multiple sessions. The metadata conventions make it work.

**Agent A (Claude Code) — initial ingest:**

```json
{
  "uri": "https://example.com/reports/safety-audit-2026.pdf",
  "collection": "compliance-audits",
  "tags": ["compliance", "safety", "2026"],
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-opus-4-6",
  "agent_notes": "Ingesting annual safety audit report. Downloaded from compliance portal.",
  "agent_metadata": {
    "intent": "archival",
    "source_url": "https://example.com/reports/safety-audit-2026.pdf",
    "status": "extracted"
  }
}
```

**Agent B (different session, maybe different user) — review and annotate:**

Agent B searches, finds the document, reads it, and then re-processes it with `force: true` to record updated metadata and findings:

```json
{
  "uri": "/uploads/safety-audit-2026.pdf",
  "collection": "compliance-audits",
  "tags": ["compliance", "safety", "2026", "status:reviewed"],
  "force": true,
  "agent_type": "claude-code",
  "initiated_by": "user:sarah",
  "model": "claude-sonnet-4-6",
  "agent_notes": "Reviewed safety audit. 3 critical findings in Sections 4, 7, 11. Remediation deadlines: April 30 (fire suppression), June 15 (ventilation), August 1 (emergency exits). No findings from prior year remain open.",
  "agent_metadata": {
    "intent": "compliance-review",
    "status": "reviewed",
    "findings": "3 critical findings: fire suppression (S4), ventilation (S7), emergency exits (S11). All prior-year findings closed.",
    "related_documents": ["doc-uuid-prior-year-audit"]
  }
}
```

Note: `force: true` re-processes the entire document (re-extraction, re-chunking, re-embedding) just to update the metadata. A metadata-only update would be more efficient — this is a known trade-off, not a bug. The interaction record and its metadata are always created regardless; `force` is needed here only because the agent also wants to update the document-level `tags`.

**Agent C (weeks later) — answering a question:**

A user asks: *"What's the status of our safety compliance?"*

Agent C searches `collection: "compliance-audits"`, finds the document, and sees from the interaction history:
- Agent A ingested it (status: `"extracted"`)
- Agent B reviewed it (status: `"reviewed"`, findings summarized)

Agent C can answer the question using Agent B's findings without re-reading the full document. The `agent_notes` from Agent B's interaction tell Agent C exactly what was found and what the deadlines are.

This is the payoff of metadata conventions: Agent C didn't need to know about Agent A or Agent B. It just searched, found a document with rich interaction history, and used that history to answer the question efficiently.

---

## Dedup

Every document is fingerprinted (SHA-256 on normalized text) before any expensive processing. If the fingerprint already exists in the target collection:

1. Extraction, chunking, and embedding are skipped
2. A `document_interactions` row is still created (recording who asked, when, and why)
3. The existing document is returned to the caller

The `force` flag on `convert_document` and `ingest` overrides this when you know a document has changed.

On a dedup skip, the response includes the existing document's `markdown`, `interactions`, and all metadata fields — the only difference is `was_dedup_skip: true` and no re-processing occurs. Callers always get the full document back.

## Provenance

Every agent call creates a record, even dedup skips. When you search and get a result, you also get the full history of who has touched that document:

- **processing_chain** (on the document) tells you how the content was processed: which extraction tool, which enrichment steps, which embedding model, with timestamps
- **document_interactions** (separate table) tells you who touched it: which agent, which model, when, what action, whether it was a dedup skip, plus `agent_notes` and `agent_metadata`

The `action` field in `document_interactions` uses these canonical values:

| Action | Source | Meaning |
|--------|--------|---------|
| `"convert"` | `convert_document` | Agent deliberately processed a single document via URL or server-side path |
| `"ingest"` | `ingest` | Document was swept up in a batch directory ingestion |
| `"search"` | `search` (in `search_log`) | Query recorded in the search log |

The distinction between `"convert"` and `"ingest"` matters for provenance — knowing whether a document was deliberately processed or swept up in a batch tells you something about intent.

---

## Search Log

Every `search` call is recorded in the `search_log` table. One row per search — not per result. This captures what agents searched for, why, and what they found, so that the full usage history of the knowledge store is preserved alongside the document provenance.

The `search_log` table stores:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `query` | text | The search query |
| `collection` | text | Collection scope (null = all collections) |
| `filters` | JSONB | Filters applied (file_type, source_file, tags, document_id) |
| `top_k` | int | Number of results requested |
| `results_count` | int | Number of results actually returned |
| `result_document_ids` | UUID[] | Document IDs of the results, in rank order |
| `agent_id` | text | Caller's session or workflow identifier |
| `agent_type` | text | Client type |
| `model` | text | LLM model |
| `initiated_by` | text | Human or system identity |
| `agent_notes` | text | Free-text context — what the agent was looking for and why |
| `agent_metadata` | JSONB | Structured JSON — the caller's custom context (project, task, reason, etc.) |
| `created_at` | timestamptz | When the search happened |

The `agent_metadata` field is the key extensibility point. Any agent builder can store whatever structured context they need — project IDs, task descriptions, batch identifiers, client names, filing types — anything that helps them organize and trace their usage of the knowledge store later.

## Collections

Logical namespaces for documents. Dedup is scoped per collection — the same document can exist in multiple collections. Search defaults to all collections but can be scoped to one.

Collections are cheap. Use them to organize by project, topic, or workflow. A messy "everything in default" collection degrades search quality.

---

## Pipeline order

This is the processing sequence for each document. The order matters.

1. Extract document to Markdown (MarkItDown)
2. Content fingerprint (SHA-256 on normalized text) — skip to step 7 on collision (unless `force`)
3. Image enrichment (vision API describes images found in the extracted Markdown)
4. Chunk (auto-selected by file type, configurable)
5. Embed (configurable API)
6. Store in vector DB
7. Record `document_interactions` row (always, even on dedup skip)

---

## Expected agent behavior

This section describes how an agent connected to Ariadne Core should behave. These patterns should be taught via the skill file and enforced via Claude Code project instructions.

### When to use `convert_document` instead of reading files directly

When the agent encounters a document (PDF, DOCX, PPTX, XLSX, or any supported format), it should use `convert_document` instead of trying to read the file directly. The extracted Markdown is cleaner, more token-efficient (often 8-15x smaller than raw content), and gets stored for future search. The only exception is very small text files (under ~10 pages of plain text) where the agent can handle them in context without extraction.

### How to handle local files

Since Ariadne Core runs as a remote service, the agent cannot pass local file paths directly to `convert_document`. When the user references a local file:

1. If the file is available at a URL, pass the URL to `convert_document` directly.
2. Otherwise, upload via `POST /api/upload` first and then call `convert_document` with the returned server-side path. This is the canonical path for local files — the bytes move over HTTP once and never enter the LLM's context.
3. If none of the above apply, tell the user the file needs to be accessible via URL or uploaded to the server first.

### How to choose a collection

The agent should never dump everything into `"default"`. Collection choice follows this logic:

1. If the user specifies a collection name, use it.
2. If the agent is working in a project context (a repo, a research topic, a client engagement), use the project name as the collection. Examples: `"ariadne-core"`, `"q4-research"`, `"acme-contract-review"`.
3. If the user is doing a one-off task with no clear project, use a descriptive name based on the document type or purpose. Examples: `"receipts"`, `"reference-docs"`, `"meeting-notes"`.
4. If none of the above apply, use `"default"` — but this should be rare.

The agent should tell the user which collection it chose and why, so the user can correct it or reuse it later.

### How to use caller metadata

Every call to `convert_document`, `search`, and `ingest` should include caller metadata. This is not optional in practice — the provenance trail is only useful if agents actually populate it.

- `agent_type`: always set. `"claude-cowork"` for Cowork, `"claude-code"` for Claude Code, `"cursor"` for Cursor, etc.
- `initiated_by`: always set when the user identity is known. Format: `"user:name"` (e.g., `"user:denson"`).
- `model`: always set. The model the agent is running on (e.g., `"claude-sonnet-4-6"`).
- `agent_notes`: set on every call. The user's prompt or a brief description of why this action is being taken. This is the most valuable provenance field — it tells future agents and future searches *why* this document was ingested or searched, not just that it was.
- `agent_id`: set when available. The session ID or workflow identifier.
- `agent_metadata`: set when there's structured context worth preserving (project ID, workflow stage, eval run details).

### When to search before answering

If the user asks a question that could be answered by documents they've previously ingested ("what did the report say about...", "find that contract clause about...", "what do we know about X"), the agent should call `search` before attempting to answer. Don't guess from memory — search first, then synthesize an answer from the results.

Use the `collection` parameter or `filters` to narrow search when the context makes it obvious. If the user says "in the research docs" and there's a `"research"` collection, scope the search there.

### When to use `ingest` vs. `convert_document`

- Single file → `convert_document`
- Multiple files already on the server → `ingest`
- The agent should tell the user how many files were found and give a time estimate before starting a large batch

### How to handle errors

- **Zero-byte or corrupt file:** tell the user the file appears damaged
- **Password-protected document:** tell the user to remove the password and retry
- **Unsupported format:** tell the user which formats are supported and suggest alternatives
- **Image with no vision API key:** the tool returns a warning — the agent should relay it and suggest configuring `VISION_API_KEY`
- **Embedding not configured:** search returns an error — the agent should explain that an embedding API key is needed for search
- **Service unreachable:** suggest checking that the Ariadne Core deployment is running and the URL is correct

### Open Brain bridge pattern (when OB1 is available)

After ingesting a document through Ariadne Core, the agent should capture a summary thought in Open Brain so the document becomes discoverable through normal brain search. The thought contains:

- **content**: 2-4 sentence summary of the document
- **metadata**: `source: "ariadne-core"`, `ariadne_document_id`, `ariadne_collection`, `source_file`, `file_type`, and `user_prompt` (the user's original request — this is the default "note" that gives future agents context about why the document was stored)

The thought is a pointer and summary, not a copy. Ariadne handles the heavy content; Open Brain handles the memory graph. Search works both ways: broad recall through Open Brain (thoughts + document summaries), precise retrieval through Ariadne (chunk-level matches).
