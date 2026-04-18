# DAVE_DONE — BL-22 migration runner wire-up + BL-25

Prod hotfix. BL-22's commit `2f15bb1` shipped `migrations/005_warnings_column.sql`
but missed the corresponding block in `_apply_migrations()`. Local tests still
passed because `docker-compose.yml` mounts `./migrations:/docker-entrypoint-initdb.d:ro`,
so Postgres applied 005 at container bootstrap; Railway (managed Pg, no
`initdb.d`) 500'd on `d.warnings` missing.

## Files edited

- `src/pipeline/stores.py` — added migration 005 block in
  `_apply_migrations()` after the 004 block, mirroring 003/004 pattern.
- `docs/BACKLOG.md` — added BL-25 capturing the `initdb.d` masking issue.
- `DAVE_DONE.md` — this report.

## The fix

`src/pipeline/stores.py`, directly after the 004 block:

```python
# Apply 005 (idempotent — uses IF NOT EXISTS)
migration_005 = Path("migrations/005_warnings_column.sql")
if migration_005.exists():
    logger.info("Applying migration 005 (warnings column) if needed")
    sql = migration_005.read_text(encoding="utf-8")
    cur.execute(sql)
    conn.commit()
```

Idempotent: the SQL uses `ADD COLUMN IF NOT EXISTS`, so re-running on a
Pg where `initdb.d` already applied it is a safe no-op.

## Fresh-Pg gate

```
docker compose down -v
docker compose up -d postgres
DB_PASSWORD=local-dev-only python -m pytest tests/test_dedup_warnings.py -v
```

Result:

```
tests/test_dedup_warnings.py::test_warnings_round_trip_via_find_by_fingerprint PASSED
tests/test_dedup_warnings.py::test_warnings_round_trip_via_list_documents PASSED
tests/test_dedup_warnings.py::test_warnings_update_on_resurrection PASSED
3 passed in 0.29s
```

Full suite against the same fresh Pg: `227 passed in 8.16s` — zero
regressions, all 3 TestPgResurrection tests run too.

## BL-25 — new backlog entry

Added under `### BL-24` in `docs/BACKLOG.md`. Captures that the
`docker-compose` `initdb.d` mount masked this runner gap locally and
that fresh-Pg local tests don't protect against the same class of bug
going forward. Three fix directions listed (drop `initdb.d`, CI smoke
on vanilla pg16, runner-completeness filename-diff check); (c) flagged
as the cheapest/highest-leverage option. No blocker.

## Scope-fence call-outs for Bob

- **No changes to `dedup.py`, `routes.py`, `services.py`, or any SELECT.**
  The BL-22 patch that landed in `2f15bb1` was complete at the SQL
  surface — only the runner wire-up was missing. Nothing else touched.
- **No migration 006.** The fix is purely in `_apply_migrations`; 005
  itself is unchanged and already in the tree.
- **`initdb.d` not modified.** Keeping the bootstrap path is a separate
  decision (BL-25). Changing it now would thrash local dev flow.

## Staging list

```
 M src/pipeline/stores.py
 M docs/BACKLOG.md
 M DAVE_DONE.md
```

User said "Push, STOP" — committing and pushing.
