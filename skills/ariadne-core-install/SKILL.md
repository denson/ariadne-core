---
name: ariadne-core-install
description: "Set up and connect Ariadne Core. Triggers: deploy ariadne, set up ariadne core, connect ariadne core, install the CLI, troubleshoot connection."
---

# Ariadne Core — Deployment & Connection

Use this skill when the user wants to deploy Ariadne Core to Railway or another host, connect their CLI / agent to an existing deployment, troubleshoot a connection, or update a deployment.

This skill has two modes:
- **AI agent mode** (default): structured commands for autonomous execution
- **Human mode**: step-by-step with explanations, links to the onboarding skill for visual walkthrough

## Runtime Requirements

**This skill requires terminal access** — `ariadne` CLI is a Python package and `ariadne login` runs a local OAuth loopback flow. Claude Code, Cursor, Cline, OpenClaw, Open Brain, and any other agent with Bash/shell tool access can drive this autonomously. For the visual onboarding walkthrough in Cowork, use the **ariadne-core-walkthrough** skill instead.

## Detect your audience

Before proceeding, determine who you're helping:

- **AI agent executing autonomously** — another LLM or automated system that needs exact commands, verification checks, and error handling. Use the **AI path** sections. Be terse. No explanations unless something fails.

- **Human following along** — a person at a keyboard. Use the **Human path** sections. Explain what each step does. Offer to hand off to the **ariadne-core-walkthrough** skill if they want the full visual walkthrough with illustrations.

If unclear, ask: *"Are you setting this up yourself, or should I run the commands?"*

---

## What Ariadne Core is

A document extraction and retrieval pipeline plus an agent-memory substrate (`bw` working memory + pgvector semantic recall). Converts documents (PDF, DOCX, PPTX, XLSX, HTML, 20+ formats) into clean Markdown and vector embeddings. Exposes them via a REST API over HTTPS.

