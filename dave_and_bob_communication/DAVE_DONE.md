# DAVE — Backlog-5 Tier-1 doc scrub: DONE (unstaged, awaiting Bob)

Per `DAVE_BACKLOG5_DOC_SCRUB.md`. Mechanical line-level edits to 4 docs +
1 new `tests/fixtures/README.md`. Nothing staged, nothing committed —
all changes left unstaged for Bob.

---

## Step 0 — pre-flight (evidence)

```
$ git status
On branch main
Your branch is up to date with 'origin/main'.

Untracked files:
	scripts/_generate_encoding_fixtures.py
	scripts/_probe_embedder.py
	scripts/_probe_text_encoding.py
	scripts/_probe_vision.py
	tests/fixtures/clean_english_sample.txt
	tests/fixtures/mojibake_sample.txt

nothing added to commit but untracked files present

$ git rev-parse HEAD
08bfde20423fce7eaed3882e974a859303648282

$ git rev-parse origin/main
08bfde20423fce7eaed3882e974a859303648282
```

HEAD and `origin/main` both at `08bfde2` ✓. Nothing modified/staged ✓.

Minor note on the untracked enumeration in the spec: only 3 `scripts/_probe*.py`
files present (not 4). The spec's "4 probes" count was approximate; no
`_probe_*.py` file is missing — Phase 7.5 shipped 3 probes plus the generator.
No other untracked `DAVE_*` / `BOB_*` diagnostics beyond this file and the
spec itself. None of that affects the edits; flagging for transparency only.

---

## Files edited (4)

- `docs/configuration.md` — Edits 1.1, 1.2, 1.3
- `docs/installation.md` — Step 2 (embedding/vision errors block)
- `migrations/001_initial.sql` — Step 3 (one-word comment fix on line 93)
- `skills/ariadne-core-build/SKILL.md` — Edits 4.1, 4.2

## Files created (1)

- `tests/fixtures/README.md` — Step 6, verbatim content (see confirmation below)

## Files deliberately left untracked (unchanged from pre-flight)

- `tests/fixtures/clean_english_sample.txt`
- `tests/fixtures/mojibake_sample.txt`

Bob stages these in his commit per Step 5.

---

## Full `git diff` of the 4 edits

```diff
diff --git a/docs/configuration.md b/docs/configuration.md
index d490ace..bd2430b 100644
--- a/docs/configuration.md
+++ b/docs/configuration.md
@@ -98,12 +98,12 @@ embedding:

 Common embedding models:

-| Model | Dimensions | Provider | Cost | Notes |
-|-------|-----------|----------|------|-------|
-| `text-embedding-3-small` | 1536 | OpenAI | $0.02/M tokens | Best value for most use cases |
-| `text-embedding-3-large` | 3072 | OpenAI | $0.13/M tokens | Slightly better quality |
-| `BAAI/bge-large-en-v1.5` | 1024 | Together AI, Fireworks | Varies | Strong open-source retrieval model |
-| `BAAI/bge-m3` | 1024 | Together AI, Fireworks | Varies | Multilingual (if your docs aren't all English) |
+| Model | Dimensions | Provider | Notes |
+|-------|-----------|----------|-------|
+| `gemini-embedding-001` | 1536 | Google Gemini (native) | Current default. Cap at 1536 for pgvector HNSW compatibility. |
+| `gemini-embedding-001` | 3072 | Google Gemini (native) | Full dimensionality. Requires a vector store that supports >2000 dims (not pgvector HNSW). |
+| `BAAI/bge-large-en-v1.5` | 1024 | Together AI, Fireworks | Requires forking per SPEC.md → "Provider constraints". |
+| `BAAI/bge-m3` | 1024 | Together AI, Fireworks | Requires forking per SPEC.md → "Provider constraints". |

 When changing models, you must also update `dimensions` to match, and re-embed existing documents (existing vectors from a different model are incompatible).

@@ -230,13 +230,13 @@ Any config value can be overridden with an environment variable using the patter

 ```bash
 # Override the embedding model
-ARIADNE_EMBEDDING_MODEL=text-embedding-3-large
+ARIADNE_EMBEDDING_MODEL=gemini-embedding-001

 # Override the embedding dimensions
 ARIADNE_EMBEDDING_DIMENSIONS=3072

 # Override the image enrichment model
-ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o
+ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash

 # Override the log level
 ARIADNE_LOGGING_LEVEL=debug
diff --git a/docs/installation.md b/docs/installation.md
index e225752..c913299 100644
--- a/docs/installation.md
+++ b/docs/installation.md
@@ -186,14 +186,14 @@ Your data is preserved in Postgres. Migrations run automatically on startup.
 - For Claude Code: verify the header in `claude mcp list` output

 **Embedding or vision errors**
-Your API key is missing, invalid, or the base URL doesn't match your provider. Verify your key works by testing directly against your provider's endpoint. For example, with OpenAI:
+Your API key is missing, invalid, or the base URL doesn't match. Verify your key works by hitting the native Gemini endpoint directly:
 ```bash
-curl https://api.openai.com/v1/embeddings \
-  -H "Authorization: Bearer your-key-here" \
+curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents" \
+  -H "x-goog-api-key: your-key-here" \
   -H "Content-Type: application/json" \
-  -d '{"model": "text-embedding-3-small", "input": "test"}'
+  -d '{"requests":[{"model":"models/gemini-embedding-001","content":{"parts":[{"text":"test"}]}}]}'
 ```
