# DAVE — Query API Pass 4: denormalize `source_reference`, push down all filters, consolidate migrations

**Pass 3 shipped** (client + skill caught up to the Pass 2 server surface).
Pass 4 is the architectural cleanup: denormalize `source_reference` onto
the `documents` table, push all three post-query filters into SQL, and
consolidate the migrations folder into a clean baseline. There is no
prod data to preserve — Bob will wipe and redeploy.

This is deliberately a bigger pass than usual. Components interlock
(can't test push-down without the new schema; can't test source_reference
maintenance without the column). Do them in the order below and don't
skip ahead.

**Scope is STRICTLY server-side.** Client library and skill docs are
already correct against the target shape — they need no change this
pass. Do not touch `client/` or `skills/`.

---

## Why this pass exists

1. **Correctness:** pagination is broken today under `tag`,
   `has_warnings`, or `has_source_reference`. `limit=20 offset=20` under
   `has_warnings=True` returns "whatever warnings-laden docs happen to
   be in the raw rows 21-40," not "the second page of warnings-laden
   docs." After this pass, all three filters live in the SQL `WHERE`
   and pagination works.

2. **Performance:** `_has_source_reference` is an N+1 per row,
   re-fetching the interaction log for every document on the page to
   reconstruct a value that could just live on `documents`. Denormalize
   once, read cheaply forever.

3. **Schema hygiene:** migrations 001-005 are a history of patches —
   002 renames a column to what it should have been in 001; 005 adds a
   column that should have been there from day one. Since we're wiping
   anyway, consolidate into a single fresh `001_initial.sql` that
   represents the schema we'd write today.

4. **Dead columns:** `documents.markdown_path` and `documents.pages`
   have zero readers and zero writers in `src/`. Drop.

---

## Pre-flight

