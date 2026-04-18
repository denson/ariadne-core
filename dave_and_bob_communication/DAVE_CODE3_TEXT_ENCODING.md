# Text-encoding language validation → native Gemini generateContent (phase 5 of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phases 1-4 merged (SPEC `db676b0`, deploy skill `731fb49`, embedder `e0caf2e`, vision `c5e923e`). This phase rewrites the text-only LLM call in `text_encoding.py` — the "is this decoded text coherent?" validator — to the native Gemini endpoint documented in SPEC.md `### Provider constraints`.

One source file to edit: `src/pipeline/extraction/text_encoding.py`. Plus a local probe before you report done.

---

## Step 1: Read SPEC.md first

Open `SPEC.md` and read `### Provider constraints`, specifically `#### Image enrichment / language validation — generateContent contract` and the **text-only** request variant. That's the source of truth.

Key facts from SPEC you will be coding to:

- **Endpoint:** `POST {base}/models/{model}:generateContent`
- **Header:** `x-goog-api-key: <key>` only.
- **Request body (text-only):**
  ```json
  {
    "contents": [{
      "parts": [{"text": "<prompt>"}]
    }]
  }
  ```
- **Response body:**
  ```json
  {"candidates": [{"content": {"parts": [{"text": "<reply>"}]}}]}
  ```

The env var used here (`ARIADNE_IMAGE_ENRICHMENT_MODEL` via `ImageEnrichmentConfig` — note the field-reuse, same as the existing code) holds a bare model name. The code prepends `models/` in the URL path.

---

## Step 2: Rewrite `text_encoding.py`

File path: `src/pipeline/extraction/text_encoding.py`.

Preserve the public API exactly:

- `detect_and_decode(path) -> tuple[str, str, float]` — **do not touch.** It's pure charset-normalizer logic, no LLM.
- `LanguageValidation` dataclass — **do not touch.** All callers depend on its fields.
- `_VALIDATION_PROMPT` constant — **do not touch.** The prompt content is fine and the JSON-asking format still works with native Gemini.
- `validate_language(text: str, config) -> LanguageValidation` — signature unchanged. Internal call path changes.

Internal changes inside `validate_language`:

### 2a. Module docstring (lines 1-6)

Replace:

```python
"""Text encoding detection and LLM language validation for .txt files.

Uses charset-normalizer (transitive dependency of MarkItDown) for encoding
detection, and the existing image enrichment API config for an LLM validation
call that confirms the decoded text is coherent (not mojibake).
"""
```

With:

```python
"""Text encoding detection and LLM language validation for .txt files.

Uses charset-normalizer (transitive dependency of MarkItDown) for encoding
detection, and Gemini's native `:generateContent` endpoint for a text-only
LLM call that confirms the decoded text is coherent (not mojibake). Reuses
the image-enrichment config (`ImageEnrichmentConfig`) so operators don't
have to configure a second provider.

See SPEC.md → "Provider constraints" for the request/response contract
and an explanation of why the OpenAI-compatible shim is not supported
for Ariadne's bundled language validator.
"""
```

### 2b. Endpoint construction (line 88)

Replace:

```python
endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
```

With:

```python
model_path = config.model
if not model_path.startswith("models/"):
    model_path = f"models/{model_path}"
endpoint = f"{config.base_url.rstrip('/')}/{model_path}:generateContent"
```

### 2c. Payload (lines 90-96)

Replace:

```python
payload = {
    "model": config.model,
    "messages": [
        {"role": "user", "content": prompt},
    ],
    "max_tokens": 256,
}
```

With:

```python
# Native Gemini text-only payload.
# See SPEC.md → "Provider constraints" → generateContent contract (text-only).
payload = {
    "contents": [
        {"parts": [{"text": prompt}]}
    ],
    "generationConfig": {"maxOutputTokens": 256},
}
```

### 2d. Comment block (lines 102-113)

The old (wrong) block says `x-goog-api-key` works on the OpenAI-compat shim — it doesn't. Replace it with:

