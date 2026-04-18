# Task: Add Client Package section to SPEC.md (Step 3)

**For:** Dave

Read `ARIADNE_CLIENT_PLAN.md` in the ariadne-core-workspace (one level up from the repo) for the full client design. That plan is the source — extract from it, don't invent.

---

## What to do

Add a new `## Client package` section to `ariadne-core/SPEC.md` immediately after the REST API section ends (after the `GET /api/stats` endpoint and its `---` divider, before `## Ingesting local files`).

This section describes `ariadne-core-client` — what it is, how to install it, how agents use it. The spec is the target (describes what we're building), so write it as if the package exists.

## Content to include

### 1. What it is

- `ariadne-core-client` — pip-installable Python package wrapping the REST API
- PyPI package name: `ariadne-core-client`
- Python import: `from ariadne_core_client import AriadneClient`
- Zero dependencies beyond Python stdlib (uses `urllib.request`)
- Provides both a Python API and a CLI (`ariadne` command)
- Lives in the same monorepo as the server (`ariadne-core/client/`)

### 2. Installation

```bash
pip install ariadne-core-client
# or
uv add ariadne-core-client
# or from the monorepo
pip install git+https://github.com/denson/ariadne-core.git#subdirectory=client
```

### 3. Credential resolution

The client resolves server URL and API key in this order:
1. Explicit params: `AriadneClient(url="...", api_key="...")`
2. Environment variables: `ARIADNE_URL`, `ARIADNE_API_KEY`
3. `.env` file in current directory or parent directories
4. `.mcp.json` file (legacy — extracts URL from ariadne server config)

Never prints, logs, or exposes credentials.

### 4. Default caller metadata

Constructor accepts `agent_type`, `initiated_by`, `model` — applied to every call automatically. Individual calls can override.

```python
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

### 5. Three ingestion methods (preference order)

| Priority | Method | Token cost | When to use |
|----------|--------|-----------|-------------|
| 1st | `ingest_url(url)` | Zero — server fetches | Document at an HTTP/HTTPS URL |
| 2nd | `ingest_file(path)` | Zero — client uploads via HTTP | Local file |
| 3rd | `ingest_bytes(content, filename)` | Already paid | File dropped in chat UI |

- `ingest_url()` auto-sets `source` to the URL if not explicitly provided
- `ingest_file()` and `ingest_bytes()` do NOT auto-set source — the file path is not provenance
- After using `ingest_bytes()`, the agent should tell the user: "Next time, give me the file path instead of dropping it — I'll ingest it directly without loading it into our conversation."

### 6. Source convenience parameter

All ingest methods accept an optional `source` string — shortcut for `agent_metadata["source_reference"]`.

```python
client.ingest_file("report.pdf", source="https://documents.worldbank.org/...")
client.ingest_bytes(content, filename="report.pdf", source="gdrive:1BxiMVs...")
```

Provenance hierarchy: DOI > URL > database/API ref > file path > "unknown".

### 7. Full method summary table

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

### 8. Return types

Return types are dataclasses, not dicts: `Document`, `SearchResult`, `Collection`, `Stats`, `Health`. Sensible `__repr__` that doesn't dump 50KB of markdown.

### 9. Error handling

Errors are exceptions: `AriadneClientError`, `AriadneAuthError` (401/403), `AriadneNotFoundError` (404), `AriadneServerError` (5xx). Each includes HTTP status code, server error message, and the request that caused it.

### 10. CLI

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

The `--manifest` flag accepts a JSONL file mapping source documents to per-file metadata. The manifest adapter pattern supports different corpus formats — each corpus type provides its own adapter.

### 11. Manifest-based ingestion

For corpora with existing metadata (World Bank reports, academic papers, regulatory documents), the CLI's `--manifest` flag attaches per-file provenance during ingestion. Each file is matched to its manifest entry and ingested with the entry's metadata as `agent_metadata`.

Manifest format is adapter-based — each corpus type has its own adapter that reads the native format and produces per-file metadata. The client doesn't enforce a fixed schema on the metadata dict.

---

## Formatting

Match the existing spec style — Markdown headers, tables, code blocks. Keep it concise. The REST API section has the detailed endpoint docs; this section is about the client layer on top.

## What NOT to change

- Sections 1-3 (approved)
- The REST API section (just reviewed and approved)
- Configuration section (Step 4)
- Anything after the Client Package section insertion point

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.
