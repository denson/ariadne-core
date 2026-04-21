# Connecting Clients to Ariadne Core

This guide covers how to connect AI clients to your Ariadne Core deployment. The service must be deployed first — see [installation.md](installation.md) if you haven't set that up yet.

## Architecture

Ariadne Core runs as a hosted service. All clients connect over HTTPS with OAuth 2.1 Bearer JWT authentication (Auth0).

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
     │  │  │  └── Claude Cowork
     │  │  └───── OpenClaw
     │  └──────── Open Brain
     └─────────── Claude Code

Authentication is OAuth 2.1 Bearer JWT (Auth0) across all editions. Clients
discover the Auth0 config via `GET /.well-known/ariadne-config` (unauthenticated)
and send `Authorization: Bearer <jwt>` on every request.
```

All endpoints except `/api/health` and `/.well-known/ariadne-config` require an `Authorization: Bearer <jwt>` header.

## Interim state (Pass 2 landed, Pass 3 pending)

Ariadne Core uses Auth0 OAuth 2.1 Bearer JWT as of the `ariadne--xft.2` merge
(commit `54165c9`). The `ariadne login` CLI that runs the PKCE flow and caches a
refresh token in the OS keyring is landing in ticket `ariadne--xft.5`. Until
then, obtain a test JWT from **Auth0 dashboard → Applications → your app → Test
tab → copy the access token**, then paste it into `Authorization: Bearer <jwt>`
in your client. Clients can discover what tenant/audience a server expects via:

```bash
curl https://your-url.up.railway.app/.well-known/ariadne-config
```

## Prerequisites

1. **Ariadne Core deployed** with a public HTTPS URL (e.g., `https://ariadne-core-production.up.railway.app`)
2. **Your JWT** — a test access token from Auth0 dashboard → Applications → your app → Test tab (for now; post-xft.5, `ariadne login` handles this)

---

## Claude Code

Claude Code connects via MCP. Use the CLI to configure:

```bash
claude mcp add ariadne-core https://your-url.up.railway.app/mcp \
  --transport http --scope user \
  --header "Authorization:Bearer your-jwt-here"
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

Open Brain connects via MCP or the REST API with the `Authorization: Bearer <jwt>` header on all requests.

```bash
# Search documents
curl -X POST https://your-url/api/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-here" \
  -d '{"query": "quarterly revenue trends", "top_k": 5}'

# Upload and convert a document
curl -X POST https://your-url/api/upload \
  -H "Authorization: Bearer your-jwt-here" \
  -F "file=@report.pdf"

# List collections
curl -H "Authorization: Bearer your-jwt-here" https://your-url/api/collections
```

OB1 agents should pass `agent_type: "ob1"` and `initiated_by: "user:name"` in request bodies for provenance tracking.

---

## OpenClaw (MCP or REST API)

Same as Open Brain — connect via MCP or REST API with the `Authorization: Bearer <jwt>` header. OpenClaw agents should use `agent_type: "openclaw"` for provenance.

---

## Cursor

Cursor supports MCP. Add the server via Cursor Settings:

1. Press `Cmd+Shift+J` (Mac) or `Ctrl+Shift+J` (Windows)
2. Navigate to **Tools & MCP**
3. Click **+ Add New MCP Server**
4. Set type to **streamable-http**
5. URL: `https://your-url.up.railway.app/mcp`
6. Add header: `Authorization: Bearer your-jwt-here`

Restart Cursor and check the MCP Logs output panel.

---

## Other MCP Clients

Any MCP client that supports Streamable HTTP transport can connect. The general pattern:

- **URL:** `https://your-url.up.railway.app/mcp`
- **Transport:** Streamable HTTP
- **Auth header:** `Authorization: Bearer your-jwt-here`

Check your client's documentation for how to set custom headers on MCP connections.

---

## Environment Variables

These are the server-side env vars your Ariadne Core deployment reads (not the client):

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH0_DOMAIN` | (none) | Auth0 tenant domain (e.g. `dev-xxxxx.us.auth0.com`). Used to build the JWKS URL and expected `iss` claim. |
| `AUTH0_CLIENT_ID` | (none) | Auth0 native-app client ID. Returned by `/.well-known/ariadne-config` so clients can run PKCE. |
| `AUTH0_AUDIENCE` | (none) | Auth0 API audience identifier (must match `aud` on every accepted JWT). |
| `ARIADNE_UPLOAD_SIGNING_SECRET` | (none) | HMAC secret for presigned upload URLs. Not an auth credential. |
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
     -H "Authorization: Bearer your-jwt-here" \
     https://your-url/mcp
   ```

### 401 Unauthorized

The server returns a specific `detail` string in the JSON body — that tells you exactly which part of the auth chain failed:

- `missing_token` — no `Authorization` header; add `Authorization: Bearer <jwt>`
- `wrong_scheme` — header present but not `Bearer` (e.g. old `X-API-Key` config); switch to `Authorization: Bearer <jwt>`
- `malformed_token` — JWT is not structurally valid (not three base64 parts)
- `invalid_signature` — signature doesn't verify against the JWKS; token likely signed by a different Auth0 tenant
- `wrong_audience` — JWT `aud` doesn't match the server's `AUTH0_AUDIENCE`
- `wrong_issuer` — JWT `iss` doesn't match `https://<AUTH0_DOMAIN>/`
- `expired_token` — JWT `exp` is in the past; grab a fresh test token from Auth0 dashboard
- `unknown_kid` — key ID in the JWT header isn't in the JWKS (even after a forced refresh)
- `missing_sub_claim` — token is valid but has no `sub` (shouldn't happen for Auth0)
- `invalid_token` — catch-all for any other JWT error

Compare your JWT's claims (decode at https://jwt.io) against the expected values:

```bash
curl https://your-url/.well-known/ariadne-config
```

### 500 `auth_misconfigured`

The server's `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, or `AUTH0_AUDIENCE` env var is unset. Set all three in your Railway variables and redeploy.

### Connection timeout

- Is the deployment running? Check your hosting dashboard.
- Health check: `curl https://your-url/api/health` (no auth needed)
- Discovery check: `curl https://your-url/.well-known/ariadne-config` (no auth needed; confirms Auth0 config is set on server)
- Check deployment logs for startup errors

### Collecting diagnostics

```bash
echo "=== Health ===" && curl -s https://your-url/api/health 2>&1
echo "=== Auth0 config ===" && curl -s https://your-url/.well-known/ariadne-config 2>&1
echo "=== Stats (auth) ===" && curl -s -o /dev/null -w "HTTP %{http_code}" -H "Authorization: Bearer your-jwt" https://your-url/api/stats 2>&1
echo "=== MCP (auth) ===" && curl -s -o /dev/null -w "HTTP %{http_code}" -H "Authorization: Bearer your-jwt" https://your-url/mcp 2>&1
```

Share this output when [opening an issue](https://github.com/anthropics/ariadne-core/issues).
