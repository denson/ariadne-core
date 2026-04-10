---
name: ariadne-core-build
description: "Build, maintain, and extend the Ariadne Core codebase. Triggers: modify code, fix bugs, add features, write tests, repo structure questions."
---

# Ariadne Core — Build & Maintain

Use this skill for modifying code, fixing bugs, adding features, updating
configuration, writing tests, or any changes to the Ariadne Core repo. Also
covers repo structure, design decisions, architecture, and file sync questions.

For using Ariadne Core as an end user (ingesting documents, searching, etc.),
use the ariadne-document-intelligence skill instead.

## Runtime Requirements

**This skill requires Claude Code or any agent with terminal access.** It involves
running tests, editing source files, and executing build commands. For the visual
overview, use the **ariadne-core-walkthrough** skill in Claude Desktop (Cowork).

## What this skill is for

This skill teaches you how to work inside the Ariadne Core codebase. It covers
repo structure, design decisions, guard rails, architecture, and which files must
stay in sync. Use this skill when modifying code — not when using the system as an
end user.

## Source of truth

Read these files in this order before making changes (use Glob to find them):

1. `**/ariadne-core/SPEC.md` — source of truth for all tool signatures, API endpoints, and behavior
2. `**/ariadne-document-intelligence/SKILL.md` — what agents are taught about using the system
3. `**/ariadne-core/docs/docint-architecture.md` — full architecture spec

If the code doesn't match the spec, the code is wrong.

## What this repo is

Ariadne Core is an open source document extraction and retrieval pipeline — the
personal/SMB alternative to enterprise document intelligence stacks. It converts
documents (PDF, DOCX, PPTX, XLSX, HTML, 20+ formats) into clean Markdown + vector
embeddings, and exposes them via MCP server and REST API.

**License:** Apache 2.0. All dependencies must be Apache 2.0 or MIT compatible.

**Phase 1 (current):** MarkItDown only. No local GPU required, but API keys needed for full performance (embedding, vision). Managed/Team editions will add enhanced extraction for formats MarkItDown handles poorly.

## Repo structure

```
ariadne-core/
├── CLAUDE.md                   # Thin pointer to this skill
├── SKILL.md                    # Routing entry point — directs to specialized skills
├── SPEC.md                     # Source of truth — tools, API, behavior
├── README.md
├── LICENSE
├── docker-compose.yml          # App + Postgres (for Railway / self-hosting)
├── Dockerfile           # Production container
├── .env.example
├── config/
│   └── ariadne.yaml            # Main config file
├── src/
│   └── pipeline/
│       ├── __init__.py
│       ├── __main__.py         # CLI entrypoint: `serve` starts MCP + REST
│       ├── mcp_server.py       # MCP tool definitions (Streamable HTTP)
│       ├── config.py           # Config file + env var loader
│       ├── dedup.py            # SHA-256 fingerprinting + dedup gate
│       ├── schema.py           # Pydantic models
│       ├── stores.py           # Store orchestration
│       ├── api/
│       │   ├── app.py          # FastAPI application
│       │   ├── routes.py       # REST endpoints (upload, documents, search, etc.)
│       │   └── auth.py         # API key middleware
│       ├── extraction/
│       │   └── markitdown.py   # MarkItDown wrapper
│       ├── enrichment/
│       │   ├── images.py       # Image enrichment post-processing
│       │   └── vision.py       # Vision API client (any OpenAI-compat endpoint)
│       ├── chunking/
│       │   └── chunker.py      # Chunking strategies (by_title, by_page, fixed_size)
│       ├── embedding/
│       │   └── embedder.py     # Embedding API client
│       └── storage/
│           ├── base.py         # VectorStore protocol
│           └── pgvector.py     # Default implementation
├── src/pyproject.toml
├── migrations/
│   ├── 001_initial.sql         # Database schema (all tables, indexes)
│   ├── 002_add_agent_notes.sql # agent_notes + agent_metadata columns
│   └── 003_search_log.sql      # Search logging table
├── tests/
│   ├── test_*.py               # Unit + integration tests
│   └── fixtures/               # Sample documents for testing
├── docs/
│   ├── docint-architecture.md  # Full architecture spec
│   ├── installation.md
│   ├── configuration.md
│   ├── mcp-setup.md            # How to connect MCP clients
│   ├── ob1-integration.md      # How to use with Open Brain
│   ├── patches/                # Applied spec patches (historical)
│   └── skills/
│       ├── ariadne-core-build/
│       │   └── SKILL.md        # This file — development skill
│       ├── ariadne-core-walkthrough/
│       │   └── SKILL.md        # Visual presentation skill (Cowork)
│       ├── ariadne-core-install/
│       │   └── SKILL.md        # Deployment & connection skill (Claude Code)
│       ├── ariadne-core-deploy/
│       │   └── SKILL.md        # Platform-specific deploy details
│       └── ariadne-document-intelligence/
│           ├── SKILL.md        # Agent skill definition (source of truth)
│           └── README.md       # Skill installation guide
└── benchmarks/
    └── run_benchmarks.py
```

