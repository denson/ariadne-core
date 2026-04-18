# Task: Encoding detection + LLM language validation for text files

**For:** Dave
**Phase:** 1, Step 3 (do this AFTER Steps 1-2 are committed)
**Files to edit:** `src/pipeline/extraction/markitdown.py`
**Files to create:** `src/pipeline/extraction/text_encoding.py`

Read `PHASE1_OVERVIEW.md` first for context.

---

## Why

MarkItDown's `convert()` reads `.txt` files as UTF-8 with no fallback. The World Bank corpus has 574 text files in multiple encodings -- Latin-1, Windows-1252, and various non-English encodings (Russian, Chinese, Arabic, French, Spanish, Portuguese, etc.). A simple cp1252 fallback would silently produce garbage for non-Latin scripts.

We need two layers:
1. **Encoding detection** -- get the bytes decoded to text correctly
2. **Language validation** -- confirm the decoded text is coherent, not mojibake from a wrong encoding guess

Nothing gets rejected. Every file is ingested. Metadata and tags tell the story.

---

## Part A: New file `src/pipeline/extraction/text_encoding.py`

### `detect_and_decode(path: Path) -> tuple[str, str, float]`

Uses `charset-normalizer` (already a transitive dependency of MarkItDown -- do NOT add it to requirements) to detect encoding and decode.

```python
from charset_normalizer import from_path
from pathlib import Path

def detect_and_decode(path: Path) -> tuple[str, str, float]:
    """Decode a text file with automatic encoding detection.
    
    Returns (decoded_text, detected_encoding, confidence).
    Confidence is 0.0-1.0 from charset-normalizer.
    """
    result = from_path(str(path)).best()
    if result is None:
        # Could not detect any encoding -- fall back to latin-1
        # (maps every byte to a character, never throws).
        # The LLM layer will catch if this produced garbage.
        raw = path.read_bytes().decode("latin-1")
        return raw, "latin-1-fallback", 0.0
    return str(result), result.encoding, result.encoding_confidence
```

Key requirements:
- **Never crashes.** If charset-normalizer can't detect anything, fall back to latin-1 (which decodes every byte) and set confidence to 0.0.
- **Returns the confidence** so downstream code can decide how much to trust it.

### `LanguageValidation` dataclass

```python
from dataclasses import dataclass

@dataclass
class LanguageValidation:
    coherent: bool
    language: str       # ISO 639-1 code or "unknown"
    script: str         # "Latin", "Cyrillic", "Arabic", "CJK", etc. or "unknown"
    confidence: str     # "high", "medium", "low"
    notes: str          # explanation if low confidence or not coherent
    model: str          # which LLM model was used
    skipped: bool       # True if LLM validation was skipped (no API key)
```

### `validate_language(text: str, config) -> LanguageValidation`

Makes a chat completion call to the model configured for image enrichment. This reuses the **existing** image enrichment API config -- same model (`gemini-3.1-flash-lite-preview`), same API key, same base URL. No new config section needed.

**How to make the API call:** Look at how `src/pipeline/enrichment/vision.py` calls the vision model. Use the same HTTP client pattern (OpenAI-compatible chat completion endpoint), but send a text prompt instead of an image. The config object you need is `ImageEnrichmentConfig` from `src/pipeline/config.py`.

**Prompt:**

```
Analyze this text sample. Respond with ONLY a JSON object, no other text:
{
  "coherent": true/false,
  "language": "ISO 639-1 code or 'unknown'",
  "script": "Latin/Cyrillic/Arabic/CJK/etc or 'unknown'",
  "confidence": "high/medium/low",
  "notes": "brief explanation if low confidence or not coherent"
}

Text sample:
"""
{first_500_chars}
"""
```

**Send only the first 500 characters** of the decoded text. This keeps the call cheap and fast.

**Parse the JSON response.** If parsing fails (model returned non-JSON), return a `LanguageValidation` with `coherent=True`, `confidence="low"`, `notes="LLM response was not valid JSON"`. Do not crash.

**If no image enrichment API key is configured**, skip the LLM call entirely. Return `LanguageValidation(skipped=True, coherent=True, confidence="low", notes="LLM validation skipped -- no image enrichment API key configured", ...)`.

---

## Part B: Modify `src/pipeline/extraction/markitdown.py`

In `markitdown.py`, the `extract()` method calls `self._md.convert(local_path)` at line 78.

### Before calling MarkItDown (for .txt files only):

1. Check if `file_type == "txt"` (the `file_type` variable is already set earlier in the method via `_guess_file_type`)
2. Call `detect_and_decode(Path(local_path))` to get the decoded text and encoding info
3. Write the decoded text to a temp file as UTF-8
4. Use the temp file path instead of `local_path` when calling `self._md.convert()`
5. Clean up the temp file after conversion (same pattern as the URL download cleanup already in the method around lines 86-91)

### After extraction (for .txt files only):

1. Call `validate_language()` on the first 500 chars of the extracted markdown
2. Add an encoding detection entry to `processing_chain`:

```python
{
    "step": "encoding_detection",
    "detected_encoding": "cp1252",
    "encoding_confidence": 0.89,
    "language": "en",
    "language_script": "Latin",
    "language_confidence": "high",
    "coherent": True,
    "llm_model": "gemini-3.1-flash-lite-preview",
    "ts": "2026-04-15T...",
    "ms": 120
}
```

