# Vision → native Gemini generateContent (phase 4 of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phases 1-3 merged (SPEC `db676b0`, deploy skill `731fb49`, embedder `e0caf2e`). This phase rewrites the vision client to the native Gemini endpoint documented in SPEC.md `### Provider constraints`. Text_encoding comes in phase 5 — **do not touch it here.**

One source file to edit: `src/pipeline/enrichment/vision.py`. Plus a local probe before you report done.

---

## Step 1: Read SPEC.md first

Open `SPEC.md` and read `### Provider constraints`, specifically `#### Image enrichment / language validation — generateContent contract` and the vision request example. That's the source of truth.

Key facts from SPEC you will be coding to:

- **Endpoint:** `POST {base}/models/{model}:generateContent`
- **Header:** `x-goog-api-key: <key>` only.
- **Request body (vision — inline image):**
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
- **Response body:**
  ```json
  {"candidates": [{"content": {"parts": [{"text": "<reply>"}]}}]}
  ```

The env var holds a bare model name (e.g. `gemini-2.0-flash`). The code prepends `models/` in the URL path.

**Behavior change for URL inputs:** Gemini native `generateContent` does not accept arbitrary HTTP(S) image URLs the way OpenAI's `image_url` part does. It accepts `inlineData` (base64 bytes) or `fileData` (Gemini-managed file service URIs — out of scope). So `describe_image_from_url(http_url)` must now **fetch the URL bytes server-side** and pass them as `inlineData`. This is a new outbound HTTP call but preserves the public API.

---

## Step 2: Rewrite `vision.py`

File path: `src/pipeline/enrichment/vision.py`.

Preserve the public API exactly:

- `VisionConfig` dataclass (keep all four fields — `base_url`, `api_key`, `model`, `prompt` — default values can stay or you can update them; config defaults are rewritten in phase 6, do not touch defaults here).
- `VisionClient` class.
- `describe_image_from_path(image_path: str) -> str`
- `describe_image_from_url(image_url: str) -> str`
- `describe_image_from_base64(data: str, mime_type: str = "image/png") -> str`
- `DEFAULT_PROMPT` constant.

Internal changes:

### 2a. Module docstring (lines 1-7)

Replace:

```python
"""Vision API client — any OpenAI-compatible endpoint.

Sends images to a vision model and returns text descriptions.
Supports OpenAI, Anthropic (via proxy), Together, Groq, or any
endpoint that accepts the OpenAI chat completions format with
image_url content parts.
"""
```

With:

```python
"""Vision API client — Gemini native generateContent with inlineData.

Sends images to Gemini's native vision endpoint and returns text
descriptions. Uses the `x-goog-api-key` header.

See SPEC.md → "Provider constraints" for the request/response contract
and an explanation of why the OpenAI-compatible shim is not supported
for Ariadne's bundled vision client.
"""
```

### 2b. `__init__` + endpoint construction (lines 39-41)

Replace:

```python
def __init__(self, config: VisionConfig) -> None:
    self._config = config
    self._endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
```

With:

```python
def __init__(self, config: VisionConfig) -> None:
    self._config = config
    model_path = config.model
    if not model_path.startswith("models/"):
        model_path = f"models/{model_path}"
    self._endpoint = (
        f"{config.base_url.rstrip('/')}/{model_path}:generateContent"
    )
```

### 2c. `describe_image_from_url` (lines 66-78)

Gemini native cannot take an HTTP(S) URL directly. Fetch the bytes and forward to the base64 path. Replace the body with:

