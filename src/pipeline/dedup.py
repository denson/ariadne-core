"""Dedup gate — SHA-256 fingerprinting and collision detection.

Fingerprints raw source bytes (file bytes for local sources, the HTTP
response body for URL sources). The hash is taken BEFORE extraction so
dedup is independent of markitdown / vision-API non-determinism. In
Phase 1 this uses an in-memory store; Phase 5 will swap in Postgres
(documents table with unique index on collection_id + content_fingerprint).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def compute_fingerprint(content: bytes) -> str:
    """SHA-256 of raw source bytes. Caller passes file bytes for local
    sources, the HTTP response body bytes for URL sources. No normalization
    is applied: byte-stable inputs are the design intent."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError(
            f"compute_fingerprint expects raw bytes; got {type(content).__name__}. "
            "Hash source bytes (file or HTTP body), not extracted text."
        )
    return hashlib.sha256(bytes(content)).hexdigest()


def _extract_source_reference(agent_metadata: dict[str, Any] | None) -> str | None:
    """Pull a non-empty source_reference string out of agent_metadata.

    Returns the trimmed value when present (including the sentinel
    'unknown', which is preserved verbatim for display/audit — the
    partial index and filter clauses exclude it). Returns None when
    agent_metadata is missing the key or the value is empty/whitespace
    or the wrong type.
    """
    if not agent_metadata or not isinstance(agent_metadata, dict):
        return None
    val = agent_metadata.get("source_reference")
    if not isinstance(val, str):
        return None
    val = val.strip()
    return val or None


@dataclass
class StoredDocument:
    """A previously processed document record."""

    document_id: str
    collection_id: str
    source_file: str
    content_fingerprint: str
    file_type: str
    engine: str
    markdown: str
    title: str | None
    processing_time_ms: int
    output_tokens_estimate: int
    token_savings_ratio: float | None
    processing_chain: list[dict[str, Any]]
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class DocumentInteraction:
    """A record of an agent touching a document."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    collection_id: str = ""
    agent_id: str | None = None
    agent_type: str | None = None
    model: str | None = None
    initiated_by: str | None = None
    agent_notes: str | None = None
    agent_metadata: dict[str, Any] | None = None
    action: str = "ingest"
    was_dedup_skip: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class SearchLogEntry:
    """A record of a search query."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ""
    collection: str | None = None
    filters: dict[str, Any] | None = None
    top_k: int = 5
    results_count: int = 0
    result_document_ids: list[str] = field(default_factory=list)
    agent_id: str | None = None
    agent_type: str | None = None
    model: str | None = None
    initiated_by: str | None = None
    agent_notes: str | None = None
    agent_metadata: dict[str, Any] | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DedupStore(Protocol):
    """Protocol for dedup storage backends."""

    def find_by_fingerprint(
        self,
        collection: str,
        fingerprint: str,
        include_deleted: bool = False,
    ) -> StoredDocument | None: ...

    def store_document(self, doc: StoredDocument) -> bool: ...

    def record_interaction(self, interaction: DocumentInteraction) -> None: ...

    def get_interactions(self, document_id: str) -> list[DocumentInteraction]: ...

    def record_search(self, entry: SearchLogEntry) -> None: ...

    def soft_delete_document(self, document_id: str) -> None: ...

    def restore_document(self, document_id: str) -> None: ...

    def soft_delete_collection(self, collection_name: str) -> int: ...

    def restore_collection(self, collection_name: str) -> int: ...

    def purge_deleted(self, older_than_hours: int = 48) -> int: ...

    def update_document_metadata(
        self,
        document_id: str,
        tags: list[str] | None = None,
        agent_metadata: dict[str, Any] | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]: ...

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
    ) -> tuple[list[StoredDocument], int]: ...


