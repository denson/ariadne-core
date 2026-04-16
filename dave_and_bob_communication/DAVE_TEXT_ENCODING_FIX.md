# Fix: Skip MarkItDown for .txt files — use charset-normalizer output directly

**For:** Dave
**Phase:** 1, Step 3 hotfix
**File to edit:** `src/pipeline/extraction/markitdown.py`

---

## What went wrong

Step 3's encoding detection works correctly — charset-normalizer decodes the file, writes clean UTF-8 to a temp file. But MarkItDown's upstream content sniffer (Magika) then re-detects the temp file as `charset='ascii'`, and PlainTextConverter tries `file_stream.read().decode('ascii')` which crashes on any multi-byte UTF-8 character (em-dashes, curly quotes, non-Latin scripts).

Confirmed by tracing: MarkItDown sets `stream_info.charset = 'ascii'` on the re-encoded file even though it's valid UTF-8. This is a MarkItDown bug we can't control.

## The fix

For `.txt` files, skip MarkItDown entirely. charset-normalizer already decoded the text — that decoded text IS the markdown output. Passing it through MarkItDown just to have MarkItDown misdetect the encoding is pointless.

## What to change in `markitdown.py`

In the `extract()` method, the current flow for `.txt` files is:

1. `detect_and_decode()` -> decoded text
2. Write decoded text to temp file as UTF-8
3. Pass temp file to `self._md.convert()` -> crashes

Change it to:

1. `detect_and_decode()` -> decoded text
2. Use decoded text directly as the markdown output
3. Do NOT call `self._md.convert()` for `.txt` files

Concretely, after the `detect_and_decode()` block (around line 86-101), when `encoding_info is not None` and `file_type == "txt"`:

- Set `markdown = decoded_text` directly
- Set `title = None` (plain text has no title extraction)
- Skip the `self._md.convert()` call entirely
- Remove the temp file write (no longer needed for .txt)

The `convert_path` / `self._md.convert()` path still runs for all non-.txt files — untouched.

## What to remove

- The temp file creation for .txt files (`tempfile.mkstemp`, `write_text`, the cleanup in `finally`). None of this is needed if we're not calling MarkItDown.
- The `txt_temp_path` variable and its cleanup block can go.

## What to keep

- The `detect_and_decode()` call — still needed
- The `validate_language()` call — still needed, runs on the decoded text
- All the encoding metadata, warnings, and suggested_tags logic — unchanged
- The `self._md.convert()` path for non-.txt files — completely unchanged

## Acceptance criteria

1. A cp1252 .txt file extracts successfully (no crash)
2. The extracted markdown is the charset-normalizer decoded text, not empty
3. Processing chain still has the `encoding_detection` step
4. Non-.txt files still go through MarkItDown as before
5. No temp file is created for .txt files

## Compile / test check

```bash
cd ariadne-core
PYTHONPATH=src python -c "
from pipeline.extraction.markitdown import MarkItDownExtractor
e = MarkItDownExtractor()
r = e.extract('D:/video_projects/world_bank_project_reports/data/content/text/sha1_0059c941360fd39d1f262005dca764aa0c339aae.txt')
print('Errors:', r.errors)
print('Markdown len:', len(r.markdown))
print('First 200:', r.markdown[:200])
print('Tags:', r.suggested_tags)
print('Chain:', [s['step'] for s in r.processing_chain])
"
```

Should print markdown content, no errors, and `['extraction', 'encoding_detection']` in the chain.

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.

---

## Review summary for Bob

**What changed:** For `.txt` files, the extractor now uses charset-normalizer's decoded text directly as markdown output instead of writing a temp file and passing it to MarkItDown. MarkItDown's content sniffer misdetects valid UTF-8 as ASCII and crashes on multi-byte characters — this bypass avoids the bug entirely.

**Why:** MarkItDown v0.1.5's upstream Magika detection sets `charset='ascii'` on files that are valid UTF-8, causing PlainTextConverter to crash on em-dashes, curly quotes, and all non-Latin scripts. We can't fix MarkItDown, and we don't need it for plain text — charset-normalizer already did the work.

**What to verify:**
- `.txt` files produce markdown output (not empty, not errors)
- Non-`.txt` files still go through MarkItDown (unchanged path)
- No temp file creation for `.txt` files
- Encoding metadata and LLM validation still run and appear in processing chain
- The test command above passes
