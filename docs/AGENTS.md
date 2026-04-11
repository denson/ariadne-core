# Ariadne Core — Guide for Non-Claude-Code Agents

This guide is for AI agents and coding tools that don't use Claude Code's plugin/skill system — Cursor, Windsurf, Open Brain, OpenClaw, Gemini, OpenAI agents, custom frameworks, and anything else that can connect via MCP or call a REST API. If you're using Claude Code, the plugin handles all of this for you.

**Author:** Denson Smith

---

## What Ariadne Core is

Ariadne Core is an open-source document extraction and retrieval pipeline. It converts PDFs, DOCX, PPTX, XLSX, HTML, and 20+ other formats into clean Markdown and vector embeddings, then exposes them via MCP server and REST API. A 4,500-word document is ~100,000 tokens as a raw PDF but only ~5,000 as clean Markdown — a **20x reduction per document**. Without a pipeline, a frontier model burns $3–$15/M tokens writing Python to extract documents itself. Ariadne replaces that with a deterministic pipeline that costs ~$0.002 per document and produces **better** results — more accurate tables, layout, and image semantics than a frontier model improvising extraction code.

Beyond extraction, Ariadne chunks the Markdown, computes semantic embeddings, and stores everything in a searchable vector database with agent-writable metadata. Five documents don't need search; five thousand are unusable without it.

---

## Connecting

**Don't have an instance yet?** Deploy one:

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/ariadne-core)

### MCP (preferred)

Any MCP-compatible client can connect over Streamable HTTP. One command (syntax varies by client):

```
URL:     https://<your-deployment>/mcp
Transport: streamable-http (or http)
Header:  X-API-Key: <your-api-key>
```

**Claude Code example:**
```bash
claude mcp add ariadne-core https://your-deployment.up.railway.app/mcp \
  --transport http --scope user \
  --header "X-API-Key:your-api-key"
```

**Cursor:** Settings > Tools & MCP > Add New MCP Server. Type: `streamable-http`. URL and header as above.

**Other MCP clients:** Same URL, same header. Consult your client's MCP configuration docs.

**MCP transport reference:** https://modelcontextprotocol.io/docs/concepts/transports

### REST API (fallback)

For agents and scripts that don't support MCP, the full REST API is available at `https://<your-deployment>/api/`. All endpoints except `/api/health` require an `X-API-Key` header.

```bash
# Health check (no auth)
curl https://your-deployment/api/health

# Search
curl -X POST https://your-deployment/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'

# Upload a file, then convert it
curl -X POST https://your-deployment/api/upload \
  -H "X-API-Key: your-api-key" \
  -F "file=@report.pdf"

# Convert (pass the path returned by upload)
curl -X POST https://your-deployment/api/documents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"uri": "/uploads/report.pdf", "collection": "research"}'
```

### Authentication

All endpoints except `/api/health` require the `X-API-Key` header. The key matches the `ARIADNE_API_KEY` environment variable on the server. API keys are stored as SHA-256 hashes.

---

## The 6 MCP tools

| Tool | What it does |
|------|-------------|
| `convert_document` | Convert a single document to Markdown. Chunks, embeds, and stores it by default. Handles dedup via content fingerprint. |
| `search` | Semantic search over stored document chunks. Filters by collection, source file, file type, tags, and document ID. |
| `get_document` | Retrieve the full Markdown content, chunks, and interaction history for a document by ID. |
| `list_documents` | Browse stored documents by collection or file type. Returns metadata for pagination. |
| `list_collections` | List all collections with document counts. Call this before choosing a collection. |
| `ingest` | Batch-ingest a server-side directory. Processes all supported files concurrently (up to 4 at a time). |

All tools accept caller metadata for provenance tracking — see the next section.

**Full parameter details, return shapes, and behavior:** see [SPEC.md](../SPEC.md), section "MCP tools".

### Document input

The server runs remotely, so local file paths won't work. Provide documents as:
- **HTTP/HTTPS URLs** — passed directly to `convert_document` via the `uri` parameter
- **Upload first** — `POST /api/upload` accepts a file and returns a server-side path, which you then pass to `convert_document`

For batch ingestion, `ingest` operates on server-side directories only.

---

## Metadata conventions

Every call to `convert_document`, `search`, and `ingest` should include caller metadata. This is what makes the provenance trail useful.

