# BOB_DONE — Query API Pass 4 review + wipe + redeploy + smoke

**Status:** REVIEWED + WIPED + REDEPLOYED + SMOKED (PASS)
**Reviewed commit:** `4d7ddb7` — *Query API Pass 4: denormalize source_reference, push down filters, consolidate migrations* (on `main`)
**Parent:** `01489e1` (Pass 3 client + skill catch-up)
**Live server:** `https://ariadne-core-production-579a.up.railway.app`
**Successful Pass 4 deployment id:** `6d9b7b9b…` (commitHash `4d7ddb77…`)

---

## 1. Review gate — diff vs. Dave's spec fences

Scope fence: nothing in `client/`, `skills/`, `src/pipeline/cli.py`, `src/pipeline/services.py`, `src/pipeline/schema.py`, `src/pipeline/stores.py`, `docs/roadmap/`, or `.claude-plugin/`. Verified via `git show --stat 4d7ddb7 -- <each path>` → empty. ✅

| Check | Result |
|---|---|
| `migrations/001_initial.sql` overwritten as the single source-of-truth file; drops dead `documents.pages` and `documents.markdown_path`; adds `documents.warnings TEXT[] NOT NULL DEFAULT '{}'`, `documents.source_reference TEXT`; adds partial index `idx_documents_source_reference` with predicate `IS NOT NULL AND <> '' AND <> 'unknown'`; adds GIN indexes on `tags` and `warnings`; folds in `document_interactions.agent_notes`/`agent_metadata` (prior 002), the `search_log` table (prior 003), and the soft-delete columns already present in base (prior 004) | ✅ |
| `migrations/002_add_agent_notes.sql`, `003_search_log.sql`, `004_soft_delete.sql`, `005_warnings_column.sql` deleted — only `001_initial.sql` tracked under `migrations/` | ✅ `git ls-files migrations/ → 001_initial.sql` |
| `src/pipeline/dedup.py::_extract_source_reference` helper — handles `None` / non-dict / non-string / whitespace-only correctly (returns `None`), preserves trimmed values including the literal `"unknown"` | ✅ `dedup.py:32-46` |
| `PgDedupStore.record_interaction` propagates `agent_metadata.source_reference` into `documents.source_reference` via an `UPDATE` that also bumps `updated_at` (latest-wins) | ✅ `dedup.py:340-355` |
| `PgDedupStore.update_document_metadata` does the symmetric propagation on the PATCH path | ✅ `dedup.py:801-812` |
| `PgDedupStore.list_documents` accepts `tag`, `has_warnings`, `has_source_reference` as keyword-only filters pushed into SQL `WHERE`. Tag uses `d.tags @> ARRAY[%(tag)s]::text[]` (GIN-friendly). `has_warnings` uses `cardinality(d.warnings) > 0` / `= 0`. `has_source_reference` predicate matches the partial-index predicate verbatim (so the index is actually used). `COUNT(*)` is now always exact | ✅ `dedup.py:478-520` |
| `InMemoryDedupStore` gains symmetric `list_documents` + `get_source_reference` + `_doc_source_ref` map so route code stops branching on backend; stable sort by `created_at DESC` mirrors Pg ordering | ✅ `dedup.py:860-960` |
| `DedupStore` protocol extended with `list_documents(...)` signature | ✅ `dedup.py:148-160` |
| `src/pipeline/api/routes.py` — `_has_source_reference` N+1 helper DELETED; the `PgDedupStore`-vs-`InMemoryDedupStore` isinstance branch in both `list_documents` and `aggregate_documents` DELETED; the post-query filter block DELETED; `total_is_exact` is unconditionally `True`. Both handlers call a single `_dedup_store.list_documents(...)` with all filters passed through | ✅ `routes.py:286-320, 558-621` |
| Filter-registry description for `has_source_reference` rewritten from "latest interaction's agent_metadata" to "document has a non-empty 'source_reference' value (latest-wins from agent_metadata)" | ✅ `routes.py:481-486` |
| `SPEC.md` — "`total_count` semantics" Pass-2 caveat paragraph removed | ✅ (single line delete) |
| `tests/test_routes_list_documents.py` — `total_is_exact` assertion under tag filter flipped to `True`; new `test_list_documents_pagination_under_filter` (30 docs, 10 with warnings, `limit=5 offset=5 has_warnings=true` ⇒ 5 rows, `total_count==10`, `total_is_exact==True`) | ✅ |
| New `tests/test_dedup_source_reference.py` — 4 Pg-integration tests covering record-interaction write, latest-wins overwrite, `"unknown"` sentinel preserved-but-excluded, and PATCH write path | ✅ |

---

## 2. Live destructive deploy — actual sequence, not the planned one

