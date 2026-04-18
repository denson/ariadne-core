# DAVE — Backlog-5: Tier-1 doc scrub + track smoke fixtures

Mechanical line-level edits to clean up stale OpenAI-shim-era example
values in active docs. Plus: track the two Phase 7.5 test fixtures so
they're reproducible across machines, with a short LLM-facing README
explaining how a future pipeline-builder should use them.

**Out of scope** (tracked as separate backlog items, DO NOT touch):
- `README.md` "Compatible providers" section — paragraph rewrite pending
  provider-framing decision
- `docs/docint-architecture.md` — 10 "any OpenAI-compatible endpoint"
  mentions, same decision blocks it
- `scripts/setup.py` — the `PROVIDERS` dict and `DEFAULTS_TABLE` already
  carry an explicit `TODO(native-gemini migration)` comment at line 40–42;
  leave the TODO in place
- `skills/ariadne-core-walkthrough/*` and `.claude/skills/walkthrough/*` —
  pending onboarding redesign
- `docs/roadmap/*` — guardrailed
- Historical `tests/COMPLY_*`, `FIX_*`, `HTTP_proxy_fix.md`, eval snapshots

**Process:** you write the edits and stop. Do NOT stage, commit, or push.
Leave everything unstaged for Bob. Hand off via `DAVE_DONE.md`.

---

## Step 0 — pre-flight

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**
- `HEAD` and `origin/main` both at `08bfde2` (Anomaly-1 commit)
- Modified/staged: nothing
- Untracked: 4 `scripts/_probe*.py` + `scripts/_generate_encoding_fixtures.py`
  + `tests/fixtures/clean_english_sample.txt` +
  `tests/fixtures/mojibake_sample.txt` + any `DAVE_*` / `BOB_*` diagnostic
  `.md` files

If anything else is modified or staged, **stop and report**.

---

## Step 1 — `docs/configuration.md`

**Edit 1.1** — replace the example-models table at lines 101–106. Current:

```
| Model | Dimensions | Provider | Cost | Notes |
|-------|-----------|----------|------|-------|
| `text-embedding-3-small` | 1536 | OpenAI | $0.02/M tokens | Best value for most use cases |
| `text-embedding-3-large` | 3072 | OpenAI | $0.13/M tokens | Slightly better quality |
| `BAAI/bge-large-en-v1.5` | 1024 | Together AI, Fireworks | Varies | Strong open-source retrieval model |
| `BAAI/bge-m3` | 1024 | Together AI, Fireworks | Varies | Multilingual (if your docs aren't all English) |
```

Replace with (only the first two rows change; third and fourth stay):

```
| Model | Dimensions | Provider | Notes |
|-------|-----------|----------|-------|
| `gemini-embedding-001` | 1536 | Google Gemini (native) | Current default. Cap at 1536 for pgvector HNSW compatibility. |
| `gemini-embedding-001` | 3072 | Google Gemini (native) | Full dimensionality. Requires a vector store that supports >2000 dims (not pgvector HNSW). |
| `BAAI/bge-large-en-v1.5` | 1024 | Together AI, Fireworks | Requires forking per SPEC.md → "Provider constraints". |
| `BAAI/bge-m3` | 1024 | Together AI, Fireworks | Requires forking per SPEC.md → "Provider constraints". |
```

Dropped the "Cost" column deliberately — pricing drifts and we don't want
to keep it up to date in two places. Match the new header with the new
body. If the surrounding prose references a "Cost" column, stop and
report rather than guessing.

**Edit 1.2** — line 233, env override example:

Change:
```
ARIADNE_EMBEDDING_MODEL=text-embedding-3-large
```
to:
```
ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
```

**Edit 1.3** — line 239, vision env override example:

Change:
```
ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o
```
to:
```
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
```

(Matches the default at line 119 and `.env.example:13`. Do NOT use
`gemini-2.5-flash` or similar — those are separate migrations.)

---

## Step 2 — `docs/installation.md` lines 188–196

