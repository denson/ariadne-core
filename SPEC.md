# Ariadne Core — Specification

This document describes how Ariadne Core works. It is the source of truth for the README, skills, MCP tool behavior, and Claude Code instructions. If the code doesn't match this doc, the code is wrong.

---

## What it is

Ariadne Core is an open source document extraction and retrieval pipeline for personal use. It takes documents in, produces clean Markdown and vector embeddings, and exposes them via MCP server and REST API.

## Supported formats

Over 20 formats, including: PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV, HTML, TXT, Markdown, JSON, XML, RTF, EPUB, EML, MSG, ZIP (recursive extraction), Jupyter notebooks (.ipynb), RST, ORG, WAV, MP3, M4A.

Images (JPG, PNG, GIF, JPEG) are supported but require a vision API key (`VISION_API_KEY`) for content extraction. Without it, image files are accepted but produce empty output — the tool returns a warning explaining that a vision API key is needed.

Not supported in the Personal Edition: scanned PDFs (no text layer), legacy Office (.doc, .ppt), complex layouts with merged cells, BMP, TIFF, HEIC.

## Deployment

Ariadne Core runs as a hosted service. One deployment serves all clients over HTTPS.

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core         │
│  ├── MCP Server         │
│  ├── REST API           │
│  ├── Postgres + pgvec   │
│  ├── MarkItDown         │
│  └── Chunking/Embed     │
└─────────────────────────┘
  MCP Server
     ▲  ▲  ▲  ▲
     │  │  │  └── Claude Cowork (Managed edition or roll your own OAuth)
     │  │  └───── OpenClaw
     │  └──────── Open Brain
     └─────────── Claude Code

Authentication is by API key for Personal edition and OAuth for Managed and higher
editions. You can also create your own OAuth for the Personal edition.
```

| Client | How it connects |
|--------|----------------|
| Claude Code | MCP with API key |
| Claude Cowork | MCP + OAuth (Managed edition or roll your own) |
| Open Brain | MCP with API key |
| OpenClaw | MCP with API key |
| Cursor | MCP with API key |
| Any MCP client | MCP over HTTPS with API key |
| Any HTTP client | REST API over HTTPS with `X-API-Key` header |

No local installation required. No Docker on the user's machine. No STDIO. One HTTPS URL for everything.

### Connecting clients

All clients connect to the same HTTPS endpoint. The URL depends on where you deploy (e.g., `https://ariadne-core.up.railway.app`).

All endpoints except `/api/health` require authentication via `X-API-Key` header.

**Claude Code** — connect via MCP. Add via CLI:

```bash
claude mcp add ariadne-core https://your-deployment.up.railway.app/mcp \
  --transport http --scope user \
  --header "X-API-Key:your-api-key"
```

**Reference:** https://code.claude.com/docs/en/mcp

**Cursor** — supports Streamable HTTP. Same `"url"` + `"headers"` config format as Claude Code.

**Open Brain, OpenClaw, and other agents** — connect via MCP the same way as Claude Code. REST API is also available for scripts and automation.

**Reference:** MCP transport specification: https://modelcontextprotocol.io/docs/concepts/transports

### Document input

Since the server runs remotely, clients cannot pass local file paths. Documents must be provided as:

- **HTTP/HTTPS URLs** — the server downloads them directly
- **Upload endpoint** — `POST /api/upload` accepts file uploads and returns a server-side path for use with `convert_document`

The MCP `convert_document` tool accepts URLs in the `uri` parameter. For local files, clients should upload them first via the REST API upload endpoint, then pass the returned path.

The `ingest` tool (batch directory ingestion) only works with server-side paths. To batch-ingest local files, upload them first or make them available via URL.

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

API keys are stored as SHA-256 hashes. `/api/health` is the only unauthenticated endpoint — all other endpoints require an `X-API-Key` header when auth is enabled.

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
- **Production (Railway/hosted):** Set `MCP_PORT` to match `PORT` for single-port mode. Railway only exposes one port — **if you forget to set `MCP_PORT`, you get dual-port mode, which silently fails** because the MCP listener on 8081 is unreachable.
- **Local development:** Leave defaults (`PORT=8000`, `MCP_PORT=8081`) for dual-port mode. This lets you restart the MCP server independently without bouncing the REST API.

