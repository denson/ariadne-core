# Task: Rewrite Configuration + Pipeline sections of SPEC.md (Step 4)

**For:** Dave

---

## What to do

Rewrite two sections in `ariadne-core/SPEC.md`:

1. **`## Configuration`** (lines ~143–167) — rewrite in place
2. **`## Pipeline order`** (lines ~999–1010) — rewrite in place

Do NOT touch anything outside these two sections.

---

## Section 1: Configuration (lines ~143–167)

### Problems with the current version

1. Env var names are wrong — production uses `ARIADNE_` prefix, not bare names
2. Model defaults are wrong — production uses Google Gemini, not OpenAI
3. The `MCP_PORT` subsection documents MCP dual-port mode which is being removed
4. The description says "same OpenAI key" — the server uses Google, not OpenAI

### Replace the entire Configuration section with:

```markdown
## Configuration

All configuration is controlled via environment variables. The config file (`config/ariadne.yaml`) interpolates them.

### Required

| Variable | Description |
|----------|-------------|
| `DB_PASSWORD` | Postgres password |
| `ARIADNE_API_KEY` | API key for authenticating client requests. Stored as SHA-256 hash on the server. |

### Embedding

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_EMBEDDING_API_KEY` | *(required for search)* | API key for the embedding provider |
| `ARIADNE_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model name |
| `ARIADNE_EMBEDDING_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` | OpenAI-compatible endpoint |

### Image enrichment

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_IMAGE_ENRICHMENT_API_KEY` | *(optional)* | API key for vision model used to describe images found in extracted documents |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | `gemini-2.0-flash` | Vision model name |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` | OpenAI-compatible endpoint |

### Language validation

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIADNE_LANGUAGE_VALIDATION_API_KEY` | *(optional — falls back to embedding key)* | API key for the LLM that validates .txt file language/coherence |
| `ARIADNE_LANGUAGE_VALIDATION_MODEL` | `gemini-2.0-flash-lite` | Lightweight model for language validation |
| `ARIADNE_LANGUAGE_VALIDATION_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` | OpenAI-compatible endpoint |

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | REST API port. On Railway, set automatically. |
| `DATABASE_URL` | — | Postgres connection string. Railway injects `DATABASE_URL_PRIVATE` (internal network, no egress fees) and `DATABASE_URL` (public); the server prefers `DATABASE_URL_PRIVATE` when available. |

All three API subsystems (embedding, image enrichment, language validation) use OpenAI-compatible endpoints. You can point them at any provider — Google Gemini (default), OpenAI, Anthropic via proxy, local models, etc. — by changing the `BASE_URL`, `MODEL`, and `API_KEY` for each.
```

### What changed vs. current

- `VISION_*` → `ARIADNE_IMAGE_ENRICHMENT_*`
- `EMBEDDING_*` → `ARIADNE_EMBEDDING_*`
- Added `ARIADNE_LANGUAGE_VALIDATION_*` (new — supports encoding detection feature)
- Defaults changed from OpenAI models to Google Gemini models
- Removed `MCP_PORT` and the entire MCP dual-port/single-port subsection
- Removed `MCP_ALLOWED_HOSTS`
- Switched from code block to tables for readability
- Added `ARIADNE_API_KEY` to required section

---

## Section 2: Pipeline order (lines ~999–1010)

### Problems with the current version

1. Missing encoding detection step (implemented in commit `560c2e4`)
2. Missing language validation step (implemented in commit `560c2e4`)
3. References `convert_document` (MCP tool name) instead of describing the pipeline neutrally

### Replace the entire Pipeline order section with:

```markdown
## Pipeline order

Processing sequence for each document. The order matters.

1. **Receive** — document arrives via URL (`POST /api/documents`), file upload (`POST /api/upload` → `POST /api/documents`), or batch path (`POST /api/ingest`)
2. **Encoding detection** *(text files only)* — charset-normalizer decodes the file; detects encoding, confidence, and language. If confidence is low or encoding is not UTF-8, adds warning tags (e.g., `encoding:windows-1252`, `encoding:low-confidence`)
3. **Extract to Markdown** — MarkItDown converts the document to clean Markdown. For .txt files, the charset-normalizer output from step 2 is used directly (MarkItDown is skipped to avoid re-detection errors)
4. **Language validation** *(text files only)* — a lightweight LLM (default: gemini-2.0-flash-lite) reads a sample of the extracted text and validates: is this coherent human-language text? Records language, script, confidence. Adds tags if the text appears to be binary data, encoding artifacts, or a non-target language
5. **Content fingerprint** — SHA-256 on normalized text. If the fingerprint already exists in the target collection, skip to step 10 (unless `force` flag is set)
6. **Image enrichment** *(optional)* — vision API describes images found in the extracted Markdown, replacing `![image](...)` placeholders with semantic descriptions
7. **Chunk** — split Markdown into chunks. Strategy is auto-selected by file type (configurable)
8. **Embed** — compute vector embeddings for each chunk. Model tracked per chunk so mixed-model corpora are handled correctly
9. **Store** — write document, chunks, and embeddings to Postgres + pgvector
10. **Record interaction** — create a `document_interactions` row (always, even on dedup skip). Records who, when, what action, and all caller metadata
```

### What changed vs. current

- Added step 1 (Receive) — makes the entry points explicit
- Added step 2 (Encoding detection) — new feature, commit `560c2e4`
- Added step 4 (Language validation) — new feature, commit `560c2e4`
- Removed MCP tool name `convert_document` — described neutrally
- Added note about .txt files skipping MarkItDown (commit `4ce57f0`)
- Added note about embedding model tracked per chunk
- Renumbered all steps

---

## What NOT to change

- Sections 1-3 (approved)
- The REST API section (approved)
- The Client package section (just committed)
- Anything between the Configuration section and Pipeline order section
- Anything after Pipeline order

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.
