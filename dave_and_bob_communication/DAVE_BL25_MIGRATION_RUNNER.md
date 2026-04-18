# DAVE — BL-25: rewrite `_apply_migrations` to dynamic discovery + `schema_migrations` tracking table

## Context

Today, `src/pipeline/stores.py::_apply_migrations` is a hardcoded per-file ladder: one explicit if-block per migration file, each one running the SQL on every boot and relying on the SQL itself being idempotent (`IF NOT EXISTS` etc.). The BL-22 failure — migration 005 shipped as a dead file on prod — happened because I (Sam) forgot to include "wire 005 into `_apply_migrations`" in the BL-22 spec. Dave followed the spec exactly; the hole was mine.

Option (c) earlier in the conversation was a filename-completeness check (CI lint that compares `migrations/*.sql` against hardcoded blocks). That catches the forget-to-wire case at CI-time. Option (a) — what this spec implements — removes the class of error entirely: make the filesystem the source of truth and track applied versions in a `schema_migrations` table. No hardcoded list means no way to forget to update it.

**This spec supersedes Dave's prior BL-25 BACKLOG entry.** His entry's fix directions (a)/(b)/(c) focused on the `initdb.d` masking that hid the bug locally. Dynamic discovery + tracking-table solves the same failure mode more robustly: even if `initdb.d` applies SQL before the Python runner boots, the runner's backfill path reconciles the state.

---

## Scope

**In scope:**
- Rewrite `_apply_migrations` in `src/pipeline/stores.py` to dynamic discovery + `schema_migrations` tracking.
- Add `migrations/006_schema_migrations.sql` — a trivial migration that is the ONLY migration explicitly created by the runner itself (bootstrap concern; see "Bootstrap" below).

Wait — scratch that. The `schema_migrations` table is created **inline** inside `_apply_migrations` via `CREATE TABLE IF NOT EXISTS`, not as a migration file. That keeps the runner's own metadata independent of the migration system it manages. No new migration file.

- Add tests in `tests/test_migration_runner.py`: fresh-DB full-apply, legacy-DB backfill, incremental-apply-of-new-file, idempotent re-run.
- Update `docs/BACKLOG.md`: replace the current BL-25 entry with a RESOLVED entry that references this commit.

**Out of scope:**
- Do NOT modify any existing `migrations/*.sql` file.
- Do NOT modify `tests/conftest.py` — the session-scoped `pg_pool` fixture already calls `_apply_migrations(pool)`, which Just Works under the new runner.
- Do NOT touch `docker-compose.yml` (the `initdb.d` mount stays; backfill path handles it).
- Do NOT add migration rollback / down functionality. One-way migrations only, same as today.
- Do NOT touch `routes.py`, `dedup.py`, `services.py`, `client/`, or any skill.

---

## The new `_apply_migrations`

Replace the entire current function body (lines 75–162 in `src/pipeline/stores.py`) with:

```python
def _apply_migrations(pool) -> None:
    """Apply any pending migrations in migrations/*.sql.

    Uses a schema_migrations tracking table to record which migrations
    have been applied to this database. Each migration file runs exactly
    once, in filename-sorted order. The filesystem is the source of
    truth for "what migrations exist"; the tracking table is the source
    of truth for "what has been applied to this database".

    Bootstrap behavior:
      - Fresh database (no 'documents' table, no 'schema_migrations'):
          creates schema_migrations, loops through every migration file
          in order and applies each.
      - Legacy database (pre-existing 'documents' table but no
          'schema_migrations'): this is the pre-BL-25 state on Railway.
          We backfill by recording every current migration file as
          applied *without re-running the SQL*, since the state is
          already correct.
      - Post-bootstrap database (schema_migrations populated): loops
          through migration files, skips any version already in the
          table, applies any that aren't.
    """
    from pathlib import Path

    migrations_dir = Path("migrations")
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        logger.warning("No migration files found in %s", migrations_dir)
        return

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Create the tracking table if it doesn't exist. This is the
            # runner's own metadata — deliberately not itself a migration
            # file, since migrations depend on it existing.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            conn.commit()

            # Decide whether to backfill (legacy) or loop (fresh /
            # post-bootstrap). Legacy detection: schema_migrations is
            # empty but 'documents' already exists.
            cur.execute("SELECT COUNT(*) FROM schema_migrations;")
            tracking_count = cur.fetchone()[0]

            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_name = 'documents'"
                ");"
            )
            documents_exists = cur.fetchone()[0]

            if tracking_count == 0 and documents_exists:
                # Legacy DB — every current migration file has been applied
                # via the old hardcoded runner. Record them without re-running.
                versions = [p.name for p in migration_files]
                logger.info(
                    "Legacy database detected — backfilling "
                    "schema_migrations with %d version(s): %s",
                    len(versions),
                    ", ".join(versions),
                )
                for version in versions:
                    cur.execute(
                        "INSERT INTO schema_migrations (version) "
                        "VALUES (%s) ON CONFLICT (version) DO NOTHING;",
                        (version,),
                    )
                conn.commit()
                return

            # Normal path: apply any unapplied migrations.
            cur.execute("SELECT version FROM schema_migrations;")
            applied = {row[0] for row in cur.fetchall()}

        # Apply each unapplied migration in its own transaction.
        for path in migration_files:
            version = path.name
            if version in applied:
                logger.debug("Migration %s already applied, skipping", version)
                continue

            logger.info("Applying migration %s", version)
            sql = path.read_text(encoding="utf-8")

            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s);",
                    (version,),
                )
                conn.commit()
```