```
cd ariadne-core
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Expected: `HEAD == origin/main`, pointing at `01489e1` (Pass 3) or a
descendant. Nothing dirty.

Also confirm Pass 3 tests still green locally before you touch anything:

```
pytest client/tests/ -v
pytest tests/ -v -k "not slow" -q
```

If anything is red before Pass 4 starts, **stop and report** — Pass 4
would mask the regression.

---

## Step 1 — Consolidate migrations 001-005 into a new `001_initial.sql`

File: `migrations/001_initial.sql` (overwrite).

The consolidated schema must encode:

- Everything from the current `001_initial.sql` **minus**:
  - `documents.pages` (dead — zero readers/writers in `src/`, extractor
    always sets it to None)
  - `documents.markdown_path` (dead — only appears in migration + one
    archived architecture doc)
- Migration 002's work already done inline:
  - `document_interactions.agent_notes TEXT` column present
  - `document_interactions.agent_metadata` column named correctly
    (**not** `metadata`)
- Migration 003's `search_log` table inlined
- Migration 004's soft-delete columns (`deleted_at`,
  `deletion_scheduled_at`) present on `documents` (already are in 001,
  verify)
- Migration 005's `warnings TEXT[] NOT NULL DEFAULT '{}'` on documents
  present
- **New for Pass 4:**
  - `documents.source_reference TEXT` (nullable) — denormalized latest
    value from `document_interactions.agent_metadata.source_reference`.
  - Partial index:
    ```sql
    CREATE INDEX idx_documents_source_reference
        ON documents (source_reference)
        WHERE source_reference IS NOT NULL
          AND source_reference <> ''
          AND source_reference <> 'unknown';
    ```
  - GIN index on `documents.tags`:
    ```sql
    CREATE INDEX idx_documents_tags ON documents USING GIN (tags);
    ```
  - GIN index on `documents.warnings`:
    ```sql
    CREATE INDEX idx_documents_warnings ON documents USING GIN (warnings);
    ```
  - (The GIN indexes are near-free at the current corpus size and
    future-proof scale without changing semantics.)

Keep `documents.metadata JSONB` as-is — it's the per-document merged
agent_metadata written by PATCH. Not in scope to rework.

Keep `document_interactions.agent_metadata` as the canonical
interaction-level metadata column.

Keep all chunk, job, api_key, and collection tables as they are in
current `001_initial.sql`. No changes there.

Top-of-file comment should read approximately:

```sql
-- Ariadne Core — Initial Database Schema
-- Requires: PostgreSQL 16+ with pgvector extension
--
-- This file is the single source of truth for a fresh deploy. It
-- folds together what was historically 001-005 plus the Pass 4
-- source_reference denormalization and pushdown-index work. Prior
-- migration files (002-005) have been removed — this is the schema
-- we would write today. On an empty database the BL-25 runner
-- applies this file exactly once and records version
-- '001_initial.sql' in schema_migrations.
```

---

## Step 2 — Delete the now-redundant migration files

```
git rm migrations/002_add_agent_notes.sql
git rm migrations/003_search_log.sql
git rm migrations/004_soft_delete.sql
git rm migrations/005_warnings_column.sql
```

After this the `migrations/` folder contains exactly one file:
`001_initial.sql`.

---

## Step 3 — Local Pg fresh-volume test

This pass is the one that proves the consolidated schema actually
creates the state the app expects. Before writing any Python:

```
docker compose down -v
docker compose up -d
# wait for health
ariadne-core serve &
# check it comes up without schema errors
curl -s http://localhost:8000/api/health
```

Expected: server starts clean, `/api/health` returns OK. No "column
does not exist" or "relation does not exist" errors in logs.

If anything errors here, the consolidated 001 is missing something.
Fix before proceeding.

Kill the local server after the check.

---

## Step 4 — `dedup.py` write-path maintenance for `source_reference`

File: `src/pipeline/dedup.py`.

### 4a. `PgDedupStore.record_interaction`

Currently (line ~272-309) INSERTs into `document_interactions`. After
the INSERT, if `interaction.agent_metadata` contains a
`source_reference` key with a non-None value, issue a second statement
in the same transaction:

```python
src_ref = None
if interaction.agent_metadata and isinstance(
    interaction.agent_metadata, dict
):
    val = interaction.agent_metadata.get("source_reference")
    if isinstance(val, str) and val.strip():
        src_ref = val.strip()

if src_ref is not None:
    cur.execute(
        """
        UPDATE documents
        SET source_reference = %(src_ref)s,
            updated_at = now()
        WHERE id = %(doc_id)s::uuid
        """,
        {"src_ref": src_ref, "doc_id": interaction.document_id},
    )
```

Latest-wins semantics — every new interaction with a
`source_reference` overwrites the column. That matches the existing
`_has_source_reference` helper's "latest interaction" behavior.

Note: we store the raw string including `"unknown"`. The partial
index excludes `"unknown"` so those rows are effectively "no
provenance" for filter purposes, but the value is preserved for
display / audit.

### 4b. `PgDedupStore.update_document_metadata`

Currently (line ~634-733) merges `agent_metadata` into
`documents.metadata`. After the UPDATE, if the incoming `agent_metadata`
dict has a non-empty `source_reference` string, propagate the same way:

```python
if agent_metadata and isinstance(agent_metadata, dict):
    val = agent_metadata.get("source_reference")
    if isinstance(val, str) and val.strip():
        cur.execute(
            """
            UPDATE documents
            SET source_reference = %(src_ref)s
            WHERE id = %(doc_id)s::uuid
            """,
            {"src_ref": val.strip(), "doc_id": document_id},
        )