```python
        # NOTE FOR FUTURE AGENTS — native Gemini endpoint, not OpenAI-compat.
        # Ariadne's language validator calls Gemini's native
        # `:generateContent` with a text-only part and the
        # `x-goog-api-key` header. The OpenAI-compatible shim at
        # `/v1beta/openai/chat/completions` is NOT supported here —
        # Google's `AQ.*`-format keys reject every auth variant on
        # that path.
        #
        # If you swap to a different OpenAI-compatible provider
        # (OpenAI proper, Together, Groq, etc.), this whole function
        # needs a rewrite — endpoint construction, payload shape
        # (chat/completions with messages), response parser, and
        # auth header all differ. Don't build a provider abstraction
        # here; let the configuring agent read the provider's docs
        # and pick a concrete path. See SPEC.md → "Provider
        # constraints" for the current native contract.
```

(The indentation must match the surrounding `headers={...}` dict — the comment sits inside the `Request(...)` call, same place as it does now.)

### 2e. Response parsing (lines 121-124)

Replace:

```python
try:
    with urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    content = result["choices"][0]["message"]["content"]
except Exception as e:
    return LanguageValidation(
        ...
```

With:

```python
try:
    with urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    # Native response: candidates[0].content.parts[].text
    candidates = result.get("candidates") or []
    if not candidates:
        raise RuntimeError(
            f"generateContent returned no candidates: {result}"
        )
    parts = candidates[0].get("content", {}).get("parts") or []
    text_parts = [p.get("text", "") for p in parts if "text" in p]
    if not text_parts:
        raise RuntimeError(
            f"generateContent returned no text parts: {result}"
        )
    content = "".join(text_parts).strip()
except Exception as e:
    return LanguageValidation(
        ...
```

Do not change the graceful-failure paths below (they already return `LanguageValidation(coherent=True, ..., notes=f"LLM API call failed: {e}", ...)` which is the correct behavior — language validation failure must never break ingest).

### 2f. Handle JSON-in-markdown-fence responses (after the response parser)

Gemini's native endpoint sometimes wraps JSON output in ```` ```json ... ``` ```` fences, which `json.loads` will reject. Add fence-stripping immediately before the existing `parsed = json.loads(content)` call (around line 137):

```python
# Gemini occasionally wraps JSON replies in a ```json ... ``` fence
# when responseMimeType is not explicitly set. Strip it before parsing.
stripped = content.strip()
if stripped.startswith("```"):
    lines = stripped.splitlines()
    # Drop the opening fence (may be ```json or ```)
    lines = lines[1:]
    # Drop the closing fence if present
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    stripped = "\n".join(lines).strip()

try:
    parsed = json.loads(stripped)
