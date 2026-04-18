# DAVE — Phase 8 post-mortem fixes (BL-18 + BL-21)

Two small, directly-related fixes surfaced by the Phase 8 V2 re-ingest
(`DAVE_DONE.md`, 2026-04-17). Both are low-risk and land together so
we close the observability loop before the Query API work starts.

**Process:** implement both fixes, add tests, write evidence to
`DAVE_DONE.md`. No commit, no push — Bob handles that per
`BOB_PHASE_8_FIXES.md`.

---

## Background — what these fixes address

Phase 8 V2 ingested 574 World Bank REE files. Results:

- 558 explicit `stored` responses, all retrievable
- 11 × HTTP 500 (NUL-byte `psycopg.DataError` — **confirmed via Railway logs**, BL-17 deferred)
- 2 × `Request timed out after 120s` — **client timed out; server completed both**, doc_ids 2957c503… and 7a80434c…, chunks 677 and 342
- 1 × 429 slip through the rate-limit stagger

The 11 × 500 took a Railway log pull to diagnose because the client
only ever received bare `[500] Internal Server Error` — the
`psycopg.DataError` body was swallowed. And the 2 × timeout cost us
doc_ids that the client can't see, even though the server landed them
successfully. Both are client-observability problems, not real ingest
failures.

---

## Fix 1 — BL-18: client ingest timeout

**Problem.** `AriadneClient(timeout=60)` applies one timeout to every
endpoint. `_upload` floors at `max(self.timeout, 120)`, but
`_create_document` (the ingest POST) uses `self.timeout` directly. On
a 574-file run, Dave passed `timeout=120` at construction — two files
with 677 / 342 chunks embedded for more than 120s on the Railway
serverless runtime and the client dropped the connection. Server
finished anyway, but the client lost the `document_id`.

**Fix.** Two changes in `ariadne-core/client/src/ariadne_core_client/client.py`:

### 1a. Add a floor to `_create_document`

Around line 230 — the `_http.json_request(...)` call inside
`_create_document`. Change `timeout=self.timeout` to
`timeout=max(self.timeout, 600)`. 10 min covers the largest WB docs
(biggest was 4319 chunks in V2) with plenty of headroom.

Add a module-level constant at the top of the file so it's easy to
bump later:

```python
DEFAULT_INGEST_TIMEOUT = 600  # seconds — embedding a large doc can take 3-5 min
```

Use it in the floor: `timeout=max(self.timeout, DEFAULT_INGEST_TIMEOUT)`.

### 1b. Per-call `timeout` kwarg on the public ingest methods

Three methods need it: `ingest_url`, `ingest_file`, `ingest_bytes`.
Signature addition: `timeout: int | None = None`. If non-None, it's
passed through to `_create_document` and overrides both the instance
timeout and the floor (agents who know their file is small can drop
it; agents ingesting a GB of PDFs can raise it).

`_create_document` gains a `timeout: int | None = None` parameter.
Resolution order inside:

```python
effective_timeout = timeout if timeout is not None else max(self.timeout, DEFAULT_INGEST_TIMEOUT)
```

Do NOT change the `_upload` floor — it's a different phase (bytes
upload) with a different characteristic time profile. Leave the
existing `max(self.timeout, 120)` alone.

### 1c. Tests

New file `client/tests/test_client_timeout.py`. Two tests:

```python
def test_create_document_floors_timeout_at_default():
    """Even with a low instance timeout, ingest POST uses DEFAULT_INGEST_TIMEOUT as the floor."""
    # monkeypatch _http.json_request to capture the timeout arg, assert it's 600

def test_ingest_file_respects_per_call_timeout_override():
    """Per-call timeout=N on ingest_file propagates to the POST call, overriding the floor."""
    # monkeypatch _http.json_request + _upload, assert the json_request timeout is exactly N
```

You'll need a minimal test harness for the client. Stand up a
`client/tests/conftest.py` with a fixture that monkeypatches
`ariadne_core_client._http.json_request` and
`ariadne_core_client._http.multipart_upload` to record calls without
actually hitting the network. Return canned responses that look like
a real `/api/upload` + `/api/documents` pair.

