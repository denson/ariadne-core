# Installation Guide

> **⚠️ v1 runtime is Gemini-native.** Only Google Gemini is wired
> up out of the box. To use a different provider, fork the repo
> and modify the clients in `src/pipeline/`. See `SPEC.md` →
> "Provider constraints."

Ariadne Core runs as a hosted service on Railway (or any Docker host). By the end of this guide, you'll have document extraction and search available to Claude Code, Open Brain, and OpenClaw over HTTPS.

## What you need

1. **A Railway account** — sign up at [railway.com](https://railway.com). Free tier works for personal use.

2. **An API key from any OpenAI-compatible provider** — used for embedding document chunks (for search) and describing images found in documents. One key covers both uses.
   - OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, or local models (Ollama, LM Studio) all work.
   - See [Compatible providers](../README.md#compatible-providers) in the README for base URLs and model names.
   - Cost: a few cents per month for personal use. Many providers offer free tiers. Local models cost nothing beyond hardware.

3. **An API key for authentication** — pick any strong secret. All clients must include this in their requests.

## Step 1: Get the code

```bash
git clone https://github.com/your-org/ariadne-core.git
cd ariadne-core
```

Or if you already have it, just `cd` into the directory.

## Step 2: Deploy to Railway

```bash
railway login
railway init
railway add --database postgres
railway up
```

Railway builds the Docker image from the `Dockerfile` in the repo and provisions a Postgres database with pgvector automatically.

## Step 3: Set environment variables

In the Railway dashboard or via CLI:

```bash
railway variables set EMBEDDING_API_KEY=your-gemini-api-key
railway variables set VISION_API_KEY=your-gemini-api-key
railway variables set EMBEDDING_MODEL=gemini-embedding-001
railway variables set VISION_MODEL=gemini-2.0-flash
railway variables set EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set VISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set ARIADNE_API_KEY=your-secret-api-key
```

Notes:
- `EMBEDDING_API_KEY` and `VISION_API_KEY` work with any OpenAI-compatible provider — not just OpenAI. Both can use the same key if you use the same provider.
- If using a non-OpenAI provider, also set `EMBEDDING_BASE_URL` and `VISION_BASE_URL` to match your provider's endpoint (see [Compatible providers](../README.md#compatible-providers)).
- `ARIADNE_API_KEY` is the key clients use to authenticate — pick any strong secret.
- Railway provides `DATABASE_URL` automatically via the Postgres plugin. No manual database config needed.

## Step 4: Get your public URL

```bash
railway domain
```

This gives you a public HTTPS URL like `https://ariadne-core-production.up.railway.app`.

## Step 5: Verify

```bash
curl https://your-url.up.railway.app/api/health
```

You should see `{"status": "healthy"}`.

## Step 6: Connect Claude Code

```bash
claude mcp add ariadne-core https://your-url.up.railway.app/mcp \
  --transport http --scope user \
  --header "X-API-Key:your-api-key"
```

Restart Claude Code. The six Ariadne Core tools should appear. Verify with `claude mcp list`.

## Step 7: Connect REST API clients

Open Brain, OpenClaw, or any HTTP client can use the REST API:

```bash
curl -X POST https://your-url.up.railway.app/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'
```

## Verify everything works

1. **In Claude Code**, ask: "List the Ariadne Core collections" — it should call `list_collections` and return results.

2. **Via REST API**, upload and convert a document:
   ```bash
   curl -X POST https://your-url/api/upload \
     -H "X-API-Key: your-api-key" \
     -F "file=@report.pdf"
   ```

3. **Search** for content in the document you just converted — it should appear.

If any of these fail, see [Troubleshooting](#troubleshooting) below.

---

## How it all fits together

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

Authentication is by API key for Personal edition and OAuth for Managed and higher
editions. You can also create your own OAuth for the Personal edition.
```

| Component | Where | What |
|-----------|-------|------|
| Postgres + pgvector | Railway plugin | Document storage and vector search |
| MCP Server | Railway container | MCP for all clients |
| REST API | Railway container | HTTP API for Open Brain, OpenClaw, scripts |

All clients share the same Postgres database. One deployment, multiple clients, one HTTPS URL.

---

## Alternative hosting

The same `Dockerfile` works on any platform:

| Option | Cost | Notes |
|--------|------|-------|
| Railway | Free tier / ~$5/mo | Simplest deployment |
| Fly.io | Free tier / ~$5/mo | Scale to zero when idle |
| Hetzner VPS | ~$4.50/mo | Best value for always-on |
| Any Docker host | Varies | `docker compose up -d` with reverse proxy |

See the [deploy skill](skills/ariadne-core-deploy/SKILL.md) for platform-specific instructions.

## Updating

Push new code and redeploy:

```bash
railway up
```

Your data is preserved in Postgres. Migrations run automatically on startup.

## Troubleshooting

**Tools don't appear in Claude Code**
- Run `claude mcp list` and check that `ariadne-core` is listed
- Make sure you used `claude mcp add` (not manual config file editing)
- Restart Claude Code after adding the MCP server
- Verify the deployment is healthy: `curl https://your-url/api/health`

**"Connection refused" or timeout**
- Is the deployment running? Check Railway dashboard.
- Verify the URL: `curl https://your-url/api/health`
- Check Railway logs for errors

**401 or 403 errors**
- Check that your `X-API-Key` header matches the `ARIADNE_API_KEY` environment variable on Railway
- For Claude Code: verify the header in `claude mcp list` output

**Embedding or vision errors**
Your API key is missing, invalid, or the base URL doesn't match. Verify your key works by hitting the native Gemini endpoint directly:
```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents" \
  -H "x-goog-api-key: your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"requests":[{"model":"models/gemini-embedding-001","content":{"parts":[{"text":"test"}]}}]}'
```
A 200 response with an `embeddings` array confirms the key and endpoint work. Google's `AQ.*`-format keys (April 2026+) only accept the `x-goog-api-key` header on the native path — the OpenAI-compat shim at `/v1beta/openai/*` is not supported.

### Collecting diagnostics

If you're stuck, run this and share the output with a coding assistant or [open an issue](https://github.com/anthropics/ariadne-core/issues):

```bash
echo "=== Health ===" && curl -s https://your-url/api/health 2>&1
echo "=== MCP ===" && curl -s -o /dev/null -w "HTTP %{http_code}" -H "X-API-Key: your-key" https://your-url/mcp 2>&1
```

## Local development

For developing on Ariadne Core itself:

```bash
docker compose up -d          # start Postgres locally
pip install -e src/           # install the app
ariadne-core serve          # start MCP (:8081) + REST API (:8000)
```

```bash
# Stop Postgres (data preserved)
docker compose down

# Wipe everything and start over
docker compose down -v
```

## Uninstalling

```bash
# Delete the Railway project
railway down

# Remove Claude Code MCP config
claude mcp remove ariadne-core
```
