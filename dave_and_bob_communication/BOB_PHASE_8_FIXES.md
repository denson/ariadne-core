# BOB — Phase 8 post-mortem fixes (review, commit, log backlog)

Per `DAVE_PHASE_8_FIXES.md`. Two fixes and three deferred backlog
items. Code and tests are staged in the working tree per Dave's
`DAVE_DONE.md`; nothing is committed. Your job:

1. Review the diffs and tests.
2. Log three backlog items in `docs/BACKLOG.md`.
3. Commit + push.

---

## What Dave fixed (read `DAVE_DONE.md` first)

| Fix | Files touched |
|---|---|
| **BL-18** — client ingest timeout floor + per-call override | `client/src/ariadne_core_client/client.py`, `client/tests/test_client_timeout.py` (new), `client/tests/conftest.py` (new) |
| **BL-21** — server 500 error body propagation | `src/pipeline/api/app.py`, `tests/test_api_error_handler.py` (new) |

---

## Review checklist

### BL-18 — client timeout

- `DEFAULT_INGEST_TIMEOUT = 600` is module-level, easy to bump later.
- `_create_document` resolves timeout as `timeout if timeout is not None else max(self.timeout, DEFAULT_INGEST_TIMEOUT)`. A low `self.timeout` at construction time (e.g. `timeout=60`) no longer causes ingest to cap at 60s.
- Public `ingest_url` / `ingest_file` / `ingest_bytes` each have `timeout: int | None = None`. `ingest_bytes` goes through `_upload` first — the upload timeout is still `max(self.timeout, 120)` (unchanged). Only the `_create_document` call takes the new kwarg. That split is intentional; confirm it's preserved.
- `_upload`'s `max(self.timeout, 120)` floor is untouched. Do NOT let Dave have touched it.
- Tests monkeypatch `_http.json_request` / `_http.multipart_upload` rather than hitting a network. Confirm no test actually tries to reach `localhost:8000` or any real URL.

### BL-21 — server 500 handler

- The handler lives in `app.py`, not `routes.py`. It's registered via `@app.exception_handler(Exception)`.
- **Critical:** existing `raise HTTPException(...)` sites in `routes.py` are unchanged. FastAPI runs the `HTTPException` handler before the generic `Exception` handler, so 422/404/410 responses must still return their current shape. The `test_http_exception_is_not_affected_by_global_handler` test covers this — verify it passes and asserts the old shape, not the new one.
- Response body shape: `{"detail": {"error_type": ..., "message": ..., "path": ..., "method": ...}}`. The `detail.message` key matches what `_parse_error_body` in the client's `_http.py` already extracts, so existing clients get a useful error message automatically. Confirm by reading `_parse_error_body` (lines 37–55 of `_http.py`) and checking the shape lines up.
- `str(exc)[:2000]` truncation is there to prevent a massive pg error from blowing out the response body. Good. Keep it.
- `logger.exception(...)` is called before returning. Railway log searches for real errors will still find them. Good.

### Tests

- `pytest tests/ -v` — all pass, count is 185 + new ones (should be 185 + 2 = 187 for the server side).
- `pytest client/tests/ -v` — new directory, 2 tests, both pass.
- No flaky / skip-when-no-pg tests introduced (these are pure unit tests).

---

## Backlog items to record in `docs/BACKLOG.md`

Three entries. Append them at the end of `docs/BACKLOG.md`, preserving
the file's existing format (bold-header sub-sections under an H2
grouping). Use a new H2 group "Phase 8 post-mortem — deferred items"
and add the entries below. **Denson flagged BL-17 and BL-19 as
priority.**

### BL-17 — NUL-byte `psycopg.DataError` on MarkItDown output

**Priority. Denson wants to get to this soon.**

Phase 8 V2 hit 11 files (of 574) where MarkItDown-extracted text
contained NUL (`0x00`) bytes, causing `psycopg.DataError: PostgreSQL
text fields cannot contain NUL (0x00) bytes` on insert and a naked
HTTP 500 to the client. Confirmed via Railway logs — 11-for-11 match
with Dave's 11 × HTTP 500 indices.

Fix direction: strip `\x00` from the MarkItDown-converted Markdown
(and any other text fields destined for Postgres) before handing the
document to `_process_single_document`. Probably in
`pipeline/extraction/markitdown.py` or a narrow post-processing step
in `pipeline/extraction/text_encoding.py`.