```python
def describe_image_from_url(self, image_url: str) -> str:
    """Describe an image from a URL.

    Fetches the URL bytes and sends them as inline data. Gemini's
    native generateContent does not accept arbitrary HTTP(S) image
    URLs; it requires inline base64 or a Gemini-managed file URI.

    Args:
        image_url: HTTP(S) URL to the image.

    Returns:
        Text description of the image.

    Raises:
        RuntimeError: If the URL fetch or the API call fails.
    """
    parsed = urlparse(image_url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError(
            f"describe_image_from_url only accepts http(s) URLs, got: {image_url}"
        )
    try:
        with urlopen(image_url) as resp:
            img_bytes = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch image URL {image_url}: {e}") from e

    mime_type = content_type.split(";")[0].strip() if content_type else ""
    if not mime_type or not mime_type.startswith("image/"):
        guessed = mimetypes.guess_type(image_url)[0]
        mime_type = guessed or "image/png"

    data = base64.b64encode(img_bytes).decode("utf-8")
    return self.describe_image_from_base64(data, mime_type=mime_type)
```

### 2d. `describe_image_from_path` (lines 43-64)

Simplify so it also routes through `describe_image_from_base64`:

```python
def describe_image_from_path(self, image_path: str) -> str:
    """Describe an image from a local file path.

    Args:
        image_path: Path to the image file.

    Returns:
        Text description of the image.

    Raises:
        FileNotFoundError: If the image file doesn't exist.
        RuntimeError: If the API call fails.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return self.describe_image_from_base64(data, mime_type=mime_type)
```

### 2e. `describe_image_from_base64` (lines 80-96)

Change its body to call the native API directly (no more `data:...;base64,...` URL intermediary):

```python
def describe_image_from_base64(
    self, data: str, mime_type: str = "image/png"
) -> str:
    """Describe an image from base64-encoded data.

    This is the terminal method — all other describe_image_* methods
    route through here.

    Args:
        data: Base64-encoded image data.
        mime_type: MIME type of the image.

    Returns:
        Text description of the image.

    Raises:
        RuntimeError: If the API call fails.
    """
    return self._call_vision_api(mime_type=mime_type, b64_data=data)
```

### 2f. `_call_vision_api` — full rewrite (lines 98-152)

Replace the whole method. Signature changes from `(self, image_url: str)` to `(self, mime_type: str, b64_data: str)`. New body:

```python
def _call_vision_api(self, mime_type: str, b64_data: str) -> str:
    """Call Gemini's native generateContent with an inline image.

    Args:
        mime_type: MIME type of the image (e.g. "image/png").
        b64_data: Base64-encoded image bytes.

    Returns:
        Text description from the model.
    """
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": b64_data,
                        }
                    },
                    {"text": self._config.prompt},
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": 1024},
    }

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        self._endpoint,
        data=body,
        # NOTE FOR FUTURE AGENTS — native Gemini endpoint, not OpenAI-compat.
        # Ariadne's vision client calls Gemini's native
        # `:generateContent` with inlineData image parts and the
        # `x-goog-api-key` header. The OpenAI-compatible shim at
        # `/v1beta/openai/chat/completions` is NOT supported here —
        # Google's `AQ.*`-format keys reject every auth variant on
        # that path.
        #
        # If you swap to a different OpenAI-compatible provider
        # (OpenAI proper, Together, Groq, etc.), this whole module
        # needs a rewrite — endpoint construction, payload shape
        # (chat/completions with image_url parts), response parser,
        # and auth header all differ. Don't build a provider
        # abstraction here; let the configuring agent read the
        # provider's docs and pick a concrete path. See SPEC.md →
        # "Provider constraints" for the current native contract.
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.api_key,
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        # Native response: candidates[0].content.parts[].text
        # Concatenate all text parts (usually one).
        candidates = result.get("candidates") or []
        if not candidates:
            raise RuntimeError(
                f"Vision API returned no candidates: {result}"
            )
        parts = candidates[0].get("content", {}).get("parts") or []
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        if not text_parts:
            raise RuntimeError(
                f"Vision API returned no text parts: {result}"
            )
        return "".join(text_parts).strip()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Vision API call failed: {e}") from e
```

### 2g. Keep imports tidy

