# DAVE — BL-17: strip NUL (0x00) bytes from extracted markdown

## Why

Postgres TEXT/VARCHAR columns reject `\x00` bytes with `psycopg.DataError:
A string literal cannot contain NUL (0x00) characters.` We saw 11 real
files hit this in the Phase 8 re-ingest (all `.txt` files from the World
Bank corpus). BL-21 now makes the 500 response body honest (error_type
+ message), but the ingest still fails — the user sees an error they
can't fix without us deleting bytes from their content.

Fix: strip NUL bytes (lossy delete) from the extracted markdown and
title before anything downstream (chunking, embedding, dedup, storage)
sees it. Warn when we did. NULs in text destined for a Postgres TEXT
column are never meaningful; dropping them is correct, not lossy in
any practical sense.

Backlog ref: `docs/BACKLOG.md` BL-17.

---

## Scope

Exactly one file of production code changes, plus tests.

### 1. `src/pipeline/extraction/markitdown.py`

After both code paths in `MarkItDownExtractor.extract()` converge on
`markdown` and `title` (i.e. between the `else:` block closing at line
127 and the `elapsed_ms = ...` line at 128), strip `\x00` from both
and append a warning if we stripped any.

Concrete shape:

```python
# (existing code ends here around line 127)

# Strip NUL (0x00) bytes. Postgres TEXT columns reject NUL; nothing
# downstream benefits from a literal 0x00 in the content, so delete
# them outright (lossy but semantically a no-op for text corpora).
# Warn so the caller knows the source wasn't clean.
nul_count = markdown.count("\x00") + (title.count("\x00") if title else 0)
if nul_count:
    markdown = markdown.replace("\x00", "")
    if title:
        title = title.replace("\x00", "")
    warnings.append(
        f"Source contained {nul_count} NUL (0x00) byte(s); stripped "
        "before storage. NUL bytes are rejected by Postgres TEXT "
        "columns and have no meaning in text content."
    )

elapsed_ms = int((time.perf_counter() - start) * 1000)
# (existing _estimate_tokens call on line 129)
```

Placement notes:

- MUST be before `_estimate_tokens(markdown)` so the token estimate
  reflects what actually gets stored.
- MUST be before `ExtractionResult(... markdown=markdown, title=title)`
  — obviously — so the returned value is the cleaned value.
- MUST be after the `errors.append(str(e))` / `markdown = ""` fallback
  in the non-.txt branch — don't try to strip on an empty-string
  fallback (harmless but meaningless).
- Keep it one contiguous block; don't spread the strip over the two
  branches. One post-convergence block is cleaner and matches the
  existing warnings-append pattern right below it (the image warning
  at line 133).

### 2. `tests/test_extraction.py`

Add 3 unit tests, one concern each, using the existing
`TestMarkItDownExtractor` class and the existing fixtures pattern
(`FIXTURES = Path(__file__).parent / "fixtures"`).

Create one new fixture file: `tests/fixtures/nul_byte_sample.txt`.
Contents: enough real English text to pass the LLM language validation
(~200+ chars), with a few literal `\x00` bytes interspersed. Must be
written as raw bytes so the NULs are preserved on disk. Example
write-helper (run once, commit the resulting file):

```python
from pathlib import Path
Path("tests/fixtures/nul_byte_sample.txt").write_bytes(
    b"The quick brown fox jumps over the lazy dog. " * 5
    + b"\x00\x00 interrupted here \x00 more text follows. "
    + b"This is enough content for the encoding validator to treat "
    + b"it as coherent English prose and not flag it as garbled."
)
```

Tests to add:

1. **`test_nul_bytes_stripped_from_markdown`** — extract the fixture,
   assert `"\x00" not in result.markdown`.