**Out-of-scope alternatives to consider before fixing:**
- Whether `\x00` is ever meaningful in downstream chunks (almost
  certainly not — pgvector, embeddings, and search all choke on it).
- Whether the strip should be lossy (drop byte) or marked (replace
  with `\ufffd`). Lossy is probably correct for pg-text destinations;
  no agent will ever query for a NUL byte.

**Blocker:** none. Ready to schedule.

### BL-19 — `store_status="error"` writes a metadata-only documents row

**Priority. Denson wants to get to this soon.**

When embedding fails mid-ingest, `_process_single_document` still
writes a `documents` row but skips the `chunks` / vectors inserts.
The row is then invisible to search (no chunks) but visible to
`list_documents` and `/api/stats` (inflates counts). Example from
Phase 8 V2: 1 errored 429-slip file → 1 orphan row → `stats` reported
561 for `world-bank-ree` vs 558 genuine stored + 2 timeout-but-landed.

Fix direction: two options.
(a) Do NOT write the `documents` row when the embed step fails —
    treat ingest as transactional; either everything lands or
    nothing does. Cleanest semantically; might need a rollback on
    the documents insert.
(b) Add a `status` column to `documents` (values like `stored`,
    `embed_failed`, `partial`) and filter on `status = 'stored'` in
    `list_documents` / `stats` / `search`. More invasive, but
    preserves the forensic trail for operators debugging failures.

Denson's call on (a) vs (b) is the blocker.

**Blocker:** (a) vs (b) product decision.

### BL-20 — `/api/stats` counts orphan rows as documents

Subsumed by BL-19. When BL-19 lands, `list_documents` / `stats`
naturally stop counting orphan rows (either because they don't exist
anymore — option a — or because they're filtered by status — option
b). No standalone fix needed; left here as a pointer so anyone
reading "stats shows the wrong count" finds the right issue.

**Blocker:** BL-19.

---

## Commit message

Two changes are independent enough to commit separately if you want,
but they both flow from the same Phase 8 post-mortem — one commit is
cleaner. Suggested shape:

```
Fix client ingest timeout + propagate server 500 bodies

Phase 8 V2's post-mortem surfaced two client-observability gaps:

- BL-18: AriadneClient used one timeout for all endpoints. On very
  large documents (thousands of chunks) the server's embed phase
  exceeded the client's 120s cap, so the client dropped the connection
  while the server kept going. Two files in a 574-file run landed in
  the DB but the client lost visibility on their document_ids.
  Fix: _create_document now floors timeout at DEFAULT_INGEST_TIMEOUT
  (600s), and public ingest_url / ingest_file / ingest_bytes expose a
  per-call `timeout` kwarg for overrides.

- BL-21: FastAPI's default 500 handler returned a bare "Internal
  Server Error" body. Dave's 11 × NUL-byte failures needed a Railway
  log pull to diagnose because the psycopg.DataError message was
  swallowed between the handler and the client response.
  Fix: app.py registers a global Exception handler that returns
  {"detail": {"error_type", "message", "path", "method"}}. Matches
  the shape _parse_error_body already extracts, so existing clients
  see a useful message in AriadneServerError without client changes.

Tests: client/tests/test_client_timeout.py (new) covers the timeout
floor + per-call override via monkeypatched _http. tests/test_api_
error_handler.py (new) covers the global handler shape and the
non-interference with existing HTTPException paths.

No schema changes, no breaking API changes. HTTPException routes
retain their current response shapes.
```

(Omit `Co-Authored-By` unless you want Claude attribution.)

---

## Post-commit

1. Deploy to Railway (`git push` should trigger the deploy hook; if
   not, the workflow Dave used in earlier rounds still applies).
2. Smoke test: run `probe_prod.py` or fire a single `ingest_url` call
   with a known-NUL-byte file — the 500 response should now include
   `detail.error_type == "DataError"` and `detail.message` containing
   the pg error text. Do this once to confirm the deploy is live.
3. `DAVE_QUERY_API_PASS_1.md` is unblocked. Sam fires it next.

---

## Out of scope for this commit

- **BL-17** — log only; do not attempt the fix in this commit.
- **BL-19** — log only; do not attempt the fix in this commit.
- Any changes to `/api/stats`, `list_documents`, or search filters.
- Any change to the existing `HTTPException` call sites in `routes.py`.

— Sam