### Version keys

`version` is the filename (e.g. `"005_warnings_column.sql"`), not a parsed number. This is deliberate:
- Survives filename renames better (no re-apply if `005_warnings.sql` is renamed to `005_warnings_column.sql` — the new name will re-apply, which is the right behavior since the content might have changed).
- No parsing ambiguity.
- Identical to what Rails / Django-ish conventions use.

---

## Tests — `tests/test_migration_runner.py` (new file)

All tests are Pg-backed, using the `pg_pool` fixture pattern. Because tests need to start from specific pre-states (fresh DB, legacy DB), they can't just reuse the session-scoped `pg_pool` — they need to set up and tear down custom state. Use the existing `pg_pool` but wrap each test in setup/teardown that drops the relevant tables.

**Import at top of file:**
```python
import pytest
from pathlib import Path
from pipeline.stores import _apply_migrations

pytestmark = pytest.mark.usefixtures("pg_pool")
```

**Helper (defined in the test module, not conftest):**
```python
def _reset_db(pool):
    """Drop every table the runner might have created, so the test
    can start from a truly empty DB. Runs inside a single transaction
    for atomicity. DOES NOT drop extensions — those are cheap to keep."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Order matters: drop dependents first. Wrap in DO block so
            # a missing table doesn't fail the whole reset.
            cur.execute("""
                DO $$
                DECLARE r RECORD;
                BEGIN
                    FOR r IN
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public'
                    LOOP
                        EXECUTE 'DROP TABLE IF EXISTS '
                             || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """)
        conn.commit()
```

### Test 1 — Fresh DB applies every migration

```python
def test_fresh_db_applies_all_migrations(pg_pool):
    """A DB with no documents table and no schema_migrations table runs
    every migration file and records each one."""
    _reset_db(pg_pool)

    _apply_migrations(pg_pool)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            # Every migration file should be recorded.
            cur.execute("SELECT version FROM schema_migrations ORDER BY version;")
            recorded = [row[0] for row in cur.fetchall()]
            expected = sorted(p.name for p in Path("migrations").glob("*.sql"))
            assert recorded == expected

            # And the schema actually landed (pick one — documents is the BL-22
            # proof-of-life: warnings column must exist).
            cur.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'warnings';
            """)
            result = cur.fetchone()
            assert result is not None, "warnings column missing — 005 didn't apply"
```

### Test 2 — Legacy DB backfills without re-running SQL

```python
def test_legacy_db_backfills_tracking(pg_pool):
    """A DB where 'documents' already exists but 'schema_migrations' does
    NOT (pre-BL-25 Railway state) should backfill the tracking table with
    every current migration file, WITHOUT re-running any SQL."""
    _reset_db(pg_pool)

    # Simulate legacy state: apply all migrations manually, then drop the
    # tracking table to create the "documents exists, tracking doesn't" mix.
    _apply_migrations(pg_pool)
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE schema_migrations;")
            # Insert a row so we can prove SQL isn't re-run (if 001 reran,
            # it would fail because 'collections' already has the seed row
            # and the INSERT is not idempotent).
            cur.execute("SELECT COUNT(*) FROM collections;")
            collections_before = cur.fetchone()[0]
        conn.commit()

    _apply_migrations(pg_pool)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            # Tracking table now populated.
            cur.execute("SELECT COUNT(*) FROM schema_migrations;")
            assert cur.fetchone()[0] == len(list(Path("migrations").glob("*.sql")))

            # SQL was NOT re-run: collection count unchanged.
            cur.execute("SELECT COUNT(*) FROM collections;")
            assert cur.fetchone()[0] == collections_before
```

### Test 3 — Idempotent re-run