### Required fields (in practice)

| Field | Description | Example |
|-------|-------------|---------|
| `agent_type` | Your client type | `"cursor"`, `"ob1"`, `"openai-agent"`, `"api"` |
| `initiated_by` | Human or system identity | `"user:denson"`, `"system:nightly-ingest"` |
| `model` | LLM model powering the session | `"gpt-4o"`, `"gemini-2.5-pro"` |
| `agent_notes` | Why this action is being taken — the most valuable provenance field | `"User asked about revenue trends in Q1 report"` |

### Optional fields

| Field | Description |
|-------|-------------|
| `agent_id` | Session or workflow identifier |
| `agent_metadata` | Structured JSON — project ID, intent, findings, status, related documents |

### Collection, tags, and agent_metadata

- **`collection`** — broad namespace for a corpus. Dedup is scoped per collection. Don't dump everything into `"default"` — name it after the project, topic, or task.
- **`tags`** — cross-cutting labels (lowercase, hyphenated). Searchable via the `tags` filter. Use namespace prefixes: `"project:atlas"`, `"status:reviewed"`, `"source:email"`.
- **`agent_metadata`** — structured facts about this specific processing event. Recommended keys: `project`, `source_url`, `intent`, `findings`, `status`, `related_documents`.

**Full conventions with worked examples:** see [SPEC.md](../SPEC.md), section "Metadata Conventions".

---

## Key docs to read

| Document | What it covers | When to read it |
|----------|---------------|-----------------|
| [SPEC.md](../SPEC.md) | Source of truth for tool signatures, API endpoints, metadata conventions, and behavior | Before using any tool or endpoint |
| [TOKEN_SAVINGS_FRAMING.md](TOKEN_SAVINGS_FRAMING.md) | Canonical anchor numbers for token savings and cost claims | Before writing or editing anything that mentions costs, pricing, or savings — use these numbers verbatim, never invent figures |
| [docint-architecture.md](docint-architecture.md) | Full architecture spec — pipeline stages, storage, config | When you need to understand how the system works internally |
| [README.md](../README.md) | Overview, getting started, compatible providers, editions | First orientation |

---

## What you're missing without Claude Code

Claude Code users get a plugin with seven skills that handle routing, onboarding, deployment, and document intelligence guidance automatically. Without the plugin, you lose:

- **Interactive walkthrough** — A visual presentation in Claude Code Desktop's preview panel that explains the token waste problem, how the pipeline fixes it, and how it applies to the user's setup. It runs through a sequence of HTML "beats" with images and branching paths based on user responses. The content covers the same material as this guide plus the framing doc, but in an interactive format.

- **Skill routing** — The plugin automatically routes user requests to the right skill (install, deploy, build, document intelligence). Without it, you need to know which doc to read for your task.

- **Install and deploy skills** — Step-by-step deployment scripts with checkpoint verification for Railway, Fly.io, and VPS. The AI path is designed for autonomous execution. If you need to deploy, read the install instructions in the [README](../README.md) or the deploy skill at `skills/ariadne-core-deploy/SKILL.md`.

- **Document intelligence skill** — Best practices for using the tools: when to search vs. read, how to choose collections, how to handle local files, error patterns. The key guidance is in [SPEC.md](../SPEC.md) under "Expected agent behavior".

### Accessing walkthrough content directly

The walkthrough's content is available in two forms you can read without Claude Code:

1. **Knowledge graph** — `skills/ariadne-core-walkthrough/project_knowledge_graph.yaml` contains 35+ concepts with full text bodies covering the token waste problem, pipeline architecture, deployment, tools, metadata, and more. Each concept has a `body` field with the explanation and a `see_also` field linking to related concepts.

2. **Beat HTML files** — `walkthrough_html/beat*.html` are the actual presentation pages. They reference images co-located in `walkthrough_html/`.

---

## Commit convention (for agents contributing to this repo)

If your agent is contributing code to the ariadne-core repo, follow the commit convention:

```
<commit message>

Executed-by: <executor-name> (<session-name>)
Reviewed-by: <reviewer-name> (<session-name>)
Co-Authored-By: <Model> <noreply@anthropic.com>
```

Every commit should be reviewed before it enters the repo. The executor and reviewer should be different agents or people.