class PgDedupStore:
    """Postgres-backed dedup store.

    Uses psycopg 3 connection pool. Queries the documents and
    document_interactions tables directly.
    """

    def __init__(self, pool) -> None:
        from psycopg_pool import ConnectionPool
        self._pool: ConnectionPool = pool

    def _ensure_collection(self, conn, collection_name: str) -> None:
        """Create the collection if it doesn't exist."""
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO collections (name)
                VALUES (%(name)s)
                ON CONFLICT (name) DO NOTHING
                """,
                {"name": collection_name},
            )

    def find_by_fingerprint(
        self,
        collection: str,
        fingerprint: str,
        include_deleted: bool = False,
    ) -> StoredDocument | None:
        deleted_clause = "" if include_deleted else "AND d.deleted_at IS NULL"
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Column order must match _row_to_stored_document.
                cur.execute(
                    f"""
                    SELECT d.id, d.collection_id, d.source_file,
                           d.content_fingerprint, d.file_type, d.engine,
                           d.markdown, d.title, d.processing_time_ms,
                           d.output_tokens_estimate, d.token_savings_ratio,
                           d.processing_chain, d.tags, d.warnings,
                           d.created_at
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(collection)s
                      AND d.content_fingerprint = %(fp)s
                      {deleted_clause}
                    LIMIT 1
                    """,
                    {"collection": collection, "fp": fingerprint},
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return _row_to_stored_document(row, collection)

    def store_document(self, doc: StoredDocument) -> bool:
        """Insert or upsert a document.

        Returns True if the upsert resurrected a previously soft-deleted row
        (i.e. the row existed with deleted_at IS NOT NULL before this call).
        """
        import json as _json
        with self._pool.connection() as conn:
            self._ensure_collection(conn, doc.collection_id)
            with conn.cursor() as cur:
                # Capture prior soft-delete state in the same transaction so
                # callers can surface "this re-ingest resurrected a row".
                # After the UPDATE below, deleted_at is always NULL, so the
                # only way to detect a resurrection is to look up the prior
                # state first.
                cur.execute(
                    """
                    SELECT d.deleted_at IS NOT NULL
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(collection)s
                      AND d.content_fingerprint = %(fp)s
                    """,
                    {"collection": doc.collection_id, "fp": doc.content_fingerprint},
                )
                prior = cur.fetchone()
                was_resurrected = bool(prior and prior[0])

                cur.execute(
                    """
                    INSERT INTO documents (
                        id, collection_id, source_file, content_fingerprint,
                        file_type, engine, markdown, title,
                        processing_time_ms, output_tokens_estimate,
                        token_savings_ratio, processing_chain, tags, warnings
                    ) VALUES (
                        %(id)s::uuid,
                        (SELECT id FROM collections WHERE name = %(collection)s),
                        %(source_file)s, %(fingerprint)s,
                        %(file_type)s, %(engine)s, %(markdown)s, %(title)s,
                        %(processing_time_ms)s, %(output_tokens_estimate)s,
                        %(token_savings_ratio)s, %(processing_chain)s::jsonb,
                        %(tags)s, %(warnings)s
                    )
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
                        warnings = EXCLUDED.warnings,
                        deleted_at = NULL,
                        deletion_scheduled_at = NULL,
                        updated_at = now()
                    RETURNING id
                    """,
                    {
                        "id": doc.document_id,
                        "collection": doc.collection_id,
                        "source_file": doc.source_file,
                        "fingerprint": doc.content_fingerprint,
                        "file_type": doc.file_type,
                        "engine": doc.engine,
                        "markdown": doc.markdown,
                        "title": doc.title,
                        "processing_time_ms": doc.processing_time_ms,
                        "output_tokens_estimate": doc.output_tokens_estimate,
                        "token_savings_ratio": doc.token_savings_ratio,
                        "processing_chain": _json.dumps(doc.processing_chain),
                        "tags": doc.tags,
                        "warnings": doc.warnings or [],
                    },
                )
                row = cur.fetchone()
                if row:
                    doc.document_id = str(row[0])
            conn.commit()
        return was_resurrected

    def record_interaction(self, interaction: DocumentInteraction) -> None:
        import json as _json
        with self._pool.connection() as conn:
            self._ensure_collection(conn, interaction.collection_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_interactions (
                        id, document_id, collection_id, agent_id, agent_type,
                        model, initiated_by, agent_notes, agent_metadata,
                        action, was_dedup_skip
                    ) VALUES (
                        %(id)s::uuid,
                        %(document_id)s::uuid,
                        (SELECT id FROM collections WHERE name = %(collection)s),
                        %(agent_id)s, %(agent_type)s,
                        %(model)s, %(initiated_by)s, %(agent_notes)s,
                        %(agent_metadata)s::jsonb,
                        %(action)s, %(was_dedup_skip)s
                    )
                    """,
                    {
                        "id": interaction.id,
                        "document_id": interaction.document_id,
                        "collection": interaction.collection_id,
                        "agent_id": interaction.agent_id,
                        "agent_type": interaction.agent_type,
                        "model": interaction.model,
                        "initiated_by": interaction.initiated_by,
                        "agent_notes": interaction.agent_notes,
                        "agent_metadata": _json.dumps(interaction.agent_metadata)
                        if interaction.agent_metadata
                        else None,
                        "action": interaction.action,
                        "was_dedup_skip": interaction.was_dedup_skip,
                    },
                )

                # Latest-wins denormalization: propagate a non-empty
                # source_reference into documents.source_reference so the
                # has_source_reference filter and partial index can read it
                # directly without an N+1 back-trawl of interactions.
                src_ref = _extract_source_reference(interaction.agent_metadata)
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
            conn.commit()

    def get_interactions(self, document_id: str) -> list[DocumentInteraction]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT di.id, di.document_id, col.name,
                           di.agent_id, di.agent_type, di.model,
                           di.initiated_by, di.agent_notes, di.agent_metadata,
                           di.action, di.was_dedup_skip, di.created_at
                    FROM document_interactions di
                    JOIN collections col ON di.collection_id = col.id
                    WHERE di.document_id = %(doc_id)s::uuid
                    ORDER BY di.created_at
                    """,
                    {"doc_id": document_id},
                )
                return [
                    DocumentInteraction(
                        id=str(row[0]),
                        document_id=str(row[1]),
                        collection_id=row[2],
                        agent_id=row[3],
                        agent_type=row[4],
                        model=row[5],
                        initiated_by=row[6],
                        agent_notes=row[7],
                        agent_metadata=row[8],
                        action=row[9],
                        was_dedup_skip=row[10],
                        created_at=row[11].isoformat() if row[11] else "",
                    )
                    for row in cur.fetchall()
                ]

    def record_search(self, entry: SearchLogEntry) -> None:
        import json as _json
        import logging as _logging
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO search_log (
                            id, query, collection, filters, top_k,
                            results_count, result_document_ids,
                            agent_id, agent_type, model, initiated_by,
                            agent_notes, agent_metadata
                        ) VALUES (
                            %(id)s::uuid, %(query)s, %(collection)s,
                            %(filters)s::jsonb, %(top_k)s,
                            %(results_count)s, %(result_document_ids)s::uuid[],
                            %(agent_id)s, %(agent_type)s, %(model)s,
                            %(initiated_by)s, %(agent_notes)s,
                            %(agent_metadata)s::jsonb
                        )
                        """,
                        {
                            "id": entry.id,
                            "query": entry.query,
                            "collection": entry.collection,
                            "filters": _json.dumps(entry.filters)
                            if entry.filters
                            else None,
                            "top_k": entry.top_k,
                            "results_count": entry.results_count,
                            "result_document_ids": entry.result_document_ids or [],
                            "agent_id": entry.agent_id,
                            "agent_type": entry.agent_type,
                            "model": entry.model,
                            "initiated_by": entry.initiated_by,
                            "agent_notes": entry.agent_notes,
                            "agent_metadata": _json.dumps(entry.agent_metadata)
                            if entry.agent_metadata
                            else None,
                        },
                    )
                conn.commit()
        except Exception:
            _logging.getLogger(__name__).warning(
                "Failed to record search log entry", exc_info=True
            )

    def get_document_by_id(
        self, document_id: str, include_deleted: bool = False
    ) -> StoredDocument | None:
        """Retrieve a document by its UUID."""
        deleted_clause = "" if include_deleted else "AND d.deleted_at IS NULL"
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Column order must match _row_to_stored_document.
                cur.execute(
                    f"""
                    SELECT d.id, d.collection_id, d.source_file,
                           d.content_fingerprint, d.file_type, d.engine,
                           d.markdown, d.title, d.processing_time_ms,
                           d.output_tokens_estimate, d.token_savings_ratio,
                           d.processing_chain, d.tags, d.warnings,
                           d.created_at,
                           col.name
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE d.id = %(doc_id)s::uuid
                      {deleted_clause}
                    LIMIT 1
                    """,
                    {"doc_id": document_id},
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return _row_to_stored_document(row[:15], row[15])

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
        """List documents with pagination. Returns (docs, total_count).

        The three keyword-only filters are pushed into SQL so COUNT(*)
        is always exact and pagination is correct across pages.
        """
        where_clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if collection:
            where_clauses.append("col.name = %(collection)s")
            params["collection"] = collection
        if file_type:
            ft = file_type.lstrip(".")
            where_clauses.append("d.file_type = %(file_type)s")
            params["file_type"] = ft
        if not include_deleted:
            where_clauses.append("d.deleted_at IS NULL")

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

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM documents d "
                    f"JOIN collections col ON d.collection_id = col.id "
                    f"{where_sql}",
                    params,
                )
                total = cur.fetchone()[0]

                # Column order must match _row_to_stored_document.
                cur.execute(
                    f"""
                    SELECT d.id, d.collection_id, d.source_file,
                           d.content_fingerprint, d.file_type, d.engine,
                           d.markdown, d.title, d.processing_time_ms,
                           d.output_tokens_estimate, d.token_savings_ratio,
                           d.processing_chain, d.tags, d.warnings,
                           d.created_at,
                           col.name
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    {where_sql}
                    ORDER BY d.created_at DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    params,
                )
                docs = [
                    _row_to_stored_document(row[:15], row[15])
                    for row in cur.fetchall()
                ]
        return docs, total


    def soft_delete_document(self, document_id: str) -> None:
        """Mark a document as soft-deleted.

        Sets both `deleted_at` and `deletion_scheduled_at` to now(). Chunks
        and interactions are preserved — they cascade only on hard delete.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE documents
                    SET deleted_at = now(),
                        deletion_scheduled_at = now()
                    WHERE id = %(doc_id)s::uuid
                    """,
                    {"doc_id": document_id},
                )
            conn.commit()

    def restore_document(self, document_id: str) -> None:
        """Clear the soft-delete on a document within the 48hr grace window.

        Raises ValueError if the document was not deleted, or if the
        deletion was requested more than 48 hours ago.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT deletion_scheduled_at
                    FROM documents
                    WHERE id = %(doc_id)s::uuid
                    """,
                    {"doc_id": document_id},
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"Document {document_id} not found")
                scheduled_at = row[0]
                if scheduled_at is None:
                    raise ValueError(
                        f"Document {document_id} is not soft-deleted"
                    )
                cur.execute(
                    """
                    UPDATE documents
                    SET deleted_at = NULL,
                        deletion_scheduled_at = NULL
                    WHERE id = %(doc_id)s::uuid
                      AND deletion_scheduled_at > now() - interval '48 hours'
                    """,
                    {"doc_id": document_id},
                )
                if cur.rowcount == 0:
                    raise ValueError(
                        f"Document {document_id} is outside the 48h "
                        f"restore window"
                    )
            conn.commit()

    def soft_delete_collection(self, collection_name: str) -> int:
        """Soft-delete all active documents in a collection.

        Only touches rows where `deleted_at IS NULL` so documents that were
        individually deleted earlier keep their original
        `deletion_scheduled_at` (the 48h restore clock is not reset).

        Returns the number of documents marked.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE documents
                    SET deleted_at = now(),
                        deletion_scheduled_at = now()
                    WHERE collection_id =
                              (SELECT id FROM collections
                               WHERE name = %(collection)s)
                      AND deleted_at IS NULL
                    """,
                    {"collection": collection_name},
                )
                marked = cur.rowcount
            conn.commit()
        return marked

    def restore_collection(self, collection_name: str) -> int:
        """Restore soft-deleted documents in a collection within the 48h
        grace window.

        Documents whose `deletion_scheduled_at` is already older than 48
        hours stay deleted (they will be purged by `purge_deleted`).

        Returns the number of documents restored.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE documents
                    SET deleted_at = NULL,
                        deletion_scheduled_at = NULL
                    WHERE collection_id =
                              (SELECT id FROM collections
                               WHERE name = %(collection)s)
                      AND deleted_at IS NOT NULL
                      AND deletion_scheduled_at > now() - interval '48 hours'
                    """,
                    {"collection": collection_name},
                )
                restored = cur.rowcount
            conn.commit()
        return restored

    def purge_deleted(self, older_than_hours: int = 48) -> int:
        """Hard-delete documents whose deletion_scheduled_at is older than
        the threshold. Chunks and interactions cascade via FK.

        When ``older_than_hours <= 0``, purges every soft-deleted row
        regardless of timing. This is what the ``DELETE
        /api/collections/{name}?purge=true`` route relies on to empty a
        collection in a single request — the interval check would
        otherwise miss rows that were marked microseconds earlier.

        Returns the number of documents purged.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if older_than_hours <= 0:
                    cur.execute(
                        """
                        DELETE FROM documents
                        WHERE deleted_at IS NOT NULL
                        """
                    )
                else:
                    cur.execute(
                        """
                        DELETE FROM documents
                        WHERE deletion_scheduled_at IS NOT NULL
                          AND deletion_scheduled_at
                              < now() - make_interval(hours => %(hrs)s)
                        """,
                        {"hrs": older_than_hours},
                    )
                purged = cur.rowcount
            conn.commit()
        return purged

    def update_document_metadata(
        self,
        document_id: str,
        tags: list[str] | None = None,
        agent_metadata: dict[str, Any] | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Partially update a document's metadata.

        - `tags` REPLACES the full tag list when provided.
        - `agent_metadata` is shallow-merged into the existing metadata
          JSONB (new keys added, existing keys overwritten, unmentioned
          keys preserved).
        - `collection` moves the document to another collection; the
          chunks belonging to this document are moved along with it. The
          target collection is created if it doesn't exist.

        Returns a dict with the post-update document metadata.
        """
        import json as _json

        with self._pool.connection() as conn:
            if collection is not None:
                self._ensure_collection(conn, collection)
            with conn.cursor() as cur:
                set_clauses: list[str] = ["updated_at = now()"]
                params: dict[str, Any] = {"doc_id": document_id}

                if tags is not None:
                    set_clauses.append("tags = %(tags)s")
                    params["tags"] = tags

                if agent_metadata is not None:
                    set_clauses.append(
                        "metadata = COALESCE(metadata, '{}'::jsonb) "
                        "|| %(agent_metadata)s::jsonb"
                    )
                    params["agent_metadata"] = _json.dumps(agent_metadata)

                if collection is not None:
                    set_clauses.append(
                        "collection_id = "
                        "(SELECT id FROM collections WHERE name = %(collection)s)"
                    )
                    params["collection"] = collection

                cur.execute(
                    f"""
                    UPDATE documents
                    SET {', '.join(set_clauses)}
                    WHERE id = %(doc_id)s::uuid
                    RETURNING id, collection_id, source_file, file_type,
                              tags, metadata
                    """,
                    params,
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"Document {document_id} not found")

                if collection is not None:
                    # Keep chunks aligned with their parent document's
                    # collection so search filters stay consistent.
                    cur.execute(
                        """
                        UPDATE chunks
                        SET collection_id =
                            (SELECT id FROM collections
                             WHERE name = %(collection)s)
                        WHERE document_id = %(doc_id)s::uuid
                        """,
                        {
                            "collection": collection,
                            "doc_id": document_id,
                        },
                    )

                # Resolve collection name for the return payload.
                cur.execute(
                    """
                    SELECT col.name
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE d.id = %(doc_id)s::uuid
                    """,
                    {"doc_id": document_id},
                )
                col_name_row = cur.fetchone()
                collection_name = col_name_row[0] if col_name_row else None

                # Latest-wins source_reference propagation — mirror of
                # record_interaction so PATCH can overwrite the column
                # without going through a new interaction row.
                src_ref = _extract_source_reference(agent_metadata)
                if src_ref is not None:
                    cur.execute(
                        """
                        UPDATE documents
                        SET source_reference = %(src_ref)s
                        WHERE id = %(doc_id)s::uuid
                        """,
                        {"src_ref": src_ref, "doc_id": document_id},
                    )

            conn.commit()

        return {
            "document_id": str(row[0]),
            "collection": collection_name,
            "source_file": row[2],
            "file_type": row[3],
            "tags": row[4] or [],
            "agent_metadata": row[5] or {},
        }


def _row_to_stored_document(row, collection_name: str) -> StoredDocument:
    """Convert a database row tuple to a StoredDocument.

    Row column order (must match every SELECT that calls this helper):
    id, collection_id, source_file, content_fingerprint, file_type,
    engine, markdown, title, processing_time_ms, output_tokens_estimate,
    token_savings_ratio, processing_chain, tags, warnings, created_at.
    """
    return StoredDocument(
        document_id=str(row[0]),
        collection_id=collection_name,
        source_file=row[2],
        content_fingerprint=row[3] or "",
        file_type=row[4],
        engine=row[5],
        markdown=row[6] or "",
        title=row[7],
        processing_time_ms=row[8] or 0,
        output_tokens_estimate=row[9] or 0,
        token_savings_ratio=row[10],
        processing_chain=row[11] or [],
        tags=row[12] or [],
        warnings=row[13] or [],
        created_at=row[14].isoformat() if hasattr(row[14], "isoformat") else str(row[14]),
    )


class InMemoryDedupStore:
    """In-memory dedup store for Phase 1 (no Postgres yet)."""

    def __init__(self) -> None:
        # Key: (collection, fingerprint) -> StoredDocument
        self._documents: dict[tuple[str, str], StoredDocument] = {}
        # Key: document_id -> list of interactions
        self._interactions: dict[str, list[DocumentInteraction]] = {}
        self._search_log: list[SearchLogEntry] = []
        # Key: document_id -> (deleted_at, deletion_scheduled_at) datetimes
        self._deletions: dict[str, tuple[datetime, datetime]] = {}
        # Key: document_id -> metadata dict (for update_document_metadata)
        self._doc_metadata: dict[str, dict[str, Any]] = {}
        # Latest agent_metadata.source_reference per document, for symmetry
        # with the Pg documents.source_reference column. Latest-wins.
        self._doc_source_ref: dict[str, str] = {}

    def _is_deleted(self, doc: StoredDocument) -> bool:
        return doc.document_id in self._deletions

    def find_by_fingerprint(
        self,
        collection: str,
        fingerprint: str,
        include_deleted: bool = False,
    ) -> StoredDocument | None:
        doc = self._documents.get((collection, fingerprint))
        if doc is None:
            return None
        if not include_deleted and self._is_deleted(doc):
            return None
        return doc

    def store_document(self, doc: StoredDocument) -> bool:
        """Insert or upsert a document.

        Returns True if the upsert resurrected a previously soft-deleted row
        at the same (collection, fingerprint) key.
        """
        key = (doc.collection_id, doc.content_fingerprint)
        prior = self._documents.get(key)
        was_resurrected = bool(prior and prior.document_id in self._deletions)
        if was_resurrected:
            # Clear the old doc's deletion entry so future queries see the
            # resurrected content as active.
            del self._deletions[prior.document_id]
        self._documents[key] = doc
        return was_resurrected

    def record_interaction(self, interaction: DocumentInteraction) -> None:
        self._interactions.setdefault(interaction.document_id, []).append(interaction)
        src_ref = _extract_source_reference(interaction.agent_metadata)
        if src_ref is not None:
            self._doc_source_ref[interaction.document_id] = src_ref

    def get_source_reference(self, document_id: str) -> str | None:
        """Return the latest-wins source_reference for this document, if any."""
        return self._doc_source_ref.get(document_id)

    def get_interactions(self, document_id: str) -> list[DocumentInteraction]:
        return self._interactions.get(document_id, [])

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
        """In-memory analogue of PgDedupStore.list_documents with symmetric filters."""
        docs = list(self._documents.values())

        if not include_deleted:
            docs = [d for d in docs if d.document_id not in self._deletions]
        if collection:
            docs = [d for d in docs if d.collection_id == collection]
        if file_type:
            ft = file_type.lstrip(".")
            docs = [d for d in docs if d.file_type == ft]
        if tag is not None:
            docs = [d for d in docs if d.tags and tag in d.tags]
        if has_warnings is True:
            docs = [d for d in docs if d.warnings]
        elif has_warnings is False:
            docs = [d for d in docs if not d.warnings]
        if has_source_reference is not None:
            def _has_src_ref(doc_id: str) -> bool:
                val = self._doc_source_ref.get(doc_id)
                return bool(val) and val != "unknown"
            docs = [
                d for d in docs
                if _has_src_ref(d.document_id) == has_source_reference
            ]

        # Mirror the Pg ORDER BY d.created_at DESC. Python sort is stable,
        # so rows with identical created_at keep insertion order.
        docs.sort(key=lambda d: d.created_at, reverse=True)

        total = len(docs)
        return docs[offset:offset + limit], total

    def record_search(self, entry: SearchLogEntry) -> None:
        self._search_log.append(entry)

    def soft_delete_document(self, document_id: str) -> None:
        now = datetime.now(timezone.utc)
        self._deletions[document_id] = (now, now)

    def restore_document(self, document_id: str) -> None:
        from datetime import timedelta
        entry = self._deletions.get(document_id)
        if entry is None:
            raise ValueError(f"Document {document_id} is not soft-deleted")
        _deleted_at, scheduled_at = entry
        if datetime.now(timezone.utc) - scheduled_at > timedelta(hours=48):
            raise ValueError(
                f"Document {document_id} is outside the 48h restore window"
            )
        del self._deletions[document_id]

    def soft_delete_collection(self, collection_name: str) -> int:
        now = datetime.now(timezone.utc)
        marked = 0
        for (coll, _fp), doc in self._documents.items():
            if coll != collection_name:
                continue
            if doc.document_id in self._deletions:
                # Individually-deleted doc keeps its original clock.
                continue
            self._deletions[doc.document_id] = (now, now)
            marked += 1
        return marked

    def restore_collection(self, collection_name: str) -> int:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        window = timedelta(hours=48)
        restored = 0
        for (coll, _fp), doc in self._documents.items():
            if coll != collection_name:
                continue
            entry = self._deletions.get(doc.document_id)
            if entry is None:
                continue
            _deleted_at, scheduled_at = entry
            if now - scheduled_at <= window:
                del self._deletions[doc.document_id]
                restored += 1
        return restored

    def purge_deleted(self, older_than_hours: int = 48) -> int:
        from datetime import timedelta
        if older_than_hours <= 0:
            to_purge = list(self._deletions.keys())
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            to_purge = [
                doc_id
                for doc_id, (_del, scheduled) in self._deletions.items()
                if scheduled < cutoff
            ]
        for doc_id in to_purge:
            del self._deletions[doc_id]
            self._interactions.pop(doc_id, None)
            self._doc_metadata.pop(doc_id, None)
            self._doc_source_ref.pop(doc_id, None)
            # Drop from _documents too
            for key, doc in list(self._documents.items()):
                if doc.document_id == doc_id:
                    del self._documents[key]
        return len(to_purge)

    def update_document_metadata(
        self,
        document_id: str,
        tags: list[str] | None = None,
        agent_metadata: dict[str, Any] | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]:
        target_doc: StoredDocument | None = None
        target_key: tuple[str, str] | None = None
        for key, doc in self._documents.items():
            if doc.document_id == document_id:
                target_doc = doc
                target_key = key
                break
        if target_doc is None or target_key is None:
            raise ValueError(f"Document {document_id} not found")

        if tags is not None:
            target_doc.tags = list(tags)

        if agent_metadata is not None:
            existing = self._doc_metadata.setdefault(document_id, {})
            existing.update(agent_metadata)
            src_ref = _extract_source_reference(agent_metadata)
            if src_ref is not None:
                self._doc_source_ref[document_id] = src_ref

        if collection is not None and collection != target_doc.collection_id:
            del self._documents[target_key]
            target_doc.collection_id = collection
            self._documents[(collection, target_doc.content_fingerprint)] = (
                target_doc
            )

        return {
            "document_id": target_doc.document_id,
            "collection": target_doc.collection_id,
            "source_file": target_doc.source_file,
            "file_type": target_doc.file_type,
            "tags": target_doc.tags,
            "agent_metadata": self._doc_metadata.get(document_id, {}),
        }
