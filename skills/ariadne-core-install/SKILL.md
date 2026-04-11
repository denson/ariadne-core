---
name: ariadne-core-install
description: "Set up and connect Ariadne Core. Triggers: deploy ariadne, set up ariadne core, connect ariadne core, configure MCP, troubleshoot connection."
---

# Ariadne Core — Deployment & Connection

Use this skill when the user wants to deploy Ariadne Core to Railway or another
host, connect Claude Code to an existing deployment, troubleshoot a connection,
or update a deployment.

This skill has two modes:
- **AI agent mode** (default): structured commands for autonomous execution
- **Human mode**: step-by-step with explanations, links to the onboarding skill
  for visual walkthrough

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

### One-click deploy (recommended)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/ariadne-core)

Click the button above. Fill in your `EMBEDDING_API_KEY` and `VISION_API_KEY`
(same key if using one provider). Everything else has defaults. After deploy,
copy your `ARIADNE_API_KEY` from the Variables tab to connect MCP clients.

### AI path — deploy via CLI (alternative)

Use this if the one-click deploy doesn't fit the user's situation (no browser,
custom configuration, etc.).

**CRITICAL: Never read, cat, copy, or display the contents of `.env` files.
You do not handle API keys. Tell the user to open `.env` in their editor and
fill in their own keys.**

Deployment has two phases. The first requires the user's interaction (browser login,
interactive CLI prompts). The second is automated.

**Phase 1 — User does these (interactive, agent cannot run them):**

Walk the user through each step. Wait for confirmation before moving to the next.

1. **Create a Railway account** at railway.com if they don't have one
   (free tier available, ~$5/mo hobby plan).
2. **Install Railway CLI:** `npm install -g @railway/cli` (or `brew install railway` on Mac).
3. **Log in:** Run `railway login` in their terminal — opens browser to authenticate.
4. **Create project:** Run `railway init` in their terminal — picks workspace and creates project.
5. **Add Postgres:** Run `railway add --database postgres` — adds the database.
   Railway automatically injects `DATABASE_URL_PRIVATE` (internal network) into the environment.

**Phase 2 — Agent does these:**

```bash
# 1. Set up configuration
cd ariadne-core
cp .env.example .env

# 2. Tell the user to open .env and fill in their API keys
#    DO NOT read or display .env contents — you don't handle keys

# 3. Deploy
railway up

# 4. Get public URL
railway domain

# 5. Verify — health check (expect {"status": "healthy"})
curl -s https://<URL>/api/health

# 6. Verify — auth check (expect 200 with JSON response)
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: <ARIADNE_API_KEY>" \
  https://<URL>/api/collections
```

**What the user fills in `.env`:**
- `EMBEDDING_API_KEY` and `VISION_API_KEY` — their provider API key
- `EMBEDDING_MODEL` and `VISION_MODEL` — model names for their provider
- `EMBEDDING_BASE_URL` and `VISION_BASE_URL` — their provider's endpoint
  (keep `https://api.openai.com/v1` for OpenAI; change for other providers)
- `ARIADNE_API_KEY` — a strong secret for client authentication

**What you do NOT need to set:**
- `DATABASE_URL` / `DATABASE_URL_PRIVATE` — injected automatically by Railway's Postgres plugin
- `PORT` — set automatically by Railway
- `MCP_PORT` — the app defaults to `PORT` automatically (single-port mode)

### Human path — deploy to Railway

If the person wants the full visual walkthrough with illustrations, hand off to the
**ariadne-core-walkthrough** skill.

Otherwise, point them at the one-click deploy first:

> **Fastest path:** Click the deploy button at the top of this section. Fill in your
> API keys, click Deploy, done. The rest of these steps are for manual setup.

If they prefer manual setup, walk them through it conversationally:

**Step 1 — Create accounts (if needed):**
- Railway account at railway.com — free tier works
- An API key from any OpenAI-compatible provider (OpenAI, Google Gemini, Groq,
  DeepSeek, Together AI, Mistral, or a local model server like Ollama)

**Step 2 — Install the Railway CLI:**
```bash
npm install -g @railway/cli    # or: brew install railway (on Mac)
```

**Step 3 — Set up Railway:**
Tell them to run these commands one at a time. Explain what each does.
```bash
railway login                    # opens browser to authenticate
cd ariadne-core                  # go to the project directory
railway init                     # creates a Railway project (picks workspace interactively)
railway add --database postgres  # adds a Postgres database
```

**Step 4 — Configure:**
Tell them to copy `.env.example` to `.env` and fill in their values:
```bash
cp .env.example .env
```

Explain each variable in `.env`:
- `EMBEDDING_API_KEY` — their API key from any OpenAI-compatible provider, for
  turning document chunks into searchable vectors
- `VISION_API_KEY` — same key (or a different provider's key), for describing
  images found in documents
- `EMBEDDING_BASE_URL` / `VISION_BASE_URL` — their provider's API endpoint
  (default is OpenAI; change for other providers)
- `EMBEDDING_MODEL` / `VISION_MODEL` — model names for their provider
- `ARIADNE_API_KEY` — a strong secret, the password clients use to connect

Variables they do NOT need to touch:
- `DATABASE_URL` / `DATABASE_URL_PRIVATE` — Railway injects these automatically from the Postgres plugin
- `PORT` — Railway sets this automatically
- `MCP_PORT` — the app defaults to Railway's PORT, no config needed

**Step 5 — Deploy and get URL:**
```bash
railway up             # builds and deploys (takes 2-3 minutes first time)
railway domain         # gives you the public HTTPS URL
```

**Step 6 — Verify:**
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
| Health returns 502 | Database connection error | Make sure Postgres is attached (`railway add --database postgres`) and check `railway logs` |
| 401 on all requests | Missing API key | Add `X-API-Key` header |
| 403 on all requests | Wrong API key | Check key matches `ARIADNE_API_KEY` in `.env` |
| MCP_PORT errors in logs | MCP_PORT set explicitly | Delete `MCP_PORT` from `.env` — the app defaults to Railway's `PORT` automatically |
| Tools don't appear in Claude Code | Config not loaded | Run `claude mcp list`, restart Claude Code |
| MCP URL wrong | Missing `/mcp` suffix | URL must end in `/mcp` for MCP clients |
| Embedding errors | Bad API key or wrong base URL | Verify key works against your provider's endpoint directly |
| DATABASE_URL errors | Set manually in `.env` | Remove `DATABASE_URL` from `.env` — Railway injects `DATABASE_URL_PRIVATE` (internal) and `DATABASE_URL` (public) automatically; the app prefers the private one |

---

## After connecting

Point the user (or agent) to the **ariadne-document-intelligence** skill for best
practices on using the tools: collection strategy, caller metadata, search-first
patterns, and provenance tracking.

For the visual version with illustrations, use the **ariadne-core-walkthrough** skill.
