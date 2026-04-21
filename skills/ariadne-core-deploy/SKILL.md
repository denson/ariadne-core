---
name: ariadne-core-deploy
description: "Deploy Ariadne Core to Railway or another host. Triggers: deploy ariadne, push to railway, update deployment, check deploy status."
---

# Ariadne Core — Deploy

Use this skill when the user wants to deploy a new instance, update an existing
deployment, check deployment status, or troubleshoot a deploy. Covers Railway,
Fly.io, Docker, or any hosting platform.

## Runtime Requirements

**This skill requires Claude Code or any agent with terminal access.** It executes
shell commands for deployment, configuration, and verification. For the visual
walkthrough, use the **ariadne-core-walkthrough** skill in Claude Desktop (Cowork).

Autonomous agent systems (OpenClaw, Open Brain, custom frameworks) can follow these
instructions without human intervention, provided their human has granted sufficient
permissions.

## What you're deploying

Ariadne Core is a document extraction and retrieval pipeline. It needs:

- **A container runtime** — the app runs in Docker
- **A Postgres database** with the pgvector extension
- **Environment variables** for API keys and database credentials
- **A public HTTPS URL** so clients (Claude Code, Open Brain, OpenClaw, etc.) can connect

The deployment exposes two endpoints from one process:
- **MCP server** at `/mcp` — for Claude Code, Cursor, any MCP client (with `Authorization: Bearer <jwt>` header)
- **REST API** at `/api/*` — for scripts, health checks, and automation (with `Authorization: Bearer <jwt>` header)

Authentication is OAuth 2.1 Bearer JWT via Auth0. See the "Auth0 configuration"
section below for the env vars the server needs; clients discover those via
`GET /.well-known/ariadne-config` (unauthenticated).

## Railway deployment (primary path)

### Prerequisites

- Railway CLI installed: `npm install -g @railway/cli` (or check with `railway --version`)
- Railway account: railway.com
- A **Google Gemini API key** (format `AQ.*` or legacy `AIza*`). Ariadne's bundled embedding, image enrichment, and language validation clients call Gemini native endpoints directly — see `SPEC.md` → `### Provider constraints` for the exact endpoint/payload contracts. Get a key at https://aistudio.google.com/apikey.

### First-time deploy

1. **Login:**
   ```bash
   railway login
   ```

2. **Navigate to the repo:**
   ```bash
   cd ariadne-core
   ```

3. **Initialize a Railway project** (if not already linked):
   ```bash
   railway init
   ```
   Choose a project name (e.g., `ariadne-core`).

4. **Add a Postgres database:**
   ```bash
   railway add --database postgres
   ```
   Railway provisions Postgres with pgvector automatically. It sets `DATABASE_URL`
   as an environment variable on the service.

5. **Set environment variables:**
   ```bash
   # Auth0 OAuth — required for all protected endpoints
   railway variables set AUTH0_DOMAIN=your-tenant.us.auth0.com
   railway variables set AUTH0_CLIENT_ID=your-native-app-client-id
   railway variables set AUTH0_AUDIENCE=https://ariadne-core
   railway variables set ARIADNE_UPLOAD_SIGNING_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

   # Embedding + vision
   railway variables set ARIADNE_EMBEDDING_API_KEY=your-gemini-api-key
   railway variables set ARIADNE_IMAGE_ENRICHMENT_API_KEY=your-gemini-api-key
   railway variables set ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
   railway variables set ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
   railway variables set ARIADNE_EMBEDDING_DIMENSIONS=1536
   railway variables set ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
   railway variables set ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta
   ```

   `DB_PASSWORD` is not needed — Railway provides `DATABASE_URL` directly.

   `AUTH0_*` values come from your Auth0 dashboard: create a native-application
   client and an API (audience), then copy the domain, native-app client ID,
   and API identifier. `ARIADNE_UPLOAD_SIGNING_SECRET` is an HMAC key for
   presigned upload URLs — it is NOT an auth credential, just a random secret.

   All three base URLs point at the Gemini native API root, not the OpenAI-compat shim at `/v1beta/openai`. Google's current `AQ.*`-format API keys reject every auth variant on the shim — use native only. See `SPEC.md` → `### Provider constraints` for the full contract. Reusing the same Gemini key for both `ARIADNE_EMBEDDING_API_KEY` and `ARIADNE_IMAGE_ENRICHMENT_API_KEY` is fine; use different keys only if you want separate usage tracking.

6. **Deploy:**
   ```bash
   railway up
   ```
   Railway builds from `Dockerfile` and starts the service. The repo includes a `railway.toml` at the root that pins the builder to `DOCKERFILE` — without it, Railway's Railpack auto-detect misreads this project (Python lives under `src/`, not the repo root) and ships a Caddy static-site image that 404s every `/api/*` request. If you fork the repo and notice your deploy returning 404s, verify `railway.toml` exists and contains `builder = "DOCKERFILE"`.

7. **Get the public URL:**
   ```bash
   railway domain
   ```
   This gives you the HTTPS URL. Railway generates a unique subdomain per project — yours will look like `https://<service>-production-<id>.up.railway.app`. The canonical Ariadne Core public instance is at `https://ariadne-core-production-579a.up.railway.app`, but every fork gets its own URL.

8. **Verify:**
   ```bash
   curl https://your-url.up.railway.app/api/health
   ```
   Should return `{"status": "healthy", "version": "0.1.0", "engine": "markitdown", "embedding_enabled": true}`.

> **For schema-breaking deploys** (changing an already-applied migration, dropping a column, consolidating migration files): the above commands are NOT enough — the DB has to be wiped first and the deploy sequence is subtle. See `dave_and_bob_communication/PLAYBOOK_DESTRUCTIVE_DEPLOY.md` for the wipe → `railway up` → verify procedure.