except (json.JSONDecodeError, TypeError):
    return LanguageValidation(
        ...
```

Keep everything below that identical — the final `return LanguageValidation(coherent=parsed.get(...))` call is unchanged.

---

## Step 3: Local probe before reporting done

Create `scripts/_probe_text_encoding.py` (untracked — do **not** `git add`):

```python
"""One-shot probe — confirms validate_language round-trips against live Gemini.

Passes a known-good English paragraph and a known-bad mojibake sample.
Asserts the good one comes back coherent=True and the bad one comes back
coherent=False (or at minimum low confidence).

Usage: python scripts/_probe_text_encoding.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

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
for k, v in env.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipeline.extraction.text_encoding import validate_language  # noqa: E402


class Config:
    def __init__(self):
        self.api_key = os.environ["ARIADNE_IMAGE_ENRICHMENT_API_KEY"]
        self.base_url = os.environ["ARIADNE_IMAGE_ENRICHMENT_BASE_URL"]
        self.model = os.environ["ARIADNE_IMAGE_ENRICHMENT_MODEL"]


cfg = Config()
print(f"model:    {cfg.model}")
print(f"base_url: {cfg.base_url}")

good = "The quick brown fox jumps over the lazy dog. This is a normal, coherent English paragraph with no encoding problems whatsoever."
bad = "Ã¢â‚¬â„¢Ã¢â‚¬Å"Ã°ÂŸÂÂŸÃ°ÂŸÂÂŸ Ã¢â‚¬â„¢Ã°ÂŸÂÂŸÃ¢â‚¬Å"Ã¢â‚¬â„¢Ã°ÂŸÂÂŸ mojibake Ã¢â‚¬Å"Ã¢â‚¬â„¢Ã°ÂŸÂÂŸÃ°ÂŸÂÂŸ garbage output test"

good_result = validate_language(good, cfg)
print(f"\n-- GOOD --")
print(f"  coherent={good_result.coherent}  language={good_result.language}  script={good_result.script}")
print(f"  confidence={good_result.confidence}  skipped={good_result.skipped}")
print(f"  notes={good_result.notes!r}")

bad_result = validate_language(bad, cfg)
print(f"\n-- BAD --")
print(f"  coherent={bad_result.coherent}  language={bad_result.language}  script={bad_result.script}")
print(f"  confidence={bad_result.confidence}  skipped={bad_result.skipped}")
print(f"  notes={bad_result.notes!r}")

assert not good_result.skipped, "validator was skipped — check API key"
assert not bad_result.skipped, "validator was skipped — check API key"
assert good_result.coherent is True, f"good text came back coherent=False: {good_result.notes}"
# The bad sample is garbage; accept either coherent=False or low-confidence as a pass.
assert (bad_result.coherent is False) or (bad_result.confidence == "low"), (
    f"bad mojibake sample was not detected: {bad_result}"
)

print("\nPASS")
```

Run it:

```bash
cd ariadne-core
python scripts/_probe_text_encoding.py
```

**Hard gate:** must print `PASS`. Good sample must come back `coherent=True`, bad sample must come back either `coherent=False` or `confidence=low`. If you get `skipped=True`, the `ARIADNE_IMAGE_ENRICHMENT_API_KEY` isn't loading — flag it. If the API call errors out and returns `coherent=True` with `notes="LLM API call failed: ..."`, the request shape is wrong — stop and report.

---

## Step 4: Do not touch anything else

Do not edit:

- `embedder.py` (phase 3, landed).
- `vision.py` (phase 4, landed).
- `config.py`, `.env.example`, `cli.py`, `setup.py`, `ariadne.yaml`, any `docs/*.md`, `README.md` (phase 6).
- Tests or `FIXES.md` (phase 7).
- `SPEC.md`, any skill file, `CLAUDE.md`.
- The `detect_and_decode` function, the `LanguageValidation` dataclass, or the `_VALIDATION_PROMPT` constant.

---

## Step 5: Verify

```bash
cd ariadne-core
python -c "from pipeline.extraction.text_encoding import detect_and_decode, validate_language, LanguageValidation; print('import OK')"
grep -n "Authorization.*Bearer\|/chat/completions\|\"messages\"\|\"max_tokens\"\|choices\[0\]" src/pipeline/extraction/text_encoding.py
grep -n ":generateContent\|x-goog-api-key\|generationConfig\|candidates" src/pipeline/extraction/text_encoding.py
git status
```

Expect:

- Import prints `OK`.
- First grep: `Authorization.*Bearer` and `chat/completions` only appear in the new comment block (read context to confirm). `"messages"`, `"max_tokens"`, `choices[0]` must be **completely absent from live code** (including comments — this isn't like vision where a comment legitimately mentions `image_url`).
- Second grep: endpoint has `:generateContent`, header is `x-goog-api-key`, payload uses `generationConfig`, response parser references `candidates`.
- `git status`: only `src/pipeline/extraction/text_encoding.py` tracked-modified (plus `DAVE_DONE.md`; `scripts/_probe_text_encoding.py` untracked).

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- The six substantive diffs (docstring, endpoint, payload, comment, response parser, fence-stripping).
- Probe output — both `good` and `bad` `LanguageValidation` results plus the `PASS` line.
- `git status` proof that nothing else was modified.
- Any anomaly flagged for Bob.
