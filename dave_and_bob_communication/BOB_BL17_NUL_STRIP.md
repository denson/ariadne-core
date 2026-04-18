# BOB — BL-17: review, commit, STOP for deploy, smoke

Per `DAVE_BL17_NUL_STRIP.md` (spec) and `DAVE_DONE.md` (report).
Dave has changes staged in the working tree; nothing committed.
Your job:

1. Review the diffs.
2. Commit + push + update `docs/BACKLOG.md` (BL-17 resolved).
3. **STOP** after push. Ask Denson to trigger the Railway deploy.
4. Only after he confirms the deploy is live, run the smoke test.

See `PROTOCOL.md` → "Deploy workflow — STOP after push" if this
convention is new to you. Do not poll prod.

---

## What Dave did (read `DAVE_DONE.md` first)

| File | Status |
|---|---|
| `src/pipeline/extraction/markitdown.py` | modified — added post-convergence NUL-strip block between the two extraction branches and `elapsed_ms` computation. Strips `\x00` from `markdown` and `title`, appends one warning with the count. |
| `tests/test_extraction.py` | modified — 3 new tests inside `TestMarkItDownExtractor`: strip, warning present, no-warning-on-clean. |
| `tests/fixtures/nul_byte_sample.txt` | new — ~200+ chars of English prose with a handful of literal `\x00` bytes interspersed. Written as raw bytes. |

