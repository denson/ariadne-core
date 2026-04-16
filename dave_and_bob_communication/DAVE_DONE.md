# DAVE_TEXT_ENCODING_FIX — Done (uncommitted)

Hotfix for Step 3: skip MarkItDown entirely for `.txt` files, use
charset-normalizer's decoded text directly as markdown output.

## File touched

- `src/pipeline/extraction/markitdown.py` — modified

## What changed

In the `extract()` method, the `.txt` file path was restructured:

**Before (Step 3 original):**
1. `detect_and_decode()` → decoded text
2. Write decoded text to UTF-8 temp file
3. Pass temp file to `self._md.convert()` → crashes (Magika misdetects UTF-8 as ASCII)

**After (this fix):**
1. `detect_and_decode()` → decoded text
2. Use decoded text directly as `markdown` output, set `title = None`
3. Do NOT call `self._md.convert()` for `.txt` files

### Removed
- Temp file creation for `.txt` files (`tempfile.mkstemp`, `write_text`)
- `txt_temp_path` variable and its cleanup block
- `convert_path` variable (no longer needed — the branch is now explicit)

### Kept unchanged
- `detect_and_decode()` call — still runs
- `validate_language()` call — still runs on the decoded text
- All encoding metadata, warnings, and `suggested_tags` logic
- `self._md.convert()` path for non-`.txt` files
- Processing chain with `encoding_detection` step
- URL download cleanup logic
- `text_encoding.py` — untouched
- `mcp_server.py` tag merge — untouched

### Structural change

The old code used a single `try/except/finally` block with `convert_path`
selecting between the temp file and the original. The new code uses an
explicit `if/else` branch:

```python
if txt_decoded is not None:
    # .txt: use charset-normalizer output directly, skip MarkItDown
    markdown = txt_decoded
    title = None
    # URL download cleanup if applicable
else:
    # All non-.txt files (and .txt fallback if detection failed)
    result = self._md.convert(local_path)
    ...
```

If `.txt` encoding detection fails (exception), `txt_decoded` stays `None`
and the file falls through to the MarkItDown path as a last resort.

## Test results

```
World Bank file: sha1_0059c941360fd39d1f262005dca764aa0c339aae.txt
Errors: []
Markdown len: 62606
First 200: Page  1\n1\nLAND ACQUISITION POLICY FRAMEWORK...
Tags: ['encoding:cp1250', 'encoding:low-confidence']
Chain: ['extraction', 'encoding_detection']
```

Non-.txt file (`.py`):
```
file_type: py
Errors: []
Markdown len: 65
suggested_tags: []
Chain: ['extraction']
```

## Acceptance criteria check

1. ✓ A cp1250 .txt file extracts successfully (no crash)
2. ✓ The extracted markdown is the charset-normalizer decoded text (62,606 chars, not empty)
3. ✓ Processing chain has `['extraction', 'encoding_detection']`
4. ✓ Non-.txt files still go through MarkItDown (tested with `.py` file)
5. ✓ No temp file is created for .txt files

## Not committed

Left for Bob. After review, amend the Step 3 commit or create a fixup commit.

## Review summary for Bob

**What changed:** For `.txt` files, the extractor now uses charset-normalizer's
decoded text directly as markdown output instead of writing a temp file and
passing it to MarkItDown. The `if/else` branch replaces the old `convert_path`
approach — `.txt` skips MarkItDown entirely, everything else is unchanged.

**Why:** MarkItDown v0.1.5's upstream Magika detection sets `charset='ascii'`
on files that are valid UTF-8, causing PlainTextConverter to crash on em-dashes,
curly quotes, and all non-Latin scripts. We can't fix MarkItDown, and we don't
need it for plain text — charset-normalizer already did the work.

**What to verify:**
- `.txt` files produce markdown output (62,606 chars for the test file, not empty)
- Non-`.txt` files still go through MarkItDown (tested — works)
- No temp file creation for `.txt` files
- Encoding metadata and LLM validation still run and appear in processing chain
- The fallback path works: if `detect_and_decode()` throws, `.txt` falls through
  to MarkItDown (same as any other file type)
- `text_encoding.py` is untouched
- `mcp_server.py` tag merge is untouched
