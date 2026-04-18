"""Store factory — creates the correct backend based on config.

Reads config.vector_store.backend:
  "pgvector" → PgVectorStore + PgDedupStore (backed by Postgres)
  "memory"   → InMemoryVectorStore + InMemoryDedupStore (for tests)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.config import AriadneConfig
from pipeline.dedup import InMemoryDedupStore, PgDedupStore
from pipeline.storage.base import InMemoryVectorStore
from pipeline.storage.pgvector import PgVectorStore

if TYPE_CHECKING:
    from pipeline.dedup import DedupStore
    from pipeline.storage.base import VectorStore

logger = logging.getLogger("ariadne.stores")

# Module-level connection pool — shared across all stores
_pool = None


def create_stores(
    config: AriadneConfig,
) -> tuple[DedupStore, VectorStore]:
    """Create dedup and vector stores based on config.

    For pgvector backend, creates a shared psycopg connection pool and
    runs the migration check on startup.

    Returns:
        (dedup_store, vector_store) tuple
    """
    global _pool

    backend = config.vector_store.backend

    if backend == "pgvector":
        logger.info("Initializing Postgres stores (backend=pgvector)")
        pool = _get_or_create_pool(config.database.url)
        _apply_migrations(pool)
        _ensure_schema(pool, config.embedding.dimensions)
        return PgDedupStore(pool), PgVectorStore(pool)

    logger.info("Using in-memory stores (backend=%s)", backend)
    return InMemoryDedupStore(), InMemoryVectorStore()


def _get_or_create_pool(database_url: str):
    """Get or create the shared connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    from psycopg_pool import ConnectionPool

    logger.info("Creating connection pool for %s", _mask_url(database_url))
    # Parse the URL into keyword args to avoid issues with special characters
    # (e.g., @ or * in passwords) that break URL parsing.
    conninfo = _parse_db_url(database_url)
    _pool = ConnectionPool(
        conninfo=conninfo,
        min_size=2,
        max_size=10,
        open=True,
    )
    return _pool


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
        newly_applied: list[str] = []
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
            newly_applied.append(version)

        # Post-loop summary — gives destructive-deploy observers a single
        # grep-able line confirming the runner completed without error,
        # even if individual "Applying migration ..." lines got lost in a
        # log-tail window. Mirrors the legacy-branch summary above.
        if newly_applied:
            logger.info(
                "Migrations applied: %d file(s): %s",
                len(newly_applied),
                ", ".join(newly_applied),
            )
        else:
            logger.info("Migrations up to date — nothing to apply")


def _ensure_schema(pool, dimensions: int) -> None:
    """Validate and create/update the chunks table schema."""
    from pipeline.schema import ensure_schema

    with pool.connection() as conn:
        status = ensure_schema(conn, dimensions)
        if status.actions_taken:
            logger.info("Schema actions: %s", "; ".join(status.actions_taken))


def close_pool() -> None:
    """Close the shared connection pool (call on shutdown)."""
    global _pool
    if _pool is not None:
        logger.info("Closing connection pool")
        _pool.close()
        _pool = None


def _mask_url(url: str) -> str:
    """Mask password in a database URL for logging."""
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _parse_db_url(url: str) -> str:
    """Convert a postgresql:// URL to a libpq conninfo string.

    This avoids issues with special characters in passwords (e.g., @, *)
    that break URL-style parsing. Produces a space-separated key=value
    string with proper quoting.
    """
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    if not parsed.hostname:
        # Already a conninfo string or something we can't parse — pass through
        return url

    parts = []
    parts.append(f"host={parsed.hostname}")
    if parsed.port:
        parts.append(f"port={parsed.port}")
    if parsed.path and parsed.path != "/":
        parts.append(f"dbname={parsed.path.lstrip('/')}")
    if parsed.username:
        parts.append(f"user={unquote(parsed.username)}")
    if parsed.password:
        # Quote the password value for libpq (single quotes, escape internal quotes)
        pw = unquote(parsed.password).replace("'", "\\'")
        parts.append(f"password='{pw}'")
    return " ".join(parts)
