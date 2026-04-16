# Bob review — DAVE_TEXT_ENCODING_FIX (Phase 1, Step 3 hotfix)

**Verdict:** Clean.

One file modified: `markitdown.py` (26 insertions / 25 deletions). Net change:
remove temp file creation, replace single `try/except/finally` with explicit
`if/else` branch separating `.txt` from non-`.txt` paths.

## Spec mapping (DAVE_TEXT_ENCODING_FIX.md)

1. **`.txt` files skip MarkItDown.** When `file_type == "txt"` and
   `detect_and_decode()` succeeds, `txt_decoded` is set (line 95). The
   `if txt_decoded is not None` branch (line 100) sets `markdown = txt_decoded`
   and `title = None` directly — `self._md.convert()` is never called. ✓

2. **Non-`.txt` files still go through MarkItDown.** The `else` branch
   (line 110) calls `self._md.convert(local_path)` exactly as before. ✓

3. **No temp file creation for `.txt` files.** The `tempfile.mkstemp`,
   `write_text`, and `txt_temp_path` cleanup are all removed. The
   `convert_path` variable is gone. ✓

4. **Encoding metadata and LLM validation still run.** The post-extraction
   block at line 149-197 is completely unchanged — `encoding_info`,
   `validate_language()`, `processing_chain.append()`, warnings, and
   `suggested_tags` all still fire for `.txt` files when `encoding_info`
   is not `None`. ✓

5. **Fallback path works.** If `detect_and_decode()` throws (line 96),
   `txt_decoded` stays `None` and the file falls through to the `else`
   branch — MarkItDown gets a shot as last resort. ✓

## Don't-do checklist

- **`text_encoding.py` untouched.** `git diff HEAD` shows no changes. ✓
- **`mcp_server.py` tag merge untouched.** `git diff HEAD` shows no changes. ✓
- **Non-`.txt` extraction paths untouched.** Same `self._md.convert()` call. ✓
- **Encoding metadata, warnings, tags logic untouched.** Lines 149-197
  identical to Step 3 commit. ✓
- **Only `markitdown.py` in diff.** `git diff --stat HEAD` confirms 1 file. ✓

## Test results

**World Bank .txt file** (`sha1_0059c941360fd39d1f262005dca764aa0c339aae.txt`):
```
Errors: []
Markdown len: 62606
First 200: Page  1\n1\nLAND ACQUISITION POLICY FRAMEWORK...
Tags: ['encoding:cp1250', 'encoding:low-confidence']
Chain: ['extraction', 'encoding_detection']
```

**Non-`.txt` file** (`.py`):
```
file_type: py
Errors: []
Markdown len: 4499
suggested_tags: []
Chain: ['extraction']
```

Both match expected behavior exactly.

## Notes for Denson

1. **URL download cleanup is duplicated** in both branches (lines 105-109
   and 122-126). This is intentional — the `if/else` structure means each
   branch manages its own cleanup, same as any branching `try/finally`
   pattern. Not a problem.

2. **Processing chain still says `"tool": "markitdown"` for `.txt` files**
   (line 143) even though MarkItDown is skipped. This is technically
   inaccurate but harmless — the extraction step entry is generic metadata.
   Could be refined later if needed.