---

## MCP tools

Six tools are available to any connected MCP client. All processing is synchronous — the tool returns the full result when it completes.

### `convert_document`

Convert a document to clean Markdown. By default, also chunks, embeds, and stores the result for future search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uri` | string | (required) | `http(s)://` URL or server-side path from upload endpoint |
| `store` | bool | `true` | Chunk, embed, and store in vector DB. Set `false` for one-time extraction without persistence |
| `collection` | string | `"default"` | Logical namespace for the document. Dedup is scoped per collection |
| `tags` | list[str] | `[]` | Tags applied to the document. Searchable via the `tags` filter |
| `force` | bool | `false` | Re-process even if the document fingerprint already exists in this collection |
| `chunking_config` | dict | `null` | Override chunking strategy. Keys: `strategy` (`"by_title"`, `"by_page"`, `"fixed_size"`), `max_characters`, `overlap` |

Returns JSON with: `document_id`, `source_file`, `title`, `markdown` (the full extracted text), `file_type`, `engine` (extraction engine used, e.g. `"markitdown"`), `content_fingerprint`, `collection`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio` (ratio of input size to output tokens), `embedding_model` (model used for chunk embeddings), `store_status` (`"stored"`, `"not_stored"`, or `"skipped"`), and `interactions` (if dedup hit).

**Dedup behavior:** If a document with the same content fingerprint already exists in the target collection, extraction/chunking/embedding are skipped. The existing document is returned, and a new `document_interactions` row is recorded. Use `force: true` to re-process.

**Chunking auto-selection:** If no `chunking_config` is provided, the strategy is chosen by file type: `.pptx` → `by_page`, `.csv`/`.xlsx` → `fixed_size`, `.txt` with no headings → `fixed_size` with high overlap, everything else → `by_title`.

**Image handling:** If the file is an image format and no vision API key is configured, the tool returns a warning in the `warnings` array explaining that a vision API key is needed for image content extraction.

### `search`

Semantic search over all stored document chunks. Returns ranked results with source metadata and interaction history.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | (required) | Natural language search query |
| `top_k` | int | `5` | Number of results to return (max 20) |
| `collection` | string | `null` | Scope search to a specific collection. If null, searches all collections |
| `filters` | dict | `null` | Additional filters (see below) |

**Supported filters:**

| Filter key | Type | Behavior |
|------------|------|----------|
| `collection` | string | Match chunks in this collection. Same as the `collection` parameter — either works |
| `document_id` | string | Match chunks from a specific document |
| `source_file` | string | Substring match (case-insensitive) against the source document's filename |
| `file_type` | string | Exact match against file extension (e.g., `".pdf"`, `".docx"`). Both `.pdf` and `pdf` are accepted — the system normalizes internally — but `.pdf` (with dot) is the recommended convention |
| `tags` | list[str] | Match documents that have any of the specified tags (OR logic) |

Unknown filter keys are silently ignored.

Returns JSON with: `query`, `results_count`, and `results` array. Each result includes `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, and `interactions` (full history of who has touched the source document).

**Requires embedding:** Search only works when an embedding API key is configured. If not, returns an error message.

### `get_document`

Retrieve the full stored document by ID. Use after search to get complete content, or to inspect a specific document's chunks and interaction history.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `document_id` | string | (required) | UUID from search results or `list_documents` |
| `include_chunks` | bool | `true` | Return all chunks with text, section, page info |
| `include_interactions` | bool | `true` | Return all interaction records (who touched it, when, what action) |

Returns JSON with: full `content_markdown`, `processing_chain`, `chunks` array, `interactions` array, and all document metadata.

### `list_documents`

Browse stored documents by collection or file type. Returns metadata only — call `get_document` for full content.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `collection` | string | `null` | Filter to a specific collection |
| `file_type` | string | `null` | Filter by extension (e.g., `".pdf"`, `".docx"`) |
| `limit` | int | `20` | Results per page (max 100) |
| `offset` | int | `0` | Pagination offset |

