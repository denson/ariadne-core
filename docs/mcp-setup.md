# Connecting Clients to Ariadne Core

This guide covers how to connect AI clients to your Ariadne Core deployment. The service must be deployed first — see [installation.md](installation.md) if you haven't set that up yet.

## Architecture

Ariadne Core runs as a hosted service. All clients connect over HTTPS with API key authentication.

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core          │
│  ├── MCP Server (/mcp)   │
│  ├── REST API (/api/*)   │
│  └── Postgres + pgvec    │
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

All endpoints (except `/api/health`) require an `X-API-Key` header.

## Prerequisites

1. **Ariadne Core deployed** with a public HTTPS URL (e.g., `https://ariadne-core-production.up.railway.app`)
2. **Your API key** — the `ARIADNE_API_KEY` value set during deployment

---

## Claude Code

Claude Code connects via MCP. Use the CLI to configure:

```bash
claude mcp add ariadne-core https://your-url.up.railway.app/mcp \
  --transport http --scope user \
  --header "X-API-Key:your-api-key"
```

Restart Claude Code. Verify the connection:

```bash
claude mcp list
```

You should see `ariadne-core` listed with its tools: `convert_document`, `search`, `get_document`, `list_documents`, `list_collections`, `ingest`.

### Removing

```bash
claude mcp remove ariadne-core
```

---

## Open Brain (MCP or REST API)

Open Brain connects via MCP or the REST API with the `X-API-Key` header on all requests.

```bash
# Search documents
curl -X POST https://your-url/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'

# Upload and convert a document
curl -X POST https://your-url/api/upload \
  -H "X-API-Key: your-api-key" \
  -F "file=@report.pdf"

# List collections
curl -H "X-API-Key: your-api-key" https://your-url/api/collections
```

OB1 agents should pass `agent_type: "ob1"` and `initiated_by: "user:name"` in request bodies for provenance tracking.

---

## OpenClaw (MCP or REST API)

Same as Open Brain — connect via MCP or REST API with the `X-API-Key` header. OpenClaw agents should use `agent_type: "openclaw"` for provenance.

---

## Cursor

Cursor supports MCP. Add the server via Cursor Settings:

1. Press `Cmd+Shift+J` (Mac) or `Ctrl+Shift+J` (Windows)
2. Navigate to **Tools & MCP**
3. Click **+ Add New MCP Server**
4. Set type to **streamable-http**
5. URL: `https://your-url.up.railway.app/mcp`
6. Add header: `X-API-Key: your-api-key`

Restart Cursor and check the MCP Logs output panel.

---

## Other MCP Clients

Any MCP client that supports Streamable HTTP transport can connect. The general pattern:

- **URL:** `https://your-url.up.railway.app/mcp`
- **Transport:** Streamable HTTP
- **Auth header:** `X-API-Key: your-api-key`

Check your client's documentation for how to set custom headers on MCP connections.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_API_KEY` | (none) | API key that clients must provide in `X-API-Key` header |
| `PORT` | `8000` | HTTP port (Railway sets this automatically) |
| `MCP_PORT` | `8000` | MCP port (set equal to PORT for single-port mode on Railway) |

---

## Troubleshooting

### Tools don't appear in Claude Code

1. Check the MCP config: `claude mcp list`
2. Make sure the URL ends with `/mcp` (not `/api/mcp` or just the root)
3. Restart Claude Code after adding the server
4. Test the endpoint directly:
   ```bash
   curl -s -o /dev/null -w "HTTP %{http_code}" \
     -H "X-API-Key: your-api-key" \
     https://your-url/mcp
   ```

### 401 Unauthorized

Your API key is missing. Make sure:
- The `X-API-Key` header is set in your client config
- The key matches the `ARIADNE_API_KEY` environment variable on the server

### 403 Forbidden

Your API key is wrong or revoked. Check:
- The key value matches exactly (no extra spaces or quotes)
- The `ARIADNE_API_KEY` env var is set on the deployment

### Connection timeout

- Is the deployment running? Check your hosting dashboard.
- Health check: `curl https://your-url/api/health` (no auth needed)
- Check deployment logs for startup errors

### Collecting diagnostics

```bash
echo "=== Health ===" && curl -s https://your-url/api/health 2>&1
echo "=== Auth ===" && curl -s -o /dev/null -w "HTTP %{http_code}" -H "X-API-Key: your-key" https://your-url/api/stats 2>&1
echo "=== MCP ===" && curl -s -o /dev/null -w "HTTP %{http_code}" -H "X-API-Key: your-key" https://your-url/mcp 2>&1
```

Share this output when [opening an issue](https://github.com/anthropics/ariadne-core/issues).
