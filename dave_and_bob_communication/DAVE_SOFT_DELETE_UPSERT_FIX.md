# Dave — Fix the soft-delete / upsert ghost-write bug

**Priority:** P0 blocker. This is the Phase 8 root cause.
**Estimated scope:** ~60 lines of code + ~80 lines of tests.
**Branch:** off current `main`.

---

## What we found

The Phase 8 re-ingest catastrophe (558 "stored" responses, 0 durable) had nothing to do with multi-worker in-memory state or broken Pg wiring. Sam ruled both of those out this session:

- Current deployment is `ariadne.stores INFO Stores initialized (backend=pgvector)` — confirmed from Railway lifespan logs.
- Six consecutive probes return identical `total_documents=11` — shared storage, no worker-state flapping.
- A fresh one-document ingest right now persists cleanly (`store_status=stored` → doc visible, stats ticks up).

The real bug is in `PgDedupStore.store_document()`. Its `INSERT ... ON CONFLICT (collection_id, content_fingerprint) DO UPDATE SET ...` updates `markdown`, `source_file`, `processing_chain`, etc. — but **does not clear `deleted_at` or `deletion_scheduled_at`**. So when a document is re-ingested after its collection was soft-deleted, the upsert writes the new markdown into the pre-existing row, returns `store_status="stored"` with the same UUID, but the row stays soft-deleted and is invisible to every default query.

### Phase 8 sequence that triggered it

1. 2026-04-16 06:14 UTC — yesterday's WB bulk ingest wrote ~100+ rows with fingerprints F1…Fn to `world-bank-ree`.
2. 2026-04-17 18:57:54 UTC — Dave's preflight `DELETE /api/collections/world-bank-ree` soft-deleted them.
3. 2026-04-17 18:58–20:04 UTC — Phase 8 re-ingested the same files. 100% fingerprint collision → every single write went through ON CONFLICT → every single row stayed soft-deleted → 558 "stored" 200s with 0 durable docs.

### Reproduction (already confirmed on live prod)

Sam's `probe_prod.py resurrection` (in the workspace, not in the repo) reproduces the exact symptom in 4 minutes:

```
Round 1: ingest → stored, visible, 1 doc in list
DELETE /api/collections/<name> → 1 document_marked
Round 2: re-ingest identical content →
    store_status="stored"  (same UUID as round 1)  was_dedup_skip=False
    list default          → 0 docs
    GET /api/documents/<uuid> → 404
```

Same UUID, success response, invisible row. Exactly the Phase 8 pathology.

### Separate issue we're NOT fixing here

During Phase 8, 16 files returned 500 with `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`. MarkItDown output for those PDFs contains embedded NULs that Pg's TEXT type rejects. This is a real but separate bug — punt to a backlog item. Do not touch it in this instruction.

---

## What to change

### (1) Fix the ON CONFLICT clause

**File:** `src/pipeline/dedup.py`, around line 187–242 (`PgDedupStore.store_document`).

In the `DO UPDATE SET` clause, add two lines that clear the soft-delete state:

```sql
DO UPDATE SET
    markdown = EXCLUDED.markdown,
    source_file = EXCLUDED.source_file,
    processing_chain = EXCLUDED.processing_chain,
    processing_time_ms = EXCLUDED.processing_time_ms,
    output_tokens_estimate = EXCLUDED.output_tokens_estimate,
    token_savings_ratio = EXCLUDED.token_savings_ratio,
    tags = EXCLUDED.tags,
    deleted_at = NULL,                  -- NEW
    deletion_scheduled_at = NULL,       -- NEW
    updated_at = now()
RETURNING id, (xmax <> 0) AS was_update, (deleted_at IS NULL) AS is_active
```

**Also update the RETURNING clause** so the caller can tell whether the row was new, updated, or resurrected. `xmax <> 0` is the standard Pg trick for "this row was updated, not inserted". If the code currently uses only `row[0]`, widen it to unpack all three columns.

Update the calling code to capture `was_update` — we'll use it in step (2). Semantics:

- `was_update=False` → new row inserted (fresh fingerprint, normal path)
- `was_update=True` → existing row updated. This is either (a) a force-re-ingest of a live doc, or (b) a resurrection of a previously soft-deleted doc. In case (b) we want to surface it.

You can detect case (b) by adding a boolean parameter `was_soft_deleted` — check it BEFORE the upsert via a quick SELECT on `(collection_id, content_fingerprint)`. Or simpler: add `was_soft_deleted` as another returning column computed from the old state via `CASE` — the easiest shape is:

```sql
RETURNING id, (xmax <> 0) AS was_update,
         (xmax <> 0 AND deleted_at IS NULL) AS is_now_active
```

…no wait, after the UPDATE `deleted_at IS NULL` always holds. You actually need to capture the PRIOR state. Simplest approach: do a cheap `SELECT deleted_at FROM documents WHERE collection_id = ? AND content_fingerprint = ?` before the upsert, inside the same transaction. If it returns a row with non-null `deleted_at`, we know this is a resurrection.

Pick whichever pattern is idiomatic for the rest of the codebase. Don't over-engineer — a bool `was_resurrected` is enough.

### (2) Emit a warning when a resurrection happens

**File:** `src/pipeline/services.py`, around line 267.

When `store_document` reports `was_resurrected=True`, append a warning to the response:

```python
warnings.append(
    "This document was previously soft-deleted and has been resurrected "
    "by re-ingest. Its deletion_scheduled_at has been cleared."
)
```

This matters for agent visibility — without it, a re-ingest over a soft-deleted row looks identical to a fresh write, and the agent has no signal that the row's history includes a delete.

