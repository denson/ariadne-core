# Tests + FIXES.md update → native Gemini (phase 7 of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phases 1-6b merged (SPEC `db676b0`, deploy skill `731fb49`, embedder `e0caf2e`, vision `c5e923e`, language-validator `43a286f`, config+env `0b9a39e`, docs `6db1663`). This phase updates the pytest suite so it asserts the native Gemini contract phases 3-5 actually implemented, deletes a stale OpenAI-only live test, and records the migration in `FIXES.md`.

**Hard gate for this phase: `python -m pytest tests/` must pass green** after your edits. No exceptions. If any test fails, stop and report; do not commit a red suite.

Four tracked-modified files + one deletion:

1. `tests/test_embedding.py` — mock shapes + assertions rewritten
2. `tests/test_enrichment.py` — mock shapes + assertions rewritten (+ URL-fetch two-call restructuring)
3. `tests/test_config.py` — default-value assertions updated
4. `tests/test_openai_live.py` — **deleted** (superseded by `scripts/_probe_embedder.py`)
5. `FIXES.md` — new numbered entry documenting the migration

---

## Step 1: Read the current code first

Before editing tests, re-read the three modules the tests exercise so the mocks match what the code actually sends and parses:

```bash
cd ariadne-core
cat src/pipeline/embedding/embedder.py
cat src/pipeline/enrichment/vision.py
```

Key shapes you'll need for the mocks (these come from SPEC.md `### Provider constraints` and the phases 3-5 implementations):

**Embedding request body (what the code sends):**
```json
{
  "requests": [
    {"model": "models/<model>", "content": {"parts": [{"text": "<text>"}]}, "outputDimensionality": 1536}
  ]
}
```

**Embedding response body (what mocks must return):**
```json
{"embeddings": [{"values": [0.1, 0.2, 0.3]}, {"values": [0.4, 0.5, 0.6]}]}
```
No `usage` key — native endpoint omits token counts. The embedder client writes `total_tokens = 0`.

**Vision request body (what the code sends):**
```json
{
  "contents": [{"parts": [{"inlineData": {"mimeType": "image/png", "data": "<b64>"}}, {"text": "<prompt>"}]}],
  "generationConfig": {"maxOutputTokens": 1024}
}
```

**Vision response body (what mocks must return):**
```json
{"candidates": [{"content": {"parts": [{"text": "<description>"}]}}]}
```

**Header** (both clients): `x-goog-api-key: <key>` — no `Authorization: Bearer`.

**Endpoint suffixes:**
- Embedding: `.../models/<model>:batchEmbedContents`
- Vision: `.../models/<model>:generateContent`

Run grep on each module to confirm the exact error-message strings before asserting on them in the tests:

```bash
grep -n "raise RuntimeError" src/pipeline/embedding/embedder.py src/pipeline/enrichment/vision.py
```

Use the exact wording the code raises — do not guess.

---

## Step 2: `tests/test_embedding.py`

Rewrite every test that mocks the HTTP call so the mock response uses the native shape.

### 2a. `TestEmbeddingConfig.test_defaults` (lines 12-17)

Update to match the new `EmbeddingConfig` defaults (phase 6a). Replace assertions:

```python
assert config.model == "gemini-embedding-001"
assert config.dimensions == 1536
assert config.base_url == "https://generativelanguage.googleapis.com/v1beta"
assert config.api_key == ""
```

Leave `test_custom` alone — it validates that custom values are accepted, no change needed. Though line 21's custom `model="text-embedding-3-small"` is now misleading; change to `model="gemini-embedding-001"` or any Gemini-flavored name for consistency. Not a correctness issue.

### 2b. `test_embed_texts_success` (lines 60-84)

Change the mock response payload from:
```python
{"data": [{"index": 0, "embedding": [...]}, ...], "usage": {"total_tokens": 10}}
```
to:
```python
{"embeddings": [{"values": [0.1, 0.2, 0.3]}, {"values": [0.4, 0.5, 0.6]}]}
```

