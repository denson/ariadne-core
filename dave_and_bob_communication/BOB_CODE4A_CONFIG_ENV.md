# Review + commit: config + env-template native-Gemini defaults (phase 6a of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_CODE4A_CONFIG_ENV.md`, `NATIVE_GEMINI_OVERVIEW.md`. Phases 1-5 merged (`db676b0`, `731fb49`, `e0caf2e`, `c5e923e`, `43a286f`).

Dave updated the runtime default values in five files so a fresh `ariadne-core init` or a no-override deploy loads Gemini-native URLs. No code paths changed — only default strings. Dave flagged five items; three of them are one-line cleanups in files already in scope, so fold them into this commit. Details below.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

**Expected tracked-modified files in the commit** (five from Dave + three in-scope cleanups you will apply — some overlap in the same files, so still five files total):

1. `src/pipeline/config.py`
2. `.env.example`
3. `client/src/ariadne_core_client/cli.py`
4. `scripts/setup.py`
5. `config/ariadne.yaml`

Plus `DAVE_DONE.md` (not in the commit). Anything else tracked-modified is out of scope; stop and flag.

---

## Step 2: Apply the three in-scope cleanups

These come from Dave's flagged items #2, #4, #5 — all one-line fixes in files already being modified. Fold into this commit, don't defer.

### 2a. `scripts/setup.py` — Dave's flag #2

The `PROVIDERS["google"]` entry still has `default_vision` pointing at `gemini-3.1-flash-lite-preview`. Change it to `gemini-2.0-flash` so it matches `.env.example` and `config.py` defaults.

Locate the line (around line 37-39 inside the `"google"` entry) that reads something like:

```python
"default_vision": "gemini-3.1-flash-lite-preview",
```

Change to:

```python
"default_vision": "gemini-2.0-flash",
```

Do **not** touch the `"openai"` or `"together"` entries.

### 2b. `src/pipeline/config.py` — Dave's flags #4 and #5

The module docstring at the top of `config.py` still references `text-embedding-3-small` and/or OpenAI. Read the top ~20 lines of `config.py` and update any stale references so the docstring describes the current state (Gemini-native defaults, OpenAI-compat no longer supported). Keep the edit small — a sentence or two at most. If the docstring is already generic ("runtime configuration dataclasses") and doesn't name specific models, leave it alone and note in your report.

Do **not** rewrite the docstring into new marketing copy. Minimum change to remove stale references.

---

## Step 3: Read the diff

```bash
git diff src/pipeline/config.py .env.example client/src/ariadne_core_client/cli.py scripts/setup.py config/ariadne.yaml
```

Verify Dave's five edits plus your two cleanups:

1. **`config.py`** — `EmbeddingConfig` and `ImageEnrichmentConfig` defaults:
   - `model` → `gemini-embedding-001` / `gemini-2.0-flash`
   - `provider` → `google-gemini` (both)
   - `base_url` → `https://generativelanguage.googleapis.com/v1beta` (both)
   - Module docstring no longer references `text-embedding-3-small` or OpenAI-compat (your 2b cleanup).
2. **`.env.example`** — `/openai/` stripped from both base URLs, vision model is `gemini-2.0-flash`.
3. **`cli.py` `_ENV_TEMPLATE`** — same three changes as `.env.example`. **There is no `PROVIDERS` dict in this file** — Dave correctly flagged that my Step 4b premise was stale. No TODO comment added here. That's correct; don't add one.
4. **`scripts/setup.py`** — `PROVIDERS["google"]["base_url"]` strips `/openai/`; `default_vision` is now `gemini-2.0-flash` (your 2a cleanup); TODO comment sits above the `"openai"` entry. `"openai"` and `"together"` entries themselves unchanged.
5. **`config/ariadne.yaml`** — both `embedding:` and `image_enrichment:` sections: `provider: google-gemini`, `base_url` default is native, models are `gemini-embedding-001` / `gemini-2.0-flash`.

No other dataclasses in `config.py` should be touched. No loader/parser logic changed.

---

## Step 4: Grep sanity

```bash
cd ariadne-core
grep -n "openai\.com\|/v1beta/openai" src/pipeline/config.py .env.example client/src/ariadne_core_client/cli.py scripts/setup.py config/ariadne.yaml
grep -n "text-embedding-3-small\|gpt-4o-mini\|gemini-3.1-flash-lite-preview" src/pipeline/config.py .env.example client/src/ariadne_core_client/cli.py scripts/setup.py config/ariadne.yaml
grep -n "generativelanguage\.googleapis\.com/v1beta" src/pipeline/config.py .env.example client/src/ariadne_core_client/cli.py scripts/setup.py config/ariadne.yaml
```