```

Place this right before `conn.commit()` at line ~724. Same transaction.

### 4c. `InMemoryDedupStore` parity

The in-memory backend currently has no source_reference concept. Add:

- An instance dict `self._doc_source_ref: dict[str, str] = {}` in
  `__init__`.
- In `record_interaction`, after recording the interaction: if
  `interaction.agent_metadata` has a non-empty `source_reference`
  string, set `self._doc_source_ref[interaction.document_id] = val`.
- In `update_document_metadata`, same propagation.
- Expose via a method `get_source_reference(document_id) -> str | None`
  returning the dict value. The list_documents filter will use this.

Alternatively, if it's cleaner, add a `source_reference` attribute on
the in-memory StoredDocument copies. Either works — pick the one that
makes Step 6 cleaner.

---

## Step 5 — `PgDedupStore.list_documents` and aggregate push-down

File: `src/pipeline/dedup.py` (the `PgDedupStore.list_documents` method,
line ~423).

### 5a. New signature

Add three parameters. Keep existing order; append after `include_deleted`:

```python
def list_documents(
    self,
    collection: str | None = None,
    file_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_deleted: bool = False,
    *,
    tag: str | None = None,
    has_warnings: bool | None = None,
    has_source_reference: bool | None = None,
) -> tuple[list[StoredDocument], int]:
```

The three new params are keyword-only (note the `*,`) to prevent
positional confusion with existing callers.

### 5b. WHERE-clause additions

Build on the existing `where_clauses` list. Add after the
`include_deleted` block:

```python
if tag is not None:
    where_clauses.append("d.tags @> ARRAY[%(tag)s]::text[]")
    params["tag"] = tag

if has_warnings is True:
    where_clauses.append("cardinality(d.warnings) > 0")
elif has_warnings is False:
    where_clauses.append("cardinality(d.warnings) = 0")

if has_source_reference is True:
    where_clauses.append(
        "d.source_reference IS NOT NULL "
        "AND d.source_reference <> '' "
        "AND d.source_reference <> 'unknown'"
    )
elif has_source_reference is False:
    where_clauses.append(
        "(d.source_reference IS NULL "
        "OR d.source_reference = '' "
        "OR d.source_reference = 'unknown')"
    )
