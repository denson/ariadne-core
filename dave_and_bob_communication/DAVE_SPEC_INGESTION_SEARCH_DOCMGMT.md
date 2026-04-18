# Task: Rewrite Ingestion + add Search & Document Management sections (Step 5)

**For:** Dave

---

## What to do

Three changes in `ariadne-core/SPEC.md`:

1. **Rewrite `## Ingesting local files`** (lines ~647–658) — remove all MCP references, rewrite around the three ingestion paths (URL, file upload, batch)
2. **Add `## Search`** — new section immediately after the rewritten ingestion section. Narrative guidance on how search works, complements the REST API endpoint docs.
3. **Add `## Document management`** — new section immediately after search. Full CRUD lifecycle, soft-delete with 48h window, collections as namespaces.

---

## Section 1: Rewrite `## Ingesting local files` (lines ~647–658)

### Problems with the current version

1. References `convert_document` MCP tool — MCP is being removed
2. Describes a two-step pattern (upload + convert_document via MCP) that confused every agent
3. Doesn't mention the client package methods
4. Doesn't mention URL-direct ingestion (server fetches)
5. Doesn't mention batch ingestion via CLI

### Replace the entire section with:

```markdown
## Ingestion

Three paths to get a document into Ariadne, in preference order:

### 1. URL — server fetches directly (zero tokens)

Pass an HTTP/HTTPS URL to `POST /api/documents`. The server downloads and processes the document. No bytes flow through the agent.

```python
client.ingest_url("https://example.com/report.pdf", collection="reports")
```

This is the best path when the document is available at a URL. The URL is automatically recorded as the document's `source_reference`.

### 2. File upload — client sends the file (zero tokens)

The client uploads the file via `POST /api/upload`, then triggers conversion via `POST /api/documents` with the returned server path. The client package wraps both steps into one call:

```python
client.ingest_file("path/to/report.pdf", collection="reports")
```

Or via CLI:

```bash
ariadne ingest report.pdf --collection reports
```

The file bytes travel over HTTP once and never enter the LLM's context. A 6 MB PDF as base64 would be ~8 MB / ~1.5-2M tokens — uploading avoids that entirely.

### 3. Bytes already in context — store what the agent has

When a user drops a file into the chat UI, the LLM already has the content. Rather than discarding it and re-uploading, `ingest_bytes` sends the content directly:

```python
client.ingest_bytes(file_content, filename="report.pdf", collection="reports")
```

After ingesting bytes, the agent should tell the user: "This file is now in Ariadne and searchable. Next time, give me the file path instead of dropping it — I'll ingest it directly without loading it into our conversation."

### Batch ingestion

For directories of files already on the server, `POST /api/ingest` processes all supported files in a directory. For local directories, the CLI handles upload + conversion per file:

```bash
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
```

The `--manifest` flag attaches per-file metadata from a JSONL manifest during ingestion. See the Client package section for details.

### What NOT to do

- Do not base64-encode file content into API calls. The bytes would flow through the LLM's context window, burning tokens for transport instead of understanding.
- Do not loop over files calling the REST API manually when the client or CLI handles batching.
- Do not pass local file paths to `POST /api/documents` — local paths are meaningless to the server. Upload first, or use the client package which handles this automatically.
```

---

## Section 2: Add `## Search` (new section, after Ingestion)

Insert this new section immediately after the `---` that closes the Ingestion section:

```markdown
## Search

Semantic search finds document chunks by meaning, not keywords. The query is embedded and compared against all stored chunk vectors using cosine similarity (pgvector HNSW index).

### Basic usage

```python
results = client.search("rare earth mining impacts", collection="world-bank-ree", top_k=10)
for r in results:
    print(r.relevance_score, r.text[:100])
