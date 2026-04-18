# Bob — Soft-delete / upsert ghost-write fix (review & commit)

Per `DAVE_SOFT_DELETE_UPSERT_FIX.md`. P0 blocker — this is the Phase 8
root cause. Code and tests are staged in the working tree. Nothing is
committed; please review the diffs, then commit + push.

---

## Changed files (6: 3 modified, 3 new)

| File | Why |
|---|---|
| `src/pipeline/dedup.py` | The load-bearing change: `PgDedupStore.store_document` now clears `deleted_at` / `deletion_scheduled_at` on ON CONFLICT and returns a `was_resurrected` bool. `purge_deleted(0)` now special-cases "purge everything soft-deleted" so it works across same-microsecond tick. Parallel `InMemoryDedupStore` changes so the two backends have symmetric contracts. |
| `src/pipeline/services.py` | Capture the new `was_resurrected` return and append a warning to the response so agents see when a re-ingest revived a deleted row. |
| `src/pipeline/api/routes.py` | Add `?purge=true` query param to `DELETE /api/collections/{name}` — hard-delete path for operator-initiated resets (Phase 8 re-run uses it). |
| `tests/conftest.py` *(new)* | Opt-in `pg_dedup_store` / `pg_pool` fixtures. Skip cleanly when Pg is unreachable; connect via `ARIADNE_TEST_DATABASE_URL` or the local docker-compose default otherwise. |
| `tests/test_dedup_resurrection.py` *(new)* | Regression test for the Phase 8 pathology — 3 InMemory tests (always run) + 3 Pg integration tests (skip without Pg). |
| `tests/test_api_delete_collection.py` *(new)* | Covers the route's default vs `?purge=true` behavior and the soft-delete → resurrection flow. TestClient + InMemory stores — no Pg needed. |

No files were modified outside the spec's scope.

---

## Load-bearing SQL change (read this carefully)

From `src/pipeline/dedup.py` → `PgDedupStore.store_document`:

```diff
                 ON CONFLICT (collection_id, content_fingerprint)
                     WHERE content_fingerprint IS NOT NULL
                 DO UPDATE SET
                     markdown = EXCLUDED.markdown,
                     source_file = EXCLUDED.source_file,
                     processing_chain = EXCLUDED.processing_chain,
                     processing_time_ms = EXCLUDED.processing_time_ms,
                     output_tokens_estimate = EXCLUDED.output_tokens_estimate,
                     token_savings_ratio = EXCLUDED.token_savings_ratio,
                     tags = EXCLUDED.tags,
+                    deleted_at = NULL,
+                    deletion_scheduled_at = NULL,
                     updated_at = now()
                 RETURNING id
```

Those two added lines are the actual bug fix. Everything else is
scaffolding.

### Why the pre-UPSERT SELECT is needed

After the UPDATE, `deleted_at` is always NULL, so we can't tell from
the RETURNING row whether it was a resurrection or a plain update. A
single cheap SELECT on the same connection/transaction captures the
prior state so the caller can surface a warning. Alternative
`xmax <> 0` + timing tricks were considered and rejected — they don't
distinguish resurrection from a normal force-re-ingest.

### Why `purge_deleted(0)` got special-cased

The pre-existing interval arithmetic was `deletion_scheduled_at < now() - interval '0'`, which reduces to `< now()`. When `soft_delete_collection` and `purge_deleted(0)` run microseconds apart on a
fast machine (test harness, or `?purge=true` handling both in one
request), the two `now()` values can land in the same microsecond and
the strict `<` returns zero rows. The new `older_than_hours <= 0` branch
uses `WHERE deleted_at IS NOT NULL`, which is the actual semantic
operators want from `?purge=true`.

---

## Migration impact

**No schema change. No migration needed.** `deleted_at` and
`deletion_scheduled_at` already exist from migration `004_soft_delete.sql`.
This is purely a change to the UPDATE clause and Python code paths.

---

## Verification results

### 1. `pytest tests/test_dedup_resurrection.py`

```
tests/test_dedup_resurrection.py::TestInMemoryResurrection::test_fresh_insert_returns_false PASSED
tests/test_dedup_resurrection.py::TestInMemoryResurrection::test_upsert_of_non_deleted_doc_returns_false PASSED
tests/test_dedup_resurrection.py::TestInMemoryResurrection::test_reingest_after_soft_delete_resurrects PASSED
tests/test_dedup_resurrection.py::TestPgResurrection::test_re_ingest_after_soft_delete_resurrects_row SKIPPED
tests/test_dedup_resurrection.py::TestPgResurrection::test_deleted_at_is_null_after_resurrection SKIPPED
tests/test_dedup_resurrection.py::TestPgResurrection::test_purge_deleted_with_zero_hours_clears_just_marked_rows SKIPPED
```

3 InMemory pass, 3 Pg skip (no local Postgres — see Caveats).

### 2. `pytest tests/test_api_delete_collection.py`