### (3) Add `?purge=true` to collection DELETE

**File:** `src/pipeline/api/routes.py`, around line 820+ (the `DELETE /api/collections/{name}` handler — grep for `soft_delete_collection`).

Add a query parameter:

```python
@router.delete("/api/collections/{collection_name}")
async def delete_collection(
    collection_name: str,
    purge: bool = Query(False, description="Hard-delete immediately instead of soft-delete."),
    api_key: APIKey | None = Depends(check_api_key),
):
    if purge:
        # Soft-delete first (to mark rows), then purge immediately.
        marked = _svc._dedup_store.soft_delete_collection(collection_name)
        purged = _svc._dedup_store.purge_deleted(older_than_hours=0)
        return {
            "collection": collection_name,
            "documents_purged": purged,
            "message": f"Hard-deleted {purged} document(s). Not recoverable.",
        }
    # existing soft-delete path unchanged
```

**Also update `PgDedupStore.purge_deleted`** (`src/pipeline/dedup.py` ~line 567) so `older_than_hours=0` actually purges everything with `deleted_at IS NOT NULL`. Check the current WHERE clause — if it's `deletion_scheduled_at < now() - interval '%s hours' % ...`, passing 0 should work already, but verify against a test.

This flag is what Denson will use to clear world-bank-ree before the Phase 8 re-run. Safe default (unchanged behavior), opt-in destruction.

### (4) Integration test — `tests/test_dedup_resurrection.py` (new file)

Write a pytest integration test that hits a real Pg (use the existing fixture pattern — `tests/conftest.py` should already set up a test DB). The test must match `probe_resurrection` step-for-step:

```python
def test_re_ingest_after_soft_delete_resurrects_row(pg_dedup_store, pg_vector_store):
    """Regression test for the Phase 8 ghost-write bug."""
    collection = "test_resurrection"
    content = b"resurrection test content"
    doc = _make_stored_doc(collection, content)

    # Round 1: insert
    pg_dedup_store.store_document(doc)
    fp = doc.content_fingerprint
    found = pg_dedup_store.find_by_fingerprint(collection, fp)
    assert found is not None and found.document_id == doc.document_id

    # Soft-delete the collection
    marked = pg_dedup_store.soft_delete_collection(collection)
    assert marked == 1
    assert pg_dedup_store.find_by_fingerprint(collection, fp) is None
    assert pg_dedup_store.find_by_fingerprint(collection, fp, include_deleted=True) is not None

    # Round 2: re-ingest identical content
    doc2 = _make_stored_doc(collection, content)   # same fingerprint
    pg_dedup_store.store_document(doc2)

    # Must be visible again
    found2 = pg_dedup_store.find_by_fingerprint(collection, fp)
    assert found2 is not None, (
        "Re-ingest after soft-delete must resurrect the row (Phase 8 regression)."
    )
    # Must be the same SQL row (same UUID)
    assert found2.document_id == doc.document_id
```

Also add a narrower unit-style test that just pokes `store_document` twice with a soft-delete in between and asserts `deleted_at IS NULL` on the final row via a direct `SELECT deleted_at FROM documents WHERE id = ...`.

### (5) Integration test — `tests/test_api_delete_collection.py` (new or existing)

If there's already a test file for the collections routes, add to it; otherwise create one. Cover:

- `DELETE /api/collections/{name}` with no query param → soft-delete (existing behavior, returns `documents_marked`)
- `DELETE /api/collections/{name}?purge=true` → hard-delete, returns `documents_purged`, row is gone from `include_deleted=True` list
- Re-ingest after `?purge=true` creates a genuinely new row (different UUID)

---

## Verification steps (run these yourself before handoff)

1. `pytest tests/test_dedup_resurrection.py` — must pass.
2. `pytest tests/test_api_delete_collection.py` — must pass.
3. `pytest` full suite — must pass. Report any pre-existing failures unchanged.
4. Spin the server locally (docker compose + `ariadne-core serve`) and run `probe_prod.py resurrection` against `http://localhost:8000`. Expected VERDICT: `[NOT REPRODUCED]`.

   (You'll need to flip `ARIADNE_URL` and `ARIADNE_API_KEY` in a temporary env — don't edit the workspace `.env`.)

---

## Hand-off to Bob

Produce `dave_and_bob_communication/BOB_SOFT_DELETE_UPSERT_FIX.md` with:

- List of changed files with one-line justification each.
- Diff of the SQL change called out verbatim (this is the load-bearing line Bob will scrutinize).
- Migration impact statement: **no schema change, no migration needed.** The `deleted_at` and `deletion_scheduled_at` columns already exist from migration 004. This is purely a UPDATE clause change.
- Test results from the `Verification` section.
- A one-paragraph note Bob can paste into the commit body explaining the Phase 8 connection, so future archaeology finds it.

Bob reviews and commits. Denson handles deploy + purge + Phase 8 re-run.

---

## DO NOT

- Touch anything related to the NUL-byte `psycopg.DataError` — that's a separate backlog item.
- Add a recovery path that un-deletes the existing 2026-04-16 rows. Denson wants a clean re-ingest, not a resurrection of stale data. After this fix lands and deploys, the plan is:
  1. `DELETE /api/collections/world-bank-ree?purge=true` (gone for good)
  2. Re-run `DAVE_PHASE_8_REINGEST.md` against the clean collection
- Change the default `DELETE /api/collections/<name>` behavior. The 48-hour grace window stays; `?purge=true` is opt-in.
- Write documentation beyond the BOB handoff file. SPEC.md and user-facing docs are a separate pass.
