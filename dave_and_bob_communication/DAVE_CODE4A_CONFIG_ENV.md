# Config + env-template defaults → native Gemini (phase 6a of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phases 1-5 merged (SPEC `db676b0`, deploy skill `731fb49`, embedder `e0caf2e`, vision `c5e923e`, language-validator `43a286f`). This phase updates the **runtime config defaults and env templates** that feed the modules you already rewrote, so a fresh `ariadne-core init` or a no-override deploy loads Gemini-native URLs out of the box. Phase 6b (docs) is separate.

Five files to edit, surgical changes only. No new code paths, no behavior changes beyond default values.

---

## Step 1: Read SPEC.md first

Open `SPEC.md` and re-read `### Provider constraints`. The canonical `base_url` the runtime now expects is:

```
https://generativelanguage.googleapis.com/v1beta
```

No `/openai/` suffix. No trailing slash (the modules all call `.rstrip('/')` anyway, but keep defaults clean).

The canonical default models for v1 are:

- Embedding: `gemini-embedding-001`
- Vision / language-validation: `gemini-2.0-flash`

Railway env vars are already set to the correct native URLs — Denson confirmed before phase 3. The workspace `.env` is Denson's concern; don't touch it.

---

## Step 2: `src/pipeline/config.py`

Lines ~49-63, two dataclasses. Change defaults only — field names, types, and order preserved.

### `EmbeddingConfig`

Replace:

```python
@dataclass
class EmbeddingConfig:
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
```

With:

```python
@dataclass
class EmbeddingConfig:
    model: str = "gemini-embedding-001"
    dimensions: int = 1536
    provider: str = "google-gemini"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    api_key: str = ""
```

### `ImageEnrichmentConfig`

Replace:

```python
@dataclass
class ImageEnrichmentConfig:
    enabled: bool = True
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    prompt: str = (
        "Describe this image in detail. Include any text, data, charts, "
        "diagrams, or visual elements. Be specific about numbers, labels, "
        "and relationships shown."
    )
```

With:

```python
@dataclass
class ImageEnrichmentConfig:
    enabled: bool = True
    provider: str = "google-gemini"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    model: str = "gemini-2.0-flash"
    api_key: str = ""
    prompt: str = (
        "Describe this image in detail. Include any text, data, charts, "
        "diagrams, or visual elements. Be specific about numbers, labels, "
        "and relationships shown."
    )
```

Do not change other dataclasses. Do not touch any loader / parser / validation logic below the dataclass definitions.

---

## Step 3: `.env.example`

File is currently 23 lines. Two base-URL lines and one model line need updating.

Change line 8:
```
ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```
to:
```
ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Change line 13:
```
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-3.1-flash-lite-preview
```
to:
```
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
```

Change line 14:
```
ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```
to:
```
ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Nothing else.

---

## Step 4: `client/src/ariadne_core_client/cli.py`

Two spots.

### 4a. `_ENV_TEMPLATE` (line 40 onward)

This is the built-in fallback template written by `ariadne-core init` if `.env.example` is missing. It must match `.env.example` exactly. Apply the same three edits from Step 3 inside the triple-quoted string:

- Line ~48: strip `/openai/` from embedding base URL.
- Line ~53: change vision model from `gemini-3.1-flash-lite-preview` to `gemini-2.0-flash`.
- Line ~54: strip `/openai/` from vision base URL.

### 4b. Google PROVIDERS entry (line ~30-39)

The `PROVIDERS` dict has a `"google"` entry whose `base_url` currently ends in `/openai/`. Find it (around line 34) and strip the `/openai/` suffix so it ends in `/v1beta` (no trailing slash).

**Leave the `"openai"` and `"together"` entries alone** in this phase. After the native-Gemini migration those provider paths are non-functional against Ariadne's rewritten HTTP calls (the modules now speak Gemini-native payloads regardless of which base URL is configured). Do not delete them, do not rewrite them, do not add any runtime guard — this is a UX / product question for a later phase. Add a one-line comment above the `"openai"` entry:

```python
    # TODO(native-gemini migration): openai/together entries assume the
    # OpenAI-compat shim; after phase 3-5 the runtime speaks Gemini
    # native only. Re-evaluate multi-provider support in a later phase.
```

Nothing else in `cli.py` changes this phase.

---

## Step 5: `scripts/setup.py`

This is the interactive setup script. It has its own copy of the PROVIDERS dict (around line 33).

Same surgical edit as Step 4b: find the `"google"` entry (around line 34) and strip the `/openai/` suffix from its `base_url` so it ends in `/v1beta`.

Leave `"openai"` and `"together"` entries alone and add the same one-line TODO comment above the `"openai"` entry.