## Files that must stay in sync

These files describe the same system from different angles. When any one changes,
check the others for drift:

| File | What it defines | Authority |
|------|----------------|-----------|
| `SPEC.md` | Tool signatures, API endpoints, behavior contracts | **Primary source of truth** |
| `skills/.../SKILL.md` | How agents should use the tools, caller metadata, processes | Must match SPEC tool signatures and response fields |
| `src/pipeline/mcp_server.py` | MCP tool implementations | Must match SPEC tool signatures |
| `src/pipeline/api/routes.py` | REST API endpoints (including `/api/upload`) | Must match SPEC API table |
| `docs/mcp-setup.md` | Client connection instructions | Must reflect current architecture |
| `config/ariadne.yaml` | Configuration schema | Must match `docs/configuration.md` |
| `migrations/*.sql` | Database schema | Must match SPEC table definitions |
| `docker-compose.yml` | Infrastructure (app + Postgres) | Must match SPEC deployment model |
| `Dockerfile` | Production container | Must match deployment instructions |

## Architecture

Ariadne Core runs as a hosted service. One deployment serves all clients over HTTPS.

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core          │
│  ├── MCP Server          │
│  ├── REST API            │
│  ├── Postgres + pgvec    │
│  ├── MarkItDown          │
│  └── Chunking/Embed      │
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

No local installation required for end users. No Docker on the user's machine.
No STDIO. One HTTPS URL for everything.

### How clients connect

| Client | How it connects |
|--------|----------------|
| Claude Code | MCP with API key |
| Claude Cowork | MCP + OAuth (Managed edition or roll your own) |
| Open Brain | MCP with API key |
| OpenClaw | MCP with API key |
| Cursor | MCP with API key |
| Any MCP client | MCP over HTTPS with API key |
| Any HTTP client | REST API over HTTPS with `X-API-Key` header |

**References:**
- MCP transports: https://modelcontextprotocol.io/docs/concepts/transports
- Claude Code MCP: https://code.claude.com/docs/en/mcp

### Document input

Since the server runs remotely, clients cannot pass local file paths. Documents
must be provided as:

- **HTTP/HTTPS URLs** — the server downloads them directly
- **Upload endpoint** — `POST /api/upload` accepts file uploads and returns a
  server-side path for use with `convert_document`

The `ingest` tool (batch directory ingestion) only works with server-side paths.

### Server entry point

`ariadne-core serve` starts both the Streamable HTTP MCP server and REST API
in a single process using `asyncio.gather` with two uvicorn servers.

The MCP server and REST API share the same pipeline code, database connection pool,
and configuration.

## MCP tools

Six tools defined in SPEC.md: `convert_document`, `search`, `get_document`,
`list_documents`, `list_collections`, `ingest`. All accept caller metadata.
`convert_document` and `ingest` accept a `force` flag to override dedup.

See SPEC.md for full parameter tables and response fields.

## Guard rails

- **No credentials, API keys, or secrets in any file.** Use `${VAR}` interpolation
  in `ariadne.yaml` and `.env` for actual values. Ship `.env.example` with placeholders.
- **No local GPU required.** No PyTorch, no detectron2, no transformers in the container.
  All model inference is via API calls (embedding, vision). A local GPU is optional but
  not needed — API providers handle the compute.
- **No additional extraction engines.** Deferred to Managed/Team editions. Do not import them, reference them in
  requirements, or add it to Docker.
