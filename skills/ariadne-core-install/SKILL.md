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
MCP server and REST API with tools for ingestion, search, and retrieval.

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

### Setup script (recommended)

Run the setup script for a guided terminal experience. It handles provider
selection, API keys, model discovery, .env configuration, and Railway deployment
via API — no Railway CLI needed:

```bash
python scripts/setup.py
```

The script deploys using Railway's GraphQL API with a Railway API token. Users
create a token at `https://railway.com/account/tokens`.

### One-click deploy (alternative)

Copy this URL and paste it into your browser:

`https://railway.com/deploy/ariadne-core`

Fill in your `EMBEDDING_API_KEY` and `VISION_API_KEY` (same key if using one
provider). Everything else has defaults.

Don't have a Railway account? Sign up at:
`https://railway.com?referralCode=RxMpbX` ($20 in free credits, no commitment).

### After deploy

After the user says the deploy is done, ask them:

*"What's the public URL Railway gave you? It looks like
`something.up.railway.app`. You can find it in the Railway dashboard — click on
the ariadne-core service, go to Settings, scroll to Networking, and copy the
Public Domain URL."*

Once you have the URL, verify it's healthy:
```bash
curl -s https://THE-URL/api/health
# Expected: {"status": "healthy"}
```

To connect MCP, tell the user to run this in their terminal (they need to paste
their own `ARIADNE_API_KEY` — you do NOT handle it):

```bash
claude mcp add ariadne-core https://THE-URL/mcp \
  --transport http --scope user \
  --header "X-API-Key:PASTE-YOUR-ARIADNE-API-KEY-HERE"
```

Tell them: *"Your `ARIADNE_API_KEY` was auto-generated during deploy. Find it in
the Railway dashboard under your ariadne-core service → Variables tab (or in
`.env` if they used the setup script). Copy it and paste it in place of
`PASTE-YOUR-ARIADNE-API-KEY-HERE`."*

### AI path — deploy via API

The setup script uses Railway's GraphQL API (`https://backboard.railway.com/graphql/v2`)
to deploy the published `ariadne-core` template. No Railway CLI is needed. The
script needs a Railway API token — users create one at
`https://railway.com/account/tokens`.

Before running the setup script, do a quick model freshness check — read defaults
from `python scripts/setup.py --help`, check the provider's model page for newer
models in the same class, suggest updates. Pass overrides via `--embedding-model`
and `--vision-model`.

Model documentation pages:
- Google: `https://ai.google.dev/gemini-api/docs/models`
- OpenAI: `https://developers.openai.com/api/docs/models`
- Together: `https://docs.together.ai/docs/inference-models`

**Never read, cat, copy, or display `.env` files — you don't handle API keys.**

### Human path — deploy to Railway

Point them at the setup script (`python scripts/setup.py`) first — it handles
everything interactively. If they want the full visual walkthrough, hand off to
the **ariadne-core-walkthrough** skill. If they prefer the one-click deploy
button, point them at the alternative above.

### Other platforms

See the **ariadne-core-deploy** skill for Fly.io and VPS instructions.

---

## Path 2: Connect to an existing deployment

The user already has a URL and API key. They just need to connect a client.

### Quickest path — copy `.mcp.json.template`

Copy `.mcp.json.template` to `.mcp.json` in the project directory, then fill in
the deployment URL and API key. The setup script (`python scripts/setup.py`)
does this automatically. This replaces the manual `claude mcp add` step below
when a project-scoped `.mcp.json` is acceptable.

### AI path — connect Claude Code

```bash
claude mcp add ariadne-core https://<URL>/mcp \
  --transport http --scope user \
  --header "X-API-Key:<ARIADNE_API_KEY>"
```

Restart Claude Code. Verify:
```bash
claude mcp list
# Expected: ariadne-core listed with its tools
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

# Upload a file (canonical path for any local file). The response includes
# a server-side path; pass it to convert_document via MCP or REST. Never
# base64-encode file content into an MCP tool call.
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
a visual tool card (img_06) showing the available tools.

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