Update `total_tokens` assertion to `== 0` (native endpoint omits usage).
Update `result.model` assertion to match new default (`"gemini-embedding-001"`).

### 2c. `test_embed_texts_preserves_order` (lines 86-107)

**Delete this test.** The old implementation needed client-side sorting because the OpenAI-compat response returned `data[].index` out of order. Native `batchEmbedContents` returns `embeddings[]` in request-index order — no client-side sort, no invariant to test. The fact that the client no longer sorts is fine because the API no longer scrambles.

Add a one-line comment in the test file where this test was: `# test_embed_texts_preserves_order removed: native batchEmbedContents returns embeddings in request order`.

### 2d. `test_embed_texts_empty_list` (lines 109-115)

Should pass unchanged — validates the "don't call API for empty input" shortcut. Keep as-is.

### 2e. `test_api_error_raises_runtime_error` (lines 117-122)

Update `match=` string to match the actual error wording in `embedder.py` after the phase-3 rewrite. Run the grep from Step 1 to find it. If the phrase is still "Embedding API call failed" leave this test alone; if it's different, update.

### 2f. `test_processing_chain_entry` (lines 124-145)

Change line 142's assertion from `"embedding-3-small" in chain["tool"]` to `"gemini" in chain["tool"]` (or more precisely, `chain["tool"].startswith("gemini:")`). That matches phase 3's `chain_entry["tool"] = f"gemini:{model}"`.

Mock response shape as in 2b.

### 2g. `test_embed_query` (lines 147-162)

Mock response shape change:
```python
{"embeddings": [{"values": [0.1, 0.2, 0.3]}]}
```

### 2h. `test_api_call_format` (lines 164-192) — biggest rewrite

This test validates the exact HTTP shape. Rewrite the assertions block:

```python
call_args = mock_urlopen.call_args
req = call_args[0][0]
# URL: .../models/<model>:batchEmbedContents, with the custom base_url
assert "custom.api" in req.full_url
assert req.full_url.endswith(":batchEmbedContents")
assert "/models/my-model" in req.full_url or "/models/models/my-model" in req.full_url
# Accept either form — depends on whether embedder.py auto-prepends `models/`
# when the configured model already lacks the prefix.
body = json.loads(req.data)
assert "requests" in body
assert body["requests"][0]["model"].endswith("my-model")
assert body["requests"][0]["content"]["parts"][0]["text"] == "hello"
# Header is x-goog-api-key, not Authorization
assert req.headers.get("X-goog-api-key") == "test-key" or req.headers.get("x-goog-api-key") == "test-key"
assert "Authorization" not in req.headers
```

The `req.headers` dict in urllib is case-preserving and case-sensitive — `urllib.request.Request` normalizes header keys by title-casing the first segment, so `x-goog-api-key` becomes `X-goog-api-key` in `req.headers`. Write the assertion to accept either form (both branches above).

Mock response shape as in 2b.

---

## Step 3: `tests/test_enrichment.py`

Two kinds of change: (a) update `TestVisionConfig.test_defaults`, (b) restructure the two `VisionClient` tests to handle the new two-call pattern in `describe_image_from_url`, (c) update the `"openai:gpt-4o-mini"` tool-label assertion.

### 3a. `TestVisionConfig.test_defaults` (lines 22-27)

Update to Gemini defaults:

```python
assert config.base_url == "https://generativelanguage.googleapis.com/v1beta"
assert config.model == "gemini-2.0-flash"
assert config.api_key == ""
```

`test_custom` — line 33's `model="gpt-4o"` is misleading now; change to `model="gemini-2.0-flash-lite"` or similar. Not a correctness issue.

### 3b. `test_describe_image_from_url` (lines 46-67) — semantic restructure

**Background:** after phase 4, `describe_image_from_url` makes **two** `urlopen` calls:
1. First call with a plain string URL — fetches the image bytes, reads `Content-Type` header.
2. Second call with a `Request` object — POSTs to Gemini's `:generateContent`.

The existing test mocks a single response. Rewrite using `mock_urlopen.side_effect` as a list of two mocks:

```python
@patch("pipeline.enrichment.vision.urlopen")
def test_describe_image_from_url(self, mock_urlopen):
    # Two urlopen calls: (1) fetch image bytes, (2) POST to Gemini
    fetch_resp = MagicMock()
    fetch_resp.read.return_value = b"\x89PNG\r\n\x1a\nfake-bytes"
    fetch_resp.headers = {"Content-Type": "image/png"}
    fetch_resp.__enter__ = lambda s: s
    fetch_resp.__exit__ = MagicMock(return_value=False)

    api_resp = MagicMock()
    api_resp.read.return_value = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "A test image"}]}}]}
    ).encode()
    api_resp.__enter__ = lambda s: s
    api_resp.__exit__ = MagicMock(return_value=False)

    mock_urlopen.side_effect = [fetch_resp, api_resp]

    config = VisionConfig(api_key="test-key")
    client = VisionClient(config)
    result = client.describe_image_from_url("https://example.com/img.png")
    assert result == "A test image"

    # Second call was the Gemini POST — verify payload shape
    assert mock_urlopen.call_count == 2
    api_call = mock_urlopen.call_args_list[1]
    req = api_call[0][0]
    assert req.full_url.endswith(":generateContent")
    body = json.loads(req.data)
    parts = body["contents"][0]["parts"]
    assert any("inlineData" in p for p in parts)
    assert any(p.get("text") for p in parts)
    # No OpenAI-compat keys leaked
    assert "messages" not in body
    assert "model" not in body
    # Auth header
    assert req.headers.get("X-goog-api-key") == "test-key" or req.headers.get("x-goog-api-key") == "test-key"
```

### 3c. `test_api_error_raises_runtime_error` (lines 69-75) — update for two-call path

With the two-call pattern, the single `mock_urlopen.side_effect = Exception(...)` will hit the image-fetch call first, not the API call. The raised error will be the "Failed to fetch image URL" wrapper from phase 4 (grep to confirm exact wording).

Rewrite so the fetch succeeds but the API call fails:

```python
@patch("pipeline.enrichment.vision.urlopen")
def test_api_error_raises_runtime_error(self, mock_urlopen):
    fetch_resp = MagicMock()
    fetch_resp.read.return_value = b"\x89PNG\r\n\x1a\n"
    fetch_resp.headers = {"Content-Type": "image/png"}
    fetch_resp.__enter__ = lambda s: s
    fetch_resp.__exit__ = MagicMock(return_value=False)

    mock_urlopen.side_effect = [fetch_resp, Exception("Connection refused")]

    config = VisionConfig(api_key="test-key")
    client = VisionClient(config)
    with pytest.raises(RuntimeError, match="Vision API call failed"):
        client.describe_image_from_url("https://example.com/img.png")
```

Adjust the `match=` string if the grep in Step 1 shows different wording in `vision.py`.

**Add a second test** covering the URL-fetch-failure path specifically:

```python
@patch("pipeline.enrichment.vision.urlopen")
def test_url_fetch_error_raises_runtime_error(self, mock_urlopen):
    mock_urlopen.side_effect = Exception("Connection refused")
    config = VisionConfig(api_key="test-key")
    client = VisionClient(config)
    with pytest.raises(RuntimeError, match="Failed to fetch image URL"):
        client.describe_image_from_url("https://example.com/img.png")
```

Adjust `match=` to the exact wording from vision.py's `describe_image_from_url` error path.

### 3d. `test_processing_chain_entry` (lines 155-166)

Change line 163 assertion from:
```python
assert chain["tool"] == "openai:gpt-4o-mini"
```
to:
```python
assert chain["tool"] == "gemini:gemini-2.0-flash"
```

This matches the default `ImageEnrichmentConfig.model = "gemini-2.0-flash"` from phase 6a and the `f"gemini:{model}"` format used by the enricher.

