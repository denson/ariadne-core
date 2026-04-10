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
    """Apply all pending migrations on startup.

    Checks if the documents table exists (from 001_initial.sql). If not,
    applies it automatically. Then applies subsequent migrations which are
    all idempotent.
    """
    from pathlib import Path

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Check if base schema exists
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_name = 'documents'"
                ");"
            )
            if not cur.fetchone()[0]:
                # Apply initial migration
                migration_001 = Path("migrations/001_initial.sql")
                if migration_001.exists():
                    logger.info("Applying migration 001 (initial schema)")
                    sql = migration_001.read_text(encoding="utf-8")
                    cur.execute(sql)
                    conn.commit()
                else:
                    raise RuntimeError(
                        "Database schema not found and migrations/001_initial.sql "
                        "is missing. Cannot initialize database."
                    )

            # Apply 002 (idempotent — uses IF NOT EXISTS / IF EXISTS checks)
            migration_002 = Path("migrations/002_add_agent_notes.sql")

            if migration_002.exists():
                logger.info("Applying migration 002 (agent_notes) if needed")
                sql = migration_002.read_text(encoding="utf-8")
                cur.execute(sql)
                conn.commit()
            else:
                # Apply inline (the migration is small and idempotent)
                cur.execute(
                    "ALTER TABLE document_interactions "
                    "ADD COLUMN IF NOT EXISTS agent_notes TEXT;"
                )
                cur.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'document_interactions'
                              AND column_name = 'metadata'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'document_interactions'
                              AND column_name = 'agent_metadata'
                        ) THEN
                            ALTER TABLE document_interactions
                                RENAME COLUMN metadata TO agent_metadata;
                        END IF;
                    END $$;
                """)
                conn.commit()

            # Apply 003 (idempotent — uses IF NOT EXISTS)
            migration_003 = Path("migrations/003_search_log.sql")
            if migration_003.exists():
                logger.info("Applying migration 003 (search_log) if needed")
                sql = migration_003.read_text(encoding="utf-8")
                cur.execute(sql)
                conn.commit()


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
