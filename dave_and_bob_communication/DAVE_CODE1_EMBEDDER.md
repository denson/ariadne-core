# Embedder → native Gemini batchEmbedContents (phase 3 of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phases 1 (spec `db676b0`) and 2 (deploy skill `731fb49`) are on `main`. This phase rewrites the embedding client to the native Gemini endpoint that SPEC.md `### Provider constraints` documents. Vision and text_encoding come in later phases — **do not touch them here.**

One source file to edit: `src/pipeline/embedding/embedder.py`. Plus a local probe before you report done.

---

## Step 1: Read SPEC.md first

Open `SPEC.md` and read the `### Provider constraints` section, specifically `#### Embedding — batchEmbedContents contract`. That section is the source of truth. The request shape, response shape, endpoint path, and auth header below are quoted from it — if anything in this file disagrees with SPEC, SPEC wins and you should stop and flag.

Key facts from SPEC you will be coding to:

- **Endpoint:** `POST {base}/models/{model}:batchEmbedContents`
- **Header:** `x-goog-api-key: <key>` (no `Authorization: Bearer`, no both-headers, no `?key=` query param)
- **Request body:**
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
- **Response body:**
  ```json
  {"embeddings": [{"values": [0.01, -0.02, ...]}]}
  ```
- **Batch cap:** up to 100 `requests` entries per call.

The env var holds a **bare** model name (e.g. `gemini-embedding-001`). The code prepends `models/` both in the URL path and in the per-request `"model"` field.

---

## Step 2: Rewrite `embedder.py`

File path: `src/pipeline/embedding/embedder.py`.

Keep what already works unchanged — do not re-architect:

- Keep `EmbeddingConfig`, `EmbeddingResult`, `EmbeddingClient` class names and public API (`embed_texts`, `embed_query`, `enabled`, `model`, `dimensions`, `MAX_BATCH_SIZE = 100`).
- Keep the retry logic (3 retries on 429/503, exponential backoff with `retryDelay` parsing).
- Keep the `_embed_in_batches` path for >100 texts.
- Keep the `processing_chain_entry` structure. Change the `"tool"` value to `f"gemini:{self._config.model}"` (was `"openai:..."`) — matches the actual provider.
- Keep `logger` usage, timing, token counting.

Change these specifically:

### 2a. Endpoint construction (around lines 50-54)

Replace:

```python
def __init__(self, config: EmbeddingConfig | None = None) -> None:
    self._config = config
    self._endpoint = (
        f"{config.base_url.rstrip('/')}/embeddings" if config else ""
    )
```

With:

```python
def __init__(self, config: EmbeddingConfig | None = None) -> None:
    self._config = config
    if config:
        model_path = config.model
        if not model_path.startswith("models/"):
            model_path = f"models/{model_path}"
        self._endpoint = (
            f"{config.base_url.rstrip('/')}/{model_path}:batchEmbedContents"
        )
        self._model_path = model_path
    else:
        self._endpoint = ""
        self._model_path = ""
```

### 2b. Request body (around lines 102-109)

Replace the OpenAI-compat payload:

```python
payload: dict[str, Any] = {
    "model": self._config.model,
    "input": texts,
}
if self._config.dimensions:
    payload["dimensions"] = self._config.dimensions
```

With the native batch payload:

```python
# Native Gemini batch payload — one entry per text.
# See SPEC.md → "Provider constraints" → batchEmbedContents contract.
per_request: dict[str, Any] = {
    "model": self._model_path,
    "content": {"parts": [{"text": ""}]},
}
if self._config.dimensions:
    per_request["outputDimensionality"] = self._config.dimensions

payload: dict[str, Any] = {
    "requests": [
        {**per_request, "content": {"parts": [{"text": t}]}}
        for t in texts
    ]
}
```

### 2c. Request headers + comment block (around lines 115-135)

Replace the current `Request(...)` call — including the now-wrong comment block from commit `0141618` — with:

```python
req = Request(
    self._endpoint,
    data=body,
    # NOTE FOR FUTURE AGENTS — native Gemini endpoint, not OpenAI-compat.
    # Ariadne's embedder calls Gemini's native `:batchEmbedContents` with
    # the `x-goog-api-key` header. The OpenAI-compatible shim at
    # `/v1beta/openai/embeddings` is NOT supported here — Google's
    # `AQ.*`-format keys reject every auth variant on that path
    # ("Missing or invalid Authorization header" with `x-goog-api-key`
    # alone, "Multiple authentication credentials received" with
    # `Authorization: Bearer`).
    #
    # If you swap to a different OpenAI-compatible provider (OpenAI
    # proper, Together, Groq, etc.), this whole module needs a rewrite
    # — endpoint construction, payload shape, response parser, and
    # auth header all differ. Don't build a provider abstraction here;
    # let the configuring agent read the provider's docs and pick a
    # concrete path. See SPEC.md → "Provider constraints" for the
    # current native contract.
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": self._config.api_key,
    },
    method="POST",
)
```

### 2d. Response parsing (around lines 199-206)

Replace the OpenAI-compat response extraction:

```python
# Extract embeddings in order (some providers like Gemini omit "index")
data = result["data"]
if data and "index" in data[0]:
    data = sorted(data, key=lambda x: x["index"])
embeddings = [item["embedding"] for item in data]

total_tokens = result.get("usage", {}).get("total_tokens", 0)
```

With native response extraction:

```python
# Native response shape: {"embeddings": [{"values": [...]}, ...]}
# Order matches the `requests` array we sent.
items = result.get("embeddings", [])
embeddings = [item["values"] for item in items]

# Native batchEmbedContents does not report token usage in the
# response body. Leave total_tokens at 0; callers should not rely
# on it for billing.
total_tokens = 0
```