```

### Filters

Search supports filtering to narrow results before vector comparison:

| Filter | Type | Behavior |
|--------|------|----------|
| `collection` | string | Scope to a single collection |
| `document_id` | string | Scope to chunks from one document |
| `source_file` | string | Substring match (case-insensitive) on filename |
| `file_type` | string | Exact match on extension (`.pdf` and `pdf` both work) |
| `tags` | list[str] | Match documents with any of these tags (OR logic) |

Filters compose — you can use `collection` + `tags` + `file_type` together.

### Planned: metadata filters

These are not yet implemented but are part of the design:

| Filter | Type | Behavior |
|--------|------|----------|
| `metadata` | dict | JSONB containment — find documents where `agent_metadata` contains these key-value pairs. Supports nested keys: `{"nested": {"field": "value"}}` |
| `metadata_exists` | list[str] | Find documents that have these keys in `agent_metadata`, regardless of value |

These will enable queries like "find all documents from project P176874" or "find all documents that have a `wb_doc_type` field." The underlying Postgres JSONB already supports this via `@>` containment, `->>` field access, and `?` key existence — the work is exposing it through the API.

### Search behavior notes

- **Approximate (ANN):** Results may vary slightly between identical queries due to HNSW index traversal. For reproducible references, pin document/chunk IDs rather than re-querying.
- **Embedding required:** Search only works when an embedding API key is configured. Returns 503 if not.
- **Search logging:** Every search is recorded in the `search_log` table with the query, filters, results, and caller metadata. See the Search Log section.
- **Soft-deleted documents** are excluded by default. Pass `include_deleted: true` to include them.
```

---

## Section 3: Add `## Document management` (new section, after Search)

Insert this new section immediately after the `---` that closes the Search section:

```markdown
## Document management

### Retrieving documents

**Get a single document** by ID with `GET /api/documents/{id}`. Returns the full document including markdown content, chunks, metadata, tags, collection, and interaction history (optionally).

**List documents** with `GET /api/documents`. Paginated (default 50, max 100). Filter by collection. Includes soft-deleted documents when `include_deleted=true`.

### Updating metadata

`PATCH /api/documents/{id}` updates a document's tags, collection, or agent_metadata without re-processing the content. This is the efficient way to annotate documents after review — no re-extraction, re-chunking, or re-embedding.

- `tags`: replaces the tag list entirely (not a merge)
- `collection`: moves the document to a different collection
- `agent_metadata`: shallow-merged with existing metadata (new keys added, existing keys overwritten, missing keys preserved)

### Soft-delete and restore

Documents and collections support soft-delete with a 48-hour recovery window.

**Delete a document:** `DELETE /api/documents/{id}` marks it as deleted. It disappears from list and search results but remains in the database for 48 hours.

**Restore a document:** `POST /api/documents/{id}/restore` un-deletes it within the 48-hour window. After 48 hours, restore returns 410 (Gone).

**Delete a collection:** `DELETE /api/collections/{name}` soft-deletes all documents in the collection.

**Restore a collection:** `POST /api/collections/{name}/restore` restores all soft-deleted documents in the collection that are still within their recovery window.

### Collections

Logical namespaces for documents. Key behaviors:

- Dedup is scoped per collection — the same document can exist in multiple collections
- Search defaults to all collections but can be scoped to one
- Collections are cheap — use them to organize by project, topic, or workflow
- A document in `"default"` signals the agent didn't think about organization
- Create collections explicitly with `POST /api/collections` or implicitly by specifying a collection name during ingestion

### Document lifecycle summary

| Action | Endpoint / Method | Effect |
|--------|-------------------|--------|
| Ingest | `POST /api/documents` | Create document, extract, chunk, embed, store |
| Read | `GET /api/documents/{id}` | Retrieve full document with metadata |
| List | `GET /api/documents` | Paginated list, filterable by collection |
| Search | `POST /api/search` | Find chunks by semantic similarity |
| Update | `PATCH /api/documents/{id}` | Modify tags, collection, metadata (no re-processing) |
| Delete | `DELETE /api/documents/{id}` | Soft-delete (48h recovery) |
| Restore | `POST /api/documents/{id}/restore` | Undo soft-delete |
| Force re-process | `POST /api/documents` with `force: true` | Re-extract, re-chunk, re-embed |
```

---

## What NOT to change

- Sections 1-3 (approved)
- The REST API section (approved)
- The Client package section (committed)
- The Configuration section (committed)
- The Pipeline order section (committed)
- Caller metadata, Metadata Conventions, Dedup, Provenance, Search Log, Collections, Expected agent behavior — all untouched (Step 6)

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.