**Note:** check whether the enricher (`src/pipeline/enrichment/images.py`) writes the tool label as `f"openai:{model}"` or `f"gemini:{model}"`. Phase 4's instruction only rewrote `vision.py`; the enricher may still write `openai:...`. If so, that's a bug phases 3-5 missed — flag it for Bob, do **not** fix in this phase (image enrichment is tested via mocks, so the phase-3 pattern of updating the label applies to the enricher too).

If the enricher still writes `openai:...`, change the test assertion to match reality (`openai:gemini-2.0-flash` — weird-looking but accurate) and flag as a backlog item. If the enricher writes `gemini:...`, the assertion above is correct.

### 3e. Leave the other `TestImageEnricher` tests alone

They all use `@patch.object(VisionClient, "describe_image_from_url")` — they mock at the VisionClient method level, not the HTTP level, so native-vs-shim shape doesn't affect them. Keep as-is.

---

## Step 4: `tests/test_config.py`

Three clusters of assertions to update.

### 4a. `TestLoadConfigDefaults.test_defaults_without_file` (lines 100-112)

Update:
```python
assert config.embedding.model == "gemini-embedding-001"
# ...
assert config.image_enrichment.model == "gemini-2.0-flash"
```

### 4b. `TestLoadConfigFromFile.test_file_overrides_defaults` (lines 122-138)

The YAML fixture at line 127 uses `text-embedding-3-small` as a test string. Change to `gemini-embedding-001` for consistency. Line 133 assertion updates accordingly. Line 137 assertion:
```python
assert config.embedding.base_url == "https://generativelanguage.googleapis.com/v1beta"
```

### 4c. Env-var test around lines 285-299

Change the test's env-var values from OpenAI-ish to Gemini-ish:
```python
"EMBEDDING_MODEL": "gemini-embedding-001",
"EMBEDDING_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
"VISION_MODEL": "gemini-2.0-flash",
"VISION_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
```

Assertions at lines 297-299 update to match.

### 4d. Line 63-66 (URL-env-var-substitution test)

This test is about `${HOST:-fallback}` substitution syntax — the OpenAI URL is just a test string showing the mechanic works. Leave alone unless it's obvious other tests read the substituted value and expect a specific provider; if the test only asserts string substitution happened, it's fine.

---

## Step 5: Delete `tests/test_openai_live.py`

```bash
cd ariadne-core
git rm tests/test_openai_live.py
```

Rationale for the commit message (which Bob will write): this standalone live-API script targeted the OpenAI `/v1/embeddings` endpoint. The native Gemini equivalent is already covered by `scripts/_probe_embedder.py`, which Bob re-ran in phase 3 and which lives outside the repo (untracked). Tests should not reach live external APIs during `pytest` runs, and the deleted script was imperative-script-style, not pytest-style. Nothing of value lost.

---

## Step 6: `FIXES.md` — add a migration closure entry

Read the current `FIXES.md` to see the numbered-section pattern. Add a new section at the top (before section 1) — this is the most recent large fix, so it leads.

Use exactly this structure, adapting the details as you like:

```markdown
## 0. Native Gemini migration (v1)

**Target state:** Bundled embedding, vision, and language-validation clients call Google Gemini's native endpoints (`:batchEmbedContents`, `:generateContent`) with `x-goog-api-key`. Multi-provider support is out of scope for v1 — other providers require forking the client modules.

**Current state:** ✅ Fixed across 7 phases (April 2026).

**What was changed:**
- SPEC.md `### Provider constraints` now documents the native contract (phase 1, `db676b0`).
- `skills/ariadne-core-deploy/SKILL.md` updated for native env vars (phase 2, `731fb49`).
- `src/pipeline/embedding/embedder.py` rewritten for native `:batchEmbedContents` (phase 3, `e0caf2e`).
- `src/pipeline/enrichment/vision.py` rewritten for native `:generateContent` with `inlineData` parts. `describe_image_from_url` now fetches URL bytes server-side — new outbound-HTTP surface (phase 4, `c5e923e`).
- `src/pipeline/extraction/text_encoding.py` language validator rewritten for native `:generateContent` with markdown-fence-strip fallback (phase 5, `43a286f`).
- Runtime defaults in `config.py`, `.env.example`, `config/ariadne.yaml`, `scripts/setup.py`, and the CLI's built-in `_ENV_TEMPLATE` now point at Gemini-native URLs (phase 6a, `0b9a39e`).
- User-facing docs (README, configuration, installation, architecture) updated with an honest "roll your own for other providers" caveat banner (phase 6b, `6db1663`).
- Pytest suite updated to assert the native HTTP contract; stale `tests/test_openai_live.py` deleted (phase 7, this commit).