```

The `None` case for each filter means "don't add a clause" — i.e.
"don't filter on this." That matches the HTTP semantics the route
already enforces.

The same `COUNT(*)` now counts post-filter, so the route's
`total_is_exact = False` dance (routes.py:685-692) becomes obsolete.

### 5c. InMemoryDedupStore parity

Give `InMemoryDedupStore.list_documents` the same signature and the
same semantics. Currently the in-memory filter logic lives in the
route. **Move it into the store.** After this pass, the route calls
`self._dedup_store.list_documents(...)` with all filters including
the three new ones, and both backends handle them symmetrically.

---

## Step 6 — `routes.py` simplification

File: `src/pipeline/api/routes.py`.

### 6a. `list_documents` endpoint

Current flow: calls `self._dedup_store.list_documents(...)` for the
Pg path with ONLY `collection`, `file_type`, `limit`, `offset`,
`include_deleted`, then does Python-side post-query filtering on
`tag`, `has_warnings`, `has_source_reference`, then rewrites `total`
and flips `total_exact`.

New flow: call the store with **all** filters, and trust the result.
Delete the Python-side filter block (lines ~672-692). Delete the
`total_exact` override — it stays `True` always.

The `else` branch (InMemoryDedupStore path with hand-rolled filtering
in the route body) also deletes — now delegated to the store per Step
5c.

Net result: the list_documents endpoint body shrinks significantly.
The `_build_row` function stays as-is (it composes row shape, not
filters).

### 6b. `aggregate_documents` endpoint

Same treatment (routes.py line ~271-389). Currently calls
`list_documents(..., limit=100000)` to pull the whole corpus, then
filters in Python, then counts.

New version: call `list_documents` with the filters built in. The
returned slice is already filtered. Just bucket and return.

Consider lowering the hard-coded `limit=100000` — with SQL filters
it's no longer a "pull everything and filter" hack, but you still
need to iterate for bucketing. Keep it as-is for now; flag in
`DAVE_DONE.md` that a proper `SELECT group, COUNT(*) ... GROUP BY`
query would replace this entirely, but don't do it this pass.

### 6c. Delete `_has_source_reference` helper

routes.py:563. Fully dead after the push-down. Delete it and any
remaining call sites.

### 6d. `_LIST_DOCUMENTS_PARAMS` and `_AGGREGATE_PARAMS`

No change — these are derived from `_FILTER_REGISTRY` which already
enumerates the three filter names. The validator still works.

---

## Step 7 — SPEC.md spot-check

Search SPEC.md for any text claiming `total_is_exact` may be False
under filters. If found, remove that caveat — it's no longer true.

One likely location: the Query API section (wherever Pass 2 added it).
If you find it, the fix is deletion, not rewording.

Do **not** rewrite any other SPEC section. If nothing matches, move
on.

---

## Step 8 — Tests

File: `tests/test_routes_list_documents.py` and
`tests/test_routes_aggregate_and_schema.py` (existing — update in
place) plus `tests/test_dedup_source_reference.py` (new).

### 8a. New tests in `test_dedup_source_reference.py`

1. `test_source_reference_written_by_record_interaction` —
   `pg_dedup_store.record_interaction(...)` with
   `agent_metadata={"source_reference": "doi:10.1234/abc"}` → direct
   DB query confirms `documents.source_reference = 'doi:10.1234/abc'`.

2. `test_source_reference_updated_on_subsequent_interaction` —
   latest-wins: second `record_interaction` with a different
   `source_reference` overwrites the first.

3. `test_source_reference_unknown_preserved_but_not_matched` — set
   `source_reference = "unknown"` via record_interaction. DB row has
   the value. Then
   `list_documents(has_source_reference=True)` does NOT include it;
   `has_source_reference=False` DOES include it.

4. `test_source_reference_written_by_update_document_metadata` — PATCH
   a document with
   `agent_metadata={"source_reference": "https://example.com"}` and
   confirm the column was updated.

### 8b. Existing test updates

In `test_routes_list_documents.py`: wherever a test currently asserts
`total_is_exact is False` under a post-query filter, flip it to
`True`. Also add at least one new test pinning that
pagination works under filter: insert 30 docs, mark 10 as
`has_warnings=True`, call with `limit=5, offset=5, has_warnings=True`,
assert 5 rows back all with warnings and
`total_count == 10, total_is_exact == True`.

In `test_routes_aggregate_and_schema.py`: wherever aggregate
currently has `total_is_exact` assertions tied to the old behavior,
fix them to reflect the new reality (always exact).

### 8c. Full suite

```
docker compose down -v && docker compose up -d
# wait for health
pytest tests/ -v -q
pytest client/tests/ -v -q
```

All existing tests must still pass. Any test that breaks because of
the new pagination correctness (e.g. a test that happened to rely on
the broken page behavior) is a test bug and should be fixed in place.

---

## Step 9 — DAVE_DONE.md

Overwrite `dave_and_bob_communication/DAVE_DONE.md` with:

1. **SHA pushed.** The one commit for Pass 4.
2. **Files touched.** All five migration changes, dedup.py, routes.py,
   tests. Bullet list.
3. **Consolidated 001 schema.** Paste the final
   `migrations/001_initial.sql` contents as a fenced block. (Bob
   needs to eyeball it before wiping prod.)
4. **Migration delete list.** Confirm 002-005 are gone:
   `git ls-files migrations/` output.
5. **Local fresh-volume proof.** Paste: `docker compose down -v && up
   -d`, server start, `/api/health` 200, a quick `list_documents`
   call that returns `total_is_exact: true`.
6. **Test output.** Final summary of `pytest tests/` and `pytest
   client/tests/`.
7. **Bob handoff.** Explicit instruction:

   > This pass requires a destructive prod action. DO NOT DEPLOY
   > UNTIL YOU WIPE THE RAILWAY POSTGRES SCHEMA. The consolidated
   > 001 will fail against the existing prod schema because columns
   > were renamed/dropped. The intended procedure is:
   >
   > 1. `railway link` (confirm correct project / env)
   > 2. `railway run psql "$DATABASE_URL" -c "DROP SCHEMA public
   >    CASCADE; CREATE SCHEMA public; CREATE EXTENSION IF NOT EXISTS
   >    vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;"`
   > 3. Trigger a manual redeploy in Railway (BL-9 — auto-deploy is
   >    unreliable)
   > 4. Watch logs: confirm runner sees empty schema_migrations,
   >    applies 001, no errors
   > 5. Smoke per the usual list
   >
   > If you skip the wipe, the app will hit errors on first write
   > because the consolidated 001 already dropped the `pages` /
   > `markdown_path` columns and any live row would still have them.