### 2e. chain_entry tool name (two sites: around lines 208-215 and 243-250)

Change both occurrences of:

```python
"tool": f"openai:{self._config.model}",
```

To:

```python
"tool": f"gemini:{self._config.model}",
```

### 2f. Module docstring (top of file, around lines 1-9)

The current docstring describes an "OpenAI-compatible" client. Replace with:

```python
"""Embedding API client — Gemini native batchEmbedContents.

Sends text chunks to Google's native Gemini embedding endpoint and
returns vectors. Uses the `x-goog-api-key` header (not OAuth).

See SPEC.md → "Provider constraints" for the request/response contract
and an explanation of why the OpenAI-compatible shim is not supported
for Ariadne's bundled embedder.

If no API key is configured, the embedder is disabled and chunks
are stored without embeddings (search will not work).
"""
```

---

## Step 3: Local probe before reporting done

Do **not** write a `DAVE_DONE.md` until the local probe below passes. The probe is the gate for Bob — if the live Gemini endpoint rejects the new payload, we need to know before code lands on `main`.

Create `scripts/_probe_embedder.py` (gitignored / untracked; Bob can delete or keep — do **not** stage it):

```python
"""One-shot probe — confirms the rewritten embedder round-trips against live Gemini.

Loads ARIADNE_EMBEDDING_* from the nearest .env walking up from cwd,
instantiates EmbeddingClient, embeds three strings, asserts shapes.

Usage: python scripts/_probe_embedder.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# --- .env walk-up loader (no external deps) ---
def load_env() -> dict[str, str]:
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        p = candidate / ".env"
        if p.is_file():
            out: dict[str, str] = {}
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                k, _, v = line.partition("=")
                k = k.strip()
                if "#" in v:
                    v = v.split("#", 1)[0]
                v = v.strip().strip('"').strip("'")
                if k:
                    out[k] = v
            return out
    return {}

env = load_env()
import os
for k, v in env.items():
    os.environ.setdefault(k, v)

# Add src/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig  # noqa: E402

cfg = EmbeddingConfig(
    model=os.environ["ARIADNE_EMBEDDING_MODEL"],
    dimensions=int(os.environ.get("ARIADNE_EMBEDDING_DIMENSIONS", "1536")),
    base_url=os.environ["ARIADNE_EMBEDDING_BASE_URL"],
    api_key=os.environ["ARIADNE_EMBEDDING_API_KEY"],
)
client = EmbeddingClient(cfg)
print(f"endpoint: {client._endpoint}")
result = client.embed_texts(["hello", "world", "third row here"])
print(f"count:    {len(result.embeddings)}")
print(f"dim[0]:   {len(result.embeddings[0])}")
print(f"first 5:  {result.embeddings[0][:5]}")
print(f"tool:     {result.processing_chain_entry['tool']}")
print(f"ms:       {result.processing_time_ms}")

assert len(result.embeddings) == 3, "expected 3 embeddings"
assert len(result.embeddings[0]) == cfg.dimensions, f"expected dim={cfg.dimensions}, got {len(result.embeddings[0])}"
assert result.processing_chain_entry["tool"].startswith("gemini:"), "tool label must be gemini:..."
print("PASS")
```

Run it:

```bash
cd ariadne-core
python scripts/_probe_embedder.py
```

**Hard gate:** must print `PASS` with endpoint ending `:batchEmbedContents`, three embeddings, dimension matching `ARIADNE_EMBEDDING_DIMENSIONS`, tool prefix `gemini:`. If you get any HTTP error back from Gemini, stop and include the full error body in `DAVE_DONE.md` — do not write a "PASS" report. Probe failure means the code is wrong (or the key / env values are, in which case flag it).

Also re-run the full existing variant probe for regression coverage:

```bash
cd ..  # back to workspace root
python test_auth_variants.py
```

Ignore the OpenAI-compat failures (they're expected and documented). Confirm the native probes still PASS.

---

## Step 4: Do not touch anything else

Do not edit:

- `vision.py` (phase 4).
- `text_encoding.py` (phase 5).
- `config.py`, `.env.example`, `cli.py`, `setup.py`, `ariadne.yaml`, any `docs/*.md`, `README.md` (phase 6).
- Tests or `FIXES.md` (phase 7).
- `SPEC.md`, any skill file, `CLAUDE.md`.
- The comment block in vision.py or text_encoding.py — those get their own replacement in their own phase.

If `config.py` breaks at import time because of the `base_url` default still saying `https://api.openai.com/v1`, flag it — **do not fix it here.** Phase 6 rewrites `config.py` and all defaults.

---

## Step 5: Verify

```bash
cd ariadne-core
python -c "from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig; print('import OK')"
grep -n "Authorization.*Bearer\|openai:" src/pipeline/embedding/embedder.py
grep -n "batchEmbedContents\|x-goog-api-key\|gemini:" src/pipeline/embedding/embedder.py
git status
```

Expect:

- Import prints `OK`.
- First grep: zero matches. No residual Bearer header in live code, no `openai:` tool labels.
- Second grep: endpoint string includes `:batchEmbedContents`, header is `x-goog-api-key`, both `tool` labels are `gemini:`.
- `git status`: only `src/pipeline/embedding/embedder.py` tracked-modified (plus `DAVE_DONE.md`; `scripts/_probe_embedder.py` is untracked and should stay untracked — do not `git add` it).

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- The four substantive diffs (endpoint construction, payload, headers+comment, response parser).
- Probe output — the actual `PASS` line plus the endpoint string, embedding count, dimension, tool label.
- `test_auth_variants.py` summary — which native variants still PASS.
- `git status` proof that nothing else was modified.
- Any anomaly (e.g. dimensions mismatch, unexpected error, config.py import issue) flagged for Bob.
