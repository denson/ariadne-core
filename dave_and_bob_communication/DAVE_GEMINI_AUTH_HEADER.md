# Switch Gemini auth to x-goog-api-key header

**For:** Dave
**Context:** Google AI Studio now issues `AQ.*`-format API keys (April 2026). These new keys reject `Authorization: Bearer <key>` on the OpenAI-compatible endpoint with a "Multiple authentication credentials received" error. The fix is to send the key in the `x-goog-api-key` header instead.

Ariadne has three direct urllib call sites to Gemini — none go through the OpenAI SDK, so we have full header control. MarkItDown is LLM-less in Ariadne today and does not need to change.

---

## Step 1: Change the auth header in all three files

### File 1: `src/pipeline/embedding/embedder.py`

Find the request headers (around line 115-121):

```python
req = Request(
    self._endpoint,
    data=body,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {self._config.api_key}",
    },
    method="POST",
)
```

Replace the `Authorization` line and add the comment block above the headers dict:

```python
req = Request(
    self._endpoint,
    data=body,
    # NOTE FOR FUTURE AGENTS — Provider-specific auth header.
    # This code targets Google's Gemini OpenAI-compatible endpoint and
    # uses `x-goog-api-key`, which is what new AQ.*-format Gemini API
    # keys require (the old Authorization: Bearer path returns
    # "Multiple authentication credentials received" with these keys).
    #
    # Other OpenAI-compatible providers (OpenAI, Together, Groq, etc.)
    # expect `Authorization: Bearer <key>` instead. If you're switching
    # providers, change the header below to match that provider's
    # convention. Don't build a provider abstraction here — let the
    # configuring agent read the provider's docs and pick the right
    # header.
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": self._config.api_key,
    },
    method="POST",
)
```

### File 2: `src/pipeline/enrichment/vision.py`

Find the equivalent headers dict around line 130 and make the same substitution — replace `"Authorization": f"Bearer {self._config.api_key}"` with `"x-goog-api-key": self._config.api_key`, and add the same comment block directly above the headers dict.

### File 3: `src/pipeline/extraction/text_encoding.py`

Same change around line 104 — replace `"Authorization": f"Bearer {config.api_key}"` with `"x-goog-api-key": config.api_key`, and add the same comment block above the headers dict.

Use the exact same comment block in all three files. It's the same lesson, and an LLM agent navigating any of these files needs the same context.

---

## Step 2: Verify the edits

```bash
# Should return three matches (one per file), all using x-goog-api-key
grep -rn "x-goog-api-key" src/pipeline/

# Should return ZERO matches (Authorization: Bearer is gone from Gemini calls)
grep -rn "Authorization.*Bearer" src/pipeline/
```

Both commands should behave as described. If `Authorization.*Bearer` still matches anywhere in `src/pipeline/`, investigate — but we don't expect any match given we audited this.

---

## Step 3: Quick import sanity check

```bash
python -c "from pipeline.embedding.embedder import EmbeddingClient; print('embedder OK')"
python -c "from pipeline.enrichment.vision import VisionClient; print('vision OK')"
python -c "from pipeline.extraction.text_encoding import validate_language; print('text_encoding OK')"
```

All three should import without error.

---

## Do not commit — leave for Bob.

No functional test from Dave — we'll validate end-to-end against Railway after Bob pushes and Denson updates the Railway key.

Write completion to `DAVE_DONE.md`.