```python
def test_re_run_is_noop(pg_pool):
    """Running _apply_migrations twice on a post-bootstrap DB is a no-op.
    No duplicate rows, no SQL re-execution."""
    _reset_db(pg_pool)
    _apply_migrations(pg_pool)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version;")
            first = cur.fetchall()

    _apply_migrations(pg_pool)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version;")
            second = cur.fetchall()

    # Same rows, same timestamps — nothing re-inserted.
    assert first == second
```

### Test 4 — New migration file picked up incrementally

```python
def test_new_migration_applied_on_next_run(pg_pool, tmp_path, monkeypatch):
    """Dropping a new file in migrations/ and re-running applies only
    that new file, not any prior ones."""
    _reset_db(pg_pool)
    _apply_migrations(pg_pool)

    # Create a temp migrations directory that contains all current files
    # PLUS one new probe file. Point the runner at it via cwd change.
    real_migrations = Path("migrations")
    staging = tmp_path / "migrations"
    staging.mkdir()
    for p in real_migrations.glob("*.sql"):
        (staging / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

    probe_version = "999_test_probe.sql"
    (staging / probe_version).write_text(
        "CREATE TABLE IF NOT EXISTS bl25_probe (id INTEGER);",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    try:
        _apply_migrations(pg_pool)
    finally:
        monkeypatch.chdir(Path(__file__).parent.parent)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version = %s);",
                (probe_version,),
            )
            assert cur.fetchone()[0], "probe migration not recorded"

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'bl25_probe'
                );
            """)
            assert cur.fetchone()[0], "probe SQL didn't run"

            # Cleanup
            cur.execute("DROP TABLE IF EXISTS bl25_probe;")
            cur.execute("DELETE FROM schema_migrations WHERE version = %s;", (probe_version,))
        conn.commit()
```

---

## BACKLOG update

Replace the current BL-25 entry at `docs/BACKLOG.md:207–229` with:

```markdown
### BL-25 — Migration runner rewritten to dynamic discovery + tracking table — RESOLVED

Resolved in this commit. `_apply_migrations` in `src/pipeline/stores.py`
now discovers `migrations/*.sql` dynamically and records applied
versions in a `schema_migrations` tracking table. The hardcoded per-file
if-ladder is gone. Dropping a new SQL file in `migrations/` is the only
step required to add a migration — the runner picks it up on next boot.

Root cause of the BL-22 regression: the hardcoded ladder required an
explicit block per migration file, so a spec that forgot to mention the
runner wire-up (BL-22's did) shipped a dead SQL file to prod. The new
runner removes the class of failure.

Legacy-database backfill handles the one-time migration from the old
runner to the new one: if `schema_migrations` is empty but `documents`
already exists, every current migration file is recorded as applied
without re-running its SQL.

See `dave_and_bob_communication/DAVE_BL25_MIGRATION_RUNNER.md` for
design notes and test coverage.
```

---

## Verification checklist

Run locally before pushing:

```bash
docker compose down -v && docker compose up -d postgres
# Wait for Pg to be ready, then:
pytest tests/test_migration_runner.py -v
pytest tests/test_dedup_warnings.py -v      # BL-22 regression check
pytest -q                                    # Full suite
```

Expected:
- `test_migration_runner.py`: 4 passed
- `test_dedup_warnings.py`: 3 passed (regression — the new runner still sets up the warnings column)
- Full suite: prior count + 4 new = matches today's baseline + 4

Deploy smoke (post-redeploy, for Bob):

1. `railway logs --service ariadne-core` should show ONE of:
   - On the legacy Railway DB (current state): `Legacy database detected — backfilling schema_migrations with 5 version(s): 001_initial.sql, 002_add_agent_notes.sql, 003_search_log.sql, 004_soft_delete.sql, 005_warnings_column.sql`
   - On a subsequent boot: no log output from the runner (all migrations already applied).
2. `GET /api/documents?limit=1` → 200 (proves the `d.warnings` SELECT still works — the runner didn't roll anything back).
3. `psql` check (if Bob has access): `SELECT version FROM schema_migrations ORDER BY version;` returns 5 rows with the expected filenames.

---

## Scope fence

Don't touch:
- Any existing `migrations/*.sql` file
- `tests/conftest.py`
- `docker-compose.yml`
- `routes.py`, `dedup.py`, `services.py`, `client/`, any skill
- `_ensure_schema` in `stores.py` (separate concern — chunks table + HNSW)

Don't add:
- Migration rollback / down functionality
- A separate CLI tool for migrations
- A `migrations/000_schema_migrations.sql` file (the tracking table is bootstrap code, not a migration)

---

## Execution

Dave: implement per above. Run the verification checklist. Push, STOP. Bob reviews + smokes post-redeploy.