### Architecture

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core           │
│  ├── REST API (/api/*)  │
│  ├── Postgres + pgvec   │
│  └── Pipeline           │
└─────────────────────────┘
       REST API + `ariadne` CLI
        ▲   ▲   ▲   ▲
        │   │   │   └── Claude Cowork
        │   │   └────── OpenClaw / Open Brain
        │   └────────── Cursor / Cline / other agents
        └────────────── Claude Code

Authentication is OAuth 2.1 Bearer JWT (Auth0). The `ariadne login` CLI runs
the PKCE flow and stores tokens in the OS keyring. Clients can also discover
the Auth0 config via `GET /.well-known/ariadne-config` and run the flow
themselves.
```

Runs as a hosted service. All endpoints except `/api/health` and `/.well-known/ariadne-config` require an `Authorization: Bearer <jwt>` header.

---

## Path 1: Deploy a new instance

The user wants to stand up their OWN Ariadne Core deployment on Railway (or another host).

### Setup script (recommended)

Run the setup script for a guided terminal experience. It handles provider selection, API keys, model discovery, .env configuration, and Railway deployment via API — no Railway CLI needed:

```bash
python scripts/setup.py
```

The script deploys using Railway's GraphQL API with a Railway API token. Users create a token at `https://railway.com/account/tokens`.

### One-click deploy (alternative)

Copy this URL and paste it into your browser:

`https://railway.com/deploy/ariadne-core`

Fill in your `EMBEDDING_API_KEY` and `VISION_API_KEY` (same key if using one provider). Everything else has defaults.

Don't have a Railway account? Sign up at: `https://railway.com?referralCode=RxMpbX` ($20 in free credits, no commitment).

### After deploy

After the user says the deploy is done, ask them:

*"What's the public URL Railway gave you? It looks like `something.up.railway.app`. You can find it in the Railway dashboard — click on the ariadne-core service, go to Settings, scroll to Networking, and copy the Public Domain URL."*

Once you have the URL, verify it's healthy:

```bash
curl -s https://THE-URL/api/health
# Expected: {"status": "healthy"}

curl -s https://THE-URL/.well-known/ariadne-config
# Expected: JSON with AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_AUDIENCE
```

If `/.well-known/ariadne-config` returns `500 auth_misconfigured`, the deploy is missing one of `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_AUDIENCE` — set those in Railway variables and redeploy.

### AI path — deploy via API

The setup script uses Railway's GraphQL API (`https://backboard.railway.com/graphql/v2`) to deploy the published `ariadne-core` template. No Railway CLI is needed. The script needs a Railway API token — users create one at `https://railway.com/account/tokens`.

Before running the setup script, do a quick model freshness check — read defaults from `python scripts/setup.py --help`, check the provider's model page for newer models in the same class, suggest updates. Pass overrides via `--embedding-model` and `--vision-model`.

Model documentation pages:
- Google: `https://ai.google.dev/gemini-api/docs/models`
- OpenAI: `https://developers.openai.com/api/docs/models`
- Together: `https://docs.together.ai/docs/inference-models`

**Never read, cat, copy, or display `.env` files — you don't handle API keys.**

### Human path — deploy to Railway

Point them at the setup script (`python scripts/setup.py`) first — it handles everything interactively. If they want the full visual walkthrough, hand off to the **ariadne-core-walkthrough** skill. If they prefer the one-click deploy button, point them at the alternative above.

### Other platforms

See the **ariadne-core-deploy** skill for Fly.io and VPS instructions.

---

## Path 2: Connect to an existing deployment

The user already has a URL (someone else's hosted instance, or their own from Path 1). They want to install the CLI and authenticate so their agents can drive Ariadne.

### AI path — install + auth (run autonomously)

```bash
# 1. Install the Python client from PyPI
pip install ariadne-core-client

# 2. Authenticate — opens a browser for Auth0 OAuth via Google
ariadne login --host https://THE-URL

# 3. Verify auth landed
ariadne whoami
# Expected: user identity + token expiry timestamp

# 4. Sanity-check the server is reachable + the corpus is accessible
ariadne stats
# Expected: total_documents, total_chunks, collections list
```

If `ariadne whoami` reports "Not authenticated" after `ariadne login`, the OAuth flow didn't complete. Check that the browser actually opened and the user signed in.

### Human path — install + auth

Tell them three short commands:

```bash
pip install ariadne-core-client
ariadne login --host https://their-url.up.railway.app
ariadne whoami
```

Explain:
- The first command installs the Python client (provides the `ariadne` CLI).
- The second opens a browser for sign-in with their Google account. After they sign in, the CLI captures the callback on a local port and stores their token in the OS keyring (no plaintext credentials on disk).
- `ariadne whoami` verifies it worked.

Once authed, they can run `ariadne search "test"` to confirm the corpus is reachable, or have their agent drive `ariadne search` calls on their behalf.

### Plugin (skill discoverability)

The Ariadne Core plugin packages the agent-facing skills (walkthrough, install, deploy, document-intelligence, factory-demo, invitation, etc.). Install it in Claude Code Desktop so agents can invoke the skills:

```bash
# Add the marketplace (one-time)
/plugin marketplace add denson/ariadne-core

# Install the plugin
/plugin install ariadne-core@ariadne-core

# Reload (or start a new session)
/reload-plugins
```

Cowork discovers plugins installed via Claude Code at user scope — install in Claude Code first, and the skills appear in Cowork too.

### Driving Ariadne from an agent

Once the CLI is installed + authed, an agent with shell / Bash tool access drives Ariadne via:

```bash
# Vector search
ariadne search "query" --collection some-collection --top-k 5

# Listing
ariadne list-collections
ariadne list-documents

# Ingest
ariadne ingest /path/to/file.pdf

# Direct REST for anything the CLI doesn't cover (e.g. /api/bw/* for bw-side
# ticket retrieval). The token is in the OS keyring:
TOKEN=$(python -c "import keyring; print(keyring.get_password('ariadne-core', 'https://THE-URL:token'))")
curl -H "Authorization: Bearer $TOKEN" https://THE-URL/api/bw/projects/some-slug/tickets/some-id
```

---

## Removing

### AI path — uninstall client

```bash
ariadne logout       # clear stored credentials
pip uninstall ariadne-core-client
```

### Removing the plugin

```bash
/plugin uninstall ariadne-core
```

### Tearing down a deployment

If they deployed their own instance and want to delete it:

```bash
railway down
```

---

## Troubleshooting

### Quick diagnostics

```bash
curl -s https://THE-URL/api/health
# Expected: {"status": "healthy"}

curl -s https://THE-URL/.well-known/ariadne-config
# Expected: JSON with AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_AUDIENCE

ariadne whoami
# Expected: identity + expiry

ariadne stats
# Expected: total_documents, collections list
```

### Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `pip install ariadne-core-client` says "no matching distribution" | Older pip or stale index | `pip install --upgrade pip` and retry, or `pip install --index-url https://pypi.org/simple ariadne-core-client` |
| `ariadne login` doesn't open a browser | Local default-browser misconfigured | Copy the URL printed by `ariadne login` into your browser manually |
| `ariadne login` says "callback port in use" | Another process is on the loopback port | Stop the conflicting process or restart your machine |
| `ariadne whoami` says "Not authenticated" after login | OS keyring not writable / sign-in didn't complete | Re-run `ariadne login`; ensure the OS keyring service is running (`gnome-keyring` on Linux, default on macOS / Windows) |
| `ariadne stats` returns 401 | Token expired (Auth0 default ~20h) | Re-run `ariadne login` |
| `ariadne stats` returns 502 | Deployment not running | Check Railway dashboard, run `railway logs` |
| `/.well-known/ariadne-config` returns 500 `auth_misconfigured` | `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_AUDIENCE` unset on the server | Set all three in Railway variables and redeploy |
| 401 `missing_token` from API | No `Authorization` header, empty header, or `Authorization: Bearer ` with no token | Add `Authorization: Bearer <jwt>` with the actual JWT |
| 401 `wrong_audience` or `wrong_issuer` | JWT was minted against a different Auth0 tenant/API | Re-run `ariadne login` against the right host; check `/.well-known/ariadne-config` for the expected values |
| 401 `expired_token` | Token has expired | Re-run `ariadne login` |
| Embedding errors in server logs | Bad API key or wrong base URL | Verify key works against your provider's endpoint directly |
| `DATABASE_URL` errors on deploy | Set manually in `.env` | Remove `DATABASE_URL` from `.env` — Railway injects `DATABASE_URL_PRIVATE` (internal) and `DATABASE_URL` (public) automatically; the app prefers the private one |

---

## After connecting

Point the user (or agent) to:

- **ariadne-document-intelligence** skill — best practices for using the tools: collection strategy, caller metadata, search-first patterns, provenance tracking.
- **factory-demo-walkthrough** skill — 5-minute hands-on demo against a pre-seeded corpus, if they want to feel the substrate before committing to their own data.

For the visual version with illustrations, use the **ariadne-core-walkthrough** skill.
