# SPEC.md — native-Gemini migration, provider constraints

**For:** Dave
**Context:** Full project context is in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Short version: `AQ.*`-format Gemini keys don't work on the OpenAI-compat shim (empirically verified, see `../../test_auth_variants.py` in the workspace). Ariadne's bundled embedding, image enrichment, and language validation must migrate to native Gemini endpoints. This is phase 1 of 8 — spec only, no code yet.

This is a **spec-only change** — the source-of-truth document. Later phases (skills, code, tests) will all read from what you write here, so be precise.

---

## Step 1: Edit `SPEC.md` — three subsystem tables

Open `SPEC.md`. You are editing three consecutive subsections under `## Configuration`: `### Embedding` (~line 156), `### Image enrichment` (~line 165), `### Language validation` (~line 173), and the summary paragraph after them (~line 188).

### 1a. Update the three tables

For each of `### Embedding`, `### Image enrichment`, `### Language validation`:

- Change the `BASE_URL` default value column from `https://generativelanguage.googleapis.com/v1beta/openai` to `https://generativelanguage.googleapis.com/v1beta` (no `/openai` suffix).
- Change the `BASE_URL` description column from `OpenAI-compatible endpoint` to `Gemini native API root. See "Provider constraints" below.`

Keep every other row (model, API key, extra params) identical. Do not change model defaults.

### 1b. Replace the summary paragraph at line ~188

The current paragraph says:

> All three API subsystems (embedding, image enrichment, language validation) use OpenAI-compatible endpoints. You can point them at any provider — Google Gemini (default), OpenAI, Anthropic via proxy, local models, etc. — by changing the `BASE_URL`, `MODEL`, and `API_KEY` for each.

Replace it with the following (verbatim):

```markdown
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
```

---

## Step 2: Do not touch anything else

No other SPEC.md sections change in this phase. Do not update REST API examples, caller metadata, ingestion, or anything downstream — those either already match or will be addressed in later phases.

Do not touch the walkthrough skill, the deploy skill, `config.py`, the three pipeline modules, `.env.example`, the CLI `_ENV_TEMPLATE`, `README.md`, any `docs/*.md`, any tests, or `FIXES.md`. All of those come in later phases and Bob will reject this commit if anything else is modified.

---

## Step 3: Verify

```bash
cd ariadne-core
grep -n "openai" SPEC.md
```

Expect: `SPEC.md` no longer mentions `/v1beta/openai`. Remaining `openai` mentions should only be in the provider-swap note or the "OpenAI proper" reference — not as part of a URL default.

```bash
grep -n "batchEmbedContents\|generateContent\|x-goog-api-key" SPEC.md
```

Expect: all three tokens appear in the new "Provider constraints" section.

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:
- The three BASE_URL rows before/after.
- A short confirmation that the "Provider constraints" section is in place with all three contracts.
- `git status` showing only `SPEC.md` modified.
