"""Database schema validation and creation.

On startup the app calls `ensure_schema()` which:
  1. Creates the chunks table if it doesn't exist (using configured dimensions)
  2. Validates that an existing embedding column matches the configured dimensions
  3. Creates the HNSW index if missing

This allows the vector dimension to be driven entirely by ariadne.yaml
(embedding.dimensions) rather than hardcoded in the migration SQL.

For Phase 1 (in-memory stores), this module provides schema SQL generation
and a validation check. When Postgres is connected, the same functions
run against the real database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("ariadne.schema")

# SQL templates with dimension placeholder

CHUNKS_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES collections(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    section TEXT,
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER,
    embedding_model TEXT,
    embedding vector({dimensions}),
    metadata JSONB DEFAULT '{{}}',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now()
);
"""

HNSW_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""

# Query to check the current vector column dimension
CHECK_DIMENSION_SQL = """\
SELECT atttypmod
FROM pg_attribute
WHERE attrelid = 'chunks'::regclass
  AND attname = 'embedding';
"""

# Alter column to change dimension (requires dropping and recreating the index)
ALTER_COLUMN_SQL = """\
DROP INDEX IF EXISTS idx_chunks_embedding;
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({dimensions});
"""


@dataclass
class SchemaStatus:
    """Result of schema validation."""

    table_exists: bool
    dimension_match: bool
    current_dimension: int | None
    configured_dimension: int
    actions_taken: list[str]


def get_chunks_ddl(dimensions: int) -> str:
    """Return the CREATE TABLE SQL for chunks with the given vector dimension."""
    return CHUNKS_TABLE_SQL.format(dimensions=dimensions)


def get_hnsw_index_ddl() -> str:
    """Return the CREATE INDEX SQL for the HNSW vector index."""
    return HNSW_INDEX_SQL


def ensure_schema(conn, dimensions: int) -> SchemaStatus:
    """Validate and create/update the chunks table schema.

    Args:
        conn: A database connection with cursor() and commit() support
              (e.g., psycopg2 connection).
        dimensions: The configured embedding dimensions from ariadne.yaml.

    Returns:
        SchemaStatus describing what was found and what actions were taken.
    """
    actions: list[str] = []
    cursor = conn.cursor()

    # Check if chunks table exists
    cursor.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables"
        "  WHERE table_name = 'chunks'"
        ");"
    )
    table_exists = cursor.fetchone()[0]

    if not table_exists:
        logger.info(
            "Creating chunks table with vector(%d) dimension", dimensions
        )
        cursor.execute(get_chunks_ddl(dimensions))
        cursor.execute(get_hnsw_index_ddl())
        conn.commit()
        actions.append(f"created chunks table with vector({dimensions})")
        actions.append("created HNSW index")
        return SchemaStatus(
            table_exists=True,
            dimension_match=True,
            current_dimension=dimensions,
            configured_dimension=dimensions,
            actions_taken=actions,
        )

    # Table exists — check current dimension
    # atttypmod for vector type stores dimension + 4
    cursor.execute(CHECK_DIMENSION_SQL)
    row = cursor.fetchone()

    if row is None or row[0] is None or row[0] <= 0:
        # Column exists but dimension is unknown (unlikely with pgvector)
        current_dim = None
        dimension_match = False
    else:
        current_dim = row[0] - 4  # pgvector stores dim + 4 in atttypmod
        dimension_match = current_dim == dimensions

    if not dimension_match and current_dim is not None:
        logger.warning(
            "Embedding dimension mismatch: database has vector(%d) but "
            "config specifies %d. Altering column...",
            current_dim,
            dimensions,
        )
        cursor.execute(ALTER_COLUMN_SQL.format(dimensions=dimensions))
        cursor.execute(get_hnsw_index_ddl())
        conn.commit()
        actions.append(
            f"altered embedding column from vector({current_dim}) "
            f"to vector({dimensions})"
        )
        actions.append("recreated HNSW index")
        current_dim = dimensions
        dimension_match = True

    if not actions:
        logger.info(
            "Schema OK: chunks table exists with vector(%d)", current_dim
        )

    return SchemaStatus(
        table_exists=True,
        dimension_match=dimension_match,
        current_dimension=current_dim,
        configured_dimension=dimensions,
        actions_taken=actions,
    )


def validate_dimensions(configured: int, store_dimensions: int | None) -> bool:
    """Check that the configured dimension matches the store dimension.

    This is the Phase 1 (in-memory) equivalent of ensure_schema — it just
    validates without touching a database.

    Args:
        configured: Dimension from ariadne.yaml embedding.dimensions.
        store_dimensions: Dimension the vector store is using, or None.

    Returns:
        True if dimensions match or store has no opinion (None).
    """
    if store_dimensions is None:
        return True
    return configured == store_dimensions