```
tests/test_api_delete_collection.py::TestDeleteCollection::test_default_is_soft_delete PASSED
tests/test_api_delete_collection.py::TestDeleteCollection::test_purge_true_hard_deletes PASSED
tests/test_api_delete_collection.py::TestDeleteCollection::test_reingest_after_purge_is_a_fresh_row_not_a_resurrection PASSED
tests/test_api_delete_collection.py::TestDeleteCollection::test_default_delete_leaves_ghost_that_resurrects_on_reingest PASSED
```

All 4 pass.

### 3. Full suite: `pytest tests/ -v`

```
======================= 185 passed, 3 skipped in 21.33s =======================
```

No regressions. Baseline before this change was 178 passed (per Dave's
last `DAVE_DONE.md` for `DAVE_EMBED_FAIL_GATE.md`); +7 new tests = 185.
The 3 skips are the Pg integration tests that need a live Postgres.

### 4. Live-server probe (`probe_prod.py resurrection`)

**Not run from this machine.** Docker Desktop's Linux engine isn't
available in this environment (`failed to connect to the docker API
at npipe:////./pipe/dockerDesktopLinuxEngine`), so I can't bring up
the local stack to probe. The pytest coverage above exercises the
same semantics:

- `test_deleted_at_is_null_after_resurrection` does a raw `SELECT
  deleted_at FROM documents WHERE ...` after round-2 ingest and
  asserts `NULL` — this is the SQL-level invariant that `probe_prod.py`
  observes indirectly via `GET /api/documents/<id>`.
- `test_reingest_after_purge_is_a_fresh_row_not_a_resurrection` covers
  the `?purge=true` operator flow end-to-end through the FastAPI
  router.

If you want the full `probe_prod.py resurrection` pass on your
machine, spin `docker compose up -d` + `ariadne-core serve` locally,
point `ARIADNE_URL=http://localhost:8000`, and run the probe. The
expected verdict is `[NOT REPRODUCED]`.

---

## Caveats

1. **Pg integration tests skip locally unless Postgres is reachable.**
   The spec said `tests/conftest.py should already set up a test DB`,
   but there was no conftest and no Pg fixture in the repo. I added
   a minimal one that tries `ARIADNE_TEST_DATABASE_URL` → falls back
   to the docker-compose default (`postgresql://app:local-dev-only@localhost:5432/pipeline`) → skips the test if neither works. On a
   machine with `docker compose up -d postgres` running, all 3 Pg
   tests should pass. Please run them before merging.

2. **Test namespacing and cleanup.** The `pg_dedup_store` fixture
   uses a unique collection per test and hard-purges it on teardown.
   Tests do NOT truncate tables, so they're safe to run against a
   shared dev DB.

3. **`store_document` return type changed.** `None` → `bool`. The
   only caller I could find is `services._process_single_document`
   (updated in this change). If there are other callers I missed
   (e.g. scripts or plugins outside `src/`), they may need an
   unpack. Grep recommends: `rg 'store_document\(' --type py -g '!tests/'`.

4. **Separate NUL-byte bug not touched.** Phase 8 also hit
   `psycopg.DataError: PostgreSQL text fields cannot contain NUL`
   on 16 files. Per the spec's DO NOT list, this fix doesn't address
   it — add a backlog item.

---

## Proposed commit message body (paste into `git commit`)

```
Fix ghost-write on re-ingest after soft-delete

PgDedupStore.store_document's ON CONFLICT clause updated content
columns but left deleted_at / deletion_scheduled_at intact. Re-ingesting
identical content into a previously soft-deleted collection produced
store_status="stored" responses with the prior UUID while the row stayed
invisible to every default query — the Phase 8 regression shape
(558 "stored" responses, 0 durable docs).

Changes:
- Clear deleted_at / deletion_scheduled_at in ON CONFLICT DO UPDATE.
- Return was_resurrected from store_document so services can surface a
  warning to agents when a re-ingest revived a deleted row.
- Add DELETE /api/collections/{name}?purge=true for operator-initiated
  hard resets (used to clean world-bank-ree before the Phase 8 re-run).
- Special-case purge_deleted(older_than_hours=0) so it purges every
  soft-deleted row regardless of same-microsecond timing.
- Integration tests against Pg (opt-in via ARIADNE_TEST_DATABASE_URL)
  plus parallel InMemory tests and FastAPI-router tests that don't
  require Postgres.

No schema migration required — deleted_at / deletion_scheduled_at
columns already exist from migration 004.
```

(Omit the `Co-Authored-By` line unless you want Claude attribution.)

---

## Denson's follow-up plan (not part of this commit)

Per the spec's post-merge sequence:

1. Deploy this commit.
2. `DELETE /api/collections/world-bank-ree?purge=true` — hard-clear the
   2026-04-16 poison.
3. Re-run `DAVE_PHASE_8_REINGEST.md` against the clean collection.
   Step 4 durability gate is now meaningful.

— Dave
