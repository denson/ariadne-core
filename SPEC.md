# Ariadne Core — Specification

This document describes how Ariadne Core works. It is the source of truth for the README, skills, client package, and all agent instructions. If the code doesn't match this doc, the code is wrong.

---

## What it is

Ariadne Core is an open source document extraction and retrieval pipeline. It takes documents in 20+ formats, produces clean Markdown and vector embeddings, and exposes them via a REST API. Agents and scripts interact with it through the `ariadne-core-client` Python package, which wraps the REST API.

The core value: a 100-page PDF that would consume 50,000-100,000 tokens as raw content becomes 5,000 tokens of clean, searchable Markdown. Documents are chunked, embedded, and stored with full provenance metadata so any agent can find them later.

## Supported formats

Over 20 formats: PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV, HTML, TXT, Markdown, JSON, XML, RTF, EPUB, EML, MSG, ZIP (recursive extraction), Jupyter notebooks (.ipynb), RST, ORG, WAV, MP3, M4A.

Images (JPG, PNG, GIF, JPEG, WEBP) are supported but require a vision API key (`ARIADNE_IMAGE_ENRICHMENT_API_KEY`) for content extraction. Without it, image files are accepted but produce empty output with a warning.

Not supported: scanned PDFs (no text layer), legacy Office (.doc, .ppt), complex layouts with merged cells, BMP, TIFF, HEIC.

## Architecture

Ariadne Core has two components:

1. **Server** — a REST API backed by Postgres + pgvector. Runs on Railway, Fly.io, any Docker host, or any VPS. Handles extraction, chunking, embedding, storage, search, and document lifecycle.

2. **Client** (`ariadne-core-client`) — a pip-installable Python package that wraps the REST API. Agents, scripts, and CI pipelines use this. Zero dependencies beyond stdlib. Provides both a Python API and a CLI (`ariadne` command).

```
Railway / Fly.io / VPS
┌─────────────────────────┐
│  ariadne-core server    │
│  ├── REST API            │
│  ├── Postgres + pgvector │
│  ├── MarkItDown          │
│  └── Chunking/Embedding  │
└─────────────────────────┘
         ▲
         │  HTTPS + Authorization: Bearer <jwt>
         │  (Auth0 OAuth 2.1; discovery at /.well-known/ariadne-config)
         │
┌────────┴─────────────────┐
│  Clients                 │
│  ├── ariadne-core-client │  pip install ariadne-core-client
│  │   ├── Python API      │  from ariadne_core_client import AriadneClient
│  │   └── CLI             │  ariadne ingest, ariadne search, ...
│  ├── Any HTTP client     │  curl, requests, urllib
│  └── Any LLM agent      │  via client package or direct REST
└──────────────────────────┘
```

The server and client live in the same monorepo (`denson/ariadne-core`) as separate Python packages. They never import each other — the REST API is the contract between them.

### Connecting clients

All clients connect to the same HTTPS endpoint. The URL depends on where you deploy (e.g., `https://ariadne-core.up.railway.app`).

All endpoints except `/api/health` and `/.well-known/ariadne-config` require authentication via an `Authorization: Bearer <jwt>` header. JWTs are issued by Auth0 — see the `Authentication` section below for the full contract.

**LLM agents (Claude Code, Cursor, etc.):** Install the client package and use the Python API. The client obtains and refreshes access tokens via the PKCE flow (run `ariadne login` once to populate the OS keyring) and resolves the server host from `--host` / `ARIADNE_HOST` env / `~/.config/ariadne/default` (in that precedence; written by `ariadne login`). **The client never reads tokens or host URLs from a `.env` file.**

```bash
pip install ariadne-core-client
# or
uv add ariadne-core-client
```

**Scripts and CI:** Use the client package or call the REST API directly.

**Any HTTP client:** Call the REST API endpoints with an `Authorization: Bearer <jwt>` header. See the REST API section for full endpoint documentation and the `Authentication` section for how to obtain a token.

### Document input — three paths

The server runs remotely. Local file bytes must be sent over HTTP. There are three ingestion paths, in order of preference:

| Priority | Method | Token cost | When to use |
|----------|--------|-----------|-------------|
| 1st | URL | Zero — server fetches directly | Document is at an HTTP/HTTPS URL |
| 2nd | File path | Zero — client uploads via HTTP | Document is a local file |
| 3rd | Bytes from context | Already paid | File was dropped in chat UI, content already in LLM context |

**Via the client package:**
```python
client = AriadneClient()

# From URL (preferred — server fetches, zero tokens)
doc = client.ingest_url("https://example.com/report.pdf", collection="reports")

# From local file (client uploads, zero tokens)
doc = client.ingest_file("path/to/report.pdf", collection="reports")

# From bytes already in context (tokens already spent)
doc = client.ingest_bytes(content, filename="report.pdf", collection="reports")
```

**Via REST directly** (two-step — prefer the client package which handles this in one call):
1. Upload: `POST /api/upload` with multipart form data, get back a server-side path
2. Convert: `POST /api/documents` with the server-side path as `uri`

**Via CLI:**
```bash
ariadne ingest report.pdf --collection reports
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
```

Never pass raw file bytes through an LLM's context window when you can avoid it. A 6 MB PDF as base64 is ~8 MB, roughly 1.5-2M tokens of payload before any processing. Use `ingest_url` or `ingest_file` instead.

### Self-hosting

Deploy with Docker or any container platform:

```bash
# Railway (recommended)
railway up

# Or any Docker host
docker compose up -d
```

The `docker-compose.yml` runs the application and Postgres together. Environment variables configure API keys and database credentials.

### Authentication

Ariadne Core uses **OAuth 2.1 Bearer JWT** for all protected endpoints. Auth0 is the identity provider; the server validates JWTs against Auth0's JWKS. The prior `X-API-Key` path was removed in Pass 2 of the `ariadne--xft` epic (commit `54165c9`); the legacy implementation is preserved on branch `legacy/api-key` and tag `v0.x-legacy-api-key` for reference.

**Server environment variables** (required; the server returns a structured `500 auth_misconfigured` on any protected request if any is unset):

| Variable | Description | Example |
|---|---|---|
| `AUTH0_DOMAIN` | Auth0 tenant domain (no scheme, no trailing slash). The server computes the issuer as `https://{AUTH0_DOMAIN}/` and the JWKS URL as `https://{AUTH0_DOMAIN}/.well-known/jwks.json`. | `dev-1inpk4rtyzwxmcgm.us.auth0.com` |
| `AUTH0_CLIENT_ID` | Auth0 Native Application client ID. Exposed verbatim via `/.well-known/ariadne-config` so clients can run the PKCE flow. | `ixpErHZnMADzV7wTEcO48N3oaiNCjNUj` |
| `AUTH0_AUDIENCE` | Auth0 API identifier. Must match the `aud` claim on issued JWTs. | `https://ariadne-core` |

`ARIADNE_UPLOAD_SIGNING_SECRET` is a separate HMAC secret for presigned upload URLs (the HMAC-authenticated `POST /api/upload/signed` endpoint) — not an auth credential. It does not grant access to any endpoint and is never handed to clients.

**Wire format.** Protected endpoints expect:

```
Authorization: Bearer <jwt>
```

**Accepted algorithms.** `RS256` only. Symmetric algorithms (`HS256`) are rejected — Auth0 signs with its private key and the server verifies with the public key fetched from JWKS.

**Claims the server checks.** On each request the server validates:

- Signature matches a key in Auth0's JWKS (fetched from `https://{AUTH0_DOMAIN}/.well-known/jwks.json`, cached 600s with forced-refresh on unknown `kid`)
- `iss` equals `https://{AUTH0_DOMAIN}/` (trailing slash — Auth0 emits it)
- `aud` equals `AUTH0_AUDIENCE`
- `exp` is in the future
- `sub` is present and is a non-empty string

On success the server exposes a `Principal{user_id, email}` to route handlers. `user_id` is the Auth0 `sub` claim (stable across refreshes) and is used for `agent_id` provenance attribution. `email` is PII; it is available at the request boundary but never written to stdout/logs.

When the caller does not provide an explicit `agent_id`, the server writes `auth0:<sub>` into `interaction_log.agent_id`. The colon prefix keeps the interaction log grep-parseable across the X-API-Key→OAuth transition (previously `api-key:<name>`). See `src/pipeline/api/routes.py:101-105`.

**Error responses.** Every auth failure returns `{"detail": "<reason>"}` with HTTP 401, using one of these detail strings (stable contract — test suites assert on them):

| Detail string | Status | Meaning |
|---|---|---|
| `missing_token` | 401 | No `Authorization` header, an empty `Authorization` header, or a header whose stripped value is the bare `Bearer` keyword (any case — `Bearer`, `bearer`, `BEARER`, etc. — with the credential portion empty; the client intended Bearer auth but the token is missing). |
| `wrong_scheme` | 401 | `Authorization` header present, non-empty after strip, and not the bare `Bearer` keyword (any case) — i.e. a non-Bearer scheme such as `Basic` or `Digest`. |
| `malformed_token` | 401 | JWT not parseable as three base64 parts / header missing `kid`. |
| `invalid_signature` | 401 | Signature does not verify against the JWKS key. |
| `wrong_audience` | 401 | `aud` claim does not match `AUTH0_AUDIENCE`. |
| `wrong_issuer` | 401 | `iss` claim does not match `https://{AUTH0_DOMAIN}/`. |
| `expired_token` | 401 | `exp` claim is in the past. |
| `kid_not_in_jwks` (emitted as `unknown_kid`) | 401 | Token's `kid` not in JWKS even after a forced JWKS refresh. |
| `invalid_token` | 401 | Catch-all for PyJWT `InvalidTokenError` subclasses not covered above. |
| `missing_sub_claim` | 401 | Token otherwise valid but has no `sub` claim. |
| `auth_misconfigured` | 500 | `AUTH0_DOMAIN` or `AUTH0_AUDIENCE` unset on the server at request time. Deploy error, not a client error. |

Response bodies never echo token contents, header values, or Auth0 error payloads.

**Sources:** `src/pipeline/auth_oauth.py` (the middleware and Principal contract), `src/pipeline/api/discovery.py` (the `/.well-known/ariadne-config` endpoint), `OAUTH_PLAN.md` (design doc — auth passes 1 through 3 of epic `ariadne--xft`).

### Discovery endpoint — `GET /.well-known/ariadne-config`

Unauthenticated. Returns the Auth0 tenant config a client needs to run the login flow:

```json
{
  "auth": {
    "issuer":    "https://<AUTH0_DOMAIN>/",
    "client_id": "<AUTH0_CLIENT_ID>",
    "audience":  "<AUTH0_AUDIENCE>",
    "scope":     "openid profile email offline_access"
  }
}
```

`offline_access` is what makes Auth0 issue a refresh token alongside the access token — the `ariadne login` CLI caches the refresh token in the OS keyring and exchanges it for fresh access tokens without user interaction.

If any of `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_AUDIENCE` is unset, the endpoint returns `500 {"detail": "auth_misconfigured"}` — the same server-misconfiguration signal as the Bearer path. Because this endpoint is unauthenticated, a deploy that forgot to set the Auth0 env vars is caught by the first client GET rather than the first authenticated request.

**Client-side authentication (Pass 3, landed in `ariadne--xft.5.1` + `xft.5.5` + `xft.5.3`):** The client package resolves credentials in this order:

1. Explicit `host` parameter: `AriadneClient(host="https://...", agent_type=..., initiated_by=..., model=...)`
2. `ARIADNE_HOST` environment variable
3. `~/.config/ariadne/default` (written by `ariadne login`)

The Bearer JWT is sourced separately by `auth.get_access_token(host)` with precedence:

1. `ARIADNE_ACCESS_TOKEN` environment variable (escape hatch — bypasses keyring; for CI/automation)
2. OS-keyring-cached access token (populated by `ariadne login`)
3. Silent refresh via stored refresh token if the cached access token is expired

The client never reads tokens from a `.env` file. The legacy `ARIADNE_URL` env var is removed; use `ARIADNE_HOST`. The legacy `.mcp.json` server-URL extraction is removed. The client never prints, logs, or exposes credentials.

## Configuration

All configuration is controlled via environment variables. The config file (`config/ariadne.yaml`) interpolates them.

### Required

| Variable | Description |
|----------|-------------|
| `DB_PASSWORD` | Postgres password |
| `AUTH0_DOMAIN` | Auth0 tenant domain (e.g. `dev-xxxxx.us.auth0.com`). Used to build the JWKS URL and the expected `iss` claim. |
| `AUTH0_CLIENT_ID` | Auth0 native-app client ID. Returned by `/.well-known/ariadne-config` so clients can run the PKCE flow. |
| `AUTH0_AUDIENCE` | Auth0 API audience identifier (e.g. `https://ariadne-core`). Must match the `aud` claim on every accepted JWT. |
| `ARIADNE_UPLOAD_SIGNING_SECRET` | HMAC secret for presigned upload URLs. Not an auth credential — used only to sign short-lived upload tokens. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |

### Embedding

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_EMBEDDING_API_KEY` | *(required for search)* | API key for the embedding provider |
| `ARIADNE_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model name |
| `ARIADNE_EMBEDDING_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Gemini native API root. See "Provider constraints" below. |
| `ARIADNE_EMBEDDING_EXTRA_PARAMS` | `{}` | JSON string of provider-specific options passed to the embedding API (planned — not yet implemented) |

### Image enrichment

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_IMAGE_ENRICHMENT_API_KEY` | *(optional)* | API key for vision model used to describe images found in extracted documents |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | `gemini-2.0-flash` | Vision model name |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Gemini native API root. See "Provider constraints" below. |

### Language validation

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_LANGUAGE_VALIDATION_API_KEY` | *(optional — falls back to embedding key)* | API key for the LLM that validates .txt file language/coherence |
| `ARIADNE_LANGUAGE_VALIDATION_MODEL` | `gemini-2.0-flash-lite` | Lightweight model for language validation |
| `ARIADNE_LANGUAGE_VALIDATION_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Gemini native API root. See "Provider constraints" below. |

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | REST API port. On Railway, set automatically. |
| `DATABASE_URL` | — | Postgres connection string. Railway injects `DATABASE_URL_PRIVATE` (internal network, no egress fees) and `DATABASE_URL` (public); the server prefers `DATABASE_URL_PRIVATE` when available. |

### Provider constraints

Ariadne's bundled embedding, image enrichment, and language validation clients call **Gemini native endpoints** directly:

| Subsystem | Endpoint | Method |
|---|---|---|
| Embedding | `{base}/models/{model}:batchEmbedContents` | `POST` |
| Image enrichment | `{base}/models/{model}:generateContent` | `POST` |
| Language validation | `{base}/models/{model}:generateContent` | `POST` |

All three authenticate with the `x-goog-api-key: <key>` header. The OpenAI-compat shim at `{base}/openai/*` is **not** supported in v1 — Google's new `AQ.*`-format API keys (April 2026) reject every auth variant on the shim ("Missing or invalid Authorization header" with `x-goog-api-key` alone, "Multiple authentication credentials received" with `Authorization: Bearer`). Use the native paths only.

#### Embedding — `batchEmbedContents` contract

Request body:

```json
{
  "requests": [
    {
      "model": "models/{model}",
      "content": {"parts": [{"text": "<chunk text>"}]},
      "outputDimensionality": 1536
    }
  ]
}
```

Response body:

```json
{
  "embeddings": [
    {"values": [0.01, -0.02, ...]}
  ]
}
```

`outputDimensionality` is optional; omit to get the model's native dimension. Batch size up to 100 requests per call.

#### Image enrichment / language validation — `generateContent` contract

Request body (vision — inline image):

```json
{
  "contents": [{
    "parts": [
      {"inlineData": {"mimeType": "image/png", "data": "<base64>"}},
      {"text": "<prompt>"}
    ]
  }]
}
```

Request body (text-only — language validation):

```json
{
  "contents": [{
    "parts": [{"text": "<prompt>"}]
  }]
}
```

Response body:

```json
{
  "candidates": [{
    "content": {
      "parts": [{"text": "<reply>"}]
    }
  }]
}
```

#### Swapping providers later

Pointing the embedder or vision client at a non-Gemini OpenAI-compatible provider (OpenAI proper, Together, Groq, etc.) is a deliberate out-of-scope change for v1. It would require changing the endpoint construction, payload shape, response parser, and auth header. A future configuring agent can make that change per-provider — Ariadne does not maintain a provider abstraction.

---

## REST API

The REST API is the server's only interface. All endpoints are under `/api/`. All processing is synchronous — the endpoint returns the full result when it completes.

All endpoints except `/api/health` and `/.well-known/ariadne-config` require an `Authorization: Bearer <jwt>` header. JWTs are validated against Auth0's JWKS (RS256, `iss`/`aud`/`exp` checked). See the [Authentication](#authentication) section above for the full contract and error-response table.