Returns JSON with: `total_count`, `documents` array (each with `document_id`, `collection`, `source_file`, `file_type`, `title`, `chunk_count`, `interaction_count`, `created_at`).

### `list_collections`

List all collections in the knowledge store with document counts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| (none) | | | |

Returns JSON with: `collections` array, each with `name`, `description`, and `document_count`.

This helps the agent discover what's already organized before choosing a collection for ingestion or scoping a search.

### `ingest`

Batch ingestion of files on the server. Processes all supported files in a server-side directory and returns a summary.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | (required) | Server-side directory path to scan for documents |
| `collection` | string | `"default"` | Collection to store all documents in |
| `recursive` | bool | `true` | Recurse into subdirectories |
| `file_types` | list[str] | `null` | Filter to specific extensions (e.g., `["pdf", "docx"]`). If null, process all supported types |
| `force` | bool | `false` | Re-process documents even if they already exist (dedup override) |
| `tags` | list[str] | `[]` | Tags to apply to all documents |

Returns JSON with: `files_found`, `files_processed`, `files_skipped` (dedup), `files_errored`, and `results` array with per-file status (document_id, source_file, was_dedup_skip, error message if any).

Processing is synchronous. Files are processed concurrently (up to 4 at a time) using asyncio. For large directories this may take minutes. The tool returns the full summary when done.

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
| `source_url` | string | Where the document was downloaded from, if applicable |
| `intent` | string | Why the agent processed this document: `"research"`, `"compliance-review"`, `"onboarding"`, `"reference"`, `"archival"` |
| `findings` | string | Brief summary of what the agent learned from the document |
| `status` | string | Processing state: `"extracted"`, `"reviewed"`, `"needs-follow-up"`, `"superseded"` |
| `related_documents` | list[str] | Document IDs of related items the agent found or was working with |

These keys are recommendations, not a schema. Agents can add any additional keys that make sense for their workflow. The value of following the convention is that another agent can filter or search `agent_metadata` for `intent: "research"` and find documents across sessions and agent types.

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

## REST API

The REST API mirrors MCP tool functionality and adds collection management, file upload, and stats. All endpoints are under `/api/`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload a file, returns server-side path for use with `convert_document` |
| `POST` | `/api/documents` | Convert and store a document (same as MCP `convert_document`) |
| `GET` | `/api/documents` | List documents with optional `collection` filter, `offset`, `limit` |
| `GET` | `/api/documents/{id}` | Get full document by ID (same as MCP `get_document`) |
| `POST` | `/api/ingest` | Batch directory ingestion (same as MCP `ingest`) |
| `POST` | `/api/search` | Semantic search (same as MCP `search`) |
| `GET` | `/api/collections` | List all collections (same as MCP `list_collections`) |
| `POST` | `/api/collections` | Create a new collection |
| `GET` | `/api/stats` | System statistics (document count, chunk count, collections) |
| `GET` | `/api/health` | Health check (no auth required) |

When `require_auth` is enabled in config, all endpoints except `/api/health` need an `X-API-Key` header. API keys are stored as SHA-256 hashes.

**Changed in v0.x:** The `GET /api/documents` endpoint now uses `offset`/`limit` pagination (matching the MCP `list_documents` tool) instead of the previous `page`/`per_page` parameters. Defaults: `offset=0`, `limit=20`, max `100`.

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
| `"convert"` | `convert_document` | Agent deliberately processed a single document |
| `"ingest"` | `ingest` | Document was swept up in a batch directory ingestion |
| `"search"` | `search` (in `search_log`) | Query recorded in the search log |

The distinction between `"convert"` and `"ingest"` matters for provenance — knowing whether a document was specifically selected mid-conversation vs. picked up in a batch tells you something about intent.

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

Since Ariadne Core runs as a remote service, the agent cannot pass local file paths directly. When the user references a local file:

1. If the agent has access to the file (e.g., in Claude Code where the agent can read the filesystem), upload it via `POST /api/upload` first, then pass the returned server-side path to `convert_document`.
2. If the file is available at a URL, pass the URL directly.
3. If neither works, tell the user the file needs to be accessible via URL or uploaded to the server.

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
