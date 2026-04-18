# DAVE_DONE — BL-17 NUL-byte strip at extraction

**Spec:** `dave_and_bob_communication/DAVE_BL17_NUL_STRIP.md`
**Date:** 2026-04-17
**Verdict:** BL-17 lands green. 202 passed / 3 skipped in `tests/`
(baseline 199 at `cf4d65f` + 3 new from this pass). No existing test
regressed. Nothing committed, nothing staged — Bob handles the commit.

---

## 1. Diff summary

### `src/pipeline/extraction/markitdown.py` (+15, −0)

One insertion block at the converged post-branch point, immediately
after the `else:` branch's `finally:` closes (original line 127) and
before `elapsed_ms = int((time.perf_counter() - start) * 1000)`
(original line 128 → now line 143). Verbatim:

```python
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
```

Placement verifies all four spec constraints:

- **Before `_estimate_tokens(markdown)`** → token estimate reflects
  what gets stored, not pre-strip length. ✓
- **Before `ExtractionResult(... markdown=markdown, title=title)`** →
  returned values are cleaned. ✓
- **After the non-.txt branch's `markdown = ""` error fallback** →
  strip does nothing on empty-string fallback (harmless). ✓
- **One contiguous block, post-convergence** → runs exactly once per
  extraction regardless of path (.txt vs. convert), matching the
  image-warning pattern 8 lines below. ✓

### `tests/test_extraction.py` (+16, −0)

Three new tests appended inside `class TestMarkItDownExtractor:` after
`test_extract_audio_wav`, using the existing `self.extractor` /
`FIXTURES` / `setup_method` pattern. One concern per test.

### `tests/fixtures/nul_byte_sample.txt` (new, 381 bytes, 3 NULs)

Built once with `write_bytes` so NUL bytes survive on disk:

```
b"The quick brown fox jumps over the lazy dog. " * 5
+ b"\x00\x00 interrupted here \x00 more text follows. "
+ b"This is enough content for the encoding validator to treat "
+ b"it as coherent English prose and not flag it as garbled."
```

Verified on disk: `size: 381, NUL count: 3`.

---

## 2. Test results

### Extraction file only (verbose)

```
pytest tests/test_extraction.py -v
============================= 17 passed in 3.99s ==============================
```

All 14 pre-existing tests still pass. The 3 new tests:

```
tests/test_extraction.py::TestMarkItDownExtractor::test_nul_bytes_stripped_from_markdown PASSED
tests/test_extraction.py::TestMarkItDownExtractor::test_nul_bytes_produce_warning PASSED
tests/test_extraction.py::TestMarkItDownExtractor::test_clean_txt_no_nul_warning PASSED
```

### Full suite

```
pytest tests/ -q
202 passed, 3 skipped in 21.57s
```

Matches spec's expected `202 passed, 3 skipped` (= 199 baseline at
`cf4d65f` + 3 new). The 3 skips are the pre-existing
`TestPgResurrection` tests that require a reachable Postgres; local
runs skip them via `conftest.py`'s `pg_pool` fixture.

---

## 3. Scope-fence call-outs

`git diff --stat` (tracked files only):

```
 src/pipeline/extraction/markitdown.py | 15 +++++++++++++++
 tests/test_extraction.py              | 16 ++++++++++++++++
 2 files changed, 31 insertions(+)
```

New untracked fixture:

```
tests/fixtures/nul_byte_sample.txt    (new, 381 bytes)
```

Explicitly untouched, per spec's DEFERRED list:

- `src/pipeline/dedup.py` → untouched (no defense-in-depth strip in
  storage layer; extraction is the choke point).
- `src/pipeline/storage/pgvector.py` → untouched.
- `src/pipeline/chunking/chunker.py` → untouched (strip upstream;
  chunker sees clean text).
- `client/` → untouched.
- `skills/` → untouched.
- `SPEC.md` → untouched (warning is a behavior detail, not a
  surface-level contract change).

`ExtractionResult` dataclass: **no new fields**. The existing
`warnings: list[str]` carries the signal; no `stripped_bytes` field
added.

The `txt_decoded` branch and the `self._md.convert()` branch are
**each untouched in isolation** — the new block sits strictly below
their convergence point.

---

## 4. Caveats / observations

1. **Non-extraction write paths are not defended.** If a future code
   path writes to `documents.markdown` or `documents.title` *without*
   going through `MarkItDownExtractor.extract()`, Postgres will still
   reject NULs. Today there is no such path — all ingest routes through
   extraction → chunking → services. If a future feature (e.g. direct
   API-level `PUT /documents/{id}` with caller-supplied markdown) lands,
   it would need its own strip or a storage-layer defense. Candidate
   for a new backlog item if/when that arrives; not filed in this pass
   to avoid pre-emptive scope creep.

2. **Other control bytes (0x01–0x08, 0x0B, 0x0C, 0x0E–0x1F) pass
   through unchanged.** Spec explicitly flagged this as out of scope.
   Postgres TEXT accepts them; they may render ugly but won't crash
   ingest. No opinion added to scope.

3. **Smoke test revealed a pre-existing, orthogonal warning on this
   fixture:** the LLM language validator votes `garbled=True` for the
   NUL-sample in local test runs (no/limited API key, or the stripped
   text triggered its threshold). This is unrelated to BL-17 and would
   have been present on this fixture regardless. The new tests do not
   depend on this behavior — they assert only on `"\x00" not in
   result.markdown` and on NUL-warning substring presence/absence.

4. **Count in the warning is `3` for the fixture.** Both `markdown`
   and `title` are summed; for .txt files, `title` is `None` so the
   `title` contribution is 0. Test 2 asserts the literal `"3"`
   substring in the warning, which is robust to the exact phrasing
   because the count is the only numeric token.

---

## 5. Local smoke (one-shot, not committed)

Ran via `python -c "..."` against the new fixture:

```
len(markdown): 378
warnings: [
  'Source contained 3 NUL (0x00) byte(s); stripped before storage. '
  'NUL bytes are rejected by Postgres TEXT columns and have no meaning '
  'in text content.',
  'Encoding validation: text may be garbled'
]
NUL in output: False
raw fixture NUL count: 3
```

Observations:

- Raw fixture on disk: 381 bytes, 3 NULs.
- Extracted `markdown`: 378 chars, 0 NULs → exactly 3 bytes removed. ✓
- Warning present, count matches, phrasing matches spec's exact
  string. ✓
- Second warning (`"text may be garbled"`) is the LLM language-
  validator's verdict on this test fixture and is orthogonal to BL-17
  (see caveat #3).

---

## 6. Hand-off to Bob

Bob: please commit the three changes as one unit:

- `M src/pipeline/extraction/markitdown.py`
- `M tests/test_extraction.py`
- `A tests/fixtures/nul_byte_sample.txt`

Suggested commit subject: `Strip NUL bytes from extracted markdown (BL-17)`.
Suggested body: summarize the Postgres TEXT NUL-rejection root cause,
the 11 Phase-8 .txt failures that motivated it, the one-file fix at the
extraction choke point, and the 3-test verification. Do **not** ping
prod — per spec, the live validation (re-ingesting one of the 11 known-
NUL sha1s against the deployed Railway service) is your post-deploy
smoke after Denson triggers the deploy, not part of this PR.
