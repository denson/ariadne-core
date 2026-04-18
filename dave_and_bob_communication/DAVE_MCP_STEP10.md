# Step 10: Setup script writes env var reference in .mcp.json, not literal key

## The problem

The setup script writes the literal API key into `.mcp.json`. Any agent can read that file and extract the key — which is exactly what happened twice, exposing the key in chat history.

## What to do

### 10a: Setup script — .mcp.json uses env var reference

**File:** `scripts/setup.py`

Find where the setup script writes `.mcp.json` (search for `X-API-Key` or `mcp.json` or `mcpServers`). Change it to write `${ARIADNE_API_KEY}` instead of the literal key value.

**Current (insecure):**
```json
"X-API-Key": "ak-the-actual-secret-key-here"
```

**Fixed (secure):**
```json
"X-API-Key": "${ARIADNE_API_KEY}"
```

Claude Code resolves `${ARIADNE_API_KEY}` at runtime from the environment. The `.env` file (already gitignored) has the actual value.

### 10b: Update .mcp.json.template

**File:** `.mcp.json.template` (repo root)

Change the placeholder to match:

```json
{
  "mcpServers": {
    "ariadne-core": {
      "type": "http",
      "url": "https://YOUR-DEPLOYMENT.up.railway.app/mcp",
      "headers": {
        "X-API-Key": "${ARIADNE_API_KEY}"
      }
    }
  }
}
```

### 10c: Fix public URL resolution in request_upload_url

**File:** `src/pipeline/mcp_server.py`

Find where `request_upload_url` reads the base URL (Dave used `ARIADNE_PUBLIC_BASE_URL` with a localhost fallback in Step 9).

Change the resolution order to:
1. `RAILWAY_PUBLIC_DOMAIN` — Railway sets this automatically on every deployment
2. `ARIADNE_PUBLIC_BASE_URL` — manual override if not on Railway
3. **No fallback** — if neither is set, return an error: "Cannot generate upload URL: no public domain configured. Set RAILWAY_PUBLIC_DOMAIN or ARIADNE_PUBLIC_BASE_URL."

Remove the `localhost` fallback entirely. A presigned URL pointing to localhost is useless and misleading.

Build the URL as `https://{domain}` — Railway domains are always HTTPS.

## Do not touch

- SPEC.md, skills, docs

## Do not commit

Report when done. Leave for Bob.