### Update an existing deployment

```bash
cd ariadne-core
railway up
```

Railway rebuilds and redeploys. Zero-downtime if configured with health checks.

### Check status

```bash
railway status          # current deployment info
railway logs            # live logs
railway logs --tail 50  # last 50 lines
```

### Environment variables reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Auto | Set by Railway's Postgres plugin |
| `AUTH0_DOMAIN` | Yes | Auth0 tenant domain (e.g. `dev-xxxxx.us.auth0.com`). Used to build the JWKS URL and the expected `iss` claim. |
| `AUTH0_CLIENT_ID` | Yes | Auth0 native-app client ID. Returned by `/.well-known/ariadne-config` so clients can run the PKCE flow. |
| `AUTH0_AUDIENCE` | Yes | Auth0 API audience identifier (must match `aud` on every accepted JWT). |
| `ARIADNE_UPLOAD_SIGNING_SECRET` | Yes | HMAC secret for presigned upload URLs — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Not an auth credential. |
| `ARIADNE_EMBEDDING_API_KEY` | Yes | API key for chunk embeddings (Google Gemini, `AQ.*` or `AIza*` format) |
| `ARIADNE_IMAGE_ENRICHMENT_API_KEY` | Yes | API key for image descriptions (Google Gemini, `AQ.*` or `AIza*` format) |
| `ARIADNE_EMBEDDING_MODEL` | No | Default: `gemini-embedding-001` |
| `ARIADNE_EMBEDDING_BASE_URL` | No | Default: `https://generativelanguage.googleapis.com/v1beta` (Gemini native root; see `SPEC.md` → `### Provider constraints`) |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | No | Default: `gemini-2.0-flash` |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | No | Default: `https://generativelanguage.googleapis.com/v1beta` (Gemini native root; see `SPEC.md` → `### Provider constraints`) |
| `PORT` | Auto | Set by Railway, used by the server to bind |

Unprefixed names (`EMBEDDING_API_KEY`, `VISION_API_KEY`, ...) also work for backward compatibility.

## Adapting to other platforms

The deployment is a standard Docker container with a Postgres dependency. Any
platform that runs Docker containers and provides Postgres can host it.

### What the container needs

- **Build:** `Dockerfile` in the repo root
- **Database:** Postgres 16+ with pgvector extension, provided via `DATABASE_URL`
- **Ports:** One port (set via `PORT` env var), serves both MCP and REST API
- **Health check:** `GET /api/health` returns `{"status": "healthy"}`
- **Persistent storage:** Postgres volume (the container itself is stateless)

### Fly.io

```bash
fly launch                          # creates fly.toml from Dockerfile
fly postgres create                 # provision Postgres
fly postgres attach                 # sets DATABASE_URL
fly secrets set EMBEDDING_API_KEY=sk-...
fly secrets set VISION_API_KEY=sk-...
fly deploy
```

### Any VPS with Docker

```bash
scp .env your-server:~/ariadne-core/
scp docker-compose.yml your-server:~/ariadne-core/
ssh your-server "cd ariadne-core && docker compose up -d"
```

Set up a reverse proxy (nginx, Caddy) for HTTPS. The `docker-compose.yml` runs
both the app and Postgres.

### Key adaptation points

1. **Database URL:** Railway and Fly.io set `DATABASE_URL` automatically. On a VPS,
   set it in `.env` or pass it as an environment variable.

2. **Port binding:** Railway and Fly.io set `PORT`. On a VPS, set `PORT` and
   `MCP_PORT` to the same value for single-port mode (recommended), or leave
   defaults (`PORT=8000`, `MCP_PORT=8081`) for dual-port mode if you want to
   restart MCP independently during development. See SPEC.md "Port Configuration"
   for details.

3. **HTTPS:** Railway and Fly.io provide HTTPS automatically. On a VPS, use a
   reverse proxy (Caddy is simplest — automatic Let's Encrypt).

4. **pgvector:** Railway's Postgres includes pgvector. On other platforms, use the
   `pgvector/pgvector:pg16` Docker image or install the extension manually.

## After deploying

Once the deployment is live, connect clients using the HTTPS URL:

- **Claude Code:** Add `"url"` and `"headers": {"Authorization": "Bearer <jwt>"}` to `~/.claude/mcp.json`
- **All MCP clients (Open Brain, OpenClaw, Claude Code, Cursor):** Connect via MCP at `https://your-url/mcp` with `Authorization: Bearer <jwt>` header
- **Scripts and automation:** Use REST API at `https://your-url/api/*` with `Authorization: Bearer <jwt>` header

Interim state (Pass 2 landed, Pass 3 pending): the `ariadne login` CLI that
runs Auth0 PKCE and caches a refresh token in the OS keyring lands in ticket
`ariadne--xft.5`. Until then, obtain a test JWT from Auth0 dashboard →
Applications → your app → Test tab → copy the access token, and paste it in
place of `<jwt>`. Clients can discover the Auth0 config via
`curl https://your-url/.well-known/ariadne-config`.

See the **ariadne-core-install** skill for detailed client connection instructions.

## Troubleshooting

**Deploy fails during build**
- Check that `Dockerfile` exists in the repo root
- Check Railway build logs: `railway logs`

**Health check fails after deploy**
- Database not connected: verify Postgres plugin is attached and `DATABASE_URL` is set
- Check logs for migration errors: `railway logs`

**MCP tools not appearing in clients**
- Verify the URL ends in `/mcp` for MCP clients
- Verify the deployment is actually running: `curl https://your-url/api/health`
**Embedding/vision errors**
- Check that `ARIADNE_EMBEDDING_API_KEY` and `ARIADNE_IMAGE_ENRICHMENT_API_KEY` are set: `railway variables`
- Verify the key works with a direct API call to your provider