The spec'd command — `railway run psql "$DATABASE_URL" -c "…"` — does not work in this project: the `ariadne-core` service only exposes `DATABASE_URL_PRIVATE` pointing at `pgvector.railway.internal`, and the `pgvector` service has no public TCP proxy. `railway run` executes locally, so the injected URL is unreachable. `railway connect pgvector` rejects the service with *"No supported database found in service"* (Railway CLI's connect only recognizes a short name-allowlist and `pgvector` isn't on it). Working alternative, used here:

```
railway ssh --service pgvector "psql -U postgres -d railway -v ON_ERROR_STOP=1 --pset pager=off \
    -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public; \
        CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;'"
```

One argv item so Railway's SSH transport doesn't strip the inner quoting (it space-joins argv when forwarding). Output: `NOTICE: drop cascades to 10 other objects; DROP SCHEMA; CREATE SCHEMA; CREATE EXTENSION; CREATE EXTENSION`. The 10 dropped objects include the two pgvector/pgcrypto extensions plus 8 tables (`collections`, `documents`, `document_interactions`, `chunks`, `jobs`, `api_keys`, `search_log`, `schema_migrations`).

**First-attempt misstep, for the record:** I ran `railway redeploy --service ariadne-core --yes` immediately after the wipe, intending it to pick up Pass 4 from `origin/main`. `redeploy` instead rebuilt the *latest* deployment — which was still pinned at Pass 3 commit `01489e1` because Railway's GitHub auto-deploy had not fired for Pass 4 (consistent with Dave's BL-9 note that auto-deploy is unreliable). The Pass 3 image booted and its multi-file runner applied migrations 001 through 005, re-introducing Pass 3's schema on top of the wiped DB. A subsequent `railway up` from a clean `git worktree` at `4d7ddb7` did register as a Pass 4 deployment, but it crashed at first query: Pass 4's runner sees the version string `"001_initial.sql"` already present in `schema_migrations` (recorded by Pass 3's first migration) and skips applying — so the running Pass 4 code hit a Pass 3 schema missing `source_reference`, failing on the first query that touched the column.

**Recovery:** re-ran the same `DROP SCHEMA public CASCADE …` command, then `railway redeploy --service ariadne-core --yes` — because the latest deployment was now the Pass 4 one (`e9fa47e7…`), redeploy rebuilt Pass 4 code from Pass 4 commit, which applied its single consolidated `001_initial.sql` cleanly. Successful deployment id `6d9b7b9b…`, status `SUCCESS`.

**Redeploy-semantics gotcha for whoever writes the next destructive-deploy spec:** `railway redeploy` replays the *latest* deployment's commit, not `origin/main`'s HEAD. If the last auto-deploy is stale, `redeploy` is a no-op relative to what you just merged; you need `railway up` from a clean tree at HEAD to seed the latest deployment with the target commit before `redeploy` does anything useful. The spec's `railway run psql` form should also be rewritten to the `railway ssh --service pgvector "…"` single-argv form for this project.

---

## 3. Post-redeploy DB proof — clean single-migration schema

```
$ railway ssh --service pgvector "psql -U postgres -d railway --pset pager=off \
    -c 'SELECT version FROM schema_migrations; \
        SELECT column_name FROM information_schema.columns \
        WHERE table_name=''documents'' \
          AND column_name IN (''source_reference'',''pages'',''markdown_path'',''warnings'') \
        ORDER BY column_name;'"

     version
-----------------
 001_initial.sql
(1 row)

   column_name
------------------
 source_reference
 warnings
(2 rows)
```

One migration recorded. `documents.source_reference` and `documents.warnings` present, `documents.pages` and `documents.markdown_path` gone — exactly the Pass 4 shape. ✅

Container boot log (relevant lines):
```
2026-04-18 11:05:36 ariadne INFO Starting REST API on :8080
2026-04-18 11:05:37 ariadne.stores INFO Initializing Postgres stores (backend=pgvector)
2026-04-18 11:05:37 ariadne.stores INFO Creating connection pool for postgres://postgres:***@pgvector.railway.internal:5432/railway
2026-04-18 11:05:37 ariadne.schema INFO Schema OK: chunks table exists with vector(1536)
2026-04-18 11:05:37 ariadne.app INFO Stores initialized (backend=pgvector)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080
```

No migration-application log line surfaced in the tail (present under Pass 3 boots that applied 5 files — silent when there is nothing new to apply is plausible on re-boot, but on a wiped DB you would expect the line and I could not retrieve it from the streaming tail). The DB state is authoritative either way — single `001_initial.sql` row in `schema_migrations`, new columns present.

---

## 4. Smoke — four checks per the hand-off

Script: `scripts/_smoke_pass4.py` (uncommitted, follows the `_`-prefixed scratch convention in `scripts/`). Runs against the live server with env from `../.env`.

### 1. `/api/health` → 200

```
[1] /api/health HTTP 200 -> {"status":"healthy","version":"0.1.0","engine":"markitdown","embedding_enabled":true}
```

### 2. `client.schema()` → Pass 2 surface

```
[2] schema.filters:     ['collection', 'file_type', 'has_source_reference',
                         'has_warnings', 'include_deleted', 'tag']
    schema.includes:    ['agent_metadata', 'last_interaction', 'markdown', 'tags']
    schema.aggregatable: ['collection', 'file_type', 'tags']
    schema.caps:        {'list_default': 500, 'list_with_markdown': 50,
                         'aggregate_buckets_max': 1000}
    PASS (Pass 2 filter surface)
```

Six filters including the three Pass 2 ones, four includes, three aggregatable fields, `caps.list_default == 500`. ✅

### 3. `client.list_documents(has_warnings=True)` → `total_is_exact: True`

```
[3] has_warnings=True total_count=1 total_is_exact=True rows=1
    PASS (total_is_exact=True under filter)
```

The Pass 4 pin. **`total_is_exact` is structurally always `True` now**, even with a filter active — compare to Pass 3 where filters flipped it to `False` and the route post-filtered in Python. ✅

(The `total_count=1` row is a leftover from a fresh scratch ingest during iteration — irrelevant to this assertion, but noted for transparency.)

### 4. Ingest doc with `source_reference`, confirm `has_source_reference=True` finds it

```
[4a] ingested document_id=be5502d1-… collection=pass4-smoke-1776510397
[4b] has_source_reference=True in scratch collection: total_count=1 total_is_exact=True
     PASS (source_reference pushdown hits the new doc)
[4c] has_source_reference=False in scratch collection: total_count=0 (expect 0)
     PASS (negative filter excludes the doc)
```

Positive filter finds the new doc, negative filter excludes it. Both report `total_is_exact=True`. The round-trip proves `record_interaction` wrote the `source_reference` column during ingest, and `list_documents` now reads it directly from the column (no N+1 interaction trawl). ✅

---

## 5. Observations / flags for the next author

1. **Destructive-deploy playbook needs the sequence tightened.** `wipe → up → redeploy-if-needed`, not `wipe → redeploy`. Redeploying without first seeding the latest deployment with the target commit burns an extra round-trip (mine cost: one extra wipe + one extra deploy). Calling out explicitly because Dave's §7 text is ambiguous on this — it says "Trigger a manual redeploy in Railway" without differentiating the Railway-dashboard *Deploy from latest commit* button (which targets `origin/main` HEAD) from the CLI `railway redeploy` (which replays the latest deployment's commit). The CLI path only works if the latest deployment is already at HEAD.
2. **`railway run psql "$DATABASE_URL" …` form is unreachable in this project.** The pgvector service has no public TCP proxy, and `DATABASE_URL_PRIVATE` resolves to an internal-only hostname. The `railway ssh --service pgvector "psql …"` single-argv form is the portable path. Worth replacing in any future destructive-deploy spec.
3. **Migration-runner log line for a clean wipe did not surface in the log tail.** The DB state is correct (one row in `schema_migrations`, Pass 4 columns present) so the migration unambiguously ran — but the "Applying migration 001_initial.sql" line that was visible under Pass 3 boots was not in my tail window. Might be a log-ordering / line-buffering quirk on Railway's side, might be a regression in how the Pass 4 runner logs. Non-blocking; worth a quick pass through `dedup.py`'s migration runner to confirm the log call is still there.
4. **Aggregate still uses the `limit=100000` fetch-and-count hack.** Dave's Pass 4 known-deferred §8 calls this out — `aggregate_documents` now correctly pushes filters into `list_documents`, but the bucketing is still Python-side. A native SQL `GROUP BY` lands the same data in one query. Performance is fine at 586 docs; flagged for whenever the corpus grows past a few thousand.
5. **The spec's stale example URL survives yet again.** Dave's hand-off correctly uses `ariadne-core-production-579a.up.railway.app`; the original Pass 2 spec's Step 0 example still points at `ariadne-core-production.up.railway.app` (no `-579a`), which 404s. Noted in my Pass 3 BOB_DONE too — still not fixed, presumably because the spec file hasn't been touched since.
6. **One failed deployment artifact.** Before the recovery redeploy, there is a `FAILED` Pass 4 deployment (`e9fa47e7…`) in the service's history. It has no deploy-phase logs (Railway never got past image publish / runtime init). Harmless; does not affect the current live deployment. Mention only for auditing the service's deployment list.

---

## 6. Net

Pass 4 is live on `ariadne-core-production-579a.up.railway.app` at commit `4d7ddb7`. DB schema is the clean single-file Pass 4 shape. All four smoke checks green. The Pass 4 pin — `total_is_exact: true` under any filter combination — verified against real data. The `source_reference` pushdown path end-to-end: ingest with `source=` → column written by `record_interaction` → `list_documents(has_source_reference=True)` finds it via the partial-index-backed SQL filter. Filter branch in `routes.py` gone, `_has_source_reference` N+1 helper gone, backend-isinstance branch gone. Scope fence clean. — Bob