The existing `from urllib.parse import urlparse` is used in `describe_image_from_url`. The existing `from urllib.request import Request, urlopen` and `mimetypes`, `base64`, `json`, `Path` are all still needed. Do not add new imports beyond what's already there.

---

## Step 3: Local probe before reporting done

Create `scripts/_probe_vision.py` (untracked — do **not** `git add`):

```python
"""One-shot probe — confirms the rewritten vision client round-trips against live Gemini.

Embeds a 1x1 PNG, sends it to Gemini native :generateContent, asserts a
non-empty string reply comes back.

Usage: python scripts/_probe_vision.py
"""
from __future__ import annotations
import os
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
for k, v in env.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipeline.enrichment.vision import VisionClient, VisionConfig  # noqa: E402

# 1x1 white PNG, base64
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)

cfg = VisionConfig(
    model=os.environ["ARIADNE_IMAGE_ENRICHMENT_MODEL"],
    base_url=os.environ["ARIADNE_IMAGE_ENRICHMENT_BASE_URL"],
    api_key=os.environ["ARIADNE_IMAGE_ENRICHMENT_API_KEY"],
)
client = VisionClient(cfg)
print(f"endpoint: {client._endpoint}")

reply = client.describe_image_from_base64(TINY_PNG_B64, mime_type="image/png")
print(f"reply len: {len(reply)}")
print(f"reply:     {reply[:200]!r}")

assert isinstance(reply, str), "expected str reply"
assert len(reply) > 0, "expected non-empty reply"
print("PASS")
```

Run it:

```bash
cd ariadne-core
python scripts/_probe_vision.py
```

**Hard gate:** must print `PASS` with endpoint ending `:generateContent` and a non-empty reply. If you get any HTTP error from Gemini, stop and include the full error body in `DAVE_DONE.md` — do not write a "PASS" report. Probe failure means the code is wrong (or the `.env` values are, in which case flag it).

A 1×1 white pixel will produce a very short reply (Gemini may say "A tiny white square" or similar). That's fine — we're testing the round-trip, not image-description quality.

---

## Step 4: Do not touch anything else

Do not edit:

- `embedder.py` (phase 3, already landed).
- `text_encoding.py` (phase 5).
- `config.py`, `.env.example`, `cli.py`, `setup.py`, `ariadne.yaml`, any `docs/*.md`, `README.md` (phase 6).
- Tests or `FIXES.md` (phase 7).
- `SPEC.md`, any skill file, `CLAUDE.md`.

If `config.py` breaks at import time because of the stale `base_url` default, flag it — **do not fix it here.**

---

## Step 5: Verify

```bash
cd ariadne-core
python -c "from pipeline.enrichment.vision import VisionClient, VisionConfig; print('import OK')"
grep -n "Authorization.*Bearer\|chat/completions\|image_url\|messages" src/pipeline/enrichment/vision.py
grep -n ":generateContent\|x-goog-api-key\|inlineData" src/pipeline/enrichment/vision.py
git status
```

Expect:

- Import prints `OK`.
- First grep: zero matches in live code. The only acceptable hit for `Authorization.*Bearer` or `chat/completions` would be inside the new comment block (read context). `image_url` and `messages` must be completely gone.
- Second grep: endpoint has `:generateContent`, header is `x-goog-api-key`, payload uses `inlineData`.
- `git status`: only `src/pipeline/enrichment/vision.py` tracked-modified (plus `DAVE_DONE.md`; `scripts/_probe_vision.py` untracked).

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- The seven substantive diffs (docstring, `__init__`, `describe_image_from_path`, `describe_image_from_url`, `describe_image_from_base64`, `_call_vision_api`, comment block).
- Probe output — actual `PASS` line, endpoint string, reply text (full, not truncated).
- The new behavior note for `describe_image_from_url` — it now fetches bytes server-side before forwarding, which is a minor semantic change worth calling out for Bob.
- `git status` proof that nothing else was modified.
- Any anomaly flagged for Bob.