### Endpoint summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check (no auth) |
| `POST` | `/api/upload` | Upload a file, returns server-side path |
| `POST` | `/api/documents` | Convert and store a document |
| `GET` | `/api/documents` | List documents (paginated) |
| `GET` | `/api/documents/{id}` | Get full document by ID |
| `PATCH` | `/api/documents/{id}` | Update document metadata (tags, collection) |
| `DELETE` | `/api/documents/{id}` | Soft-delete a document (48h recovery window) |
| `POST` | `/api/documents/{id}/restore` | Restore a soft-deleted document |
| `POST` | `/api/search` | Semantic search over stored chunks |
| `POST` | `/api/ingest` | Batch directory ingestion (server-side paths) |
| `GET` | `/api/collections` | List all collections |
| `POST` | `/api/collections` | Create a new collection |
| `DELETE` | `/api/collections/{name}` | Soft-delete all documents in a collection |
| `POST` | `/api/collections/{name}/restore` | Restore a soft-deleted collection |
| `GET` | `/api/stats` | System statistics |
| — | `/api/bw/projects/{slug}/...` | Beadwork ticket store HTTP surface (23 endpoints — see [bw HTTP surface](#bw-http-surface)) |

---

### Error responses

All endpoints return errors as JSON with this structure:

```json
{"detail": {"message": "Human-readable error description", "document_id": "uuid-if-applicable"}}
```

Common HTTP status codes:
- `400` — Invalid request (missing required fields, malformed JSON)
- `401` — Authentication failed (see [Authentication](#authentication) for the full `detail` string table — `missing_token`, `wrong_scheme`, `malformed_token`, `invalid_signature`, `wrong_audience`, `wrong_issuer`, `expired_token`, `unknown_kid`, `missing_sub_claim`, `invalid_token`)
- `404` — Document or collection not found
- `410` — Soft-delete window expired (restore too late)
- `413` — Source size between the soft cap (`max_source_bytes`, default 200 MB) and the hard cap (`max_source_bytes_hard`, default 5 GB) on `POST /api/documents` when `require_confirmation_above_soft=true`. The response body carries `code: "confirmation_required"` and a server-issued HMAC `confirmation_token`; re-submit the same request with the token to bypass the soft-cap check. See "Source-size confirmation flow" under `POST /api/documents` for the structured body shape and walkthrough.
- `422` — Extraction failed (encoding error, unsupported format, corrupt file), source read failed (file not found, URL fetch error), embedding failed (transient provider error), per-request `chunking_config` validation failed (unknown keys — see "Per-request chunking config" under `POST /api/documents`), per-request `ingest_config` validation failed (unknown keys, OR a server-policy key like `confirmation_token_ttl_seconds` that cannot be overridden per-request — see "Per-request size caps" under `POST /api/documents`), source size at or above the hard cap (`code: "exceeds_hard_limit"`, no token), OR source size between caps when `require_confirmation_above_soft=false` (`code: "exceeds_soft_cap_strict"`, no token; legacy strict mode). Ingest is transactional: on a 422 no document row is written.
- `503` — Embedding not configured (search endpoint only)

---

### `GET /api/health`

Health check. No authentication required.

**Response:**
```json
{"status": "healthy", "version": "0.1.0", "commit": "4a33658", "engine": "markitdown", "embedding_enabled": true}
```

The `commit` field is the short (7-char) SHA of the deployed commit, resolved on first request from `RAILWAY_GIT_COMMIT_SHA` (Railway-injected when deploying from a GitHub trigger), then `GIT_COMMIT`, then `.git/HEAD` for local dev, then the literal string `"unknown"`. Cached at module level for the lifetime of the process; a container restart re-reads it (which is the lifecycle event a SHA flip corresponds to anyway).

**Client method:** `client.health()`

---

### `POST /api/upload`

Upload a local file to the server. Returns a server-side path for use with `POST /api/documents`.

**Request:** Multipart form data with `file` field.

```bash
curl -s -X POST "$ARIADNE_HOST/api/upload" \
  -H "Authorization: Bearer $ARIADNE_ACCESS_TOKEN" \
  -F "file=@path/to/document.pdf"
```

**Response:**
```json
{"path": "data/uploads/document.pdf", "filename": "document.pdf", "size_bytes": 38560}
```

Use the `path` value as `uri` in `POST /api/documents`.

---

### `POST /api/documents`

Convert a document to clean Markdown. By default, also chunks, embeds, and stores the result for future search.

**Request body (JSON):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `uri` | string | (required) | HTTP/HTTPS URL or server-side path from `/api/upload` |
| `store` | bool | `true` | Chunk, embed, and store in vector DB. `false` for one-time extraction |
| `collection` | string | `"default"` | Logical namespace. Dedup is scoped per collection |
| `tags` | list[str] | `[]` | Tags applied to the document. Searchable via the `tags` filter |
| `force` | bool | `false` | Re-process even if fingerprint already exists in this collection |
| `chunking_config` | dict | `null` | Override chunking. Keys: `strategy` (`"by_title"`, `"by_page"`, `"fixed_size"`), `max_characters`, `overlap` |
| `ingest_config` | dict | `null` | Per-request override for ingest knobs (`max_source_bytes`, `max_source_bytes_hard`, `require_confirmation_above_soft`). Unknown keys — and server-policy keys that cannot be overridden per-request, namely `confirmation_token_ttl_seconds` — raise 422. See "Per-request size caps" below. |
| `confirmation_token` | string | `null` | Opaque token (HMAC-signed; treat as a string, do not parse) returned by a prior 413 `confirmation_required` response. Re-submit with this token to bypass the soft-cap check. The hard cap is still enforced via the chunked-read accumulator. See "Source-size confirmation flow" below. |
| `inline_content` | bytes | `null` | _(internal / bw bridge — Phase 3, ariadne--8fd.5)_ Caller-supplied document bytes. When set, the server skips the URI source-read (no HTTP fetch, no `file://` open, no `Path.stat()` probe) and fingerprints / ingests the inline bytes directly; the `uri` becomes a synthetic identifier displayed as `source_file`. Used by the bw HTTP bridge to ingest the freshly-rendered frontmatter+body payload without a round-trip through the filesystem. Because no URI read occurs, **the `max_source_bytes` soft cap and `max_source_bytes_hard` hard cap are not enforced on this path** — the cap exists to protect against unbounded URI reads, not against bytes already committed to RAM by a trusted internal caller. Not part of the public surface; reserved for first-party bridges. See design §D2.6 for the inline-ingest contract. |
| `agent_id` | string | `null` | Caller identity |
| `agent_type` | string | `null` | Client type (e.g. `"claude-code"`, `"script"`) |
| `model` | string | `null` | LLM model the caller is running |
| `initiated_by` | string | `null` | Human or system identity (e.g. `"user:denson"`) |
| `agent_notes` | string | `null` | Why this action is being taken |
| `agent_metadata` | dict | `null` | Structured metadata (source_url, intent, findings, etc.) |

**Response:** JSON with `document_id`, `source_file`, `title`, `markdown`, `file_type`, `engine`, `content_fingerprint`, `collection`, `chunk_count`, `was_dedup_skip`, `provenance`, `warnings`, `warnings_count`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `embedding_model`, `store_status` (`"stored"` / `"not_stored"` / `"skipped"` / `"error"`), `interactions`. `warnings_count` equals `len(warnings)` and is included on every response path that emits `warnings` (success, dedup-skip, embedding-failure).

**Dedup behavior:** If a document with the same content fingerprint already exists in the target collection, extraction/chunking/embedding are skipped. The existing document is returned, and a new `document_interactions` row is recorded. Use `force: true` to re-process.

**Embedding-failure behavior:** If the embedding provider raises
during a store-mode ingest, the document markdown is still stored
(future retries can find it by fingerprint), but no chunks are
written to the vector store. `store_status` is `"error"`,
`chunk_count` is `0`, and `warnings` contains an `"Embedding failed: ..."`
entry with the provider error. Callers should treat this as a retryable
failure: fix the underlying provider issue, then re-ingest with
`force: true`.

**Chunking auto-selection:** If no `chunking_config` is provided, the strategy is chosen by file type: `.pptx` -> `by_page`, `.csv`/`.xlsx` -> `fixed_size`, `.txt` with no headings -> `fixed_size` with high overlap (`overlap=400`), everything else -> `by_title`.

**Per-request chunking config — layering and validation:** A per-request `chunking_config` payload layers onto the auto-selected baseline: omitted knobs inherit from `auto_select_strategy()` output, not from the chunker dataclass defaults. Worked example: a per-request payload `{"strategy": "by_title"}` on a headingless `.txt` resolves to `ChunkingConfig(strategy="by_title", overlap=400, ...)` — auto-select's `overlap=400` boost survives the underlying `dataclasses.replace` because the per-request payload did not override `overlap`. Unknown keys in `chunking_config` raise `ValueError` naming both the offending key(s) and the valid keys; the route layer captures this and surfaces it as **HTTP 422** with `message: "Invalid chunking config: Unknown chunking config keys: [...]. Valid keys: [...]."`.

**Per-request size caps:** A per-request `ingest_config` payload overrides the server's `IngestConfig` defaults for the lifetime of one request. Recognized fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_source_bytes` | int | `209715200` (200 MB) | **Soft cap.** Sources at or above this size trigger the confirmation flow (HTTP 413 with `confirmation_required`) when `require_confirmation_above_soft=true`. Field name unchanged from pre-m5e; the meaning rotated from "hard refuse" to "soft cap that triggers confirmation," but callers passing the same field continue to work. |
| `max_source_bytes_hard` | int | `5368709120` (5 GB) | **Hard cap.** Sources at or above this size are refused outright with HTTP 422 `exceeds_hard_limit` — no token, no override path. Also enforced as the post-confirmation memory-safety floor: a confirmed-but-grew source still aborts at the hard cap via the chunked-read accumulator. Must be `>= max_source_bytes`. |
| `require_confirmation_above_soft` | bool | `true` | When `true`, sources between the soft and hard caps return 413 `confirmation_required`. When `false`, the soft cap acts as a strict cap (legacy semantics) and sources between caps return HTTP 422 `exceeds_soft_cap_strict` — no token. Useful for CI / scripted batch ingest that prefers fail-fast over confirmation. |

**Server-policy fields (NOT per-request overridable):** `confirmation_token_ttl_seconds` (default `300`, the TTL stamped into a 413's `ttl_seconds` field) is a deployment-policy knob configurable only at startup via the YAML config — not via `ingest_config`. A request that sets it returns HTTP 422 with the unknown-keys error message, surfacing the operator's mistake loudly rather than silently flowing a per-request value through. The denylist is intentional and will grow as more fields are promoted to server-only policy.

Unknown keys (typos, fields not in `IngestConfig`) and denied keys (server-policy fields like `confirmation_token_ttl_seconds`) both raise the same **HTTP 422** with `message: "Invalid ingest config: Unknown ingest config keys: [...]. Valid keys: [...]. (...)"`.

**Source-size confirmation flow:** For sources between the soft and hard caps, the server probes the source size before reading and returns a structured 413 `confirmation_required` response carrying an HMAC-signed `confirmation_token`. The caller re-submits the same request body with the token in the `confirmation_token` field to bypass the soft-cap check. Sequence:

1. Client submits `POST /api/documents` with `uri` and no `confirmation_token`.
2. Server probes the source size (HTTP HEAD with `Content-Length` for `http(s)://`, `Path.stat()` for `file://` and bare paths).
3. **`size >= max_source_bytes_hard`** → HTTP **422** with `code: "exceeds_hard_limit"`. No token; the request is fatal at this URI until the source shrinks or `max_source_bytes_hard` is raised server-side.
4. **`max_source_bytes <= size < max_source_bytes_hard`** AND `require_confirmation_above_soft=true` → HTTP **413** with `code: "confirmation_required"` and a structured body (see below) including `confirmation_token` and `ttl_seconds`.
5. The client surfaces the size to the operator (UX is client-side; the server is neutral on how confirmation is gathered) and, on confirm, re-submits the same `uri` with `confirmation_token` set to the value from the 413 body.
6. Server validates the token (HMAC + URI match + `exp`). On VALID it bypasses the soft-cap check and reads up to the hard cap. On TAMPERED / EXPIRED / URI_MISMATCH it returns a fresh 413 with a new token (the simplest UX — caller sees "your token didn't apply, here's a new one"). The hard cap is still enforced via the chunked-read accumulator: a confirmed-but-grew source can still fail with `exceeds_hard_limit` 422 mid-fetch.
7. **`max_source_bytes <= size < max_source_bytes_hard`** AND `require_confirmation_above_soft=false` → HTTP **422** with `code: "exceeds_soft_cap_strict"`. No token; this deployment has opted out of the confirmation flow.

**HEAD failure / `Content-Length` absent:** HEAD failures (405, timeout, network error) and `Content-Length`-missing responses fall through to the GET path. The chunked-read accumulator gates the read at the soft cap; on overrun the server classifies the threshold-crossing observation against the hard cap and returns either `confirmation_required` 413 (soft<size<hard, with `reported_size = bytes_seen` and an "is at least N bytes" message) or `exceeds_hard_limit` 422 (size at or above hard).

**413 response body (`confirmation_required`):**

```json
{
  "detail": {
    "code": "confirmation_required",
    "message": "Source size 364445696 (347 MB) exceeds default cap 209715200 (200 MB). Confirm to proceed; this token is valid for 300s and may be re-submitted to resume after a transient failure.",
    "soft_cap": 209715200,
    "hard_cap": 5368709120,
    "reported_size": 364445696,
    "source": "https://example.org/big.pdf",
    "content_type": "application/pdf",
    "last_modified": "2026-04-15T12:00:00+00:00",
    "confirmation_token": "eyJ2IjoxLCJ1cmkiOi...HZGFEN0pfczQ",
    "ttl_seconds": 300
  }
}
```

`content_type` and `last_modified` are nullable. For `file://` and bare-path sources, `last_modified` is the file's mtime as ISO-8601 UTC and `content_type` is the MIME type guessed via `mimetypes.guess_type` from the filename (nullable if unrecognized). For HTTP sources, the `Last-Modified` header (RFC 7231) is normalized to ISO-8601 UTC; if HEAD did not return either header, the field is `null`. When the size came from a chunked-read overrun (HEAD missing or `Content-Length` absent) the message is phrased "Source size is at least N bytes (Content-Length unavailable from server)" and the token is tagged with `size_precise: false` internally — the caller sees the same wire shape either way.

**422 response body (`exceeds_hard_limit`):**

```json
{
  "detail": {
    "code": "exceeds_hard_limit",
    "message": "Source size 6442450944 (6.0 GB) exceeds hard limit 5368709120 (5.0 GB); cannot override.",
    "reported_size": 6442450944,
    "hard_cap": 5368709120,
    "source": "https://example.org/huge.zip"
  }
}
```

**422 response body (`exceeds_soft_cap_strict`):**

```json
{
  "detail": {
    "code": "exceeds_soft_cap_strict",
    "message": "Source size 364445696 (347 MB) exceeds strict cap 209715200 (200 MB). This deployment has require_confirmation_above_soft=False; raise the cap server-side or use a deployment with confirmation enabled.",
    "reported_size": 364445696,
    "soft_cap": 209715200,
    "hard_cap": 5368709120,
    "source": "https://example.org/big.pdf"
  }
}
```

All three shapes nest under the standard `detail:` envelope. Tokens are valid for `confirmation_token_ttl_seconds` and may be re-used (read-only validation; multi-shot within TTL is supported, covers transient retries during a real ingest). A container restart regenerates the per-process HMAC secret and invalidates in-flight tokens; the caller path is identical to `EXPIRED` — re-submit gets a fresh 413 with a new token.

**Image handling:** If the file is an image format and no vision API key is configured, a warning is returned explaining that a vision API key is needed for image content extraction.

The response also includes `token_savings` — a dict with `original_size` (bytes), `markdown_size` (bytes), and `reduction_ratio` (e.g., `15.2` means 15.2x smaller). This quantifies the extraction efficiency per document.

---

### `GET /api/documents`

List stored documents. Returns metadata only — use `GET /api/documents/{id}` for full content.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `collection` | string | `null` | Filter to a specific collection. Mutually exclusive with `collections` |
| `collections` | list[string] | `null` | Filter to docs whose collection is in this list. Repeat the query param: `collections=a&collections=b`. Mutually exclusive with `collection`. Empty list rejected (422). Each slug must match `^[a-z0-9_-]{1,64}$`. Mirrors the `POST /api/search` `collections` parameter (ariadne--vis) |
| `file_type` | string | `null` | Filter by extension (e.g. `pdf`, `docx`) |
| `tag` | string | `null` | Match docs whose tag list contains this tag |
| `has_warnings` | bool | `null` | If `true`, only docs with at least one warning; if `false`, only docs with none |
| `has_source_reference` | bool | `null` | If `true`, only docs whose `source_reference` (latest-wins from `agent_metadata`) is a non-empty string other than the literal `"unknown"`; if `false`, inverse |
| `include` | list[string] | `[]` | Repeatable. Thickens each row. Accepted: `agent_metadata`, `tags`, `last_interaction`, `markdown` |
| `limit` | int | `20` | Results per page (shape-dependent cap — see below) |
| `offset` | int | `0` | Pagination offset |
| `include_deleted` | bool | `false` | Include soft-deleted documents |

**Response:** JSON with `total_count`, `total_is_exact`, `documents` array. Each row always contains `document_id`, `source_file`, `title`, `file_type`, `collection`, `content_fingerprint`, `chunk_count`, `interaction_count`, `created_at`, `warnings_count`. `include=` values add the corresponding fields.

### Querying documents — filters, includes, and cap

**Filters** (all optional query params on `GET /api/documents`):

| Param | Type | Effect |
|---|---|---|
| `collection` | string | Exact match on collection name. Mutually exclusive with `collections` |
| `collections` | list[string] | Match docs whose collection is in this list (repeat the query param). Mutually exclusive with `collection` |
| `file_type` | string | Exact match (leading dot stripped, so `pdf` and `.pdf` both work) |
| `tag` | string | Match docs whose tag list contains this tag |
| `has_warnings` | bool | If `true`, only docs with at least one warning; if `false`, only docs with none |
| `has_source_reference` | bool | If `true`, only docs whose `source_reference` (latest-wins from `agent_metadata`) is a non-empty string other than `"unknown"`; if `false`, inverse |
| `include_deleted` | bool | Include soft-deleted docs (default `false`) |
| `limit` | int | Max rows per page (shape-dependent cap — see below) |
| `offset` | int | Pagination offset |

> **Multi-collection scoping (ariadne--vis):** `collection` (single) and
> `collections` (list) are mutually exclusive at the request layer.
> Passing both returns `422` with `mutually_exclusive_collections`.
> Passing `collections=` with no value (empty list) returns `422` with
> `empty_collections_list` — omit the parameter to list across every
> collection. Each element of `collections` must match
> `^[a-z0-9_-]{1,64}$` or `422 invalid_collection_slug`. The same
> mutual-exclusion semantics apply on `/api/documents/aggregate`.

> **Filter backing note:** `has_warnings` queries the persisted
> `warnings_count` column; it does not walk `processing_chain`.
> `has_source_reference` queries a denormalized `source_reference`
> column on `documents` that is updated on every interaction write
> using latest-wins semantics (the most recent `agent_metadata`
> entry wins). Both filters are indexed, so they stay O(log n) at
> any collection size. If a historical document has the wrong
> `warnings_count` or `source_reference` value because of a stale
> row, re-ingest with `force=true` to refresh the denormalized
> fields from the current `agent_metadata`.

**Includes** — use `include=` query param (repeatable) to thicken the returned row. Default row is always returned; `include=` adds fields.

| Include value | Adds |
|---|---|
| `agent_metadata` | Latest interaction's `agent_metadata` dict |
| `tags` | Full tag list |
| `last_interaction` | `{agent_notes, action, created_at}` for the most recent interaction |
| `markdown` | Full document markdown body |

Unknown include values return `400` with a list of valid values.

**Cap** — `limit` is bounded by the include set:

| Include set contains | Cap |
|---|---|
| `markdown` | 50 |
| anything else, or default | 500 |

`limit > cap` returns `400` with the applicable cap and rationale.

**Default row shape** (always returned):

```json
{
  "document_id": "...",
  "source_file": "...",
  "title": "...",
  "file_type": "...",
  "collection": "...",
  "content_fingerprint": "...",
  "chunk_count": 42,
  "interaction_count": 3,
  "created_at": "...",
  "warnings_count": 0
}
```

**Brute-force fallback** — if the question you're asking can't be expressed with these filters, paginate `list_documents` with `include=[...]` covering the fields you need, then filter client-side:

```python
all_docs = []
offset = 0
while True:
    page = client.list_documents(
        collection="my-collection",
        include=["agent_metadata", "tags"],
        limit=500,
        offset=offset,
    )
    all_docs.extend(page.documents)
    if len(page.documents) < 500:
        break
    offset += 500
# now filter client-side
```

### Aggregate — group-by summary

`GET /api/documents/aggregate` returns per-group document counts.

**Required:** `group_by` (one of `collection`, `file_type`, `tags`).

**Optional filters** (same semantics as `/api/documents`, applied as a WHERE clause before grouping): `collection`, `collections`, `file_type`, `tag`, `has_warnings`, `has_source_reference`, `include_deleted`. `collection` and `collections` are mutually exclusive — same 422 dispatch shapes as `/api/documents` (see the multi-collection callout above).

**Response shape:**

```json
{
  "group_by": "file_type",
  "filters": {"collection": "world-bank-ree"},
  "buckets": [
    {"group": "pdf", "count": 450},
    {"group": "docx", "count": 100},
    {"group": "txt", "count": 22}
  ],
  "total_buckets": 3,
  "total_documents": 572
}
```

**Ordering:** `buckets` is sorted by `count` descending, tie-broken by `group` ascending (deterministic).

**`tags` special case:** docs with multiple tags contribute to multiple buckets. Docs with no tags contribute to none. For `group_by=tags`, `total_documents` is the count of distinct docs in the filter scope, NOT the sum of bucket counts.

**Cap:** if a query would produce more than 1000 buckets, returns `400` with a hint to narrow via filters.

**Unknown `group_by` value** returns `400` with the list of valid values.

### Schema — discovery endpoint

`GET /api/documents/schema` returns the complete query surface as a single JSON blob. Agents should call this once at the start of a reasoning session to know what filters, includes, and group_by values are valid without probing.

**Response fields:**

- `filters` — map of filter-name → human description. Every key here is accepted on `/api/documents` and (minus `include`) on `/api/documents/aggregate`.
- `includes` — map of include-value → description. Every key is accepted as a repeated `include=` query param on `/api/documents`.
- `aggregatable_fields` — map of group_by-value → description. Exactly the values accepted by `/api/documents/aggregate`'s `group_by` param.
- `caps` — numeric limits: `list_default` (max rows per list call without markdown), `list_with_markdown` (max rows with markdown), `aggregate_buckets_max` (max buckets per aggregate call).
- `brute_force_fallback` — prose explanation of how to handle questions the filters can't express.
- `deferred` — fields/filters intentionally not implemented, with brief reasons.

The registries that back the filter / include / group_by validators also drive this response — the schema cannot drift from the validators by construction.

---

### `GET /api/documents/{id}`

Retrieve the full stored document by ID. Use after search to get complete content, or to inspect chunks and interaction history.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_chunks` | bool | `true` | Return all chunks with text, section, page info |
| `include_interactions` | bool | `true` | Return all interaction records |

**Response:** JSON with `document_id`, `source_file`, `title`, `file_type`, `engine`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `content_fingerprint`, `collection`, `tags`, `processing_chain`, `warnings`, `warnings_count`, `content_markdown`, `chunks` array (each: `chunk_id`, `text`, `section`, `page`, `token_count`, `embedding_model`), `interactions` array (each: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`, `action`, `was_dedup_skip`, `created_at`). `warnings` is the array of warning strings persisted on the `StoredDocument` at ingest time and survives across reads; `warnings_count` equals `len(warnings)`. Both fields are always present (empty array / `0` when no warnings were emitted).

---

### `PATCH /api/documents/{id}`

Update metadata on an existing document.

**Request body (JSON):**

| Field | Type | Description |
|-------|------|-------------|
| `tags` | list[str] | Replaces existing tags |
| `collection` | string | Moves document to a different collection |
| `agent_id` | string | Caller identity (recorded in interaction) |
| `agent_type` | string | Client type |
| `initiated_by` | string | Human or system identity |
| `model` | string | LLM model the caller is running |
| `agent_metadata` | dict | Structured metadata |
| `agent_notes` | string | Why this update is being made |

**Response:** JSON with `document_id`, `collection`, `tags`, `agent_metadata` (dict, shallow-merged), `updated_fields` (list of field names that were changed, e.g. `["tags", "collection"]`).

**Client method:** `client.update_document(document_id, tags=None, collection=None)`

---

### `DELETE /api/documents/{id}`

Soft-delete a document. The document is hidden immediately but can be restored within 48 hours. After 48 hours, it is permanently purged (chunks, interactions, and all data cascade-deleted).

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `document_id`, `status: "scheduled_for_deletion"`, `deletion_scheduled_at`.

**Client method:** `client.delete_document(document_id)`

---

### `POST /api/documents/{id}/restore`

Restore a soft-deleted document within the 48-hour window. Returns 410 if the window has passed.

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `document_id`, `status: "restored"`.

**Client method:** `client.restore_document(document_id)`

---

### `POST /api/search`

Semantic search over all stored document chunks. Returns ranked results with source metadata and interaction history.

**Request body (JSON):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | (required) | Natural language search query |
| `top_k` | int | `5` | Number of results (max 20) |
| `collection` | string | `null` | Scope to a single collection. Mutually exclusive with `collections`. |
| `collections` | list[str] | `null` | Scope to multiple collections (list-membership). Each element must match the slug allow-list `^[a-z0-9_-]{1,64}$`. Mutually exclusive with `collection`; empty list rejected (omit the field to search every collection). ariadne--wgi. |
| `filters` | dict | `null` | Additional filters (see below) |
| `include_deleted` | bool | `false` | Include soft-deleted documents in results |
| `agent_id` | string | `null` | Caller identity |
| `agent_type` | string | `null` | Client type |
| `model` | string | `null` | LLM model the caller is running |
| `initiated_by` | string | `null` | Human or system identity |
| `agent_notes` | string | `null` | Why this search is being performed |
| `agent_metadata` | dict | `null` | Structured metadata |

**Filters:**

| Filter key | Type | Behavior |
|------------|------|----------|
| `collection` | string | Match chunks in this collection. Same as the top-level `collection` parameter — either works. If both are provided, the filter value takes precedence. AND-composes with `collection_in` when both are present in the filters dict — the chunk's collection must satisfy both predicates (so `collection: "z"` plus `collection_in: ["x", "y"]` returns rows only if `z ∈ ["x", "y"]`). The recommended path is the mutually-exclusive top-level `collection` / `collections` fields, not direct filter-dict use. |
| `collection_in` | list[str] | Match chunks whose collection is in this list (list-membership). Typically set indirectly via the top-level `collections` parameter (which mirrors into `filters.collection_in`); a caller may also set it directly in the `filters` dict for parity with the other filter keys. AND-composed with the other filter keys including `collection` (see the `collection` row above). Pg backend uses `WHERE col.name = ANY(...)`; in-memory backend uses Python `in`. ariadne--wgi. |
| `document_id` | string | Match chunks from a specific document |
| `source_file` | string | Substring match (case-insensitive) against filename |
| `file_type` | string | Exact match against extension. Both `.pdf` and `pdf` accepted |
| `tags` | list[str] | Match documents with any of these tags (OR logic) |
| `metadata` | dict | JSONB containment match against the latest interaction's `agent_metadata`. Nested keys supported: `{"nested": {"field": "value"}}` matches documents where `agent_metadata.nested.field == "value"`. |
| `metadata_exists` | list[str] | Find documents that have these keys in the latest interaction's `agent_metadata` (regardless of value) |

Unknown filter keys are silently ignored.

See § Search › Filters for composition semantics and indexing details.

**Multi-collection scope (ariadne--wgi):** the top-level `collection` (single string) and `collections` (list of slugs) are **mutually exclusive** at the request layer — sending both returns **422** `mutually_exclusive_collections`. An empty `collections: []` is also **422** `empty_collections_list` (ambiguous: caller meant `null` to get the no-filter case). Each element of `collections` must match the slug allow-list `^[a-z0-9_-]{1,64}$`; a bad element returns **422** `invalid_collection_slug`. When `collections` is set, the search route mirrors the list into `filters.collection_in` so both backends apply the same list-membership predicate. The response always includes both `collection` and `collections` fields (one is `null` depending on which the caller used) for shape stability across pre-wgi and wgi clients.

**Response:** JSON with `query`, `top_k`, `collection`, `collections`, `results_count`, `results` array. Each result: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, `metadata` object, `interactions` array. The `metadata` object is the owning document's full `documents.metadata` (the structured metadata folded in at ingest via `agent_metadata` — e.g. `ticket_id`, `bw_status`, `source_type` for bw-ingested documents); it is `{}` for documents ingested without structured metadata. Top-level `collection` and `collections` echo back whichever scope was sent — at most one is non-null per response (mutual exclusion is enforced at the request layer).

**Requires embedding:** Search only works when an embedding API key is configured. Returns 503 if not.

**Search is approximate (ANN):** Results may vary slightly between identical queries due to HNSW index traversal. For reproducible results, pin document/chunk IDs rather than re-querying.

---

### `POST /api/ingest`

Batch ingestion of files already on the server. Processes all supported files in a server-side directory and returns a summary.

**Request body (JSON):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | (required) | Server-side directory path |
| `collection` | string | `"default"` | Collection for all documents |
| `recursive` | bool | `true` | Recurse into subdirectories |
| `file_types` | list[str] | `null` | Filter to extensions (e.g. `["pdf", "docx"]`). Null = all supported |
| `force` | bool | `false` | Re-process even if fingerprint exists (dedup override) |
| `tags` | list[str] | `[]` | Tags applied to all documents |
| `agent_id` | string | `null` | Caller identity |
| `agent_type` | string | `null` | Client type |
| `model` | string | `null` | LLM model |
| `initiated_by` | string | `null` | Human or system identity |
| `agent_notes` | string | `null` | Why this ingestion is being done |
| `agent_metadata` | dict | `null` | Structured metadata |

**Response (top-level fields):**

| Field | Type | Description |
|-------|------|-------------|
| `files_found` | int | Total files matching `file_types` (or all supported extensions if null), respecting `recursive`. |
| `files_processed` | int | Files newly ingested in this call (no error and not a dedup skip). |
| `files_skipped` | int | Files matched by content-fingerprint dedup against an existing document; no new row written. |
| `files_errored` | int | Files where extraction or storage raised an exception. |
| `results` | list[ResultEntry] | Per-file outcomes, one entry per file in `files_found`. |

**`ResultEntry` shape (each element of `results`):**

| Field | Type | Description |
|-------|------|-------------|
| `source_file` | string | File **basename** (e.g. `report.pdf`), not the full server-side path. The directory prefix from `path` is stripped; only the leaf name is returned. |
| `document_id` | string \| null | The new document's UUID on success, the existing document's UUID on a dedup skip, or `null` when the file errored before a document row could be assigned. |
| `was_dedup_skip` | bool | `true` if this file's content fingerprint matched an already-stored document (no new row written; `document_id` points at the existing row). `false` for newly-ingested files and for errored files. |
| `error` | string \| null | Human-readable error message when the file failed to ingest; `null` on success and on dedup skips. |

The four counters partition `files_found` exactly: `files_processed + files_skipped + files_errored == files_found`. Dedup skips are not errors; they are a successful no-op that preserves the prior document row.

Processing is synchronous. Files are processed concurrently (up to 4 at a time). For large directories this may take minutes. The endpoint returns the full summary when done.

**Oversized files in batch mode:** Files at or above the soft cap (`max_source_bytes`) are skipped with a per-file error logged in the `results` array; the `confirmation_token` is **not** surfaced to the batch caller. Batch ingest is by construction autonomous (no operator at the prompt to confirm a single file out of a directory), so per-file confirmation is structurally inappropriate. Callers needing the oversized-source workflow should use single-file ingest via `POST /api/documents`, which returns the structured 413 with the token. Files above the hard cap (`max_source_bytes_hard`) are likewise skipped-and-logged in batch mode; the same per-file error shape is used.

**Note:** This endpoint only works with server-side paths. For local files, use the client package (`client.ingest_file()`) or the CLI (`ariadne ingest`), which handle upload + conversion automatically.

---

### `GET /api/collections`

List all collections with document counts.

**Response:**
```json
{"collections": [{"name": "world-bank-ree", "description": null, "document_count": 502}]}
```

---

### `POST /api/collections`

Create a new named collection.

**Request body (JSON):**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Collection name |
| `description` | string | Optional description |
| `initiated_by` | string | Who created this collection |

**Response:** JSON with `name`, `description`, `status: "created"`. Returns 409 if collection already exists.

**Client method:** `client.create_collection(name, description=None)`

---

### `DELETE /api/collections/{name}`

Soft-delete all documents in a collection. Each document keeps its own 48-hour recovery window.

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `collection`, `documents_marked` (int — count of documents soft-deleted), `message`.

**Client method:** `client.delete_collection(name)`

---

### `POST /api/collections/{name}/restore`

Restore soft-deleted documents in a collection. Only restores documents within their 48-hour window.

**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

**Response:** JSON with `collection`, `documents_restored` (int — count of documents restored).

**Client method:** `client.restore_collection(name)`

---

### `GET /api/stats`

System statistics.

**Response:**
```json
{"total_documents": 502, "total_chunks": 124000, "total_collections": 3, "embedding_enabled": true, "collections": {"world-bank-ree": 502, "default": 0, "test-empty": 0}}
```

`total_collections` always equals the size of the `collections` map. The map is the union of doc-bearing collections (any `collection_id` with at least one stored document) and registered-but-empty collections (created via `POST /api/collections` with no documents yet); registered-but-empty collections appear with `0` doc count. This invariant matches `GET /api/collections`, which returns the same union.

**Client method:** `client.stats()`

---

### bw HTTP surface

`/api/bw/projects/{slug}/...` is a thin HTTP shim over the `bw` (beadwork) CLI (https://github.com/jallum/beadwork). It lets an agent (or a human via the REST API) drive a beadwork repository that lives on the server's volume — without holding a shell on the host. Phase 2 of the bw integration (ariadne--8fd.2). All endpoints require `Authorization: Bearer <jwt>` (same `require_user` dependency as the rest of `/api/*`).

**URL convention — path-prefix-per-project:** every endpoint hangs off `/api/bw/projects/{slug}/...`. The slug identifies a beadwork repo on disk; the server resolves it to `{BW_REPOS_ROOT}/{slug}` (default `BW_REPOS_ROOT=/data/bw-repos`) and invokes `bw -C <repo>` against it. Slug allow-list is anchored at `^[a-z0-9_-]{1,64}$` — lowercase letters, digits, dash, underscore, max 64 chars. Anything else returns **422** `invalid_slug` before any subprocess call happens. The slug space is intentionally distinct from bw's ticket-ID space (`bw-{4-char-hex}`), so a ticket ID can never be passed where a project slug is expected.

**Method convention — action-endpoint pattern:** each mutating bw subcommand maps to a POST against a sub-path named for the action (`POST .../close`, `POST .../defer`, `POST .../labels`). Read-only subcommands map to GET. Removing an enumerable child (a label, a dep) maps to DELETE.

**Concurrency — per-slug in-process lock:** mutating endpoints acquire an `asyncio.Lock` keyed on `slug` for the duration of the bw call; reads skip the lock (git reads are concurrent-safe). v1 is single-instance — distributed locking for multi-replica deploys is deferred to Phase 5 (ariadne--8fd.5).

**Endpoint summary — ticket-shaped (16):**

| Method | Endpoint | bw subcommand |
|--------|----------|---------------|
| `POST` | `/api/bw/projects/{slug}/tickets` | `bw create` (returns **201**) |
| `GET` | `/api/bw/projects/{slug}/tickets` | `bw list` |
| `GET` | `/api/bw/projects/{slug}/tickets/{ticket_id}` | `bw show` |
| `PATCH` | `/api/bw/projects/{slug}/tickets/{ticket_id}` | `bw update` |
| `DELETE` | `/api/bw/projects/{slug}/tickets/{ticket_id}` | `bw delete` (preview by default; `?force=true` to commit) |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/start` | `bw start` |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/close` | `bw close` |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/reopen` | `bw reopen` |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/comments` | `bw comment` (returns **201**) |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/labels` | `bw label <id> +<label>` (returns **201**) |
| `DELETE` | `/api/bw/projects/{slug}/tickets/{ticket_id}/labels/{label}` | `bw label <id> -<label>` |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/defer` | `bw defer` |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/undefer` | `bw undefer` |
| `POST` | `/api/bw/projects/{slug}/tickets/{ticket_id}/deps` | `bw dep add <id> blocks <target>` (returns **201**) |
| `DELETE` | `/api/bw/projects/{slug}/tickets/{ticket_id}/deps/{target}` | `bw dep remove <id> blocks <target>` |
| `GET` | `/api/bw/projects/{slug}/tickets/{ticket_id}/history` | `bw history` |

**Endpoint summary — collection-level (1, ariadne--9e7):**

| Method | Endpoint | bw subcommand |
|--------|----------|---------------|
| `POST` | `/api/bw/projects` | `mkdir + git init + bw init --prefix` (mounted on its own router because the path has no `{slug}` — body carries the slug). Returns **201**. |

**Endpoint summary — repo-level (7):**

| Method | Endpoint | bw subcommand |
|--------|----------|---------------|
| `GET` | `/api/bw/projects/{slug}/ready` | `bw ready` |
| `GET` | `/api/bw/projects/{slug}/blocked` | `bw blocked` |
| `POST` | `/api/bw/projects/{slug}/sync` | `bw sync` (no `--json`; output verbatim) |
| `GET` | `/api/bw/projects/{slug}/onboard` | `bw onboard` (no `--json`; output verbatim) |
| `GET` | `/api/bw/projects/{slug}/prime` | `bw prime` (no `--json`; output verbatim) |
| `GET` | `/api/bw/projects/{slug}/export` | `bw export` (JSONL output; verbatim) |
| `POST` | `/api/bw/projects/{slug}/reembed` | In-place re-embed (no bw subcommand — reads the repo, re-ingests docs) |

**Label prefix composition:** bw's CLI uses a `+` prefix to add and `-` prefix to remove labels on a single shared `bw label` subcommand. The HTTP surface splits these into two endpoints (POST to add, DELETE to remove) and composes the prefix **server-side**. A caller that prepends `+` or `-` to the label value gets a **422** `invalid_label` — use the DELETE endpoint to remove.

**Label format:** labels (request body or path segment) are constrained to `1..128` chars and must not start with `+` or `-`. No other character restriction at the surface — bw itself rejects characters it does not support.

**JSON shape — array wrapping:** when a `--json` bw subcommand returns a top-level JSON array (e.g. `bw list --json`), the HTTP response wraps it as `{"items": [...]}` so every endpoint returns a JSON object at the top level. This matches the `/api/*` convention and keeps OpenAPI declarations honest.

**Empty stdout from `--json`:** an empty stdout from a `--json` subcommand resolves to an empty `{}` response (not a 500). Some bw versions legitimately print nothing on success for certain subcommands (e.g. `dep add`).

**bw exit-code mapping:**

| Condition | HTTP status | `detail` shape |
|-----------|-------------|----------------|
| bw exits non-zero (caller error: bad id, invalid date, missing arg, etc.) | **400** | `{"error": "bw_exit_nonzero", "exit_code": <int>, "stderr": <str>, "stdout": <str>}` |
| bw binary not on PATH at import (or disappears) | **500** | `{"error": "bw_binary_missing", "message": <str>}` |
| Subprocess exceeded `BW_SUBPROCESS_TIMEOUT_SECONDS` (default 30s) | **500** | `{"error": "bw_timeout", "message": <str>}` |
| `--json` subcommand returned non-JSON stdout | **500** | `{"error": "bw_json_parse", "message": <str>, "stdout": <first 2000 chars>}` |
| Slug failed the `^[a-z0-9_-]{1,64}$` allow-list | **422** | `{"error": "invalid_slug", "message": <str>}` |
| Slug is valid but `{BW_REPOS_ROOT}/{slug}/.git` is missing on disk (Phase 5) | **404** | `{"error": "bw_project_uninitialized", "slug": <str>, "message": <operator-action str>}` |
| Label payload starts with `+` or `-` | **422** | `{"error": "invalid_label", "message": <str>}` |
| `PATCH /tickets/{id}` with empty body (no fields) | **400** | `{"error": "no_fields_to_update", "message": <str>}` |
| Null byte (`\x00`) in a user-text field (title, description, comment text, reason, defer expression) | **422** | Pydantic field-validator error |

400 vs 500 split: **400 = caller can fix it** (re-submit with valid args). **500 = deploy / bw bug** (operator must fix; caller cannot retry into success).

**stderr / stdout in 400 responses:** bw's stderr and stdout are surfaced verbatim under `detail` on a non-zero exit. This is intentional — bw's CLI errors are the actionable debugging signal, and a server-side mask would force callers to read host logs to debug a malformed request. The slug allow-list and the argv-list-no-shell invocation ensure stderr cannot leak unintended state.

**Backup hook (Phase 5, ariadne--8fd.9):** every successful mutating call invokes `_backup_push(slug)`. The hook resolves `BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}` (the slug uppercased with dashes mapped to underscores — env-var names cannot contain dashes); if the env var is **unset**, the hook is a silent no-op (slug has no configured backup, which is a legitimate operator choice for low-value repos). If set, the hook runs `git -C {repo_path} push {remote} beadwork:beadwork --force-with-lease` with a separate `BW_BACKUP_TIMEOUT_SECONDS` (default 60s, longer than the per-bw-call timeout because the push does network I/O). The hook is NOT invoked when the bw write itself fails (exit != 0); pushing a failed write would push nothing useful and could mask a real error. **Infallibility contract:** the hook MUST NOT raise. Any failure (non-zero exit, timeout, unexpected exception) logs a WARNING, increments the per-slug `_backup_skip_count`, and returns normally so the request still completes 2xx. The `_backup_skip_count` is cumulative-lifetime (Phase 5 sub-task: replace with a time-windowed Prometheus gauge). Token-bearing remote URLs (`https://x-access-token:<TOKEN>@host/...`) are masked in log lines (the pre-`@` portion becomes `***`). `--force-with-lease` is used rather than `--force` because bw is single-writer per repo in v1 (per-slug lock + single-instance deploy), so the local ref is always ahead-of-or-equal to the remote — but `--force-with-lease` refuses the push if the remote moved unexpectedly, catching the case where two operators accidentally point at the same backup remote (or where a future multi-instance deploy raced two writers).

**Project initialization guard:** every bw route resolves the repo path via `_resolve_repo_path(slug)`, which verifies that `{BW_REPOS_ROOT}/{slug}/.git` exists. If missing, the route returns **404** `bw_project_uninitialized` with an operator-actionable message naming both the API-driven path (`POST /api/bw/projects`, ariadne--9e7) and the host-shell `bw init` sequence. The check is intentionally NOT an auto-init (provisioning a beadwork repo is an explicit operator action, not a side effect of the first 404). The check can be disabled at module level (`BW_REQUIRE_INITIALIZED_REPO = False`) for route-level tests that mock `subprocess.run` and don't materialize a real `.git` tree.

**In-place re-embed — `POST /api/bw/projects/{slug}/reembed` (ariadne--uuo.5):** the GOOD migration path. Walks the on-disk bw repo for `slug` and re-ingests every ticket's body + comments **in place** — same `documents.id`, new clean embed-content under the current ingest logic — without recreating any bw ticket. This is distinct from `scripts/seed_bw_corpus.py` (the BAD path, which recreates tickets via `POST /tickets`). It is the reusable operational capability for every future ingest-logic change. Request body (both fields optional): `{"ticket_ids": [...], "dry_run": false}` — `ticket_ids` restricts the walk to a subset (unknown IDs are reported in `errors`, not silently dropped); `dry_run=true` enumerates + counts + runs the orphaned-ticket detection and writes nothing. Mechanics: per ticket, resolve the existing `documents.id` for each body/comment slot via the `(source_type, comment_n)` keys in `documents.metadata`; re-ingest each via the snapshot-driven ingest core with `force=True` (deletes the old chunks before inserting the new ones) and `existing_document_id=<resolved id>` (routes the documents-row write through `update_document_content`, an UPDATE-by-id). A slot with no resolved id is INSERTed fresh (`existing_document_id=None`), never skipped. The per-slug write lock (`_lock_for`) is acquired/released at the **per-ticket boundary** — held atomically across one ticket's body + entire comments loop, released between tickets — so a live bw write cannot interleave within a single ticket's re-embed but can proceed between tickets. **Reconciliation:** a `documents` row whose `ticket_id` is absent from the on-disk bw repo is reported in the response's `orphaned_tickets` and emits a `reembed-orphan-ticket` WARNING log line — it is **never auto-deleted** (disposition is an operator call). Summary response: `{reembedded, fresh_inserted, orphaned_tickets, errors, dry_run, tickets_enumerated}` (plus `docs_would_reembed` on a dry run). Returns **404** `bw_repo_enumeration_failed` if the on-disk repo / `beadwork` branch is missing, **500** for an unexpected git failure.

**Project bootstrap — `POST /api/bw/projects` (ariadne--9e7):** initializes a new bw project on disk without an SSH shell on the host. Closes the gap left by Phase 5 (8fd.9), whose operator-setup checklist hard-coded a manual `mkdir + git init + bw init` sequence. The handler runs the same three steps under the per-slug write lock; rollback (`shutil.rmtree`) restores the pre-call state on any failure in step 2 or 3 so the next operator attempt starts clean.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `slug` | string | yes | 1..64 chars; must match `^[a-z0-9_-]{1,64}$` (same allow-list as the slug-scoped routes). |
| `options` | dict | no | Reserved-for-future per-project knobs. Accepted for shape stability; ignored in v1. Backup-remote configuration stays env-var-driven via `BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}`. |

Response:

| Status | `detail` shape |
|--------|----------------|
| **201** | `{"slug": <slug>, "status": "created", "repo_path": <absolute path>}` |
| **409** | `{"error": "slug_already_exists", "slug": <slug>, "repo_path": <str>, "message": <operator-action str>}` — the slug directory already exists on disk. Refusing to re-initialize is intentional (idempotent re-init would silently destroy the orphan beadwork branch). |
| **422** | `{"error": "invalid_slug", "message": <str>}` — slug failed the allow-list. |
| **500** | `{"error": "init_failed", "step": "git_init" \| "bw_init" \| "makedirs", "slug": <slug>, "exit_code": <int (optional)>, "stderr": <str>}` — any subprocess in the chain returned non-zero or raised an OS error. The partial slug dir is rolled back before returning. |
| **500** | `{"error": "bw_binary_missing", "message": <str>}` — same shape as every other bw route. |
| **401** | (FastAPI default) — same `require_user` dependency as the rest of the bw surface. |

Init chain (all under the per-slug lock):

1. `os.makedirs({BW_REPOS_ROOT}/{slug}, exist_ok=False)` — `exist_ok=False` is the 409 trigger.
2. `git init {BW_REPOS_ROOT}/{slug}` via subprocess. Rolls back on failure.
3. `bw -C {BW_REPOS_ROOT}/{slug} init --prefix {slug}` via subprocess. Rolls back on failure.

This endpoint replaces step 2 of the Phase 5 operator-setup checklist below. Operators may still run the three-command sequence on the host directly (e.g., as a one-shot exec, init container, or Railway "Run command") for non-interactive provisioning; both paths produce the same on-disk layout.

**Deferred surface — explicitly NOT in v1:**

| bw subcommand | Reason for deferral |
|---------------|---------------------|
| `bw upgrade` | Admin / manual ops; not an agent-facing call. |
| `bw config` | Admin surface. Defer until an ACL story exists; until then config changes happen on the host directly. |
| `bw registry` | Host-local registry; per-process state, not per-repo. Not relevant to the slug-routed API. |
| `bw attach` | Needs multipart upload semantics. Deferred to Phase 3 / Phase 4 (settled alongside the inline-ingest upload surface). |
| `bw import` | Same multipart surface as `attach`. |

A caller that hits `/api/bw/projects/{slug}/<deferred>` simply gets a 404 (no route registered); the deferred-subcommand list is documentation, not a runtime check.

**Request bodies:**

`POST /api/bw/projects/{slug}/tickets` — `TicketCreate`:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | string | yes | 1..512 chars; null bytes rejected (422) |
| `description` | string | no | null bytes rejected (422) |
| `priority` | int | no | 0..4 |
| `type` | string | no | |
| `defer` | string | no | bw-parseable date expression |
| `due` | string | no | |
| `parent` | string | no | parent ticket ID |

`PATCH /api/bw/projects/{slug}/tickets/{id}` — `TicketUpdate`: same field set as `TicketCreate` plus `assignee`, `status`. **All fields optional**; empty body returns **400** `no_fields_to_update`. `due: ""` (empty string) is the documented "clear the field" shape (matches `bw update --due ""`). `null` means "don't touch".

`POST .../start` — `TicketStart`: optional `assignee` (bw uses git `user.name` default if absent).

`POST .../close` — `TicketClose`: optional `reason` (null bytes rejected).

`POST .../comments` — `CommentCreate`: required `text` (≥1 char; null bytes rejected), optional `author`.

`POST .../labels` — `LabelAdd`: required `label` (1..128 chars, must not start with `+` or `-`).

`POST .../defer` — `DeferRequest`: required `when` (bw-parseable date expression, null bytes rejected).

`POST .../deps` — `DepAdd`: required `blocks` (target ticket ID; semantics: `{ticket_id}` blocks `{blocks}`).

#### Deployment configuration

Every bw-related environment variable, in one place. Phase 5 (ariadne--8fd.9) is the source of truth.

| Env var | Default | Required | Semantics |
|---------|---------|----------|-----------|
| `BW_BINARY` | `shutil.which("bw")` at app import | No | Path to the `bw` binary. Resolved once at module import. If `None`, every endpoint returns **500** `bw_binary_missing`. The Dockerfile installs bw at `/usr/local/bin/bw`. |
| `BW_REPOS_ROOT` | `/data/bw-repos` | Yes (production) | Root directory for per-slug bw repos. Layout: `{BW_REPOS_ROOT}/{slug}/.git`. App startup `makedirs(..., exist_ok=True)` the root; per-slug subdirs are operator-provisioned via `POST /api/bw/projects` (ariadne--9e7) or the host-shell `bw init` sequence (see Project bootstrap). |
| `BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}` | unset | No | Per-project git remote URL for `_backup_push`. Slug `my-project` maps to `BW_BACKUP_REMOTE_MY_PROJECT` (uppercased, dashes → underscores). If unset for a slug, that slug's writes do NOT push to a backup remote (silent no-op). Set to a private git URL (HTTPS-with-token or SSH) to enable. |
| `BW_SUBPROCESS_TIMEOUT_SECONDS` | `30.0` | No | Per-bw-call subprocess timeout. Set at module load. |
| `BW_BACKUP_TIMEOUT_SECONDS` | `60.0` | No | Per-backup-push subprocess timeout. Separate from `BW_SUBPROCESS_TIMEOUT_SECONDS` because git push does network I/O. |
| `BW_REQUIRE_INITIALIZED_REPO` | `True` (module-level constant) | No | Whether `_resolve_repo_path` enforces the `.git`-exists check. Production-true. Route-level tests monkey-patch to `False`. Not an env-var read (no operator should need to flip this in production); it lives as a module constant so tests can toggle. |
| `BW_RETRY_POLL_SECONDS` | `30.0` | No | Phase 3: polling interval for the bw ingest-retry worker. |
| `BW_RETRY_BATCH_SIZE` | `10` | No | Phase 3: max rows drained per retry poll. |
| `BW_RETRY_BASE_BACKOFF_SECONDS` | `30.0` | No | Phase 3: exponential backoff base for retry attempts. |
| `BW_RETRY_MAX_BACKOFF_SECONDS` | `3600.0` | No | Phase 3: ceiling on backoff between retry attempts. |
| `BW_RETRY_MAX_ATTEMPTS` | `24` | No | Phase 3: after this many failures a row moves to the dead-letter table. |

**Operator setup checklist (per Ariadne deployment):**

1. **Provision a persistent volume** mounted at `/data/bw-repos`. On Railway: dashboard → Service → Settings → Volumes → "Add volume", mount path `/data/bw-repos` (Railway's docs explicitly ban the Dockerfile `VOLUME` keyword, so the layer hint is intentionally omitted). On a self-hosted Docker host: bind-mount or named volume at runtime (`-v <host-path>:/data/bw-repos`). Override via `BW_REPOS_ROOT` if the deployment target requires a different writable path.
2. **Initialize the per-project bw repo.** Two equivalent paths:
   - **API (preferred, ariadne--9e7):** `POST /api/bw/projects` with body `{"slug": "<slug>"}` and a valid Bearer JWT. The handler runs the three steps below under the per-slug lock; rolls back on failure; returns **409** if the slug directory already exists. See the "Project bootstrap" section above for the full request/response contract.
   - **Manual (host shell):** for non-interactive provisioning (a one-shot exec, init container, or Railway "Run command"):
     ```
     mkdir -p {BW_REPOS_ROOT}/{slug}
     git init {BW_REPOS_ROOT}/{slug}
     cd {BW_REPOS_ROOT}/{slug} && bw init --prefix {slug}
     ```
   Both paths create the slug subdir, initialize a git repo, and create the orphan beadwork branch with the slug as the ticket-ID prefix. No auto-init — the explicit step (whichever path) prevents a typo'd slug from materializing an empty repo on first 404.
3. **Configure per-project backup** (optional). For each project that needs a backup remote, set `BW_BACKUP_REMOTE_{SLUG_UPPER_UNDERSCORE}` to a private git URL. The URL may carry an access token (`https://x-access-token:<TOKEN>@host/...`); the bw HTTP surface masks the credential portion in log lines. With no env var set, the slug's writes complete locally and skip the backup (no failures, no counter bumps). **First-push note:** the backup remote should be empty / freshly created. If it already carries unrelated content (e.g., the operator pointed at the wrong remote), `--force-with-lease` correctly rejects with `stale info` rather than clobbering — recoverable by either repointing the env var or running a one-time manual seed (`git fetch && git push --force` to align the remote intentionally).
4. **Verify** via `GET /api/bw/projects/{slug}/health` (any initialized slug) — returns the ingest-retry depth and is also a smoke test that `BW_REPOS_ROOT` and the slug subdir are wired correctly.

#### Ingest coupling (Phase 3 / ariadne--8fd.5)

Every successful bw write triggers an inline Ariadne ingest inside the same per-slug lock, so search reflects the new bw content within the response cycle — no separate `POST /api/ingest` round-trip required. The write endpoint returns bw's own JSON shape with an additional `ariadne_ingest` key carrying the ingest result; the bw shape itself is unchanged from Phase 2.

**Per-endpoint behavior (the 22-endpoint matrix from design §D3):**

| Endpoint | bw effect | Ariadne effect |
|---|---|---|
| `POST /tickets` | new ticket + body | New `body`-type doc; `agent_metadata` carries the frontmatter schema below |
| `POST /tickets/{id}/comments` | new comment | New `comment`-type doc with `comment_n = len(bw_response.comments)` |
| `PATCH /tickets/{id}` (title or description changed) | mutate body | Soft-delete prior body doc(s); ingest new body doc with the post-update content |
| `PATCH /tickets/{id}` (fields-only) | mutate fields | PATCH-meta on body doc — re-emit full `agent_metadata` surface (latest-interaction semantics; full surface mandatory per design §D3.1) |
| `DELETE /tickets/{id}?force=true` | delete ticket | Soft-delete body doc + every comment doc for the ticket |
| `DELETE /tickets/{id}` (preview, no force) | no mutation | No-op |
| `POST /tickets/{id}/start` | status → in_progress + assignee | PATCH-meta |
| `POST /tickets/{id}/close` (no reason) | status → closed | PATCH-meta |
| `POST /tickets/{id}/close` (with reason) | status → closed + reason comment | PATCH-meta on body AND new comment doc for the reason |
| `POST /tickets/{id}/reopen` | status → open | PATCH-meta |
| `POST /tickets/{id}/defer` | status → deferred | PATCH-meta |
| `POST /tickets/{id}/undefer` | status → open | PATCH-meta |
| `POST /tickets/{id}/labels` | add label | PATCH-meta (re-emits FULL `labels` dict + `labels_flat` + every other key) |
| `DELETE /tickets/{id}/labels/{label}` | remove label | PATCH-meta |
| `POST /tickets/{id}/deps` | add dep | No-op (v1) |
| `DELETE /tickets/{id}/deps/{target}` | remove dep | No-op (v1) |
| `POST /sync` | git fetch+rebase+push | No-op (v1 single-writer only) |

The read-only endpoints (`GET /tickets`, `GET /tickets/{id}`, `GET /ready`, `GET /blocked`, `GET /tickets/{id}/history`, `GET /onboard`, `GET /prime`, `GET /export`) do not trigger ingest.

**Frontmatter / `agent_metadata` schema** — the ingest payload is YAML frontmatter (alphabetically-sorted keys for fingerprint stability) followed by the bw body or comment text. The same dict is sent as `agent_metadata` on every ingest interaction and re-emitted in full on every PATCH-meta. Keys:

| Key | Type | Notes |
|---|---|---|
| `ticket_id` | str | Canonical bw ticket id (the `id` field of `bw show`) |
| `project` | str | Project slug; equals the Ariadne collection name |
| `source_type` | `"body"` \| `"comment"` | Only two values in v1 |
| `comment_n` | int \| null | 1-indexed within the ticket's comments array; null for body docs |
| `author` | str \| null | bw author of the body / comment (the `--author` flag value, or git user.name) |
| `timestamp` | str | RFC3339 UTC; captured at the API request boundary inside the lock |
| `bw_commit_sha` | str | 40-hex commit SHA of the bw mutation, from `bw history --json --limit 1` |
| `bw_status` | str | `open` / `in_progress` / `closed` / `deferred` — snapshot at write time |
| `parent_ticket_id` | str \| null | bw `parent` field, pass-through |
| `assignee` | str \| null | bw `assignee` field, pass-through |
| `labels` | dict[str,str] | Structured `kind:value` labels parsed on the first `:`; bare labels skipped |
| `labels_flat` | list[str] | Every label verbatim — kinded AND bare. Use `metadata_exists=["labels_flat"]` to find any labeled doc; nested containment (`metadata={"labels":{"kind":"person"}}`) for typed filters. |

`priority`, `due`, `defer_until`, `type`, and bw-internal timestamps are deliberately NOT in v1 frontmatter — bw-internal scheduling fields, not load-bearing for search.

**Body-author preservation across PATCH:** label-add, status-change, defer/undefer, start, close, and fields-only PATCH all preserve the `agent_metadata.author` field of the original body author across the mutation. The PATCH actor's identity is recorded on the `document_interactions` row (`agent_id`), but `agent_metadata.author` continues to point at the bw `create`-row author. This is mandatory because Phase 1's metadata filter resolves against the latest interaction's `agent_metadata` — a naive "use the just-completed mutation's author" rule would silently overwrite alice's name with bob's the first time bob adds a label to alice's body.

**Eventual-consistency contract.** A bw write returns HTTP 201/200 once the bw repo is committed and the Ariadne ingest has either succeeded OR enqueued for retry. The response carries `ariadne_ingest.ingest_status` — `"ok"` (search reflects the write immediately) or `"enqueued_for_retry"` (search reflects the write within ~`BW_RETRY_POLL_SECONDS` after the upstream issue resolves). The bw repo is canonical (locked decision); a successful bw write is never lost, even when Ariadne ingest fails repeatedly.

**Failure-mode escalation:**

1. **Ingest exception** → enqueue into the Postgres `bw_ingest_retry_queue` table.
2. **Postgres-enqueue exception** (`OperationalError`, etc.) → fall back to the on-disk JSONL file `${BW_REPOS_ROOT}/{slug}/.bw_ingest_dead_letter.jsonl`. Append-only, fsync per line. The retry worker drains this file via atomic-rename-then-read on every poll.
3. **Retry budget exhausted** (`attempt_count >= BW_RETRY_MAX_ATTEMPTS`) OR **stale-by-design** (a later body PATCH already advanced the ticket past the queued SHA) OR **orphan SHA** (the queued SHA is no longer in `bw history`) → move the row to `bw_ingest_retry_dead_letter`. The operator (POLYBIUS) can inspect / replay manually; no automatic re-replay from the dead-letter table.

**Observability** — `GET /api/bw/projects/{slug}/health` returns:

| Key | Type | Meaning |
|---|---|---|
| `bw_ingest_retry_queue_depth` | int | Current row count in `bw_ingest_retry_queue` |
| `bw_ingest_retry_dead_letter_count` | int | Cumulative row count in `bw_ingest_retry_dead_letter` |
| `bw_ingest_retry_by_slug` | dict[str,int] | Per-slug retry-queue depth |
| `bw_ingest_file_fallback_drain_count` | int | Cumulative file-fallback lines drained since process start |
| `bw_ingest_file_fallback_pending_lines` | int | Sum of pending lines across every slug's `.bw_ingest_dead_letter.jsonl` |

A non-zero `bw_ingest_file_fallback_pending_lines` means Postgres is currently unreachable or the drain itself is failing — both worth alerting on.

**Searchable surface.** The set of `agent_metadata` keys above is the filter surface; combine with the `metadata` / `metadata_exists` filters documented in the §Search › Filters table to query bw-derived documents. The collection name equals the slug, so `POST /api/search` with `{"collection": "<slug>", "filters": {"metadata": {"ticket_id": "<id>"}}}` returns the body + every comment for that ticket.

### Bulk seed adapter (scripts/seed_bw_corpus.py)

`scripts/seed_bw_corpus.py` is a generic one-shot adapter for migrating an existing `bw` (beadwork) repo onto a target Ariadne deployment via the Phase 2 HTTP surface + Phase 3 inline ingest. Phase 4 of the bw integration (`ariadne--8fd.6`).

**Invocation:**

```bash
python scripts/seed_bw_corpus.py \
    --bw-repo /path/to/source-bw-repo \
    --project target-slug \
    [--limit N] \
    [--ariadne-host URL] \
    [--dry-run] \
    [--start-after TICKET_ID] \
    [--state-file PATH] \
    [--rate-limit-sleep SECONDS]
```

**Mechanism:**

- **Source enumeration via `git show`** (no `bw` CLI dependency on the caller's machine). The script reads `git show beadwork:issues` for the ticket listing and `git show beadwork:issues/<id>.json` for each ticket body + its inline comment list.
- **POST per ticket** to `POST /api/bw/projects/{slug}/tickets` with the `TicketCreate` body (`title`, `description`, `priority`, `type`, `parent`). The server's `bw create` generates a fresh target ticket ID — the script does not pass through source IDs (bw does not accept them at create time).
- **POST per comment** to `POST /api/bw/projects/{slug}/tickets/{target_id}/comments` with the `CommentCreate` body. Phase 3's `_ingest_bw_write` handles each Ariadne ingest inline as part of the POST.
- **Auth via `ariadne_core_client.auth`** — same precedence chain as `ariadne login` / `mcp_auth.py` (`ARIADNE_ACCESS_TOKEN` env → keyring access token → silent refresh). No new auth surface invented in the script.

**Idempotency (two cooperating layers):**

1. **Script-level state file** at `<bw-repo>/.ariadne_seed_state.json` by default (override via `--state-file`). Records `{source_ticket_id: {target_id, target_comments, seeded_at}}`. On restart the script skips every source ticket already in the map; if the source has grown additional comments since the last run, only the new comments are POSTed. Written atomically via temp-then-rename after every successfully-processed ticket so a mid-run crash leaves a coherent on-disk state.
2. **Ariadne `content_fingerprint` dedup.** Phase 3's ingest layer reports `ariadne_ingest.was_dedup_skip=true` whenever the embed payload matches an existing document. The script tallies this in the `dedup_skipped` counter — distinct from `tickets_skipped_state` so the operator can tell "skipped because we did this last run" (state-file) apart from "POSTed but Ariadne already had identical content" (content-fingerprint).

**Failure handling.** A 4xx or 5xx on any POST increments `errors`, logs the response body (first 300 chars), and continues with the next ticket / comment. A network failure retries once with a fixed 5-second backoff before being counted. The process exit code is `0` when `errors == 0`, otherwise `1`. Config / argument errors exit `2`.

**Known limitations (Phase 4).** `status`, `assignee`, and `labels` from the source ticket are NOT propagated — seeded tickets land on the target with `status: open`, no `labels`, no `assignee`. The Phase 2 `POST /tickets` body does not accept those fields at create-time, and the Phase 4 deliverable does not emit follow-up PATCHes. Operators who need fidelity must extend the script post-seed (`bw status` / `bw label` / `bw start --assignee` against each target ticket) or wait on a follow-up enhancement.

**Operator action gating (out of scope for `ariadne--8fd.6`).** Running the full bulk seed against a large corpus is a separate PRINCIPAL operator action — not part of the Phase 4 deliverable. Bulk-seed cost is dominated by the Gemini embedding round-trip per POST: at typical throughput, an 11k-ticket corpus runs over multiple hours under the account's rate-limit allowance. The script's `--rate-limit-sleep` knob exists to ride under the upstream rate cap without surfacing as 429s mid-run.

---

## Client package

`ariadne-core-client` is a pip-installable Python package that wraps the REST API. Agents, scripts, and CI pipelines use this to talk to an Ariadne Core server. It lives in the same monorepo as the server (`ariadne-core/client/`).

- **PyPI package:** `ariadne-core-client`
- **Python import:** `from ariadne_core_client import AriadneClient`
- **Zero dependencies** beyond Python stdlib (uses `urllib.request`)
- **Provides both** a Python API and a CLI (`ariadne` command)

### Installation

```bash
pip install ariadne-core-client
# or
uv add ariadne-core-client
# or from the monorepo
pip install git+https://github.com/denson/ariadne-core.git#subdirectory=client
```

### Credential resolution

Pass 3 (`ariadne--xft.5.1` + `xft.5.5` + `xft.5.3`) landed the `ariadne login` CLI + OS-keyring-backed token cache. The client resolves the server host and the Bearer JWT via two separate precedence chains:

**Host:**

1. Explicit `host` parameter on `AriadneClient(host=..., ...)`
2. `ARIADNE_HOST` environment variable
3. `~/.config/ariadne/default` (written by `ariadne login`)

**Bearer JWT:**

1. `ARIADNE_ACCESS_TOKEN` environment variable (CI/automation escape hatch — bypasses keyring)
2. OS-keyring-cached access token (populated by `ariadne login`)
3. Silent refresh via stored refresh token

The client never reads tokens from a `.env` file. The legacy `.env` / `.mcp.json` auto-resolution chains are removed. The client never prints, logs, or exposes credentials.

### Default caller metadata

The constructor accepts `agent_type`, `initiated_by`, `model` — applied to every call automatically. Individual calls can override.

```python
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

### Ingestion methods (preference order)

| Priority | Method | Token cost | When to use |
|----------|--------|-----------|-------------|
| 1st | `ingest_url(url)` | Zero — server fetches | Document at an HTTP/HTTPS URL |
| 2nd | `ingest_file(path)` | Zero — client uploads via HTTP | Local file |
| 3rd | `ingest_bytes(content, filename)` | Already paid | File dropped in chat UI |

- `ingest_url()` auto-sets `source` to the URL if not explicitly provided
- `ingest_file()` and `ingest_bytes()` do NOT auto-set source — the file path is not provenance
- After using `ingest_bytes()`, the agent should tell the user: "Next time, give me the file path instead of dropping it — I'll ingest it directly without loading it into our conversation."

### Source convenience parameter

All ingest methods accept an optional `source` string — shortcut for `agent_metadata["source_reference"]`.

```python
client.ingest_file("report.pdf", source="https://documents.worldbank.org/...")
client.ingest_bytes(content, filename="report.pdf", source="gdrive:1BxiMVs...")
```

Provenance hierarchy: DOI > URL > database/API ref > file path > "unknown".

### Method summary

| Method | REST endpoint | Description |
|--------|--------------|-------------|
| `ingest_url(url, ...)` | `POST /api/documents` | Ingest from URL (server fetches) |
| `ingest_file(path, ...)` | `POST /api/upload` + `POST /api/documents` | Upload + convert in one call |
| `ingest_bytes(content, filename, ...)` | `POST /api/upload` + `POST /api/documents` | Store content already in context |
| `search(query, ...)` | `POST /api/search` | Semantic search |
| `get_document(document_id, ...)` | `GET /api/documents/{id}` | Full document retrieval |
| `list_documents(...)` | `GET /api/documents` | Browse documents |
| `list_collections()` | `GET /api/collections` | List collections |
| `create_collection(name, ...)` | `POST /api/collections` | Create a collection |
| `update_document(document_id, ...)` | `PATCH /api/documents/{id}` | Update metadata |
| `delete_document(document_id)` | `DELETE /api/documents/{id}` | Soft-delete |
| `restore_document(document_id)` | `POST /api/documents/{id}/restore` | Undo soft-delete |
| `delete_collection(name)` | `DELETE /api/collections/{name}` | Soft-delete collection |
| `restore_collection(name)` | `POST /api/collections/{name}/restore` | Restore collection |
| `stats()` | `GET /api/stats` | System statistics |
| `health()` | `GET /api/health` | Health check |

### Return types

Return types are dataclasses, not dicts: `Document`, `SearchResult`, `Collection`, `Stats`, `Health`. Sensible `__repr__` that doesn't dump 50KB of markdown.

### Error handling

Errors are exceptions, not error dicts:

- `AriadneClientError` — base exception
- `AriadneAuthError` — 401/403
- `AriadneNotFoundError` — 404
- `AriadneServerError` — 5xx

Each includes the HTTP status code, the server's error message, and the request that caused it.

### CLI

```bash
ariadne ingest report.pdf --collection reports
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
ariadne search "rare earth mining" --collection world-bank-ree --top-k 10
ariadne list-documents --collection world-bank-ree
ariadne list-collections
ariadne stats
ariadne health
```

### Manifest-based ingestion

For corpora with existing metadata (World Bank reports, academic papers, regulatory documents), the CLI's `--manifest` flag attaches per-file provenance during ingestion. Each file is matched to its manifest entry and ingested with the entry's metadata as `agent_metadata`.

Manifest format is adapter-based — each corpus type has its own adapter that reads the native format and produces per-file metadata. The client doesn't enforce a fixed schema on the metadata dict.

---

## Ingestion

Three paths to get a document into Ariadne, in preference order:

### 1. URL — server fetches directly (zero tokens)

Pass an HTTP/HTTPS URL to `POST /api/documents`. The server downloads and processes the document. No bytes flow through the agent.

```python
client.ingest_url("https://example.com/report.pdf", collection="reports")
```

This is the best path when the document is available at a URL. The URL is automatically recorded as the document's `source_reference`.

### 2. File upload — client sends the file (zero tokens)

The client uploads the file via `POST /api/upload`, then triggers conversion via `POST /api/documents` with the returned server path. The client package wraps both steps into one call:

```python
client.ingest_file("path/to/report.pdf", collection="reports")
```

Or via CLI:

```bash
ariadne ingest report.pdf --collection reports
```

The file bytes travel over HTTP once and never enter the LLM's context. A 6 MB PDF as base64 would be ~8 MB / ~1.5-2M tokens — uploading avoids that entirely.

### 3. Bytes already in context — store what the agent has

When a user drops a file into the chat UI, the LLM already has the content. Rather than discarding it and re-uploading, `ingest_bytes` sends the content directly:

```python
client.ingest_bytes(file_content, filename="report.pdf", collection="reports")
```

After ingesting bytes, the agent should tell the user: "This file is now in Ariadne and searchable. Next time, give me the file path instead of dropping it — I'll ingest it directly without loading it into our conversation."

### Batch ingestion

For directories of files already on the server, `POST /api/ingest` processes all supported files in a directory. For local directories, the CLI handles upload + conversion per file:

```bash
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
```

The `--manifest` flag attaches per-file metadata from a JSONL manifest during ingestion. See the Client package section for details.

### What NOT to do

- Do not base64-encode file content into API calls. The bytes would flow through the LLM's context window, burning tokens for transport instead of understanding.
- Do not loop over files calling the REST API manually when the client or CLI handles batching.
- Do not pass local file paths to `POST /api/documents` — local paths are meaningless to the server. Upload first, or use the client package which handles this automatically.

---

## Search

Semantic search finds document chunks by meaning, not keywords. The query is embedded and compared against all stored chunk vectors using cosine similarity (pgvector HNSW index).

### Basic usage

```python
results = client.search("rare earth mining impacts", collection="world-bank-ree", top_k=10)
for r in results:
    print(r.relevance_score, r.text[:100])
```

### Filters

Search supports filtering to narrow results before vector comparison:

| Filter | Type | Behavior |
|--------|------|----------|
| `collection` | string | Scope to a single collection |
| `document_id` | string | Scope to chunks from one document |
| `source_file` | string | Substring match (case-insensitive) on filename |
| `file_type` | string | Exact match on extension (`.pdf` and `pdf` both work) |
| `tags` | list[str] | Match documents with any of these tags (OR logic) |
| `metadata` | dict | JSONB containment against the latest interaction's `agent_metadata`. Nested keys supported: `{"labels": {"project": "atlas"}}` matches docs where `agent_metadata.labels.project == "atlas"`. |
| `metadata_exists` | list[str] | Every listed key must be present (as a top-level key) in the latest interaction's `agent_metadata`. Value-agnostic. |

Filters compose with AND semantics across keys — `collection` + `tags` + `metadata` together narrow further on each axis. Inside `tags`, the listed tags compose with OR. Inside `metadata_exists`, the listed keys compose with AND (every key must be present).

`metadata` and `metadata_exists` resolve against the *latest* interaction's `agent_metadata` per document — matching the "agent_metadata is per-interaction" convention used everywhere else in the system (see § Metadata Conventions and the `agent_metadata` include on `GET /api/documents`). A GIN index on `document_interactions(agent_metadata)` makes both operators index-eligible at scale. Malformed input (`metadata` not a dict, `metadata_exists` not a list of strings) returns 422 before the embedding API is called.

**Note on latest-interaction semantics.** Each `document_interactions` row stores the `agent_metadata` dict that was submitted on that call — not the merged result. After `PATCH /api/documents/{id}` with a partial `agent_metadata` body (e.g. `{"status": "reviewed"}`), the latest interaction's `agent_metadata` is just `{"status": "reviewed"}`; keys set by earlier interactions are not re-included. Filter against the latest-interaction surface accordingly — to match a doc reliably across PATCH updates, pass the keys you care about on every PATCH, or filter against `metadata_exists` on a key set by ingestion.

### Search behavior notes

- **Approximate (ANN):** Results may vary slightly between identical queries due to HNSW index traversal. For reproducible references, pin document/chunk IDs rather than re-querying.
- **Embedding required:** Search only works when an embedding API key is configured. Returns 503 if not.
- **Search logging:** Every search is recorded in the `search_log` table with the query, filters, results, and caller metadata. See the Search Log section.
- **Soft-deleted documents** are excluded by default. Pass `include_deleted: true` to include them.

---

## Document management

### Retrieving documents

**Get a single document** by ID with `GET /api/documents/{id}`. Returns the full document including markdown content, chunks, metadata, tags, collection, and interaction history (optionally).

**List documents** with `GET /api/documents`. Paginated (default 50, max 100). Filter by collection. Includes soft-deleted documents when `include_deleted=true`.

### Updating metadata

`PATCH /api/documents/{id}` updates a document's tags, collection, or agent_metadata without re-processing the content. This is the efficient way to annotate documents after review — no re-extraction, re-chunking, or re-embedding.

- `tags`: replaces the tag list entirely (not a merge)
- `collection`: moves the document to a different collection
- `agent_metadata`: shallow-merged with existing metadata (new keys added, existing keys overwritten, missing keys preserved)

### Soft-delete and restore

Documents and collections support soft-delete with a 48-hour recovery window.

**Delete a document:** `DELETE /api/documents/{id}` marks it as deleted. It disappears from list and search results but remains in the database for 48 hours.

**Restore a document:** `POST /api/documents/{id}/restore` un-deletes it within the 48-hour window. After 48 hours, restore returns 410 (Gone).

**Delete a collection:** `DELETE /api/collections/{name}` soft-deletes all documents in the collection.

**Restore a collection:** `POST /api/collections/{name}/restore` restores all soft-deleted documents in the collection that are still within their recovery window.

### Collections

Logical namespaces for documents. Key behaviors:

- Dedup is scoped per collection — the same document can exist in multiple collections
- Search defaults to all collections but can be scoped to one
- Collections are cheap — use them to organize by project, topic, or workflow
- A document in `"default"` signals the agent didn't think about organization
- Create collections explicitly with `POST /api/collections` or implicitly by specifying a collection name during ingestion

### Document lifecycle summary

| Action | Endpoint / Method | Effect |
|--------|-------------------|--------|
| Ingest | `POST /api/documents` | Create document, extract, chunk, embed, store |
| Read | `GET /api/documents/{id}` | Retrieve full document with metadata |
| List | `GET /api/documents` | Paginated list, filterable by collection |
| Search | `POST /api/search` | Find chunks by semantic similarity |
| Update | `PATCH /api/documents/{id}` | Modify tags, collection, metadata (no re-processing) |
| Delete | `DELETE /api/documents/{id}` | Soft-delete (48h recovery) |
| Restore | `POST /api/documents/{id}/restore` | Undo soft-delete |
| Force re-process | `POST /api/documents` with `force: true` | Re-extract, re-chunk, re-embed |

---

## Caller metadata

All document and search endpoints accept these optional fields for provenance tracking. Ingestion endpoints (`POST /api/documents`, `POST /api/ingest`) create a `document_interactions` row on every call, even dedup skips. `POST /api/search` creates a `search_log` row on every call.

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Caller's session or workflow identifier (e.g., `"cowork-session-abc"`) |
| `agent_type` | string | Client type: `"claude-code"`, `"cursor"`, `"api"`, `"ci"`, etc. |
| `model` | string | LLM model powering this session (e.g., `"claude-sonnet-4-6"`) |
| `initiated_by` | string | Human or system identity (e.g., `"user:denson"`) |
| `agent_notes` | string | Free-text context (e.g., the user's prompt that triggered the call) |
| `agent_metadata` | dict | Structured JSON for any additional context (project ID, eval run details, etc.) |

## Metadata Conventions

The caller metadata fields (`agent_notes`, `agent_metadata`, `collection`, `tags`) are intentionally flexible — any agent can write any value. But flexibility without convention produces unsearchable noise. These conventions exist so that metadata written by one agent, in one session, is discoverable and meaningful to a different agent, in a different session, weeks later.

None of these conventions are enforced by the system. They are recommendations. Agents that follow them produce metadata that composes well with search, filtering, and provenance queries. Agents that ignore them still work — their metadata is just harder to use.

### When to use `collection` vs `tags` vs `agent_metadata`

These three fields serve different purposes. Using the wrong one doesn't break anything, but it makes filtering harder.

| Field | Scope | Purpose | Example |
|-------|-------|---------|---------|
| `collection` | Per-document | Broad namespace for a corpus. Dedup is scoped per collection. Search can be scoped to one. | `"quarterly-reports"`, `"legal-contracts"`, `"project-atlas"` |
| `tags` | Per-document | Cross-cutting labels that span collections. Searchable via the `tags` filter (OR logic). | `["pricing", "q1-2026", "reviewed"]` |
| `agent_metadata` | Per-interaction | Structured facts about this specific processing event. JSON with known keys. | `{"intent": "research", "project": "atlas", "status": "extracted"}` |

**`collection`** answers: *what corpus does this document belong to?*
**`tags`** answer: *what cross-cutting categories apply to this document?*
**`agent_metadata`** answers: *why did this agent process this document right now, and what did it find?*

Every document should have a collection. A document in the `"default"` collection is a signal that the agent didn't think about organization — which means future search and filtering are degraded. If you don't know what collection to use, name it after the project, topic, or task.

### Recommended `agent_metadata` keys

`agent_metadata` accepts arbitrary JSON. These conventional keys make metadata written by different agents interoperable:

| Key | Type | Description |
|-----|------|-------------|
| `project` | string | Project name or identifier (e.g., `"atlas"`, `"q4-review"`) |
| `source_url` | string | Where the document was downloaded from, if applicable. Still valid; `source_reference` is preferred going forward. |
| `source_reference` | string | Most authoritative reference to the document's origin: DOI, URL, database/API reference, local file path, or the literal `"unknown"`. See "Source provenance" below. |
| `source_notes` | string | Free-text context about provenance — especially when the source is unknown, ambiguous, or required interpretation. |
| `intent` | string | Why the agent processed this document: `"research"`, `"compliance-review"`, `"onboarding"`, `"reference"`, `"archival"` |
| `findings` | string | Brief summary of what the agent learned from the document |
| `status` | string | Processing state: `"extracted"`, `"reviewed"`, `"needs-follow-up"`, `"superseded"` |
| `related_documents` | list[str] | Document IDs of related items the agent found or was working with |

These keys are recommendations, not a schema. Agents can add any additional keys that make sense for their workflow. The value of following the convention is that another agent can filter or search `agent_metadata` for `intent: "research"` and find documents across sessions and agent types.

### Source provenance

Every document should carry a `source_reference`. This is the most important metadata field for corpus integrity: a document with no recorded origin is unverifiable and uncitable, and a corpus full of unsourced documents quickly becomes noise.

**Default hierarchy** (most authoritative first):

1. **DOI** — for research papers, format as `"doi:10.xxxx/..."`
2. **URL** — the original URL the document was downloaded from (not the server upload path)
3. **Database / API reference** — the query, endpoint, or record ID the document came from
4. **Local file path** — the original filesystem path, when no upstream source exists
5. **`"unknown"`** — explicit, when the agent considered provenance and could not determine it

**Explicit unknown is better than missing.** Setting `"source_reference": "unknown"` (with a `source_notes` explanation) signals that an agent considered provenance and couldn't determine it. A missing field signals that no one tried.

**Backward compatibility.** `source_url` remains valid and readers should accept either key. New code should write `source_reference`; both keys may coexist on the same document.

**Project-specific override.** Project skills (e.g., a cannabis research skill) may override this hierarchy with stricter, domain-specific rules — for example, requiring a DOI for research papers and tagging missing-DOI papers `provenance:no-doi` and `status:needs-review`.

**Worked examples:**

```json
{
  "agent_metadata": {
    "source_reference": "doi:10.1038/s41586-024-07123-4",
    "intent": "research",
    "project": "atlas"
  }
}
```

```json
{
  "agent_metadata": {
    "source_reference": "unknown",
    "source_notes": "User pasted PDF contents into chat with no filename or URL. Asked but they didn't recall where it came from.",
    "intent": "reference"
  }
}
```

### How to write useful `agent_notes`

`agent_notes` is a free-text string. It should help the next agent (or the same agent in a future session) decide whether to re-read this document or skip it.

**Bad:**
```
"processed this file"
```

**Good:**
```
"Extracted for Q1 pricing review. Found 3 tables on revenue projections.
Section 4.2 has the margin breakdown the user asked about."
```

**Good:**
```
"User uploaded during contract negotiation. Key clauses: termination (Section 8),
IP assignment (Section 12), non-compete (Section 15). No unusual terms flagged."
```

The test: if a different agent searches and finds this document six months from now, will the note tell them enough to decide whether it's relevant without re-reading the full content?

### Tag conventions

Tags are free-form strings, but following these conventions makes them composable with search filters:

- **Lowercase, hyphenated:** `"q1-2026"` not `"Q1 2026"`
- **Namespace prefixes for categories:** `"project:atlas"`, `"status:reviewed"`, `"source:email"`, `"dept:legal"`
- **Keep tags searchable:** they compose with the `tags` filter in `search` (OR logic). A tag like `"reviewed"` is useful; a tag like `"reviewed-by-jane-on-tuesday"` is too specific to filter on

Common tag patterns:

| Pattern | Examples | Use case |
|---------|----------|----------|
| Time period | `"q1-2026"`, `"fy-2025"` | Filter documents by business period |
| Status | `"status:reviewed"`, `"status:needs-follow-up"` | Track review workflow |
| Source | `"source:email"`, `"source:slack"`, `"source:upload"` | Filter by how the document arrived |
| Domain | `"legal"`, `"financial"`, `"technical"` | Cross-collection topic filtering |
| Project | `"project:atlas"`, `"project:onboarding"` | When documents span multiple collections but share a project |

### Worked examples

#### 1. Single document extraction — user drags a PDF into chat

The user says: *"Can you look at this quarterly report and tell me about the revenue trends?"*

The agent ingests the file:

```python
doc = client.ingest_file("acme-q1-2026-report.pdf",
    collection="acme-financials",
    tags=["financial", "q1-2026"],
    source="https://acme.com/investor-relations/q1-2026-report.pdf",
    agent_notes="User asked about revenue trends in Acme Q1 2026 quarterly report. Extracting for analysis.",
    agent_metadata={"intent": "research", "project": "acme-review"}
)
```

After extraction, the agent reads the Markdown and answers the user's question. The document is now searchable — if the user asks about Acme financials next week, `search` with `collection: "acme-financials"` will find it.

#### 2. Batch project ingest — agent processes a folder of contracts

The user says: *"Process everything in /data/contracts/ — these are the vendor agreements for Project Atlas."*

The agent checks existing collections, then ingests the directory:

```bash
ariadne ingest /data/contracts/ \
    --collection atlas-vendor-contracts \
    --tags legal,project:atlas,vendor \
    --recursive
```

Or via Python:

```python
# The CLI handles the batch; the agent sets metadata via env or config
```

After ingest completes, the agent reports: *"Processed 23 files (2 skipped as duplicates, 1 failed — password-protected). All are now searchable in the `atlas-vendor-contracts` collection."*

#### 3. Research session — agent searches, reads, and annotates across multiple docs

The user says: *"What do our contracts say about termination clauses? I need to compare across vendors."*

**Step 1 — Search:**

```python
results = client.search("termination clause early exit penalty",
    collection="atlas-vendor-contracts",
    top_k=10,
    agent_notes="User comparing termination clauses across vendor contracts for Project Atlas.",
    agent_metadata={"intent": "research", "project": "atlas"}
)
```

**Step 2 — Deep read:** The agent calls `client.get_document()` on the top results to read full content, then synthesizes a comparison.

**Step 3 — Follow-up search** (narrowing):

```python
results = client.search("early termination penalty fee 30 days notice",
    collection="atlas-vendor-contracts",
    top_k=5,
    filters={"tags": ["vendor"]},
    agent_notes="Narrowing to specific penalty terms. 4 of 10 had relevant clauses.",
    agent_metadata={
        "intent": "research",
        "project": "atlas",
        "findings": "Termination clauses in Vendor A (S8), C (S12), D (S6.3), F (S9). Vendor B has none."
    }
)
```

Note how the `agent_notes` and `agent_metadata.findings` evolve across calls — the second search's metadata captures what was learned from the first. A future agent reviewing the search log can reconstruct the research trajectory.

#### 4. Multi-agent handoff — agent A ingests, agent B reviews, agent C answers

This pattern spans multiple sessions. The metadata conventions make it work.

**Agent A (Claude Code) — initial ingest:**

```python
doc = client.ingest_url("https://example.com/reports/safety-audit-2026.pdf",
    collection="compliance-audits",
    tags=["compliance", "safety", "2026"],
    agent_notes="Ingesting annual safety audit report. Downloaded from compliance portal.",
    agent_metadata={"intent": "archival", "status": "extracted"}
)
```

**Agent B (different session, maybe different user) — review and annotate:**

Agent B searches, finds the document, reads it, and updates it with review findings:

```python
client.update_document(doc.document_id,
    tags=["compliance", "safety", "2026", "status:reviewed"],
    agent_metadata={
        "intent": "compliance-review",
        "status": "reviewed",
        "findings": "3 critical findings: fire suppression (S4), ventilation (S7), emergency exits (S11). All prior-year findings closed.",
        "related_documents": ["doc-uuid-prior-year-audit"]
    }
)
```

Note: `update_document` (PATCH) updates metadata without re-processing content — no re-extraction, re-chunking, or re-embedding. This is the efficient way to annotate after review.

**Agent C (weeks later) — answering a question:**

A user asks: *"What's the status of our safety compliance?"*

Agent C searches `collection: "compliance-audits"`, finds the document, and sees from the interaction history:
- Agent A ingested it (status: `"extracted"`)
- Agent B reviewed it (status: `"reviewed"`, findings summarized)

Agent C can answer the question using Agent B's findings without re-reading the full document. The `agent_notes` from Agent B's interaction tell Agent C exactly what was found and what the deadlines are.

This is the payoff of metadata conventions: Agent C didn't need to know about Agent A or Agent B. It just searched, found a document with rich interaction history, and used that history to answer the question efficiently.

---

## Dedup

Every document is fingerprinted (SHA-256 on the raw source bytes — file bytes for local sources, the HTTP response body after redirect resolution for URL sources, with no Content-Encoding decompression so fingerprint and extraction read byte-identical content) before any expensive processing. Dedup is therefore independent of extraction non-determinism (markitdown version, vision-API caption variance). As of `ariadne--k7n` (2026-05-06): pre-fix entries retain their original markdown-derived fingerprints; re-ingesting one of those source files produces a NEW entry under the new algorithm. No automatic migration; track via `ariadne--<future-migration-ticket>` if duplicate-pollution becomes load-bearing at scale.

If the fingerprint already exists in the target collection:

1. Extraction, chunking, and embedding are skipped
2. A `document_interactions` row is still created (recording who asked, when, and why)
3. The existing document is returned to the caller

The `force` flag on `POST /api/documents` and `POST /api/ingest` overrides this when you know a document has changed.

On a dedup skip, the response includes the existing document's `markdown`, `interactions`, and all metadata fields — the only difference is `was_dedup_skip: true` and no re-processing occurs. Callers always get the full document back.

## Provenance

Every agent call creates a record, even dedup skips. When you search and get a result, you also get the full history of who has touched that document:

- **processing_chain** (on the document) tells you how the content was processed: which extraction tool, which enrichment steps, which embedding model, with timestamps
- **document_interactions** (separate table) tells you who touched it: which agent, which model, when, what action, whether it was a dedup skip, plus `agent_notes` and `agent_metadata`

The `action` field in `document_interactions` uses these canonical values:

| Action | Source | Meaning |
|--------|--------|---------|
| `"convert"` | `POST /api/documents` | Agent deliberately processed a single document via URL or server-side path |
| `"ingest"` | `POST /api/ingest` | Document was swept up in a batch directory ingestion |
| `"search"` | `POST /api/search` (in `search_log`) | Query recorded in the search log |

The distinction between `"convert"` and `"ingest"` matters for provenance — knowing whether a document was deliberately processed or swept up in a batch tells you something about intent.

---

## Search Log

Every `search` call is recorded in the `search_log` table. One row per search — not per result. This captures what agents searched for, why, and what they found, so that the full usage history of the knowledge store is preserved alongside the document provenance.

The `search_log` table stores:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `query` | text | The search query |
| `collection` | text | Single-collection scope (null = either multi-scope or no filter) |
| `collections` | text[] | Multi-collection scope (ariadne--2cf). NULL on single-collection / no-collection searches. GIN-indexed for `'X' = ANY(collections)` and `unnest(collections) GROUP BY` analytics |
| `filters` | JSONB | Filters applied (file_type, source_file, tags, document_id, etc.). Multi-collection scope is also reachable via `filters @> '{"collection_in": [...]}'::jsonb` — the `collections` column is the analytics fast-path; the JSONB filter is the general dispatch mechanism |
| `top_k` | int | Number of results requested |
| `results_count` | int | Number of results actually returned |
| `result_document_ids` | UUID[] | Document IDs of the results, in rank order |
| `agent_id` | text | Caller's session or workflow identifier |
| `agent_type` | text | Client type |
| `model` | text | LLM model |
| `initiated_by` | text | Human or system identity |
| `agent_notes` | text | Free-text context — what the agent was looking for and why |
| `agent_metadata` | JSONB | Structured JSON — the caller's custom context (project, task, reason, etc.) |
| `created_at` | timestamptz | When the search happened |

The `agent_metadata` field is the key extensibility point. Any agent builder can store whatever structured context they need — project IDs, task descriptions, batch identifiers, client names, filing types — anything that helps them organize and trace their usage of the knowledge store later.

**Analytics on multi-collection usage (ariadne--2cf):**

```sql
-- Multi-collection usage rate
SELECT COUNT(*) AS multi_scope_searches
FROM search_log WHERE collections IS NOT NULL;

-- Co-occurrence: which collections do agents query together?
SELECT unnest(collections) AS collection_name, COUNT(*) AS hits
FROM search_log
WHERE collections IS NOT NULL
GROUP BY 1 ORDER BY hits DESC;

-- Every search that touched collection X (covers both single + multi scope)
SELECT * FROM search_log
WHERE collection = 'X' OR 'X' = ANY(collections);
```

## Pipeline order

Processing sequence for each document. The order matters.

1. **Receive** — document arrives via URL (`POST /api/documents`), file upload (`POST /api/upload` → `POST /api/documents`), or batch path (`POST /api/ingest`)
2. **Encoding detection** *(text files only)* — charset-normalizer decodes the file; detects encoding, confidence, and language. If confidence is low or encoding is not UTF-8, adds warning tags (e.g., `encoding:windows-1252`, `encoding:low-confidence`)
3. **Extract to Markdown** — MarkItDown converts the document to clean Markdown. For .txt files, the charset-normalizer output from step 2 is used directly (MarkItDown is skipped to avoid re-detection errors). If extraction produces empty content, the document is still stored but tagged `content:empty` and a warning is included in the response.
4. **Language validation** *(text files only)* — a lightweight LLM (default: gemini-2.0-flash-lite) reads a sample of the extracted text and validates: is this coherent human-language text? Records language, script, confidence. Adds tags if the text appears to be binary data, encoding artifacts, or a non-target language

Extraction may add suggested tags to the document (e.g., `encoding:windows-1252`, `language:french`, `content:binary-data`). These are informational — they help agents and users filter or review documents but do not affect processing.

5. **Content fingerprint** — SHA-256 over raw source bytes (computed BEFORE extraction). If the fingerprint already exists in the target collection, skip to step 10 (unless `force` flag is set).
6. **Image enrichment** *(optional)* — vision API describes images found in the extracted Markdown, replacing `![image](...)` placeholders with semantic descriptions
7. **Chunk** — split Markdown into chunks. Strategy is auto-selected by file type (configurable)
8. **Embed** — compute vector embeddings for each chunk. Model tracked per chunk so mixed-model corpora are handled correctly
9. **Store** — write document, chunks, and embeddings to Postgres + pgvector
10. **Record interaction** — create a `document_interactions` row (always, even on dedup skip). Records who, when, what action, and all caller metadata

---

## Expected agent behavior

These patterns should be taught via the skill file and reinforced via Claude Code project instructions.

### When to use Ariadne instead of reading files directly

When the agent encounters a document (PDF, DOCX, PPTX, XLSX, or any supported format), it should ingest it via the client package instead of trying to read the file directly. The extracted Markdown is cleaner, more token-efficient (often 8-15x smaller than raw content), and gets stored for future search. The only exception is very small text files (under ~10 pages of plain text) where the agent can handle them in context without extraction.

### How to choose an ingestion method

1. **Document at a URL** → `client.ingest_url(url)` — server fetches directly, zero tokens
2. **Local file** → `client.ingest_file(path)` — client uploads, zero tokens
3. **Content already in context** (user dropped file in chat) → `client.ingest_bytes(content, filename)` — stores what the agent already has

Never pass raw file bytes through the LLM's context when you can avoid it. A 6 MB PDF as base64 is ~1.5-2M tokens of transport payload.

### How to choose a collection

The agent should never dump everything into `"default"`. Collection choice follows this logic:

1. If the user specifies a collection name, use it.
2. If the agent is working in a project context (a repo, a research topic, a client engagement), use the project name. Examples: `"ariadne-core"`, `"q4-research"`, `"acme-contract-review"`.
3. If the user is doing a one-off task with no clear project, use a descriptive name. Examples: `"receipts"`, `"reference-docs"`, `"meeting-notes"`.
4. If none apply, use `"default"` — but this should be rare.

The agent should tell the user which collection it chose and why, so the user can correct it or reuse it later.

### How to use caller metadata

Every call should include caller metadata. This is not optional in practice — the provenance trail is only useful if agents actually populate it.

- `agent_type`: always set. `"claude-code"`, `"cursor"`, `"api"`, etc.
- `initiated_by`: always set when user identity is known. Format: `"user:name"`.
- `model`: always set. The model the agent is running on.
- `agent_notes`: set on every call. The user's prompt or a brief description of why this action is being taken. This is the most valuable provenance field.
- `agent_id`: set when available. The session ID or workflow identifier.
- `agent_metadata`: set when there's structured context worth preserving.

When using the client package, set defaults on the constructor and they apply to every call:

```python
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

### When to search before answering

If the user asks a question that could be answered by documents they've previously ingested ("what did the report say about...", "find that contract clause about..."), the agent should call `client.search()` before attempting to answer. Don't guess from memory — search first, then synthesize from results.

Use the `collection` parameter or `filters` to narrow search when the context makes it obvious.

### When to use batch vs. single ingestion

- Single file → `client.ingest_url()` or `client.ingest_file()`
- Directory of files → `ariadne ingest` CLI command (handles batching, progress, error recovery)
- The agent should tell the user how many files were found and give a time estimate before starting a large batch