3. Add warnings to `ExtractionResult.warnings`:
   - If encoding is not UTF-8: `"Source file encoding: {encoding} (not UTF-8)"`
   - If LLM reports low confidence: `"Encoding validation: low confidence"`
   - If LLM reports not coherent: `"Encoding validation: text may be garbled"`

### New field on ExtractionResult

Add a new field to the `ExtractionResult` dataclass:

```python
suggested_tags: list[str] = field(default_factory=list)
```

Populate it in the encoding step:
- `encoding:{detected_encoding}` for any non-UTF-8 file (e.g. `encoding:cp1252`)
- `language:{code}` always (e.g. `language:en`, `language:ru`)
- `encoding:low-confidence` when LLM reports low confidence
- `encoding:suspect` when LLM reports not coherent
- `status:needs-review` when LLM reports not coherent

### Part C: Minimal change in `mcp_server.py`

The caller in `mcp_server.py` (`_process_single_document`, around line 900+) needs to merge `suggested_tags` into the document's tag list before storing. Look at how tags currently flow from extraction to storage. You likely need just a few lines:

```python
if hasattr(result, 'suggested_tags') and result.suggested_tags:
    tags = list(tags or []) + result.suggested_tags
```

Keep this minimal. Do not restructure the tag handling.

---

## What NOT to change

- The extraction path for non-.txt files (PDFs, DOCX, etc. are fine as-is)
- The chunking pipeline
- The embedding pipeline
- The search tools
- The image enrichment code (you're reusing its config, not modifying it)
- Any REST API routes
- `requirements.txt` / `pyproject.toml` (charset-normalizer is already a transitive dep)
- The skill file (already updated in Step 1)
- The MCP ingest tool error messages (already updated in Step 2)

## Acceptance criteria

1. A `.txt` file in Windows-1252 encoding is successfully extracted (no crash)
2. The extraction result includes encoding metadata in the processing chain
3. The extraction result includes language information from the LLM validation
4. Non-coherent text gets `encoding:suspect` and `status:needs-review` tags
5. Non-UTF-8 files get an `encoding:{name}` tag
6. All `.txt` files get a `language:{code}` tag
7. If no image enrichment API key is set, LLM validation is skipped gracefully with a warning
8. UTF-8 `.txt` files still work exactly as before (charset-normalizer detects UTF-8, LLM confirms, minimal overhead)
9. Non-`.txt` files are completely untouched by this change

## Compile / test check

```bash
cd ariadne-core
pip install -e src/ 2>&1 | tail -5
python -c "from pipeline.extraction.text_encoding import detect_and_decode, validate_language, LanguageValidation; print('import ok')"
python -c "from pipeline.extraction.markitdown import MarkItDownExtractor; print('import ok')"
```

Quick encoding test:
```python
from pathlib import Path
from pipeline.extraction.text_encoding import detect_and_decode
# Create a test file with cp1252 bytes (smart quotes)
Path("/tmp/test_cp1252.txt").write_bytes(b"Hello \x93world\x94")
text, enc, conf = detect_and_decode(Path("/tmp/test_cp1252.txt"))
print(f"Decoded: {text!r}, encoding: {enc}, confidence: {conf}")
```

Cyrillic test:
```python
from pathlib import Path
from pipeline.extraction.text_encoding import detect_and_decode
text_bytes = "Привет мир".encode("cp1251")
Path("/tmp/test_cp1251.txt").write_bytes(text_bytes)
text, enc, conf = detect_and_decode(Path("/tmp/test_cp1251.txt"))
print(f"Decoded: {text!r}, encoding: {enc}, confidence: {conf}")
```

## Do not commit

Leave all changes for Bob. Write your completion report to `DAVE_DONE.md`.

---

## Review summary for Bob

**What changed:**
- New file `src/pipeline/extraction/text_encoding.py` with encoding detection (charset-normalizer) and LLM language validation (Gemini flash-lite via existing image enrichment config)
- Modified `src/pipeline/extraction/markitdown.py` to intercept `.txt` file extraction: decode with charset-normalizer first, validate with LLM after, add encoding/language metadata to processing chain and suggested tags
- New `suggested_tags` field on `ExtractionResult` for encoding/language tags
- Minimal change in `mcp_server.py` to merge suggested_tags into document tags

**Why:** World Bank `.txt` files in non-UTF-8 encodings crash MarkItDown. We need to handle any language our embedding model supports (100+ languages via gemini-embedding-001) and detect when decoding produced garbage.

**What to verify:**
- `text_encoding.py` never crashes (latin-1 fallback, JSON parse fallback, skipped-LLM fallback)
- Only `.txt` files are affected -- all other file types untouched
- The LLM call reuses the existing image enrichment config (no new API keys or config sections)
- `charset-normalizer` is NOT added to requirements (it's already transitive)
- Encoding metadata appears in the processing chain
- Tags flow correctly from `suggested_tags` through to storage
- Import checks pass
- The `suggested_tags` merge in mcp_server.py is minimal and doesn't restructure existing tag handling
