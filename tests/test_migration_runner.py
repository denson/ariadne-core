"""BL-25: migration runner uses dynamic discovery + schema_migrations tracking.

The runner must:
  - Apply every migration on a fresh DB and record each version.
  - Backfill the tracking table on a legacy DB (pre-BL-25 state) without
    re-running any SQL.
  - Be a no-op when re-run on a post-bootstrap DB.
  - Pick up a new migration file dropped into migrations/ on next run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.stores import _apply_migrations

pytestmark = pytest.mark.usefixtures("pg_pool")


def _reset_db(pool):
    """Drop every table the runner might have created, so the test
    can start from a truly empty DB. Runs inside a single transaction
    for atomicity. DOES NOT drop extensions — those are cheap to keep."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
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


def test_fresh_db_applies_all_migrations(pg_pool):
    """A DB with no documents table and no schema_migrations table runs
    every migration file and records each one."""
    _reset_db(pg_pool)

    _apply_migrations(pg_pool)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY version;")
            recorded = [row[0] for row in cur.fetchall()]
            expected = sorted(p.name for p in Path("migrations").glob("*.sql"))
            assert recorded == expected

            cur.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'warnings';
            """)
            result = cur.fetchone()
            assert result is not None, "warnings column missing — 005 didn't apply"


def test_legacy_db_backfills_tracking(pg_pool):
    """A DB where 'documents' already exists but 'schema_migrations' does
    NOT (pre-BL-25 Railway state) should backfill the tracking table with
    every current migration file, WITHOUT re-running any SQL."""
    _reset_db(pg_pool)

    _apply_migrations(pg_pool)
    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE schema_migrations;")
            cur.execute("SELECT COUNT(*) FROM collections;")
            collections_before = cur.fetchone()[0]
        conn.commit()

    _apply_migrations(pg_pool)

    with pg_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM schema_migrations;")
            assert cur.fetchone()[0] == len(list(Path("migrations").glob("*.sql")))

            cur.execute("SELECT COUNT(*) FROM collections;")
            assert cur.fetchone()[0] == collections_before


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

    assert first == second


def test_new_migration_applied_on_next_run(pg_pool, tmp_path, monkeypatch):
    """Dropping a new file in migrations/ and re-running applies only
    that new file, not any prior ones."""
    _reset_db(pg_pool)
    _apply_migrations(pg_pool)

    real_migrations = Path("migrations").resolve()
    staging = tmp_path / "migrations"
    staging.mkdir()
    for p in real_migrations.glob("*.sql"):
        (staging / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

    probe_version = "999_test_probe.sql"
    (staging / probe_version).write_text(
        "CREATE TABLE IF NOT EXISTS bl25_probe (id INTEGER);",
        encoding="utf-8",
    )

    original_cwd = Path.cwd()
    monkeypatch.chdir(tmp_path)
    try:
        _apply_migrations(pg_pool)
    finally:
        monkeypatch.chdir(original_cwd)

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

            cur.execute("DROP TABLE IF EXISTS bl25_probe;")
            cur.execute("DELETE FROM schema_migrations WHERE version = %s;", (probe_version,))
        conn.commit()
