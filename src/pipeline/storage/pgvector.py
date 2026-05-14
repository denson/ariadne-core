"""PgVector-backed vector store.

Uses psycopg 3 with a connection pool to store chunks and embeddings
in Postgres with the pgvector extension. Implements the VectorStore
protocol defined in base.py.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from psycopg_pool import ConnectionPool

from pipeline.chunking.chunker import Chunk
from pipeline.storage.base import SearchResult

logger = logging.getLogger("ariadne.pgvector")


class PgVectorStore:
    """Postgres/pgvector implementation of VectorStore."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # -- VectorStore protocol methods ------------------------------------------

    def insert(self, chunks: list[Chunk]) -> None:
        """INSERT chunks with embeddings into the chunks table."""
        if not chunks:
            return

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for c in chunks:
                    embedding_str = (
                        _vector_literal(c.embedding) if c.embedding else None
                    )
                    # Generate a stable UUID for the chunk (the chunker uses
                    # string IDs like "docid-chunk-0001", not UUIDs)
                    chunk_uuid = str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"ariadne:{c.document_id}:{c.chunk_index}",
                    ))
                    cur.execute(
                        """
                        INSERT INTO chunks (
                            id, document_id, collection_id, chunk_index,
                            text, section, page_start, page_end,
                            token_count, embedding_model, embedding, metadata
                        ) VALUES (
                            %(id)s,
                            %(document_id)s,
                            (SELECT id FROM collections WHERE name = %(collection)s),
                            %(chunk_index)s,
                            %(text)s, %(section)s, %(page_start)s, %(page_end)s,
                            %(token_count)s, %(embedding_model)s,
                            %(embedding)s::vector,
                            %(metadata)s::jsonb
                        )
                        ON CONFLICT (id) DO NOTHING
                        """,
                        {
                            "id": chunk_uuid,
                            "document_id": c.document_id,
                            "collection": c.collection_id,
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "section": c.section,
                            "page_start": c.page_start,
                            "page_end": c.page_end,
                            "token_count": c.token_count,
                            "embedding_model": c.embedding_model,
                            "embedding": embedding_str,
                            "metadata": json.dumps(c.metadata),
                        },
                    )
            conn.commit()

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
    ) -> list[SearchResult]:
        """Vector similarity search using pgvector cosine distance."""
        embedding_str = _vector_literal(query_embedding)

        # Build WHERE clause from filters
        where_clauses: list[str] = []
        params: dict[str, Any] = {
            "embedding": embedding_str,
            "top_k": top_k,
        }

        # The ``documents d`` join is unconditional and inlined into the
        # query below: search results always carry ``d.metadata`` (the
        # document's structured metadata object) regardless of
        # ``include_deleted`` or which filters are active. It is also
        # needed for the ``d.deleted_at`` predicate below and for the
        # ``source_file``/``file_type``/``tags`` filters.
        if not include_deleted:
            where_clauses.append("d.deleted_at IS NULL")
        if filters:
            if "collection" in filters:
                where_clauses.append(
                    "col.name = %(filter_collection)s"
                )
                params["filter_collection"] = filters["collection"]
            if "document_id" in filters:
                where_clauses.append(
                    "c.document_id = %(filter_doc_id)s::uuid"
                )
                params["filter_doc_id"] = filters["document_id"]
            if "source_file" in filters:
                where_clauses.append(
                    "d.source_file ILIKE '%%' || %(filter_source)s || '%%'"
                )
                params["filter_source"] = filters["source_file"]
            if "file_type" in filters:
                where_clauses.append("d.file_type = %(filter_file_type)s")
                params["filter_file_type"] = filters["file_type"].lstrip(".")
            if "tags" in filters:
                where_clauses.append("d.tags && %(filter_tags)s::text[]")
                params["filter_tags"] = filters["tags"]
            # ``metadata`` and ``metadata_exists`` resolve against the
            # *latest* ``document_interactions.agent_metadata`` per
            # document — matching the SPEC's "per-interaction"
            # convention and the existing GET/list read pattern that
            # surfaces "the latest interaction's agent_metadata dict".
            #
            # We use a correlated subquery picking the most recent
            # interaction row per document, then apply ``@>`` for
            # containment and ``?`` for key existence against its
            # ``agent_metadata`` JSONB. A GIN index on
            # ``document_interactions(agent_metadata)`` (migration 002)
            # makes both operators index-eligible.
            #
            # Composition: ``metadata`` and each entry in
            # ``metadata_exists`` AND together (default filter
            # composition), matching the top-level AND semantics other
            # filter keys already use.
            if "metadata" in filters or "metadata_exists" in filters:
                # ``ORDER BY created_at DESC, id DESC`` gives a
                # deterministic latest-row pick when two interactions
                # share the same microsecond — without the ``id`` tie-
                # breaker the planner is free to return either row and
                # the filter becomes flaky. ``id`` is a unique UUID
                # PRIMARY KEY (see migrations/001_initial.sql) so the
                # second sort key fully orders any same-instant pair.
                latest_meta_sql = (
                    "(SELECT di.agent_metadata FROM document_interactions di "
                    "WHERE di.document_id = d.id "
                    "ORDER BY di.created_at DESC, di.id DESC LIMIT 1)"
                )
                if "metadata" in filters:
                    where_clauses.append(
                        f"{latest_meta_sql} @> %(filter_metadata)s::jsonb"
                    )
                    params["filter_metadata"] = json.dumps(filters["metadata"])
                if "metadata_exists" in filters:
                    # One ``?`` clause per requested key, AND-composed.
                    # Parameterise each key individually so it survives
                    # quoting; psycopg's ``?`` operator works against
                    # text parameters bound as the right operand.
                    for idx, key in enumerate(filters["metadata_exists"]):
                        pname = f"filter_meta_key_{idx}"
                        where_clauses.append(
                            f"{latest_meta_sql} ? %({pname})s"
                        )
                        params[pname] = key

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        query = f"""
            SELECT
                c.id, c.document_id, c.chunk_index,
                c.text, c.section, c.page_start, c.page_end,
                c.token_count, c.embedding_model, c.metadata,
                col.name AS collection_name,
                1 - (c.embedding <=> %(embedding)s::vector) AS score,
                d.metadata AS document_metadata
            FROM chunks c
            JOIN collections col ON c.collection_id = col.id
            JOIN documents d ON c.document_id = d.id
            {where_sql}
            ORDER BY c.embedding <=> %(embedding)s::vector
            LIMIT %(top_k)s
        """

        results: list[SearchResult] = []
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                for row in cur.fetchall():
                    chunk = Chunk(
                        chunk_id=str(row[0]),
                        document_id=str(row[1]),
                        collection_id=row[10],  # collection_name
                        chunk_index=row[2],
                        text=row[3],
                        section=row[4],
                        page_start=row[5],
                        page_end=row[6],
                        token_count=row[7] or 0,
                        embedding_model=row[8],
                        metadata=row[9] or {},
                    )
                    results.append(
                        SearchResult(
                            chunk=chunk,
                            score=float(row[11]),
                            document_id=str(row[1]),
                            collection_id=row[10],
                            # ``document_metadata`` is left as the raw
                            # ``d.metadata`` value (``None`` when the column
                            # is SQL NULL). The search route is the single
                            # canonical coalesce point — it applies ``or {}``
                            # when building the response dict (ariadne--buc).
                            document_metadata=row[12],
                        )
                    )
        return results

    def delete(self, chunk_ids: list[str]) -> None:
        """DELETE specific chunks by ID."""
        if not chunk_ids:
            return
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM chunks WHERE id = ANY(%(ids)s::uuid[])",
                    {"ids": chunk_ids},
                )
            conn.commit()

    def delete_by_document(self, document_id: str) -> None:
        """DELETE all chunks belonging to a document."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM chunks WHERE document_id = %(doc_id)s::uuid",
                    {"doc_id": document_id},
                )
            conn.commit()

    def count(
        self,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
    ) -> int:
        """COUNT chunks, optionally filtered."""
        where_clauses: list[str] = []
        params: dict[str, Any] = {}

        if filters:
            if "collection" in filters:
                where_clauses.append(
                    "c.collection_id = "
                    "(SELECT id FROM collections WHERE name = %(col)s)"
                )
                params["col"] = filters["collection"]
            if "document_id" in filters:
                where_clauses.append("c.document_id = %(doc_id)s::uuid")
                params["doc_id"] = filters["document_id"]

        # Default: exclude chunks whose parent document is soft-deleted.
        doc_join = ""
        if not include_deleted:
            doc_join = "JOIN documents d ON c.document_id = d.id"
            where_clauses.append("d.deleted_at IS NULL")

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM chunks c {doc_join} {where_sql}",
                    params,
                )
                return cur.fetchone()[0]

    # -- Additional methods for get_document / list_documents ------------------

    def get_document_chunks(
        self, document_id: str, include_deleted: bool = False
    ) -> list[Chunk]:
        """Get all chunks for a document, ordered by chunk index."""
        deleted_join = (
            "" if include_deleted
            else "JOIN documents d ON c.document_id = d.id"
        )
        deleted_clause = "" if include_deleted else "AND d.deleted_at IS NULL"
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT c.id, c.document_id, col.name, c.chunk_index,
                           c.text, c.section, c.page_start, c.page_end,
                           c.token_count, c.embedding_model, c.metadata
                    FROM chunks c
                    JOIN collections col ON c.collection_id = col.id
                    {deleted_join}
                    WHERE c.document_id = %(doc_id)s::uuid
                      {deleted_clause}
                    ORDER BY c.chunk_index
                    """,
                    {"doc_id": document_id},
                )
                return [
                    Chunk(
                        chunk_id=str(row[0]),
                        document_id=str(row[1]),
                        collection_id=row[2],
                        chunk_index=row[3],
                        text=row[4],
                        section=row[5],
                        page_start=row[6],
                        page_end=row[7],
                        token_count=row[8] or 0,
                        embedding_model=row[9],
                        metadata=row[10] or {},
                    )
                    for row in cur.fetchall()
                ]

    def count_by_document(
        self, document_id: str, include_deleted: bool = False
    ) -> int:
        """Count chunks for a specific document."""
        if include_deleted:
            query = (
                "SELECT COUNT(*) FROM chunks "
                "WHERE document_id = %(doc_id)s::uuid"
            )
        else:
            query = (
                "SELECT COUNT(*) FROM chunks c "
                "JOIN documents d ON c.document_id = d.id "
                "WHERE c.document_id = %(doc_id)s::uuid "
                "AND d.deleted_at IS NULL"
            )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {"doc_id": document_id})
                return cur.fetchone()[0]


def _vector_literal(v: list[float]) -> str:
    """Convert a Python list of floats to a pgvector literal string."""
    return "[" + ",".join(str(f) for f in v) + "]"
