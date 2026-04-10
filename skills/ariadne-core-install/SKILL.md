---
name: ariadne-core-install
description: |
  Deploy and connect Ariadne Core — a document extraction and retrieval pipeline.
  Use this skill when the user wants to deploy Ariadne Core to Railway or another
  host, connect Claude Code to an existing deployment, troubleshoot a connection, or
  update a deployment. Triggers: "deploy ariadne", "set up ariadne core", "connect
  ariadne core", "ariadne core isn't working", "set up document pipeline",
  "configure MCP for ariadne", or any request to get Ariadne Core running.

  This skill has two modes:
  - AI agent mode (default): structured commands for autonomous execution
  - Human mode: step-by-step with explanations, links to the onboarding skill for
    visual walkthrough
version: 3.0.0
---

# Ariadne Core — Deployment & Connection

## Runtime Requirements

**This skill requires Claude Code or any agent with terminal access.** It executes
shell commands, sets environment variables, and verifies deployments — none of which
work in Claude Desktop (Cowork). For the visual onboarding walkthrough, use the
**ariadne-core-walkthrough** skill in Cowork instead.

Autonomous agent systems (OpenClaw, Open Brain, custom frameworks) can follow the
**AI path** sections below without human intervention, provided their human has
granted sufficient permissions (shell access, environment variable management, and
network requests). The AI path is written as structured commands with verification
checks — any agent that can execute shell commands and parse JSON responses can
complete the deployment autonomously.

## Detect your audience

Before proceeding, determine who you're helping:

- **AI agent executing autonomously** — another LLM or automated system that needs
  exact commands, verification checks, and error handling. Use the **AI path** sections
  below. Be terse. No explanations unless something fails.

- **Human following along** — a person at a keyboard. Use the **Human path** sections.
  Explain what each step does. Offer to hand off to the **ariadne-core-walkthrough**
  skill if they want the full visual walkthrough with illustrations.

If unclear, ask: *"Are you setting this up yourself, or should I run the commands?"*

---

## What Ariadne Core is

A document extraction and retrieval pipeline. Converts documents (PDF, DOCX, PPTX,
XLSX, HTML, 20+ formats) into clean Markdown and vector embeddings. Exposes them via
MCP server and REST API. Six MCP tools for ingestion, search, and retrieval.