-If using a different provider, substitute their base URL and model name. See [Compatible providers](../README.md#compatible-providers).
+A 200 response with an `embeddings` array confirms the key and endpoint work. Google's `AQ.*`-format keys (April 2026+) only accept the `x-goog-api-key` header on the native path — the OpenAI-compat shim at `/v1beta/openai/*` is not supported.

 ### Collecting diagnostics

diff --git a/migrations/001_initial.sql b/migrations/001_initial.sql
index c223985..918d60c 100644
--- a/migrations/001_initial.sql
+++ b/migrations/001_initial.sql
@@ -90,7 +90,7 @@ CREATE INDEX idx_interactions_collection ON document_interactions (collection_id
 -- NOTE: The embedding column dimension is configured at runtime via
 -- ariadne.yaml (embedding.dimensions). The app validates/creates the
 -- column with the correct dimension on startup. Default: 1536
--- (text-embedding-3-small). If you run this migration manually, replace
+-- (gemini-embedding-001). If you run this migration manually, replace
 -- %EMBEDDING_DIM% with your configured dimension (e.g. 1536, 1024, 768).
 -- ============================================================================
 CREATE TABLE IF NOT EXISTS chunks (
diff --git a/skills/ariadne-core-build/SKILL.md b/skills/ariadne-core-build/SKILL.md
index 4a2fa24..8acc295 100644
--- a/skills/ariadne-core-build/SKILL.md
+++ b/skills/ariadne-core-build/SKILL.md
@@ -77,7 +77,7 @@ ariadne-core/
 │       │   └── markitdown.py   # MarkItDown wrapper
 │       ├── enrichment/
 │       │   ├── images.py       # Image enrichment post-processing
-│       │   └── vision.py       # Vision API client (any OpenAI-compat endpoint)
+│       │   └── vision.py       # Vision API client (native Gemini generateContent)
 │       ├── chunking/
 │       │   └── chunker.py      # Chunking strategies (by_title, by_page, fixed_size)
 │       ├── embedding/
@@ -218,9 +218,10 @@ See SPEC.md for full parameter tables and response fields.
   in migration files.
 - **MCP server must be client-agnostic.** No Claude-specific assumptions. Works
   with any MCP client.
-- **API-first for embedding and vision.** Default path uses API calls to any
-  OpenAI-compatible endpoint. Local model support exists only as a config option —
-  never the default.
+- **API-first for embedding and vision.** Default path uses API calls to
+  Google Gemini's native endpoints (`batchEmbedContents`, `generateContent`).
+  Other providers require forking per SPEC.md → "Provider constraints".
+  Local model support exists only as a config option — never the default.
 - **Never store vectors from different embedding models in the same index without
   tracking which model produced them.** The `embedding_model` column on `chunks`
   must always be populated.
```

(Git emitted CRLF warnings on the three non-SKILL edits — expected on Windows
and informational only; no content is affected.)

---

## Step 6 confirmation — `tests/fixtures/README.md` created verbatim

I wrote `tests/fixtures/README.md` using the exact content from Step 6 of
the spec, starting from `# Test fixtures` and ending at
`2. Your language validator doesn't false-positive on clean text.`, with
the fenced code block containing the regenerate command and every table
row intact. The file is 2.0 KB, UTF-8, no BOM. It is currently untracked
(`??` in `git status`) and will be staged by Bob alongside the two
`.txt` fixtures.

---

## Step 7 — final working-tree state

```
$ git status --short
 M docs/configuration.md
 M docs/installation.md
 M migrations/001_initial.sql
 M skills/ariadne-core-build/SKILL.md
?? scripts/_generate_encoding_fixtures.py
?? scripts/_probe_embedder.py
?? scripts/_probe_text_encoding.py
?? scripts/_probe_vision.py
?? tests/fixtures/README.md
?? tests/fixtures/clean_english_sample.txt
?? tests/fixtures/mojibake_sample.txt
```

Exactly matches Step 7 expectations:
- 4 modified (unstaged): ✓
- 1 new untracked (`tests/fixtures/README.md`): ✓
- 2 pre-existing untracked fixtures (`clean_english_sample.txt`, `mojibake_sample.txt`): ✓
- 3 probes + generator untracked (unchanged): ✓

Nothing staged. Nothing else modified.

---

## pytest

Skipped — no source code touched (Step 8 marks pytest optional for this
pass). Hard gate from the prior task (`08bfde2`) was 177/177 green and
none of the present edits can regress tests.

---

## Hand-off to Bob

Seven paths to stage + commit + push:

1. `docs/configuration.md` (modified)
2. `docs/installation.md` (modified)
3. `migrations/001_initial.sql` (modified)
4. `skills/ariadne-core-build/SKILL.md` (modified)
5. `tests/fixtures/README.md` (new)
6. `tests/fixtures/clean_english_sample.txt` (new, from Phase 7.5)
7. `tests/fixtures/mojibake_sample.txt` (new, from Phase 7.5)

Deferred per the spec's Do-NOT list and handled in a later backlog:
`README.md` (Tier-2 / Backlog-5a), `docs/docint-architecture.md`
(Tier-2 / Backlog-5a), `scripts/setup.py` (explicit TODO, Backlog-5a),
walkthrough skills (Backlog-5.5), `docs/roadmap/*` (guardrailed).

— Dave