- **No `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, or unqualified `DELETE FROM`**
  in migration files.
- **MCP server must be client-agnostic.** No Claude-specific assumptions. Works
  with any MCP client.
- **API-first for embedding and vision.** Default path uses API calls to any
  OpenAI-compatible endpoint. Local model support exists only as a config option —
  never the default.
- **Never store vectors from different embedding models in the same index without
  tracking which model produced them.** The `embedding_model` column on `chunks`
  must always be populated.
- **All deployments should enable API key auth.** The `require_auth` config flag
  gates all endpoints except `/api/health`.

## Design decisions (settled — do not change)

### Dedup and interactions

Every incoming document is fingerprinted (SHA-256 on normalized text) BEFORE any
expensive processing. If the fingerprint exists in the target collection, skip
extraction/chunking/embedding. But ALWAYS record the interaction.

Two separate concerns, two tables:
- `documents` — one row per unique document per collection. Owns the content,
  fingerprint, processing_chain.
- `document_interactions` — one row per agent call. Records agent_id, agent_type,
  model, initiated_by, action, was_dedup_skip, agent_notes, agent_metadata. Grows
  with every touch, even dedup skips.

When search returns results, include all `document_interactions` for each matched
document.

### Agent-based tenancy

Different agents are the tenants, not organizations. Every MCP tool and REST
endpoint accepts caller metadata: `agent_id`, `agent_type`, `model`,
`initiated_by`, `agent_notes`, `agent_metadata`. This metadata goes into
`document_interactions`, not onto the document itself.

`org_id` column exists on all tables for future row-level security, but is not
enforced in Phase 1. Default value: `00000000-0000-0000-0000-000000000000`.

### Collections

Logical namespaces for documents. Dedup is scoped per collection (unique index on
`collection_id, content_fingerprint`). Same document can exist in multiple
collections. Search defaults to all collections but can be scoped.

### Two-layer provenance

- `documents.processing_chain` (JSONB, append-only) — tracks HOW content was
  processed: extraction tool, enrichment steps, embedding model, timestamps,
  durations.
- `document_interactions` — tracks WHO touched the document: which agent, when,
  what action, whether it was a dedup skip, plus `agent_notes` and `agent_metadata`.

### Search log

Every `search` call is recorded in the `search_log` table. One row per search —
not per result. Captures query, filters, results, and full caller metadata.

### Config

Single `ariadne.yaml` in `config/`. Supports `${VAR}` interpolation for
secrets. Resolution: defaults → config file → env vars.

## Database schema

Key tables: `collections`, `documents`, `document_interactions`, `chunks`,
`api_keys`, `search_log`. Schema spread across three migrations:
- `001_initial.sql` — core tables
- `002_add_agent_notes.sql` — agent_notes + agent_metadata columns
- `003_search_log.sql` — search logging table

The unique constraint `(collection_id, content_fingerprint)` on `documents`
enforces dedup.

## Pipeline order

1. Extract document to Markdown (MarkItDown)
2. Content fingerprint (SHA-256 on normalized text) — skip to step 7 on collision
   (unless `force`)
3. Image enrichment (vision API describes images)
4. Chunk (auto-selected by file type, configurable)
5. Embed (configurable API)
6. Store in vector DB
7. Record `document_interactions` row (ALWAYS, even on dedup skip)

## Batch ingestion concurrency

The `ingest` tool processes files concurrently using `asyncio.Semaphore(4)` and
`asyncio.gather`. Each file is processed in a `_process_file_safe()` wrapper that
catches exceptions per-file so one failure doesn't abort the batch.

Thread safety: psycopg_pool is thread-safe, embedding client uses urllib
(thread-safe), MarkItDown creates local state per call, singletons are read-only
during processing.

## Testing

- Every pipeline step should have unit tests.
- Integration test: ingest a PDF, verify Markdown output, verify chunks in
  pgvector, verify search returns relevant results.
- Dedup test: ingest same document twice. Second call should skip processing,
  create interaction row, return existing document. Third call with `force=true`
  should re-process.
- Multi-agent test: two different agent_ids ingest the same document. Search
  should return the document with both interactions.

## Deployment

### Railway (recommended)

```bash
railway up
```

Railway reads `Dockerfile` and `docker-compose.yml`. Environment variables
are set in the Railway dashboard.

### Any Docker host

```bash
docker compose up -d
```

The `docker-compose.yml` runs the application and Postgres together.

### Development (local)

For local development, you can run Postgres in Docker and the app on the host:

```bash
# Start just Postgres
docker compose up -d postgres

# Install and run the app
pip install -e src/
ariadne-core serve
```

This gives you hot reload and debugger access while still using the production
database.

## Open questions

1. **Embedding re-indexing workflow** — need a CLI command to re-embed corpus
   incrementally when users change embedding models.
2. **Scanned PDF fallback** — MarkItDown's `markitdown-ocr` plugin can send pages
   to vision API. Expensive. Consider explicit opt-in with cost warnings.
3. **MCP Sampling** — future optimization when MCP clients support
   `sampling/createMessage`. Not Phase 1.
