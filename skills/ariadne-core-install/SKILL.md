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
     │  │  │  └── Claude Cowork
     │  │  └───── OpenClaw
     │  └──────── Open Brain
     └─────────── Claude Code

Authentication is OAuth 2.1 Bearer JWT (Auth0) across all editions. Clients run a
PKCE flow against Auth0 and send `Authorization: Bearer <jwt>` on every request.
```

Runs as a hosted service. All endpoints except `/api/health` and
`/.well-known/ariadne-config` require an `Authorization: Bearer <jwt>` header.

### Auth interim state (Pass 2 landed, Pass 3 pending)

Ariadne Core uses Auth0 OAuth 2.1 Bearer JWT as of the `ariadne--xft.2` merge
(commit `54165c9`). The `ariadne login` CLI that runs the PKCE flow and caches a
refresh token in the OS keyring is landing in ticket `ariadne--xft.5`. Until
then, obtain a test JWT from **Auth0 dashboard → Applications → your app → Test
tab → copy the access token**, then pass it as `Authorization: Bearer <jwt>` in
your MCP header or REST client. Clients can discover the Auth0 config via
`GET /.well-known/ariadne-config` (unauthenticated).

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
their own JWT — you do NOT handle it):

```bash
claude mcp add ariadne-core https://THE-URL/mcp \
  --transport http --scope user \
  --header "Authorization:Bearer PASTE-YOUR-JWT-HERE"
```

Tell them: *"Ariadne Core uses Auth0 OAuth 2.1 Bearer JWT. The `ariadne login`
CLI that runs the PKCE flow automatically is landing in ticket `ariadne--xft.5`.
Until then, grab a test JWT from Auth0 dashboard → Applications → your app →
Test tab → copy the access token, and paste it in place of `PASTE-YOUR-JWT-HERE`.
You can also run `curl https://THE-URL/.well-known/ariadne-config` to see the
Auth0 config the server expects."*

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

The user already has a URL and a JWT (test-tab token from Auth0 for now; a
keyring-cached access token once `ariadne--xft.5` lands). They just need to
connect a client.

### Quickest path — copy `.mcp.json.template`

Copy `.mcp.json.template` to `.mcp.json` in the project directory, then fill in
the deployment URL and JWT. The setup script (`python scripts/setup.py`)
does this automatically. This replaces the manual `claude mcp add` step below
when a project-scoped `.mcp.json` is acceptable.

### AI path — connect Claude Code

```bash
claude mcp add ariadne-core https://<URL>/mcp \
  --transport http --scope user \
  --header "Authorization:Bearer <JWT>"
```

Restart Claude Code. Verify:
```bash
claude mcp list
# Expected: ariadne-core listed with its tools
```

**If tools don't appear:**
1. Check URL ends with `/mcp` (not `/api/mcp`)
2. Check the JWT is valid: decode it at https://jwt.io and verify `iss`
   matches `https://<AUTH0_DOMAIN>/` and `aud` matches the server's
   `AUTH0_AUDIENCE` (run `curl https://<URL>/.well-known/ariadne-config` to
   see the expected values)
3. Restart Claude Code (required after `claude mcp add`)
4. Test endpoint directly: `curl -s -H "Authorization: Bearer <jwt>" https://<URL>/mcp`

### AI path — connect other MCP clients or REST API

All MCP clients connect the same way as Claude Code. REST API is also available
for scripts and automation. All endpoints use the `Authorization: Bearer <jwt>`
header. Base URL pattern: `https://<URL>/api/`.

```bash
# Discovery (no auth required — returns Auth0 config for the PKCE flow)
curl https://<URL>/.well-known/ariadne-config

# Search
curl -X POST https://<URL>/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt>" \
  -d '{"query": "search terms", "top_k": 5}'

# Upload a file (canonical path for any local file). The response includes
# a server-side path; pass it to convert_document via MCP or REST. Never
# base64-encode file content into an MCP tool call.
curl -X POST https://<URL>/api/upload \
  -H "Authorization: Bearer <jwt>" \
  -F "file=@document.pdf"

# List collections
curl -H "Authorization: Bearer <jwt>" https://<URL>/api/collections

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
  --header "Authorization:Bearer their-jwt"
```

Tell them:
- The `ariadne login` CLI (ticket `ariadne--xft.5`) isn't out yet. Until
  then, grab a test JWT from Auth0 dashboard → Applications → your app →
  Test tab → copy the access token, and paste it in place of `their-jwt`.
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
5. Header: `Authorization: Bearer their-jwt`

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
curl -s https://<URL>/.well-known/ariadne-config     # confirms Auth0 config is set on server
curl -s -o /dev/null -w "HTTP %{http_code}" -H "Authorization: Bearer <jwt>" https://<URL>/api/stats
curl -s -o /dev/null -w "HTTP %{http_code}" -H "Authorization: Bearer <jwt>" https://<URL>/mcp
```

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Health returns nothing | Deployment not running | Check Railway dashboard, run `railway logs` |
| Health returns 502 | Database connection error | Make sure Postgres is attached (`railway add --database postgres`) and check `railway logs` |
| `/.well-known/ariadne-config` returns 500 `auth_misconfigured` | `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_AUDIENCE` unset on the server | Set all three in Railway variables and redeploy |
| 401 `missing_token` | No `Authorization` header, an empty header, or `Authorization: Bearer ` with no token | Add `Authorization: Bearer <jwt>` with the actual JWT |
| 401 `wrong_scheme` | Header present with a non-Bearer scheme (e.g. old `X-API-Key` config, `Basic` auth) | Use `Authorization: Bearer <jwt>` — X-API-Key was removed in Pass 2 |
| 401 `wrong_audience` or `wrong_issuer` | JWT was minted against a different Auth0 tenant/API | Re-issue the test token from the correct Auth0 app; check `/.well-known/ariadne-config` for the expected values |
| 401 `expired_token` | JWT has expired | Issue a fresh test token (Auth0 access tokens default to 24h) |
| 401 `invalid_signature` | Token signed by a different key (wrong tenant) | Check `iss`, re-issue from the right tenant |
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
