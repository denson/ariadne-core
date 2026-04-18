# Step 2: Bulk ingest CLI — scripts/bulk_ingest.py

**Context:** Read `DAVE_BULK_SCOPE.md` for the full plan. This is step 2 of 3. Step 1 (`ariadne_client.py`) must be committed first.

## What to build

A command-line script that uploads and ingests a directory of documents into Ariadne Core. Uses the `ariadne_client` helper from Step 1.

**File:** `ariadne-core/scripts/bulk_ingest.py` (new)

## CLI interface

```
python scripts/bulk_ingest.py <directory> --collection <name> [options]
```

### Required arguments

- `directory` — path to directory containing files to ingest
- `--collection <name>` — target collection name

### Optional arguments

- `--recursive` — walk subdirectories (default: only top level)
- `--tags <tag1,tag2,...>` — comma-separated tags applied to every document
- `--agent-notes <text>` — agent_notes applied to every document
- `--dry-run` — list what would be ingested, don't actually upload
- `--skip-existing` — skip files whose fingerprint already exists (dedup check)
- `--max-files <N>` — stop after N successful ingests (useful for testing)
- `--extensions <ext1,ext2,...>` — only ingest these extensions (default: all supported)
- `--log-file <path>` — write detailed log to this file (default: stderr)

### Supported extensions (default)

Match the server's supported formats:
`.pdf .docx .pptx .xlsx .csv .html .txt .md .json .xml .rtf .epub .eml .msg .zip .ipynb .wav .mp3 .png .jpg .jpeg .gif .bmp .tiff .svg`

## Behavior

1. **Discover files** — scan the directory, filter by extension, report count before starting
2. **Show plan** — print "Found N files. Target: collection <name>. Proceed? [y/N]" unless `--dry-run`
3. **Process in order** — for each file:
   - Upload via `client.upload_file()`
   - Call `client.convert_document()` with `store=True`
   - Track success/failure
4. **Progress reporting** — update status every file, format: `[123/574] filename.pdf → OK (45 chunks)` or `[124/574] filename.pdf → FAILED (rate limit, retrying)`
5. **Summary** — at the end: total attempted, succeeded, failed, skipped (dedup), elapsed time
6. **Error log** — failed files written to `<directory>/bulk_ingest_errors.log` with timestamp, filename, and error

## Error handling

- Individual file failures don't stop the script — log and continue
- Network errors (URLError) → retry via the client's built-in retry
- File read errors → log and skip
- Ctrl-C → show summary of what was done so far, exit cleanly
- Invalid collection name or unreachable server → exit early with clear error

## Progress output format

```
Ariadne Core bulk ingest
  Source: D:\video_projects\world_bank_project_reports\data\content\text
  Target: initial_batch
  Files:  574

Starting...
  [001/574] sha1_00b06cc9....txt → OK (315 chunks, 1834 tokens/sec)
  [002/574] sha1_00c14e2a....txt → OK (87 chunks, 1920 tokens/sec)
  [003/574] sha1_00d89fbc....txt → FAILED: HTTP 429 (retrying in 5s)
  [003/574] sha1_00d89fbc....txt → OK (142 chunks, 1750 tokens/sec)
  ...
  
Done.
  Attempted: 574
  Succeeded: 569
  Failed:    3
  Skipped:   2 (dedup)
  Elapsed:   42m 18s

Errors logged to: D:\...\bulk_ingest_errors.log
```

Use `\r` to rewrite the current line for non-error status (so the terminal doesn't scroll for every file), but print errors on their own lines so they're visible.

Only flush to stdout if `sys.stdout.isatty()` — if piped to a file, write one line per event (don't use `\r`).

## Imports

```python
from ariadne_client import AriadneClient
```

The script lives in `scripts/` alongside `ariadne_client.py`, so the import is direct.

## Don't do

- Don't use any third-party libraries beyond what's in the stdlib. No `rich`, no `tqdm`, no `click`. Use `argparse` and plain print.
- Don't embed the API key or URL. Let `AriadneClient()` discover them.
- Don't do parallel uploads. Serial is fine for now. Future optimization, not initial build.
- Don't try to be clever about batching through `/api/ingest`. That endpoint only works with server-side paths. Use upload + convert per file.

## Do not commit

Report when done. Leave for Bob.
