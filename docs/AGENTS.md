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
URL:       https://<your-deployment>/mcp
Transport: streamable-http (or http)
Header:    Authorization: Bearer <your-jwt>
```

**Claude Code example:**
```bash
claude mcp add ariadne-core https://your-deployment.up.railway.app/mcp \
  --transport http --scope user \
  --header "Authorization:Bearer your-jwt-here"
```

**Cursor:** Settings > Tools & MCP > Add New MCP Server. Type: `streamable-http`. URL and header as above.

**Other MCP clients:** Same URL, same header. Consult your client's MCP configuration docs.

**MCP transport reference:** https://modelcontextprotocol.io/docs/concepts/transports

### REST API (fallback)

For agents and scripts that don't support MCP, the full REST API is available at `https://<your-deployment>/api/`. All endpoints except `/api/health` and `/.well-known/ariadne-config` require an `Authorization: Bearer <jwt>` header.

```bash
# Health check (no auth)
curl https://your-deployment/api/health

# Auth0 discovery (no auth — returns issuer, client_id, audience, scope)
curl https://your-deployment/.well-known/ariadne-config

# Search
curl -X POST https://your-deployment/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-here" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'

# Upload a file, then convert it
curl -X POST https://your-deployment/api/upload \
  -H "Authorization: Bearer your-jwt-here" \
  -F "file=@report.pdf"

# Convert (pass the path returned by upload)
curl -X POST https://your-deployment/api/documents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-here" \
  -d '{"uri": "/uploads/report.pdf", "collection": "research"}'
```

### Authentication

Ariadne Core uses **OAuth 2.1 Bearer JWT** for all protected endpoints. Auth0 is the identity provider; the server validates JWTs against Auth0's JWKS (RS256, `iss`/`aud`/`exp` checked). All endpoints except `/api/health` and `/.well-known/ariadne-config` require an `Authorization: Bearer <jwt>` header.

**Principal contract:** on success, the server derives a `Principal{user_id, email}` from the JWT — `user_id` is the Auth0 `sub` claim and is used as `agent_id` in provenance tracking. When the caller does not provide an explicit `agent_id`, the server writes `auth0:<sub>` into `interaction_log.agent_id`. The colon prefix keeps the interaction log grep-parseable across the X-API-Key→OAuth transition (previously `api-key:<name>`). See `src/pipeline/api/routes.py:101-105`.

**Interim state (Pass 2 landed, Pass 3 pending):** the `ariadne login` CLI that runs the Auth0 PKCE flow automatically is landing in ticket `ariadne--xft.5`. Until then, agents obtain a test JWT from **Auth0 dashboard → Applications → your app → Test tab → copy the access token**, then pass it in the `Authorization: Bearer <jwt>` header. Machine-to-machine agents (OB1, OpenClaw, custom) should use Auth0's client-credentials flow once Pass 3 lands; until then, the test token path is the only option.

**Discovery:** clients can fetch the Auth0 tenant config (issuer, client_id, audience, scope) from the unauthenticated discovery endpoint:

```bash
curl https://<your-deployment>/.well-known/ariadne-config
```

Full error-response contract (`detail` strings like `missing_token`, `wrong_audience`, `expired_token`, etc.): see [SPEC.md](../SPEC.md#authentication).

---

## MCP tools

| Tool | What it does |
|------|-------------|
| `convert_document` | Convert a single document to Markdown from a URL or server-side path. Chunks, embeds, and stores it by default. Handles dedup via content fingerprint. For local files, upload via REST `POST /api/upload` first and pass the returned server-side path. |
| `search` | Semantic search over stored document chunks. Filters by collection, source file, file type, tags, and document ID. |
| `get_document` | Retrieve the full Markdown content, chunks, and interaction history for a document by ID. |
| `list_documents` | Browse stored documents by collection or file type. Returns metadata for pagination. |
| `list_collections` | List all collections with document counts. Call this before choosing a collection. |
| `ingest` | Batch-ingest a server-side directory. Processes all supported files concurrently (up to 4 at a time). |

All tools accept caller metadata for provenance tracking — see the next section.

**Full parameter details, return shapes, and behavior:** see [SPEC.md](../SPEC.md), section "MCP tools".

### Document input

The server runs remotely. Provide documents as:
- **HTTP/HTTPS URLs** — pass directly to `convert_document`
- **Local files** — upload first via `POST /api/upload` (multipart form data with `Authorization: Bearer <jwt>` header), then pass the returned server-side `path` to `convert_document`

For batch ingestion of a local directory, use the helper script pattern documented in the project skills, or call `ingest` with a server-side directory path after uploading files.

Never base64-encode file content into an MCP tool argument. The bytes would pass through the LLM context, defeating the entire point of the pipeline. A 6 MB PDF becomes ~8 MB of base64 and burns ~1.5–2 M tokens of tool-call payload. Always use the REST upload endpoint for local files.

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

Claude Code users get a plugin with skills that handle routing, onboarding, deployment, and document intelligence guidance automatically. Without the plugin, you lose:

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