Do not rewrite any other part of `setup.py`. The helper functions (`query_google_models`, `query_openai_models`, etc.) still work — they hit providers' model-listing endpoints, not the generation endpoints we migrated.

---

## Step 6: `config/ariadne.yaml`

Four lines change. Section boundaries (lines 12-26):

Current:
```yaml
embedding:
  model: ${EMBEDDING_MODEL:-text-embedding-3-small}
  dimensions: 1536
  provider: openai-compatible
  base_url: ${EMBEDDING_BASE_URL:-https://api.openai.com/v1}
  api_key: ${EMBEDDING_API_KEY}

image_enrichment:
  enabled: true
  provider: openai-compatible
  base_url: ${VISION_BASE_URL:-https://api.openai.com/v1}
  model: ${VISION_MODEL:-gpt-4o-mini}
  api_key: ${VISION_API_KEY}
```

Target:
```yaml
embedding:
  model: ${EMBEDDING_MODEL:-gemini-embedding-001}
  dimensions: 1536
  provider: google-gemini
  base_url: ${EMBEDDING_BASE_URL:-https://generativelanguage.googleapis.com/v1beta}
  api_key: ${EMBEDDING_API_KEY}

image_enrichment:
  enabled: true
  provider: google-gemini
  base_url: ${VISION_BASE_URL:-https://generativelanguage.googleapis.com/v1beta}
  model: ${VISION_MODEL:-gemini-2.0-flash}
  api_key: ${VISION_API_KEY}
```

**Flag for Bob but do not fix:** this file uses `EMBEDDING_*` / `VISION_*` env var names while `.env.example`, `cli.py`, and the rest of the codebase use `ARIADNE_EMBEDDING_*` / `ARIADNE_IMAGE_ENRICHMENT_*`. That is a pre-existing naming drift, not something this phase introduced. Do not fix here.

---

## Step 7: Do not touch anything else

Do not edit:

- `SPEC.md`, any skill file, `CLAUDE.md`.
- `embedder.py`, `vision.py`, `text_encoding.py` (phases 3-5 already landed).
- Any `tests/*` file (phase 7).
- `FIXES.md` (phase 7).
- Docs: `README.md`, `docs/configuration.md`, `docs/installation.md`, `docs/docint-architecture.md`, `docs/roadmap/*.md`. (Phase 6b — separate instruction.)
- Walkthrough skills (backlog item 17).
- The workspace-local `.env` at `ariadne-core-workspace/ariadne-core/.env` — that's Denson's personal file, not repo-tracked.

---

## Step 8: Verify

```bash
cd ariadne-core
python -c "from pipeline.config import EmbeddingConfig, ImageEnrichmentConfig; e = EmbeddingConfig(); v = ImageEnrichmentConfig(); print(e.base_url, e.model); print(v.base_url, v.model); assert '/openai' not in e.base_url; assert '/openai' not in v.base_url; print('config defaults OK')"
grep -n "openai\.com\|/v1beta/openai" src/pipeline/config.py .env.example client/src/ariadne_core_client/cli.py scripts/setup.py config/ariadne.yaml
git status
```

Expect:

- First command prints the two Gemini-native URLs + default models + `config defaults OK`.
- Grep:
  - **`src/pipeline/config.py`, `.env.example`, `config/ariadne.yaml`**: zero hits.
  - **`client/src/ariadne_core_client/cli.py`**: hits only inside the `"openai"` PROVIDERS entry (genuine OpenAI URLs that remain as placeholders per Step 4b) and any OpenAI-related helper function (`query_openai_models`, the URL-to-provider string helpers). The `"google"` entry and `_ENV_TEMPLATE` must have zero `/openai/` hits.
  - **`scripts/setup.py`**: same shape as `cli.py` — OK inside `"openai"` entry and `query_openai_models`, zero hits inside `"google"` entry.
- `git status`: exactly five tracked-modified files (plus `DAVE_DONE.md`):
  1. `src/pipeline/config.py`
  2. `.env.example`
  3. `client/src/ariadne_core_client/cli.py`
  4. `scripts/setup.py`
  5. `config/ariadne.yaml`

If any other tracked file is modified, stop and flag.

---

## Step 9: No runtime probe this phase

There's no live-API probe for this phase — defaults are static data, not code paths. The import-and-assert line in Step 8 is sufficient. If you want extra confidence, construct an `EmbeddingClient` with the default `EmbeddingConfig` and confirm `client._endpoint` ends in `:batchEmbedContents` and contains `generativelanguage.googleapis.com`. Optional — not a gate.

---

## Step 10: Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- The five diffs (one per file), short and mechanical.
- The output of the import-and-assert line.
- The output of the grep line.
- `git status` proof.
- The `ariadne.yaml` env-var-naming-drift flag from Step 6 for Bob's backlog.
- Any other anomaly you noticed.