Current block:

```
**Embedding or vision errors**
Your API key is missing, invalid, or the base URL doesn't match your provider. Verify your key works by testing directly against your provider's endpoint. For example, with OpenAI:
```bash
curl https://api.openai.com/v1/embeddings \
  -H "Authorization: Bearer your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-3-small", "input": "test"}'
```
If using a different provider, substitute their base URL and model name. See [Compatible providers](../README.md#compatible-providers).
```

Replace with:

```
**Embedding or vision errors**
Your API key is missing, invalid, or the base URL doesn't match. Verify your key works by hitting the native Gemini endpoint directly:
```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents" \
  -H "x-goog-api-key: your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"requests":[{"model":"models/gemini-embedding-001","content":{"parts":[{"text":"test"}]}}]}'
```
A 200 response with an `embeddings` array confirms the key and endpoint work. Google's `AQ.*`-format keys (April 2026+) only accept the `x-goog-api-key` header on the native path — the OpenAI-compat shim at `/v1beta/openai/*` is not supported.
```

Drop the "See [Compatible providers]" link — that section is being
rewritten in a later backlog.

---

## Step 3 — `migrations/001_initial.sql` line 93

Change:
```
-- (text-embedding-3-small). If you run this migration manually, replace
```
to:
```
-- (gemini-embedding-001). If you run this migration manually, replace
```

One word. Nothing else in the file.

---

## Step 4 — `skills/ariadne-core-build/SKILL.md`

**Edit 4.1** — line 80, file-tree comment:

Change:
```
│       │   └── vision.py       # Vision API client (any OpenAI-compat endpoint)
```
to:
```
│       │   └── vision.py       # Vision API client (native Gemini generateContent)
```

**Edit 4.2** — lines 221–223, guard-rail bullet:

Change:
```
- **API-first for embedding and vision.** Default path uses API calls to any
  OpenAI-compatible endpoint. Local model support exists only as a config option —
  never the default.
```
to:
```
- **API-first for embedding and vision.** Default path uses API calls to
  Google Gemini's native endpoints (`batchEmbedContents`, `generateContent`).
  Other providers require forking per SPEC.md → "Provider constraints".
  Local model support exists only as a config option — never the default.
```

---

## Step 5 — Track the Phase 7.5 test fixtures

These two files are currently untracked:

- `tests/fixtures/clean_english_sample.txt`
- `tests/fixtures/mojibake_sample.txt`

Do NOT `git add` them — leave them in the working tree for Bob to stage.
Bob's Step handles staging (same pattern as for the edits above).

---

## Step 6 — Create `tests/fixtures/README.md` (new file)

Write exactly this content:

```markdown
# Test fixtures

Byte-level fixtures for the extraction + encoding-validator pipeline.

## Files

| File | What it is |
|------|-----------|
| `clean_english_sample.txt` | UTF-8 English text. Known-good input. |
| `mojibake_sample.txt` | The same text deliberately corrupted: UTF-8 bytes decoded as cp1252 (produces sequences like `â€™s CEO`, `â€œ...â€`). Known-garbled input. |

## Expected pipeline behavior

A correct ariadne-core pipeline produces these `encoding_detection`
chain entries:

| Fixture | `encoding_confidence` | `llm_coherent` | `coherent` (final) | Suggested tags |
|---------|----------------------|----------------|--------------------|----------------|
| clean   | > 0.5                | true           | true               | `language:en` only |
| mojibake | ≈ 0.0               | true (LLM reads through mojibake) | **false** (byte gate overrides) | `language:en`, `encoding:suspect`, `status:needs-review` |

If both fixtures produce `coherent=true`, the byte-confidence gate at
`src/pipeline/extraction/markitdown.py` is bypassed or broken. If the
mojibake fixture produces `coherent=true` and no `encoding:suspect`
tag, the validator is trusting the LLM's raw vote — that's the exact
bug Phase 7.5 was built to catch (see commit `5d239cd` + `08bfde2`).

## Why these are tracked as bytes, not regenerated

Mojibake is hard to reproduce byte-for-byte across machines — terminal
encoding, editor autocorrect, and Python's default encoding can all
silently normalize the bytes back to valid UTF-8. Tracking the exact
bytes makes the live-smoke tests deterministic across environments.

## Regenerating (only if you really need to)

```bash
python scripts/_generate_encoding_fixtures.py
```

Note: the generator's final preview `print()` crashes on Windows
`cp1252` consoles. The files are written correctly before the crash.

## Use in testing

**Unit tests** (`tests/test_extraction.py`) stub `detect_and_decode` and
`validate_language` via `monkeypatch` — they don't read these files.
Keep that way for hermeticity.

**Live smoke** (`dave_and_bob_communication/DAVE_PHASE_7_5_SMOKE_TEST.md`)
ingests these fixtures against a real deployment to verify:

- The embedder actually reaches the configured provider (not a mock)
- The language validator's byte-confidence gate fires on real mojibake
- The suggested-tag block picks up the gate signal

## Building your own pipeline on top of ariadne-core

If you fork ariadne-core to run a different extraction or validation
path, drop these fixtures into your own test suite. They're a cheap
way to prove two things:

1. Your encoding-detection path actually runs — if both fixtures return
   `coherent=true`, your gate is probably bypassed.
2. Your language validator doesn't false-positive on clean text.
```

---

## Step 7 — hand off

Run a final `git status --short`. Expected modified (unstaged):
- ` M docs/configuration.md`
- ` M docs/installation.md`
- ` M migrations/001_initial.sql`
- ` M skills/ariadne-core-build/SKILL.md`

Expected new untracked files (still untracked, for Bob to stage):
- `tests/fixtures/README.md` (new, just written by you)

Expected newly-becoming-trackable untracked files (still untracked, for
Bob to stage — they were untracked before your work):
- `tests/fixtures/clean_english_sample.txt`
- `tests/fixtures/mojibake_sample.txt`

Plus the ongoing untracked diagnostic/helper set (unchanged):
- 4 `scripts/_probe*.py`
- `scripts/_generate_encoding_fixtures.py`

If anything else is modified, **stop and report**. If you inadvertently
staged anything, unstage (`git restore --staged <path>`) and report.

---

## Step 8 — overwrite `dave_and_bob_communication/DAVE_DONE.md`

Short report for Bob, containing:

- List of files edited (paths only)
- Full `git diff` of the edits (should be small — the tables and curl
  block are the biggest changes)
- Confirm you created `tests/fixtures/README.md` with the exact content
  from Step 6
- Confirm the two fixture `.txt` files are untracked and unchanged
- pytest is NOT required for this pass (no source code touched), but you
  MAY run it as a sanity check — report the result if you do. Expected
  177/177 green, same as `08bfde2`.

Bob will review, stage all seven paths (4 edited + 3 new/newly-tracked),
commit, push.

---

## Do NOT

- Touch `README.md` — Tier-2, deferred to Backlog-5a
- Touch `docs/docint-architecture.md` — Tier-2, deferred to Backlog-5a
- Touch `scripts/setup.py` — has explicit TODO; leave in place
- Touch `skills/ariadne-core-walkthrough/*` or `.claude/skills/walkthrough/*`
  — pending onboarding redesign (Backlog-5.5)
- Touch `docs/roadmap/*` — guardrailed
- Remove the `TODO(native-gemini migration)` at `scripts/setup.py:40–42`
  — it's the load-bearing flag for Backlog-5a
- Fabricate pricing numbers — if you reach for a "$0.xx/M tokens" figure
  for the Gemini rows and it isn't already in the repo or verifiable on
  `ai.google.dev/gemini-api/docs/pricing`, leave the cell out (the
  updated table spec above already drops the Cost column to sidestep
  this)
- Stage, commit, or push — Bob owns those steps
