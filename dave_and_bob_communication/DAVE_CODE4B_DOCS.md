# Docs: native-Gemini defaults + "roll your own" multi-provider caveat (phase 6b of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phases 1-6a merged (SPEC `db676b0`, deploy skill `731fb49`, embedder `e0caf2e`, vision `c5e923e`, language-validator `43a286f`, config+env `0b9a39e`). This phase reconciles the user-facing docs with the Gemini-native runtime the code is now pinned to.

**Scope boundary — read this first.**

Two kinds of edit only:

1. **Tactical** — fix stale URL / model-name strings in config examples, Railway command blocks, YAML examples, env-override blocks, default-value tables, and JSON tool-label strings. Pure mechanical substitution.
2. **One honest caveat banner** — insert at the top of README's "Compatible providers" section (and mirror briefly in `docs/configuration.md` and `docs/installation.md`). Wording below. Frames multi-provider as "roll your own" — accurate to the current code — without ripping out the existing provider tables.

**Explicitly out of scope:**

- Rewriting the "Compatible providers" provider tables. Leave them.
- Rewriting narrative prose that says "any OpenAI-compatible provider works." Leave it — the banner above it provides the correction.
- `docs/roadmap/*.md`. Token-savings guardrail applies; handled in a separate phase 6c under Sam's supervision.
- Walkthrough skill references (backlog item 17).
- The unprefixed-env-var-names drift in `docs/installation.md` (`EMBEDDING_API_KEY` vs `ARIADNE_EMBEDDING_API_KEY`). Known backlog item from phase 2. Not in scope here.

Six files touched:

1. `README.md`
2. `docs/configuration.md`
3. `docs/installation.md`
4. `docs/docint-architecture.md`
5. `scripts/setup.py` (one line — Bob's phase-6a flag #4)
6. `client/src/ariadne_core_client/cli.py` (only if `DEFAULTS_TABLE` exists there; Bob's flag said L80 of cli.py but phase-6a found `DEFAULTS_TABLE` in `setup.py` L76, not cli.py. If cli.py has no such table, leave cli.py untouched and confirm in your report.)

---

## Step 1: The caveat banner (canonical wording)

Use this exact wording when the instruction below says "insert the caveat banner." Do not paraphrase.

```markdown
> **⚠️ v1 runtime is Gemini-native.** Ariadne Core's bundled
> embedding, vision, and language-validation clients call Google
> Gemini's native endpoints directly. The tables below list other
> provider URLs for reference — to use any of them you'll need to
> fork the repo and modify `src/pipeline/embedding/embedder.py`,
> `src/pipeline/enrichment/vision.py`, and
> `src/pipeline/extraction/text_encoding.py` to match that
> provider's request/response shapes. See `SPEC.md` →
> "Provider constraints" for the current native contract.
```

Shorter variant for `configuration.md` and `installation.md` (use this one where indicated):

```markdown
> **⚠️ v1 runtime is Gemini-native.** Only Google Gemini is wired
> up out of the box. To use a different provider, fork the repo
> and modify the clients in `src/pipeline/`. See `SPEC.md` →
> "Provider constraints."
```

---

## Step 2: `scripts/setup.py` — Bob's phase-6a flag #4

Line 80, inside `DEFAULTS_TABLE`. Replace:

```
    Vision:    gemini-3.1-flash-lite-preview
```

With:

```
    Vision:    gemini-2.0-flash
```

The OpenAI block below (lines 83-86) stays as-is — those are genuine OpenAI defaults for the reference table, not something we pretend our code supports.

---

## Step 3: `client/src/ariadne_core_client/cli.py`

Grep for `DEFAULTS_TABLE` in cli.py:

```bash
cd ariadne-core
grep -n DEFAULTS_TABLE client/src/ariadne_core_client/cli.py
```

If zero hits, cli.py has no such table — leave the file untouched and note in your report that Bob's flag was setup.py, not cli.py.

If there's a hit, apply the same L80-equivalent edit as Step 2.

---

## Step 4: `README.md`

### 4a. Railway command block (lines 169-173)

Replace:

```
railway variables set ARIADNE_EMBEDDING_API_KEY=your-provider-api-key
railway variables set ARIADNE_IMAGE_ENRICHMENT_API_KEY=your-provider-api-key
railway variables set ARIADNE_EMBEDDING_MODEL=text-embedding-3-small
railway variables set ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o-mini
railway variables set ARIADNE_API_KEY=your-secret-api-key
```

With:

```
railway variables set ARIADNE_EMBEDDING_API_KEY=your-gemini-api-key
railway variables set ARIADNE_IMAGE_ENRICHMENT_API_KEY=your-gemini-api-key
railway variables set ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
railway variables set ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
railway variables set ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set ARIADNE_API_KEY=your-secret-api-key
```

Two extra lines for the base URLs — readers deploying for the first time need those set, and the defaults in `config.py` apply only if the env var is absent.

### 4b. Insert the long caveat banner

Find the `## Compatible providers` heading (line 352) and insert the **long-form** banner from Step 1 **immediately after** that heading, before the existing paragraph "Ariadne Core works with any OpenAI-compatible API..." Keep the existing paragraph; the banner sits above it.

### 4c. Google Gemini row in the providers table (line 361)

Replace:

```
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-3-flash-preview`, `gemini-2.5-pro` |
```

With:

```
| **Google Gemini** (v1 default) | `https://generativelanguage.googleapis.com/v1beta` | `gemini-embedding-001`, `gemini-2.0-flash` |
```

### 4d. Cost table (lines 401-404)

Replace:

```
| What | Model | Cost |
|------|-------|------|
| Embedding | text-embedding-3-small | ~$0.02 per million tokens |
| Image description | gpt-4o-mini | ~$0.15 per million input tokens |
```

With:

```
| What | Model | Cost |
|------|-------|------|
| Embedding | gemini-embedding-001 | ~$0.15 per million tokens |
| Image description | gemini-2.0-flash | ~$0.10 per million input tokens |
```

(Numbers are approximate as of April 2026 Gemini pricing; they're labeled "approximate" in the prose around the table.)

### 4e. Leave alone

Do not touch:

- L98, L152, L176 prose about "any OpenAI-compatible provider" — the banner handles the correction.
- The full providers tables (L358-381). Leave them.
- L327 "OpenAI-compatible embedding client" in the ASCII tree — it's a one-liner, banner covers it.
- Anything in `skills/` (backlog item 17).

---

## Step 5: `docs/configuration.md`

### 5a. Insert the short caveat banner

Immediately after the `# Configuration` heading at the top of the file (before the first section). Use the **short** banner from Step 1.

### 5b. Defaults table (lines 36-39)

Replace these four rows:

```
| `ARIADNE_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model name |
| `ARIADNE_EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | Embedding API endpoint |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | `gpt-4o-mini` | Vision model name |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | `https://api.openai.com/v1` | Vision API endpoint |
```

With:

```
| `ARIADNE_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model name |
| `ARIADNE_EMBEDDING_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Embedding API endpoint |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | `gemini-2.0-flash` | Vision model name |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Vision API endpoint |
```

### 5c. Embedding YAML example (lines 77-83)

Replace:

```yaml
embedding:
  model: text-embedding-3-small
  dimensions: 1536
  provider: openai-compatible
  base_url: https://api.openai.com/v1
  api_key: ${EMBEDDING_API_KEY}
```

With:

```yaml
embedding:
  model: gemini-embedding-001
  dimensions: 1536
  provider: google-gemini
  base_url: https://generativelanguage.googleapis.com/v1beta
  api_key: ${EMBEDDING_API_KEY}
```

### 5d. Embedding defaults table (lines 88-92)

Replace the four rows so defaults are `gemini-embedding-001`, `google-gemini`, and `https://generativelanguage.googleapis.com/v1beta`. Keep descriptive text for each row but drop the "(OpenAI, Together AI, Fireworks, Ollama, etc.)" list — the banner covers multi-provider.

### 5e. Image-enrichment YAML example (lines 109-115)

Replace:

```yaml
image_enrichment:
  enabled: true
  provider: openai-compatible
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  api_key: ${VISION_API_KEY}
  prompt: "Describe this image in detail. ..."
```

With:

```yaml
image_enrichment:
  enabled: true
  provider: google-gemini
  base_url: https://generativelanguage.googleapis.com/v1beta
  model: gemini-2.0-flash
  api_key: ${VISION_API_KEY}
  prompt: "Describe this image in detail. ..."
```

(Preserve the full existing prompt text — don't truncate.)

### 5f. Image-enrichment defaults table (lines 120-124)

Replace the four rows so defaults are `google-gemini`, `https://generativelanguage.googleapis.com/v1beta`, `gemini-2.0-flash`. The row for `model` should mention `gemini-2.0-flash` as the default and drop the `gpt-4o` / `gpt-4o-mini` recommendation text.

### 5g. Embedding model-recommendation table (lines 96-101)

Leave alone. It's a reference table of open-source embedding models — OpenAI and BAAI/bge rows stay. These are "roll your own" candidates, covered by the banner at the top of the file.

---

## Step 6: `docs/installation.md`

### 6a. Insert the short caveat banner

Immediately after the first heading. Use the **short** banner from Step 1.

### 6b. Railway command block (lines 41-45)

Replace:

```
railway variables set EMBEDDING_API_KEY=your-provider-api-key
railway variables set VISION_API_KEY=your-provider-api-key
railway variables set EMBEDDING_MODEL=text-embedding-3-small
railway variables set VISION_MODEL=gpt-4o-mini
railway variables set ARIADNE_API_KEY=your-secret-api-key
```

With:

```
railway variables set EMBEDDING_API_KEY=your-gemini-api-key
railway variables set VISION_API_KEY=your-gemini-api-key
railway variables set EMBEDDING_MODEL=gemini-embedding-001
railway variables set VISION_MODEL=gemini-2.0-flash
railway variables set EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set VISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta
railway variables set ARIADNE_API_KEY=your-secret-api-key
```

Keep the unprefixed var names in this file. They're legacy-naming drift (known backlog item, not in this phase's scope).

### 6c. Curl example (lines 184-188)

Leave alone. It's a diagnostic for reaching OpenAI specifically ("if you're using OpenAI, run this to verify the key") and the surrounding prose frames it that way. The banner at the top of the file is enough.

---

## Step 7: `docs/docint-architecture.md`

### 7a. Env override block (lines 353-357)

Replace:

```
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5      # Model name
EMBEDDING_DIMENSIONS=1024                     # Must match chosen model
EMBEDDING_PROVIDER=openai-compatible          # Any OpenAI-compatible endpoint
EMBEDDING_BASE_URL=https://api.openai.com/v1  # Endpoint
EMBEDDING_API_KEY=${EMBEDDING_API_KEY}
```

With:

```
EMBEDDING_MODEL=gemini-embedding-001           # Model name
EMBEDDING_DIMENSIONS=1536                      # Must match chosen model
EMBEDDING_PROVIDER=google-gemini               # v1 runtime is Gemini-native
EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
EMBEDDING_API_KEY=${EMBEDDING_API_KEY}
```

### 7b. YAML config example (lines 565-581)

Same substitutions as configuration.md Steps 5c and 5e. Model → `gemini-embedding-001` / `gemini-2.0-flash`, provider → `google-gemini`, base_url → `https://generativelanguage.googleapis.com/v1beta`. Keep the prompt text verbatim.

### 7c. Optional-overrides hint block (lines 637-642)

Replace:

```
# EMBEDDING_MODEL=text-embedding-3-small
# VISION_MODEL=gpt-4o-mini
# ARIADNE_EMBEDDING_MODEL=bge-m3
```

With:

```
# EMBEDDING_MODEL=gemini-embedding-001
# VISION_MODEL=gemini-2.0-flash
```

Drop the `bge-m3` line — out of scope, and the banner (added below) explains the one-provider-only stance.

### 7d. Tool-label strings in JSON chain_entry examples (lines 238, 245, 850-851)

Find every JSON snippet whose value is `"openai:<model>"` (there should be three or four) and change the prefix to `gemini:` so the examples match what phases 3-5 actually write to the chain:

- `"tool": "openai:gpt-4o-mini"` → `"tool": "gemini:gemini-2.0-flash"`
- `"tool": "openai:bge-large-en-v1.5"` → `"tool": "gemini:gemini-embedding-001"`

Both instances each (lines 238 and 850 for image_enrichment; lines 245 and 851 for embedding).

### 7e. Insert the short caveat banner

Near the top of the file, under the main heading. Use the **short** banner from Step 1.

### 7f. Leave alone

- L24, L41, L63, L65, L539-541, L983 — all say "any OpenAI-compatible endpoint" or similar. Banner handles the correction.
- Vision cost-options table lines 282-286. Those are reference rates like README's cost table — leaving the gpt-4o rows as "roll your own" candidates is consistent with this phase's framing.

---

## Step 8: Verify

```bash
cd ariadne-core
grep -n "text-embedding-3-small\|gpt-4o-mini\|gemini-3.1-flash-lite-preview" \
  README.md docs/configuration.md docs/installation.md docs/docint-architecture.md scripts/setup.py
grep -n "v1 runtime is Gemini-native" \
  README.md docs/configuration.md docs/installation.md docs/docint-architecture.md
grep -n "openai:gpt-4o-mini\|openai:bge-large-en-v1.5" docs/docint-architecture.md
git status
```

Expect:

- **First grep** (stale model defaults): hits only in the allowed reference positions I called out as "leave alone" — the OpenAI block of `setup.py` `DEFAULTS_TABLE` (lines 84-85), the OpenAI row of README's providers table (line 360), the Anthropic/aggregator examples, the vision-options table in docint-architecture.md, the curl example in installation.md. Zero hits in the edited Railway blocks, YAML examples, env-override blocks, or default-value tables.
- **Second grep** (caveat banner placement): exactly four hits, one per doc file.
- **Third grep** (JSON tool labels): zero hits.
- `git status`: exactly five or six tracked-modified files (depending on whether cli.py had `DEFAULTS_TABLE` — if not, five). Plus `DAVE_DONE.md`. Nothing else.

No live-API probe this phase. No import test. This is pure-docs.

---

## Step 9: Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- A per-file summary of every edit (short, enumerated).
- The output of the three greps from Step 8.
- The `cli.py DEFAULTS_TABLE` grep result (hit or no hit) and what you did accordingly.
- Any prose you were tempted to rewrite but left alone per Step 4e / 5g / 6c / 7f (one-line notes — shows Bob you considered them).
- Any anomaly you hit while editing (markdown table alignment breaking, unexpected whitespace, etc.).