- **First grep** (stale `/openai/` shim paths): hits only allowed inside the `"openai"` PROVIDERS entry of `scripts/setup.py` (that's `api.openai.com/v1` — genuine OpenAI, not the Gemini shim) and inside `query_openai_models` / `url.lower() in ...openai.com...` string-matching helpers. Zero hits in `config.py`, `.env.example`, `cli.py`, `config/ariadne.yaml`, and zero hits inside the `"google"` PROVIDERS entry of `setup.py`.
- **Second grep** (stale model defaults): zero hits across all five files. If `text-embedding-3-small` appears in a `config.py` module docstring, your 2b cleanup did not remove it — go back.
- **Third grep** (new native URL): hits in `config.py` (×2), `.env.example` (×2), `cli.py` `_ENV_TEMPLATE` (×2), `config/ariadne.yaml` (×2), and `setup.py` `"google"` entry (×1+). Roughly 9+ hits total.

---

## Step 5: Import + construct clients

```bash
cd ariadne-core
python -c "
from pipeline.config import EmbeddingConfig, ImageEnrichmentConfig
from pipeline.embedding.embedder import EmbeddingClient
from pipeline.enrichment.vision import VisionClient
e = EmbeddingConfig(api_key='dummy')
v = ImageEnrichmentConfig(api_key='dummy')
ec = EmbeddingClient(e)
vc = VisionClient(v)
print('emb endpoint:', ec._endpoint)
print('vis endpoint:', vc._endpoint)
assert ec._endpoint.endswith(':batchEmbedContents'), ec._endpoint
assert vc._endpoint.endswith(':generateContent'), vc._endpoint
assert 'generativelanguage.googleapis.com' in ec._endpoint
assert 'generativelanguage.googleapis.com' in vc._endpoint
assert '/openai/' not in ec._endpoint
assert '/openai/' not in vc._endpoint
print('defaults compose to native endpoints OK')
"
```

**Hard gate:** must print both endpoints and `defaults compose to native endpoints OK`. If either assertion fails, do not commit. This is the integration check that ties phase 6a back to the code that phases 3-5 rewrote.

No live-API probe this phase — defaults are static data.

---

## Step 6: Commit + push

Suggested subject: `Update config + env templates to Gemini-native defaults`

Body: switches EmbeddingConfig, ImageEnrichmentConfig, `.env.example`, the built-in `_ENV_TEMPLATE` in the CLI, `scripts/setup.py`'s Google provider entry, and `config/ariadne.yaml` to the native Gemini base URL (`https://generativelanguage.googleapis.com/v1beta`) and default models (`gemini-embedding-001` / `gemini-2.0-flash`). `"openai"` and `"together"` PROVIDERS entries in `scripts/setup.py` retain their OpenAI-compat URLs for a future multi-provider decision — marked with a TODO. References SPEC.md `### Provider constraints`. Phase 6a of the native-Gemini migration.

Push to default branch.

---

## Step 7: Backlog items

Copy verbatim into `BOB_DONE.md`:

1. **`config/ariadne.yaml` env-var naming drift** — section uses legacy `EMBEDDING_*` / `VISION_*` names while the rest of the codebase uses `ARIADNE_EMBEDDING_*` / `ARIADNE_IMAGE_ENRICHMENT_*`. Pre-existing, not introduced this phase. Backlog for a config-cleanup pass.
2. **Multi-provider support is broken after the native-Gemini migration.** `scripts/setup.py` still offers OpenAI and Together as provider choices in its interactive menu, but the runtime now speaks Gemini-native payloads regardless of which base URL is selected — picking OpenAI or Together would configure a base URL the rewritten embedder/vision/text-encoding modules can't drive. TODO comment in place. Not a blocker for single-provider Gemini deploys; needs a product call on whether to restore multi-provider (via provider abstraction) or drop those options entirely.
3. **Phase 6b (docs) pending.** README, `docs/configuration.md`, `docs/installation.md`, `docs/docint-architecture.md`, `docs/roadmap/pro-pricing.md`, `docs/roadmap/token_pricing_snapshot.md` still reference OpenAI-compat URLs and model names. Separate Dave instruction forthcoming.

Do **not** fix any of these in this commit.

---

## Step 8: Report

Write completion to `BOB_DONE.md`: commit SHA, push target, one-line confirmation that exactly five files were in the commit, which of Dave's flagged items you folded in (your 2a and 2b cleanups), the three backlog items verbatim, the endpoint-assertion output from Step 5 as independent verification.

No Railway action required — env vars already correct.