**Why:** Google's `AQ.*`-format API keys are rejected by every auth variant on the OpenAI-compatible shim at `/v1beta/openai/*`. Empirical probe (April 2026) confirmed native endpoints with `x-goog-api-key` as the only viable path.

**Known carry-forward items:**
- `docs/roadmap/pro-pricing.md` and `docs/roadmap/token_pricing_snapshot.md` still reference OpenAI-compat defaults (phase 6c, pending).
- Multi-provider support (OpenAI, Together, Groq) deferred to v2 via a provider abstraction.
- `docs/installation.md` still uses legacy unprefixed env var names (`EMBEDDING_API_KEY` vs `ARIADNE_EMBEDDING_API_KEY`) — separate backlog item.

**How to test:**
- `python -m pytest tests/` passes green.
- `python scripts/_probe_embedder.py` and `python scripts/_probe_vision.py` print PASS against live Gemini (probes are not tracked; re-create from phase 3/4 `DAVE_CODE*.md` if needed).
- `curl -H "x-goog-api-key: $KEY" "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents" -d '{"requests":[{"model":"models/gemini-embedding-001","content":{"parts":[{"text":"test"}]},"outputDimensionality":1536}]}'` returns a 200 with an embeddings array.
```

If the existing FIXES.md already has a section 0 or uses a non-numeric top heading, adapt the insert position but keep the content structure above.

---

## Step 7: Run the test suite — this is the hard gate

```bash
cd ariadne-core
python -m pytest tests/ -v
```

**Must pass green.** If any test fails, do not report PASS; stop and investigate. A red suite means either:

- Your mock shape doesn't match what the code actually sends/reads — re-read Step 1 and the module source.
- An assertion in the code (e.g. an error-message match string) doesn't match the actual wording — grep the module and copy the exact string.
- The enricher tool-label is still `openai:` (see 3d) — flag for Bob, update the assertion to match reality, do not touch the enricher.
- The `outputDimensionality` field is absent when `config.dimensions` is falsy — the embedder only sets it when truthy. Tests that mock without setting dimensions may need to pass `dimensions=1536` explicitly, or accept either presence.

Expected pass count: whatever the current count was before this phase, minus the deleted `test_openai_live.py` file (if it was ever collected by pytest — it's a `__main__`-style script, not a test class, so pytest likely skipped it anyway), minus `test_embed_texts_preserves_order` (intentional deletion per 2c), plus `test_url_fetch_error_raises_runtime_error` (new per 3c).

---

## Step 8: Verify

```bash
cd ariadne-core
grep -n "openai:\|openai\.com\|/embeddings\|/chat/completions\|text-embedding-3-small\|gpt-4o-mini" tests/
git status
```

- **First grep:** zero hits in `tests/test_*.py` files. A hit inside `tests/fixtures/` is OK (raw sample data). A hit inside a test docstring is OK. Any hit inside an assertion or mock payload fails the phase.
- `git status`: four tracked-modified test files (`test_embedding.py`, `test_enrichment.py`, `test_config.py`, `FIXES.md`) and one tracked-deleted file (`test_openai_live.py`). Plus `DAVE_DONE.md`.

---

## Step 9: Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- Per-file summary of edits.
- The `pytest -v` output (or at least the final green-line tally and any skips).
- The output of the Step 8 grep.
- Whether the enricher writes `openai:` or `gemini:` as the tool label (from your Step 3d investigation) — this is a real datum Bob needs.
- Any test you had to restructure more deeply than the instruction anticipated (the two-urlopen mock pattern most likely).
- Any anomaly.