Expected test results (Dave's log confirms):
- `pytest tests/test_extraction.py -v` → all prior tests green + 3 new pass
- `pytest tests/ -q` → 202 passed, 3 skipped (199 baseline at `cf4d65f` + 3 new)

---

## Review checklist

### Scope fences (the boring important part)

- **`src/pipeline/dedup.py`** — must be untouched. If you see edits
  here, Dave added defense-in-depth in the storage layer after the
  spec told him not to. Stop and flag.
- **`src/pipeline/storage/pgvector.py`** — must be untouched. Same
  reasoning.
- **`src/pipeline/chunking/chunker.py`** — must be untouched.
- **`src/pipeline/extraction/text_encoding.py`** — must be untouched.
  The strip belongs at the extraction output convergence point, not
  in the decoder.
- **`client/`** — must be untouched.
- **`skills/`** — must be untouched.
- **`SPEC.md`** — must be untouched. Warning text is a behavior
  detail, not a contract surface.

`git diff --stat` should show exactly 2 modified files + 1 new file:

```
src/pipeline/extraction/markitdown.py | (+~10 -0)
tests/test_extraction.py              | (+~30 -0)
tests/fixtures/nul_byte_sample.txt    | (new)
```

If the stat shows anything else, stop and check.

### Strip-block placement

Open `markitdown.py` and confirm the new strip block:

- Lives AFTER both the `if txt_decoded is not None:` branch and the
  `else:` / `try/finally` branch close. Single post-convergence
  block, not duplicated.
- Lives BEFORE `_estimate_tokens(markdown)` — so token counts reflect
  what's actually stored.
- Uses `.replace("\x00", "")` — delete, not substitute. No spaces,
  no `\ufffd`.
- Appends warning using the existing `warnings: list[str]` pattern,
  not a new field on `ExtractionResult`.
- Handles `title is None` without crashing. `title.count("\x00")`
  without a None-check is a bug — verify Dave guarded it.

### Test file

- New tests go inside `class TestMarkItDownExtractor:` alongside the
  existing `test_extract_txt_*` tests, using the same `setup_method`
  / `self.extractor` pattern. No new class.
- Each test has one concern. No omnibus tests.
- Fixture file `nul_byte_sample.txt` is actually written as raw
  bytes — verify with:

  ```bash
  python -c "print(open('tests/fixtures/nul_byte_sample.txt','rb').read().count(b'\\x00'))"
  ```

  Should print a positive integer. If it prints 0, Dave wrote the
  fixture through text mode and the NULs were lost — stop and ask.

### BACKLOG.md update (do this as part of this commit)

`docs/BACKLOG.md` has an active `### BL-17` entry around line 184.
After this commit, BL-17 is resolved. Replace the body of that entry
with a one-line resolution note pointing at this commit's SHA (you'll
know the SHA after you commit, so: commit first, then amend OR do a
follow-up edit in the same commit by staging the edit alongside
Dave's files before `git commit`). Cleanest approach:

1. Stage Dave's 3 files.
2. Edit the BL-17 section of `docs/BACKLOG.md` to strike the entry.
3. Stage the BACKLOG edit.
4. Commit everything together.

Resolution-note shape to match the repo's convention:

```markdown
### BL-17 — NUL-byte `psycopg.DataError` on MarkItDown output — RESOLVED

Resolved in this commit. `MarkItDownExtractor.extract()` now strips
`\x00` bytes from `markdown` and `title` at the extraction output
convergence point and emits a warning with the stripped count. All
downstream layers (chunking, dedup, storage) therefore never see
NULs. Re-ingest of the 11 known-NUL-byte Phase 8 sha1s is expected
to succeed after deploy.
```

(Keep the heading exactly as shown so the anchor doesn't break any
existing cross-refs.)

### Test count math

- Baseline at `cf4d65f`: 199 passed / 3 skipped.
- After this commit: 202 passed / 3 skipped (199 + 3 new).
- If Dave reports a different number, ask him to re-run and verify.

---

## Commit message

Suggested:

```
Strip NUL (0x00) bytes from extracted markdown (BL-17)

Postgres TEXT columns reject `\x00`, which surfaced as 11-of-574 HTTP
500s during the Phase 8 World Bank re-ingest. The bytes have no
semantic meaning in a text corpus; stripping them at extraction time
is the correct, single-choke-point fix.

Changes:
- `MarkItDownExtractor.extract()` now strips `\x00` from `markdown`
  and `title` at the post-convergence point (after both the
  txt-decoded and MarkItDown-convert branches, before token estimate
  and ExtractionResult construction). Emits one warning per
  extraction with the stripped byte count.
- 3 new unit tests in `tests/test_extraction.py` + 1 new raw-bytes
  fixture (`nul_byte_sample.txt`): strip happens, warning is
  present, clean text produces no NUL warning.
- `docs/BACKLOG.md` → BL-17 marked RESOLVED.

Scope fence: no changes to dedup.py, storage/, chunking/,
text_encoding.py, client/, skills/, or SPEC.md. Extraction is the
single point where all ingest paths converge; defensive strip in
storage is deferred as future hardening if a non-extraction write
path is ever added.

Tests: 202 passed, 3 skipped (199 baseline at cf4d65f + 3 new).
```

(Omit `Co-Authored-By` unless you want Claude attribution.)

### What to stage

Exactly 4 paths:

- `src/pipeline/extraction/markitdown.py`
- `tests/test_extraction.py`
- `tests/fixtures/nul_byte_sample.txt`
- `docs/BACKLOG.md`

Plus `DAVE_DONE.md` is whitelisted in `.gitignore` — do NOT stage it
(it's scratch, overwritten per task; it does happen to be whitelisted
but it isn't part of this commit). Nothing from `phase_8_*`,
`scripts/_probe_*`, or `smoke_bl21.py` gets staged — all scratch,
all ignored or deliberately untracked.

---

## Post-commit: STOP

1. Confirm push succeeded. Cite the new commit hash.
2. **STOP.** Tell Denson:

   > Commit <sha> is on `origin/main`. Please trigger the Railway
   > deploy (Deployments tab → Deploy). Ping me when it's live and
   > I'll run the BL-17 smoke.

3. Do nothing else. Do not curl `/api/health`. Do not curl anything.
   Wait for Denson's confirmation.

---

## Smoke test (ONLY after Denson confirms deploy is live)

Re-ingest one of the 11 known-NUL-byte files from Dave's Phase 8 V2
log. The file is at:

```
D:\video_projects\REE_projects\world_bank\world_bank_project_reports\data\content\text\sha1_17a21c127e26dce69c0789ae13457f8bcdb313b9.txt
```

`smoke_bl21.py` in the workspace root already has the upload +
submit-ingest scaffolding. For BL-17 the expected outcome is
different: the ingest should **succeed** now, not produce an HTTP
500. A quick adaptation:

```python
# BL-17 smoke — copy of smoke_bl21.py's main(), but expect HTTP 200
# Ingest the same sha1 into a throwaway collection.
# Expect: status == 200 (or 201), document_id present in the
# response, and warnings list contains one entry mentioning "NUL"
# or "0x00" with a positive count.
```

Either write `smoke_bl17.py` alongside `smoke_bl21.py` (workspace-
level scratch, untracked) or run the curls inline:

```bash
# 1. Upload the known-NUL file
curl -sS -X POST "$ARIADNE_URL/api/upload" \
  -H "X-API-Key: $ARIADNE_API_KEY" \
  -F "file=@D:/video_projects/REE_projects/world_bank/world_bank_project_reports/data/content/text/sha1_17a21c127e26dce69c0789ae13457f8bcdb313b9.txt"
# → save the returned "path"

# 2. Submit ingest — expect HTTP 200/201, not 500
curl -sS -X POST "$ARIADNE_URL/api/documents" \
  -H "X-API-Key: $ARIADNE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"uri": "<path from step 1>",
       "collection": "smoke-bl17-<random>",
       "agent_type": "smoke-test",
       "initiated_by": "user:denson",
       "agent_notes": "BL-17 smoke: re-ingest known-NUL-byte file, expect success with strip warning",
       "force": true}' \
  | python -m json.tool | head -60
# Expect: document_id present, warnings contains a "NUL (0x00) byte"
# entry, no HTTP 500.
```

Success: HTTP 2xx, `document_id` present, warnings list contains one
`"NUL"` or `"0x00"` entry with a positive count.

Failure modes:
- HTTP 500 with `error_type: DataError` → strip didn't run. Something
  went wrong with the deploy (stale image?) or Dave's placement is
  wrong. Tell Sam, do not roll back.
- HTTP 2xx but no warning → strip ran on a file that didn't actually
  have NULs, OR the warning wasn't appended. Pick another sha1 from
  Dave's V2 log and retry; if still no warning, check the warning
  block code.

Paste the smoke output as a short post-commit note (append to
`DAVE_DONE.md` or write a new `BOB_DONE.md` — your call).

---

## Out of scope for this commit

- **BL-19** — orphan-row-on-embed-fail. Next on the queue after this
  lands; needs a planning call on option (a) transactional rollback
  vs option (b) status column. Not this commit.
- **BL-20** — subsumed by BL-19. Not a standalone fix.
- **Defensive strip in storage layer** — deliberate no-go per Dave's
  spec. If you think of a scenario where a non-extraction path could
  write to `documents.content_markdown`, flag it as a new backlog
  entry. Do not add to this commit.
- **Other control bytes** (0x01–0x1F except 0x09/0x0A/0x0D) —
  separate question; Postgres TEXT only rejects 0x00.

— Sam