### Architecture

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core          │
│  ├── MCP Server (/mcp)   │
│  ├── REST API (/api/*)   │
│  ├── Postgres + pgvec    │
│  └── Pipeline            │
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

Runs as a hosted service. All endpoints except `/api/health` require `X-API-Key` header.

---

## Path 1: Deploy a new instance

### AI path — deploy to Railway

Execute these commands in sequence. Verify after each critical step.

```bash
# 1. Authenticate
railway login

# 2. Navigate to repo
cd ariadne-core

# 3. Initialize project
railway init

# 4. Add Postgres (provides DATABASE_URL automatically)
railway add --plugin postgresql

# 5. Set required environment variables
railway variables set EMBEDDING_API_KEY=<provider-api-key>
railway variables set VISION_API_KEY=<provider-api-key>
railway variables set ARIADNE_API_KEY=<generate-a-strong-secret>
railway variables set EMBEDDING_MODEL=text-embedding-3-small
railway variables set VISION_MODEL=gpt-4o-mini
railway variables set MCP_PORT=8000

# 6. Deploy
railway up

# 7. Get public URL
railway domain
```

**Verification sequence** (run all, expect all to pass):
```bash
# Health check — expect {"status": "healthy"}
curl -s https://<URL>/api/health

# Auth check — expect 200 with JSON response
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: <ARIADNE_API_KEY>" \
  https://<URL>/api/collections

# MCP check — expect non-404 response
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: <ARIADNE_API_KEY>" \
  https://<URL>/mcp
```

**If health check fails:** Check `railway logs` for startup errors. Common issues:
- Missing `DATABASE_URL` → Postgres plugin not attached
- Migration errors → check `railway logs` for SQL errors
- Port binding → `PORT` is set automatically by Railway, don't override it

**Required variables summary:**

| Variable | Value | Notes |
|----------|-------|-------|
| `EMBEDDING_API_KEY` | Provider API key | Any OpenAI-compatible provider |
| `VISION_API_KEY` | Provider API key | Can be same key if same provider |
| `ARIADNE_API_KEY` | Strong secret | Clients authenticate with this |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Or any compatible model |
| `VISION_MODEL` | `gpt-4o-mini` | Or any compatible model |
| `MCP_PORT` | `8000` | Must equal PORT for single-port mode |
| `DATABASE_URL` | Auto | Provided by Railway Postgres plugin |
| `PORT` | Auto | Provided by Railway |

### Human path — deploy to Railway

If the person wants the full visual walkthrough with illustrations, hand off to the
**ariadne-core-walkthrough** skill. It has step-by-step images (img_04 — Hosting Options,
img_05 — Your Agent Does the Heavy Lifting) that make the process much clearer.

Otherwise, walk them through it conversationally:

**Step 1 — Create accounts (if needed):**
- Railway account at railway.com — free tier works
- An API key from any OpenAI-compatible provider (OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, or a local model server like Ollama)

**Step 2 — Deploy:**
Tell them to run these commands one at a time. Explain what each does.
```bash
railway login          # opens browser to authenticate
cd ariadne-core      # go to the project directory
railway init           # creates a Railway project
railway add --plugin postgresql   # adds a Postgres database
```

**Step 3 — Set your keys:**
They need three keys. Explain each one:
- `EMBEDDING_API_KEY` — their API key from any OpenAI-compatible provider, for turning document chunks into searchable vectors
- `VISION_API_KEY` — same key (or a different provider's key), for describing images found in documents
- If using a non-OpenAI provider, they also need `EMBEDDING_BASE_URL` and/or `VISION_BASE_URL`
- `ARIADNE_API_KEY` — a secret they pick, like a password for accessing the service

```bash
railway variables set EMBEDDING_API_KEY=their-provider-key
railway variables set VISION_API_KEY=their-provider-key
railway variables set ARIADNE_API_KEY=pick-a-strong-secret
```

**Step 4 — Deploy and get URL:**
```bash
railway up             # builds and deploys (takes 2-3 minutes first time)
railway domain         # gives you the public HTTPS URL
```

**Step 5 — Verify:**
Have them hit the health endpoint:
```bash
curl https://their-url.up.railway.app/api/health
```
Should return `{"status": "healthy"}`.

### Other platforms

See the **ariadne-core-deploy** skill for Fly.io and VPS instructions.

---

## Path 2: Connect to an existing deployment

The user already has a URL and API key. They just need to connect a client.

### AI path — connect Claude Code

```bash
claude mcp add ariadne-core https://<URL>/mcp \
  --transport http --scope user \
  --header "X-API-Key:<ARIADNE_API_KEY>"
```

Restart Claude Code. Verify:
```bash
claude mcp list
# Expected: ariadne-core listed with 6 tools
```

**If tools don't appear:**
1. Check URL ends with `/mcp` (not `/api/mcp`)
2. Check API key matches the `ARIADNE_API_KEY` env var on the server
3. Restart Claude Code (required after `claude mcp add`)
4. Test endpoint directly: `curl -s -H "X-API-Key: <key>" https://<URL>/mcp`

### AI path — connect other MCP clients or REST API

All MCP clients connect the same way as Claude Code. REST API is also available
for scripts and automation. All endpoints use `X-API-Key` header. Base URL pattern: `https://<URL>/api/`.

```bash
# Search
curl -X POST https://<URL>/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <key>" \
  -d '{"query": "search terms", "top_k": 5}'

# Upload a file
curl -X POST https://<URL>/api/upload \
  -H "X-API-Key: <key>" \
  -F "file=@document.pdf"

# List collections
curl -H "X-API-Key: <key>" https://<URL>/api/collections

# Health check (no auth needed)
curl https://<URL>/api/health
```

For Open Brain agents, include provenance metadata in request bodies:
```json
{
  "query": "search terms",
  "agent_id": "ob1-agent-name",
  "agent_type": "ob1",
  "initiated_by": "user:name"
}
```

### Human path — connect Claude Code

One command in their terminal:
```bash
claude mcp add ariadne-core https://their-url.up.railway.app/mcp \
  --transport http --scope user \
  --header "X-API-Key:their-api-key"
```

Tell them:
- Restart Claude Code after running this
- Check it worked with `claude mcp list`
- Try asking Claude Code: "List the Ariadne Core collections"

If they want to see what the tools do, the **ariadne-core-walkthrough** skill has
a visual tool card (img_06) showing all six tools.

### Human path — connect Cursor

Same URL and auth, different config method:
1. `Cmd+Shift+J` (Mac) or `Ctrl+Shift+J` (Windows) to open Settings
2. Tools & MCP → Add New MCP Server
3. Type: streamable-http
4. URL: `https://their-url/mcp`
5. Header: `X-API-Key: their-key`

---

## Removing

### AI path
```bash
claude mcp remove ariadne-core
```

### Human path
```bash
claude mcp remove ariadne-core
# Then optionally: railway down   (to delete the Railway project)
```

---

## Troubleshooting

### Quick diagnostics (run all three)

```bash
curl -s https://<URL>/api/health
curl -s -o /dev/null -w "HTTP %{http_code}" -H "X-API-Key: <key>" https://<URL>/api/stats
curl -s -o /dev/null -w "HTTP %{http_code}" -H "X-API-Key: <key>" https://<URL>/mcp
```

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Health returns nothing | Deployment not running | Check Railway dashboard, run `railway logs` |
| 401 on all requests | Missing API key | Add `X-API-Key` header |
| 403 on all requests | Wrong API key | Check key matches `ARIADNE_API_KEY` env var |
| Tools don't appear in Claude Code | Config not loaded | Run `claude mcp list`, restart Claude Code |
| MCP URL wrong | Missing `/mcp` suffix | URL must end in `/mcp` for MCP clients |
| Embedding errors | Bad API key or wrong base URL | Verify key works against your provider's endpoint directly |

---

## After connecting

Point the user (or agent) to the **ariadne-document-intelligence** skill for best
practices on using the tools: collection strategy, caller metadata, search-first
patterns, and provenance tracking.

For the visual version with illustrations, use the **ariadne-core-walkthrough** skill.