2. **`test_nul_bytes_produce_warning`** — extract the fixture, assert
   one of the warnings mentions NUL or 0x00 and includes the count
   (substring check — don't pin exact wording).

3. **`test_clean_txt_no_nul_warning`** — extract the existing
   `sample.txt` (known clean), assert NO warning mentions NUL (again,
   substring check — "NUL" or "0x00" absent from every warning
   string).

All 3 tests go inside `class TestMarkItDownExtractor:` using the
existing `setup_method` / `self.extractor` pattern. One assert per
test (plus the trivial shape assert if needed) — no omnibus tests.

---

## Explicitly DEFERRED / Out of scope

- **`src/pipeline/dedup.py` and `src/pipeline/storage/pgvector.py`** —
  do NOT add defense-in-depth strip in the storage layer. Extraction
  is the single choke point for all ingest paths; if we strip there,
  every downstream layer is safe. Duplicated strip in storage is
  backlog fodder if we ever add a non-extraction write path.
- **chunking layer** (`src/pipeline/chunking/chunker.py`) — untouched.
  Strip upstream; chunker sees clean text.
- **client library** (`client/`) — untouched. Server-side fix.
- **Retroactive cleanup** of the 11 already-failed Phase 8 sha1s — NOT
  this task. Those rows don't exist (ingest failed before any row was
  written). When Denson re-runs the Phase 8 re-ingest after this
  deploys, they'll succeed — no backfill needed.
- **Other control bytes** (0x01–0x08, 0x0B, 0x0C, 0x0E–0x1F) —
  separate question. Postgres TEXT only rejects 0x00; other control
  bytes are legal but may be ugly. Flag as backlog if you have a
  strong opinion; do not change scope here.
- **Input file path sanitization** — NULs in filenames are a different
  bug class (filesystem, not Postgres). Not this task.
- **charset-normalizer / `text_encoding.py`** — untouched. NULs
  survive any encoding conversion; stripping at extraction output is
  correct regardless of where they came from.

---

## DO NOT list

- Do NOT commit, stage, or push. Bob handles that.
- Do NOT touch `src/pipeline/dedup.py`, `src/pipeline/storage/*`,
  `src/pipeline/chunking/*`, `client/`, or `skills/`.
- Do NOT modify the `txt_decoded` branch or the `self._md.convert()`
  branch in isolation — the strip goes in the converged post-branch
  block so it runs exactly once per extraction regardless of path.
- Do NOT `.replace("\x00", " ")` (space) or `"?"` or anything else.
  Delete, don't substitute. A NUL has no meaningful replacement in
  text content.
- Do NOT change `ExtractionResult`'s field types or add new fields.
  The warning list is the only signal needed; no new `stripped_bytes`
  field.
- Do NOT amend existing tests. Add new ones.
- Do NOT touch SPEC.md. The warning is a behavior detail, not a
  surface-level contract change — no endpoint shape changes, no new
  request/response fields.

---

## Deliverable

Overwrite `DAVE_DONE.md` at the repo root with:

1. **Diff summary** — which lines changed in `markitdown.py` (the
   insert block), paths of the new test file(s), the new fixture
   file path.
2. **Test results** — `pytest tests/test_extraction.py -v` output
   (all existing tests still pass + 3 new pass); then full-suite
   count: `pytest tests/ -q` summary line (expect 202 passed, 3
   skipped = 199 baseline at cf4d65f + 3 new).
3. **Scope-fence call-outs** — confirm `dedup.py`, `storage/`,
   `chunking/`, `client/`, `skills/` are untouched. `git diff --stat`
   output pasted verbatim is the cleanest way to show this.
4. **Caveats** — anything you noticed but didn't fix (e.g. "chunker
   doesn't validate input; future NUL source outside extraction would
   still crash storage — filed as a candidate for BL-NN if Sam
   wants").
5. **Local smoke (optional but nice)** — write a tiny script that
   instantiates `MarkItDownExtractor`, runs it against the fixture,
   and prints `len(result.markdown)`, the warnings list, and whether
   `"\x00"` is present. One-shot, not committed. Paste the output.

Hand off to Bob when `DAVE_DONE.md` is written. Do not ping prod. The
live validation (re-ingest one of the 11 known-NUL sha1s against the
deployed service) is Bob's post-deploy smoke after Denson triggers
the Railway deploy — not yours.

— Sam