Note: `client/tests/` does not currently exist. Create the directory.

---

## Fix 2 — BL-21: server 500 error body propagation

**Problem.** FastAPI's default handler for uncaught exceptions returns
`{"detail": "Internal Server Error"}` with no info about the actual
failure. Agents seeing 11 × `HTTP 500` can't tell NUL-byte from OOM
from a deploy regression without server-side log access.

**Fix.** Add a global exception handler in
`ariadne-core/src/pipeline/api/app.py` that catches any uncaught
`Exception`, logs it, and returns a structured body the client can
parse.

### 2a. Handler

Add to `app.py` after the `app = FastAPI(...)` block:

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return structured error bodies for uncaught exceptions.

    FastAPI's default 500 handler returns a bare "Internal Server Error"
    that gives agents no signal. Surface the exception type and message
    so the client can see what actually broke. HTTPException has its own
    handler and is NOT affected by this — this only catches exceptions
    that would otherwise bubble up as naked 500s.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "error_type": type(exc).__name__,
                "message": str(exc)[:2000],  # truncate — pg error messages can be massive
                "path": request.url.path,
                "method": request.method,
            }
        },
    )
```

The `detail.message` shape matches what `_parse_error_body` in the
client's `_http.py` already looks for, so clients get a useful string
in `AriadneServerError.message` for free — no client change needed
for this half.

**Do NOT** change any of the existing `raise HTTPException(...)` call
sites in `routes.py`. FastAPI's `HTTPException` handler runs before
our generic `Exception` handler, so the 422/404/410/etc. responses
are untouched. This handler only fires for exceptions that currently
escape as naked 500s.

### 2b. Tests

Add to `ariadne-core/tests/test_api_error_handler.py` (new file):

```python
def test_unhandled_exception_returns_structured_500():
    """A route that raises a non-HTTPException returns detail.{error_type, message, path, method}."""
    # Build a TestClient app, monkeypatch _process_single_document to raise ValueError("boom"),
    # POST to /api/documents, assert status 500 and response.json()["detail"] has all four fields.

def test_http_exception_is_not_affected_by_global_handler():
    """HTTPException raised in a route still returns its own detail, not the Exception handler's shape."""
    # Post something that triggers an existing HTTPException (e.g. auth failure or a known-422 path),
    # assert detail shape is the route's existing shape, not the global handler's.
```

Use the existing test infrastructure in `tests/` — `conftest.py`
already has client/app fixtures.

---

## Out of scope for this task

- **BL-17 (NUL-byte cleanup).** Separate task, deferred. Do not touch
  MarkItDown output or the ingestion path.
- **BL-19 (metadata-only error row).** Separate task, deferred. Do not
  change what `_process_single_document` does when embed fails.
- **BL-20 (stats count).** Subsumed by BL-19; nothing to do here.
- Any refactor of the existing `HTTPException` usage in `routes.py`.
- Touching anything under `skills/` or `docs/`.

## Do NOT

- Do NOT commit or push. Bob handles that.
- Do NOT run against prod to verify. Tests only. (If you want a live
  sanity check later, `probe_prod.py` on the deploy is the right
  tool — but it's Bob's call, not this task.)
- Do NOT modify the `_upload` timeout floor. Different phase,
  different timing profile, not in scope.

---

## Deliverable: `DAVE_DONE.md`

Overwrite the current `DAVE_DONE.md` with a fresh report:

- **Changed files** table (paths + one-liner on why).
- **Diffs** — paste the actual edits for each load-bearing change
  (the `_create_document` body, the `@app.exception_handler` block).
- **Test results** — `pytest tests/ -v` and
  `pytest client/tests/ -v` output. All should pass; note baseline
  count before the change (currently 185).
- **Manual verification, if any.** If you want to local-test the
  exception handler by starting `ariadne-core serve` and curling a
  broken payload, include the transcript.
- **Caveats** — anything Bob should know before committing.

— Sam
