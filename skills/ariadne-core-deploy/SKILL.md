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
- **MCP server** at `/mcp` — for Claude Code, Cursor, any MCP client (with `X-API-Key` header)
- **REST API** at `/api/*` — for scripts, health checks, and automation (with `X-API-Key` header)

## Railway deployment (primary path)

### Prerequisites

- Railway CLI installed: `npm install -g @railway/cli` (or check with `railway --version`)
- Railway account: railway.com
- An API key from any OpenAI-compatible provider (OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, or local models)

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
   railway variables set ARIADNE_EMBEDDING_API_KEY=your-provider-api-key
   railway variables set ARIADNE_IMAGE_ENRICHMENT_API_KEY=your-provider-api-key
   railway variables set ARIADNE_EMBEDDING_MODEL=text-embedding-3-small
   railway variables set ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o-mini
   ```

   `DB_PASSWORD` is not needed — Railway provides `DATABASE_URL` directly.

   Both API keys work with any OpenAI-compatible provider — not just OpenAI. They can use the same key if you use the same provider. If using a non-OpenAI provider, also set `ARIADNE_EMBEDDING_BASE_URL` and `ARIADNE_IMAGE_ENRICHMENT_BASE_URL`. Use different keys if you want separate usage tracking or different providers for each. For backward compatibility, unprefixed names (`EMBEDDING_API_KEY`, `VISION_API_KEY`, ...) also work.

6. **Deploy:**
   ```bash
   railway up
   ```
   Railway builds from `Dockerfile` and starts the service.

7. **Get the public URL:**
   ```bash
   railway domain
   ```
   This gives you the HTTPS URL (e.g., `https://ariadne-core-production.up.railway.app`).

8. **Verify:**
   ```bash
   curl https://your-url.up.railway.app/api/health
   ```
   Should return `{"status": "healthy"}`.

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
| `ARIADNE_EMBEDDING_API_KEY` | Yes | API key for chunk embeddings (any OpenAI-compatible provider) |
| `ARIADNE_IMAGE_ENRICHMENT_API_KEY` | Yes | API key for image descriptions (any OpenAI-compatible provider) |
| `ARIADNE_EMBEDDING_MODEL` | No | Default: `text-embedding-3-small` |
| `ARIADNE_EMBEDDING_BASE_URL` | No | Default: `https://api.openai.com/v1` |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | No | Default: `gpt-4o-mini` |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | No | Default: `https://api.openai.com/v1` |
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

- **Claude Code:** Add `"url"` and `"headers": {"X-API-Key": "..."}` to `~/.claude/mcp.json`
- **All MCP clients (Open Brain, OpenClaw, Claude Code, Cursor):** Connect via MCP at `https://your-url/mcp` with `X-API-Key` header
- **Scripts and automation:** Use REST API at `https://your-url/api/*` with `X-API-Key` header

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
