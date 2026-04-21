# Ariadne Core — Personal Edition

Ariadne Core works with any agentic system — Claude Code, Open Brain, OpenClaw, Cursor, Gemini, OpenAI Desktop, and more — to dramatically reduce document ingestion tokens. Our tool directly addresses the token cost problem Nate is talking about in [this video](https://youtu.be/5ztI_dbj6ek?si=I_EbV_afT7f7r4X0) ([article version](https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what)), and more. The document ingestion deep-dive starts a bit after [4:20](https://youtu.be/5ztI_dbj6ek?t=260). We'll let him make the case — we'll just explain how we address the problem and how to set it up for you and your agents to use.

[![Your Claude Sessions Cost 10x What They Should](skills/ariadne-core-walkthrough/assets/images/video_thumbnail.png)](https://youtu.be/5ztI_dbj6ek?t=260)

## Install the plugin

Ariadne Core is distributed as a **plugin** — a packaged bundle of skills, metadata, and (optionally) an MCP server. A plugin is just an advanced form of a skill: where a standalone skill is a single `SKILL.md` that teaches an agent how to do one thing, a plugin bundles multiple skills together with a manifest so they can be discovered, installed, and updated as a unit.

This plugin includes a router, onboarding, install, deploy, build, document intelligence, and ConceptViz prompt generation skills.

### Claude Code (recommended)

Two commands — add the marketplace, then install the plugin:

```bash
# Add the marketplace (one-time)
/plugin marketplace add denson/ariadne-core

# Install the plugin
/plugin install ariadne-core@ariadne-core
```

Choose a scope when prompted:
- **User scope** — available in every project (recommended for personal use)
- **Project scope** — available to all collaborators on the current repo
- **Local scope** — only for you, only in the current repo

After installing, reload plugins to activate:

```bash
/reload-plugins
```

> **Note:** Slash command availability varies between Claude Code (terminal) and Claude Desktop. If `/reload-plugins` isn't recognized in your environment, start a new session instead — that always works. The plugin system is evolving rapidly; if any command here doesn't match your experience, ask your AI assistant what's changed.

Then say "run the install skill" to deploy and connect, or "run the onboarding skill" for a visual walkthrough.

You can also install from the CLI outside a session:

```bash
claude plugin marketplace add denson/ariadne-core
claude plugin install ariadne-core@ariadne-core --scope user
```

### Cowork (Claude Desktop)

Cowork discovers plugins installed via Claude Code — install the plugin in Claude Code first (see above), and the skills will be available in both environments. Plugins installed at user scope are shared across Claude Code and Cowork.

You can also browse and manage plugins directly in Cowork through **Customize > Plugins** in the sidebar.

**Private repos only:** If the plugin repo is private, Cowork needs the [Claude GitHub App](https://github.com/apps/claude) installed on the repo to access it. Install the app, authorize it for the repo, and Cowork will be able to sync the plugin. You can also install the app from Claude Code with `/install-github-app`. Public repos don't need this.

> **Note:** The Claude Desktop UI and plugin system are evolving rapidly. If the steps above don't match what you see, ask your AI assistant how plugin management currently works — it will know the latest flow.

### Updating the plugin

When a new version is released, update from either environment:

**Claude Code:**

```bash
/plugin marketplace update ariadne-core
/plugin install ariadne-core@ariadne-core
```

Then run `/reload-plugins` or start a new session to pick up the changes.

**Cowork (Claude Desktop):**

Go to **Customize > Plugins**, find Ariadne Core, and use the update option. Start a new conversation or use `/reload-plugins` if available.

> **Note:** Plugin updates are keyed by version number. If the version hasn't been bumped, the cache won't refresh. If you suspect stale skills, uninstall and reinstall. The plugin system and available slash commands are evolving — terminal and desktop environments may support different commands at any given time.

### Uninstalling

```bash
/plugin uninstall ariadne-core
```

### Run skills directly from the repo

If you'd rather skip the plugin system, you can run skills directly from a cloned copy of this repo:

**Want to understand what this is?** Open this repo in [Claude Desktop](https://claude.com/download) ([setup guide](https://support.claude.com/en/articles/10065433-installing-claude-desktop)) and say "run the onboarding skill." It walks you through everything visually — one concept at a time, with illustrations — and adapts to whether you're a developer, an agent builder, or evaluating the tool.

**Want to get it running?** Open this repo in [Claude Code](https://claude.ai/code) and say "run the install skill." It handles deployment and connection step by step. Or point your agentic system (OpenClaw, Open Brain, or any agent with terminal access) at the install skill — the AI path is designed for autonomous execution without human intervention.

## What it does

It takes documents in (PDF, DOCX, PPTX, XLSX, HTML, CSV, and 20+ other formats), extracts them into clean Markdown, chunks and embeds them for search, and stores everything in Postgres with pgvector. When your agent needs information, it searches and gets back 500 tokens of exactly what's relevant — not 100,000 tokens of raw PDF. That's 100-200x more efficient.

1. **Extracts** documents to clean Markdown using MarkItDown (Microsoft, MIT license, free)
2. **Deduplicates** by fingerprinting content before any expensive processing (free)
3. **Enriches** images by sending them to a vision API for descriptions (optional — skip if your docs don't have images worth describing)
4. **Chunks** intelligently based on document type (headings for reports, pages for slide decks, fixed windows for logs) (free)
5. **Embeds** chunks via any OpenAI-compatible embedding API (required for search)
6. **Stores** everything in Postgres + pgvector for semantic search with SQL filtering
7. **Tracks provenance** on every interaction: which agent, which model, when, what action

Basic extraction is free via MarkItDown, but the full pipeline needs API keys. The only costs are cheap embedding and vision API calls (pennies per document). The expensive model never touches raw documents.

This is the **Personal Edition** — open source, you deploy and manage it yourself. Managed versions (Managed, Team, Enterprise) are coming if you'd rather not deal with infrastructure and security at scale or you need this organization wide.

> **Only need extraction?** You don't need Ariadne Core for that — [MarkItDown](https://github.com/microsoft/markitdown) is open source and handles extraction on its own. Claude Code or any coding agent can install it for you. Ariadne Core adds dedup, chunking, embedding, search, and provenance on top.

## Supported formats

Over 20 formats, including PDF, DOCX, PPTX, XLSX, CSV, HTML, XML, JSON, TXT, Markdown, RTF, EPUB, EML, MSG, ZIP (recursive extraction), Jupyter notebooks, WAV, MP3, and more. MarkItDown handles all conversion. Extraction quality improves with API keys for vision-dependent content.

Images (JPG, PNG, GIF) are supported but require a vision API key (`VISION_API_KEY`) for content extraction. Without it, image files are accepted but produce empty output.

## Architecture

Ariadne Core runs as a hosted service. One deployment serves all clients over HTTPS. No local installation required for end users.

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

Authentication is OAuth 2.1 Bearer JWT (Auth0) across all editions. Clients
discover the Auth0 tenant config via `GET /.well-known/ariadne-config`.
```

All protected endpoints require OAuth 2.1 Bearer JWT auth via the
`Authorization: Bearer <jwt>` header. Open (no auth) endpoints: `/api/health` and
`/.well-known/ariadne-config`.

## Manual setup (if you prefer doing it yourself)

### One-click deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/ariadne-core)

Click the button, fill in your API keys (embedding/vision) and the Auth0 tenant values (`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_AUDIENCE`), done. Everything else has sensible defaults. After deploy, clients discover the Auth0 config at `https://<your-url>/.well-known/ariadne-config`.

### Prerequisites (for manual CLI setup)

- A Railway account — [railway.com](https://railway.com). Free tier works for personal use.
- An API key from any OpenAI-compatible provider — for embeddings and image descriptions. OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, or any local model server (Ollama, LM Studio) all work. See [Compatible providers](#compatible-providers) below.

### Step 1: Deploy to Railway

```bash
railway login
cd ariadne-core
railway init
railway add --database postgres
railway up
```

### Step 2: Set environment variables

In the Railway dashboard or via CLI:

```bash
# Upstream model/API config
railway variables set ARIADNE_EMBEDDING_API_KEY=your-gemini-api-key
railway variables set ARIADNE_IMAGE_ENRICHMENT_API_KEY=your-gemini-api-key
railway variables set ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
railway variables set ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
railway variables set ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta

# OAuth 2.1 / Auth0 tenant config (server-side auth)
railway variables set AUTH0_DOMAIN=your-tenant.us.auth0.com
railway variables set AUTH0_CLIENT_ID=your-native-app-client-id
railway variables set AUTH0_AUDIENCE=https://ariadne-core

# HMAC secret for presigned upload URLs (separate from auth)
railway variables set ARIADNE_UPLOAD_SIGNING_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

`ARIADNE_EMBEDDING_API_KEY` and `ARIADNE_IMAGE_ENRICHMENT_API_KEY` work with any OpenAI-compatible provider — they don't have to be OpenAI. Both can use the same key if you use the same provider for both. If you use a non-OpenAI provider, also set `ARIADNE_EMBEDDING_BASE_URL` and/or `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` to match (see [Compatible providers](#compatible-providers)). For backward compatibility, unprefixed names (`EMBEDDING_API_KEY`, `VISION_API_KEY`, ...) also work.

`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, and `AUTH0_AUDIENCE` configure OAuth 2.1 Bearer JWT auth. The server validates JWTs against Auth0's JWKS; clients fetch `/.well-known/ariadne-config` to discover these values and then run the PKCE flow. The `ariadne login` CLI that wraps this is landing in `ariadne--xft.5` (Pass 3 client work) — until then, obtain a test JWT from the Auth0 dashboard → Applications → your app → Test tab → copy the access token, and pass it as `Authorization: Bearer <token>` in every request.

`ARIADNE_UPLOAD_SIGNING_SECRET` is the HMAC secret used to sign presigned upload URLs. It is not an auth credential and must not be shared with clients — pick any strong random secret (e.g., 32 URL-safe bytes).

Railway provides `DATABASE_URL` automatically via the Postgres plugin.

### Step 3: Get your URL

```bash
railway domain
```

This gives you a public HTTPS URL like `https://ariadne-core-production.up.railway.app`.

### Step 4: Verify

```bash
curl https://your-url.up.railway.app/api/health
```

You should see `{"status": "healthy"}`.

### Step 5: Connect Claude Code

```bash
claude mcp add ariadne-core https://your-url.up.railway.app/mcp \
  --transport http --scope user \
  --header "Authorization:Bearer YOUR_JWT_HERE"
```

Where `YOUR_JWT_HERE` is an access token issued by your Auth0 tenant with audience `https://ariadne-core`. Until the `ariadne login` CLI lands (`ariadne--xft.5`), obtain a test token from Auth0 dashboard → Applications → your app → Test tab → copy the access token. Once the CLI lands, you'll run `ariadne login` once and the client package will attach tokens automatically — you won't edit the MCP config by hand.

Restart Claude Code. The Ariadne Core tools should appear. Verify with `claude mcp list`.

### Step 6: Connect other clients

All clients (Open Brain, OpenClaw, Cursor, etc.) connect via MCP the same way as Claude Code. The REST API is also available for scripts and automation:

```bash
curl -X POST https://your-url.up.railway.app/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_HERE" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'
```

## Hosting options

| Option | Cost | Notes |
|--------|------|-------|
| Railway | Free tier / ~$5/mo | Simplest deployment |
| Fly.io | Free tier / ~$5/mo | Scale to zero when idle |
| Hetzner VPS | ~$4.50/mo | Best value for always-on |
| Any Docker host | Varies | `docker compose up -d` with `Dockerfile` |

All options use the same `Dockerfile` and environment variables. See [deploy skill](skills/ariadne-core-deploy/SKILL.md) for platform-specific instructions.

## MCP tools

The following tools are available to any connected MCP client. See [SPEC.md](SPEC.md) for full parameter details.

| Tool | What it does |
|------|-------------|
| `convert_document` | Convert a document to Markdown. Chunks, embeds, and stores automatically. Handles dedup. For local files, upload via REST `POST /api/upload` first and pass the returned server-side path. |
| `search` | Semantic search over your document store. Filters by collection, source file, file type, or tags. Returns ranked chunks with provenance. |
| `get_document` | Retrieve the full Markdown content, chunks, and interaction history for a document by ID. |
| `list_documents` | Browse documents by collection or file type. Returns metadata for pagination. |
| `list_collections` | List all collections with document counts. |
| `ingest` | Batch-ingest a directory of documents. Processes all supported files and returns a summary. |

All tools accept caller metadata (`agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`) for provenance tracking. Every call creates an interaction record, even dedup skips.

## REST API

The REST API mirrors MCP tool functionality and adds collection management and stats. All endpoints require an `Authorization: Bearer <jwt>` header except `/api/health` and `/.well-known/ariadne-config` (the OAuth discovery endpoint).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload a file and get a server-side path for use with `convert_document` |
| `POST` | `/api/documents` | Convert and store a document (same as MCP `convert_document`) |
| `GET` | `/api/documents` | List documents with optional `collection` filter, `page`, `per_page` |
| `GET` | `/api/documents/{id}` | Get full document by ID (same as MCP `get_document`) |
| `POST` | `/api/ingest` | Batch directory ingestion (same as MCP `ingest`) |
| `POST` | `/api/search` | Semantic search (same as MCP `search`) |
| `GET` | `/api/collections` | List all collections with document counts |
| `POST` | `/api/collections` | Create a new collection |
| `GET` | `/api/stats` | System statistics (document count, chunk count, collections) |
| `GET` | `/api/health` | Health check (no auth required) |

```bash
# Upload a file
curl -X POST https://your-url/api/upload \
  -H "Authorization: Bearer YOUR_JWT_HERE" \
  -F "file=@report.pdf"

# Convert and store
curl -X POST https://your-url/api/documents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_HERE" \
  -d '{"uri": "https://example.com/report.pdf", "collection": "research"}'

# Search
curl -X POST https://your-url/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_HERE" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'

# Health check (no auth)
curl https://your-url/api/health

# OAuth discovery (no auth) — clients fetch this to learn AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_AUDIENCE
curl https://your-url/.well-known/ariadne-config
```

## How dedup works

Every document is fingerprinted (SHA-256 on normalized text) before any expensive processing. If the fingerprint already exists in the target collection:

1. Extraction, chunking, and embedding are skipped
2. A `document_interactions` row is still created (recording who asked, when, and why)
3. The existing document is returned to the caller

This means you can point multiple agents at the same document store without wasting compute. The `force` flag on `convert_document` and `ingest` overrides this when you know a document has changed.

## How provenance works

Every agent call creates a record, even dedup skips. When you search and get a result, you also get the full history of who has touched that document:

- **processing_chain** (on the document) tells you how the content was processed: which extraction tool, which enrichment steps, which embedding model, with timestamps
- **document_interactions** (separate table) tells you who touched it: which agent, which model, when, what action, whether it was a dedup skip, plus `agent_notes` and `agent_metadata`

## Development

For local development, run Postgres in Docker and the app on the host:

```bash
docker compose up -d          # start Postgres
pip install -e src/           # install the app
ariadne-core serve          # start MCP (:8081) + REST API (:8000)
```

## Project structure

```
ariadne-core/
├── config/ariadne.yaml       # Main config
├── Dockerfile                # Production container
├── docker-compose.yml        # Postgres for local dev
├── .env.example              # Environment variables template
├── migrations/               # Postgres schema (auto-runs on first start)
├── src/pipeline/             # All source code
│   ├── __main__.py           # CLI entrypoint (serve command)
│   ├── mcp_server.py         # MCP tool definitions
│   ├── api/                  # FastAPI REST endpoints + auth
│   ├── extraction/           # MarkItDown wrapper
│   ├── enrichment/           # Vision API image descriptions
│   ├── chunking/             # by_title, by_page, fixed_size
│   ├── embedding/            # OpenAI-compatible embedding client
│   └── storage/              # Vector store (pgvector default)
├── tests/
├── benchmarks/
└── docs/
```

## Documentation

- [SPEC.md](SPEC.md) — source of truth for all tool signatures, API endpoints, and behavior
- [Architecture spec](docs/docint-architecture.md) — full technical design
- [Configuration reference](docs/configuration.md) — all `ariadne.yaml` options
- [OB1 integration](docs/ob1-integration.md) — using with Open Brain

### Skills (included in the plugin)

| Skill | Runtime | What it does |
|-------|---------|-------------|
| [Router](skills/ariadne-core-router/SKILL.md) | Any | Routes to the right skill and serves as onboarding entry point |
| [Onboarding](skills/ariadne-core-walkthrough/SKILL.md) | Cowork | Standalone visual walkthrough with illustrations |
| [Install](skills/ariadne-core-install/SKILL.md) | Claude Code / terminal agent | Deploy and connect |
| [Deploy](skills/ariadne-core-deploy/SKILL.md) | Claude Code / terminal agent | Platform-specific deployment |
| [Document Intelligence](skills/ariadne-document-intelligence/SKILL.md) | Any | Best practices for using the tools |
| [Build](skills/ariadne-core-build/SKILL.md) | Claude Code / terminal agent | Developing on the codebase |

## Compatible providers

> **⚠️ v1 runtime is Gemini-native.** Ariadne Core's bundled
> embedding, vision, and language-validation clients call Google
> Gemini's native endpoints directly. The tables below list other
> provider URLs for reference — to use any of them you'll need to
> fork the repo and modify `src/pipeline/embedding/embedder.py`,
> `src/pipeline/enrichment/vision.py`, and
> `src/pipeline/extraction/text_encoding.py` to match that
> provider's request/response shapes. See `SPEC.md` →
> "Provider constraints" for the current native contract.

Ariadne Core works with any OpenAI-compatible API for embeddings and vision. You are not locked to OpenAI — use whichever provider fits your needs and budget.

### Providers with native OpenAI compatibility

| Provider | Base URL | Good models for this task |
|----------|----------|--------------------------|
| **OpenAI** | `https://api.openai.com/v1` (default) | `text-embedding-3-small`, `gpt-4o-mini` |
| **Google Gemini** (v1 default) | `https://generativelanguage.googleapis.com/v1beta` | `gemini-embedding-001`, `gemini-2.0-flash` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-4-70b`, `mixtral-8x22b` |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` |
| **Together AI** | `https://api.together.xyz/v1` | `BAAI/bge-large-en-v1.5` (embeddings) |
| **Mistral AI** | `https://api.mistral.ai/v1` | `mistral-large-2512` |
| **Perplexity** | `https://api.perplexity.ai/v1` | `sonar-huge-online` |

### Local models (on-device)

| Runtime | Base URL |
|---------|----------|
| **Ollama** | `http://localhost:11434/v1` |
| **LM Studio** | `http://localhost:1234/v1` |
| **vLLM** | `http://localhost:8000/v1` |

### Anthropic Claude

Anthropic uses a proprietary API format, not OpenAI-compatible. If you want to use Claude models for vision or embeddings, route through an aggregator:

- **OpenRouter:** `https://openrouter.ai/api/v1` — supports `anthropic/claude-4.6-opus`, `anthropic/claude-4.6-sonnet`
- **Bifrost:** `https://api.bifrost.ai/v1` — enterprise gateway option

### Configuration

To use a non-default provider, set the base URL and model alongside the API key:

```bash
railway variables set ARIADNE_EMBEDDING_BASE_URL=https://api.together.xyz/v1
railway variables set ARIADNE_EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
railway variables set ARIADNE_EMBEDDING_API_KEY=your-together-key
```

Google Gemini and OpenAI models work particularly well for this task. We plan to deploy custom open models in the future.

> **Tip:** Some providers accept both `https://api.example.com` and `https://api.example.com/v1`. If you get a 404, try adding or removing the `/v1` suffix.

## Cost

Basic extraction is free — no API calls needed. But for full performance (image descriptions, embeddings for search), you need API keys from any OpenAI-compatible provider. No local GPU required. Costs vary by provider — here are OpenAI's rates as a baseline:

| What | Model | Cost |
|------|-------|------|
| Embedding | gemini-embedding-001 | ~$0.15 per million tokens |
| Image description | gemini-2.0-flash | ~$0.10 per million input tokens |

Many providers (Groq, DeepSeek, Together AI) are significantly cheaper or offer free tiers. Local models (Ollama, LM Studio) cost nothing beyond hardware.

For a typical document, this works out to less than $0.01 per document. A personal document library of thousands of documents costs a few dollars to process.

### Platform costs

Railway, Fly.io, and similar platforms charge for compute, storage, and data egress. For personal use this is minimal — a few dollars a month. Storage costs scale with your Postgres database size; egress costs scale with how often clients query the API.

If your other systems (OpenClaw, Open Brain, etc.) run on the same platform, egress between services is typically free or negligible — the data stays on the same network. This is the recommended setup for keeping costs low.

## Limitations

### Database scaling

The Personal Edition uses Postgres with pgvector for vector storage. This works well for personal document libraries — thousands of documents, hundreds of thousands of chunks. But you will eventually outgrow a single Postgres instance if your corpus grows large enough.

We're currently testing more robust vector database options for the Managed, Team, and Enterprise editions, including Pinecone, Snowflake, Qdrant, and Weaviate Cloud. We'll share our findings and recommendations for personal/professional users as we evaluate them.

### Format limitations

- **Scanned PDFs** with no text layer produce poor results — MarkItDown can't do OCR
- **Legacy Office formats** (.doc, .ppt) are not supported
- **Complex table layouts** with merged cells use heuristics, not ML layout detection
- **BMP, TIFF, HEIC images** are not supported

The Managed and Team editions will fill these gaps with enhanced extraction capabilities beyond what MarkItDown provides.

## Editions

This is the **Personal Edition** — open source, self-hosted, deploy it yourself.

| Edition | Status | What you get |
|---------|--------|-------------|
| **Personal** | Available now | Open source, self-hosted, full pipeline, you manage everything |
| **Managed** | Coming soon | Managed hosting, enhanced security, priority support |
| **Team** | Coming soon | Managed hosting, team features, SSO, audit logging |
| **Enterprise** | Coming soon | Dedicated infrastructure, custom integrations, SLA |

Higher tiers are fully managed — for those who'd rather not deal with infrastructure and security at scale or need this organization wide.

Interested in Managed, Team, or Enterprise? [Get in touch](https://natesnewsletter.substack.com).

## License

Apache 2.0. See [LICENSE](LICENSE).

All dependencies are Apache 2.0 or MIT compatible.