8. **Known deferred.** Anything spotted but not done:
   - Native SQL GROUP BY for aggregate (still does fetch-and-count)
   - `documents.metadata` column usage review (written by PATCH,
     not read by get_document — separate audit thread)
   - Batch-fetch of interactions to eliminate the N+1 on
     `include=agent_metadata` / `include=last_interaction`
   - CLI parity with aggregate/schema (from Pass 3 deferred list —
     still deferred)
   - SQL schema for document_interactions has four indexes; some
     may be redundant. Not audited.

---

## Step 10 — Commit + push

One commit. Suggested message:

```
Query API Pass 4: denormalize source_reference, push down filters,
consolidate migrations

- Fold migrations 001-005 into a single clean 001_initial.sql.
  Drops dead columns (documents.markdown_path, documents.pages).
  Adds documents.source_reference + partial index. Adds GIN indexes
  on documents.tags and documents.warnings.
- PgDedupStore.record_interaction and update_document_metadata now
  propagate agent_metadata.source_reference to documents.source_
  reference (latest-wins).
- PgDedupStore.list_documents accepts tag, has_warnings,
  has_source_reference as keyword-only filters, pushed into SQL
  WHERE. COUNT(*) is now always exact under any filter combination.
- InMemoryDedupStore gains symmetric filtering so route code stops
  branching on backend.
- routes.py: delete post-query filter block, delete
  _has_source_reference helper, stop conditionally flipping
  total_is_exact. Aggregate reuses the same filter path.

Breaks schema compatibility — requires DROP SCHEMA public CASCADE
on the live database before redeploy. No production data preserved
(there is none).
```

Push:

```
git push origin main
```

**STOP after push.** Do not wipe or redeploy Railway — that's Bob's
job. He needs to review the consolidated schema visually before
destroying live data, and he handles the wipe-and-redeploy sequence
as one atomic verification step.

---

## Scope fence (strict)

Allowed:

- ✅ `migrations/001_initial.sql` (overwrite)
- ✅ Delete `migrations/002*.sql` through `migrations/005*.sql`
- ✅ `src/pipeline/dedup.py`
- ✅ `src/pipeline/api/routes.py`
- ✅ `tests/test_routes_list_documents.py`
- ✅ `tests/test_routes_aggregate_and_schema.py`
- ✅ `tests/test_dedup_source_reference.py` (new)
- ✅ `SPEC.md` — one narrow deletion if the Pass 2 caveat text exists
- ✅ `dave_and_bob_communication/DAVE_DONE.md`

Forbidden (flag in DAVE_DONE if you want to):

- ❌ Anything in `client/`
- ❌ Anything in `skills/`
- ❌ `src/pipeline/cli.py`
- ❌ `src/pipeline/services.py` (the provenance warning there reads
  `agent_metadata["source_reference"]` on the inbound request — not
  on the stored column — and still works unchanged)
- ❌ `src/pipeline/schema.py` (the `ensure_schema` helper — untouched
  this pass)
- ❌ `src/pipeline/stores.py` (the BL-25 runner — untouched this pass)
- ❌ Any docs/roadmap/ file
- ❌ Any file under `.claude-plugin/`

If the scope fence doesn't cover a file you want to change, **flag
it in DAVE_DONE.md and leave it.** Scope discipline matters.
