"""Dedup gate — SHA-256 fingerprinting and collision detection.

Normalizes extracted text (lowercase, trimmed, collapsed whitespace),
computes SHA-256, and checks against a store. In Phase 1 this uses an
in-memory store; Phase 5 will swap in Postgres (documents table with
unique index on collection_id + content_fingerprint).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def normalize_text(text: str) -> str:
    """Normalize text for fingerprinting: lowercase, trim, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def compute_fingerprint(text: str) -> str:
    """Compute SHA-256 fingerprint of normalized text."""
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
        self, collection: str, fingerprint: str
    ) -> StoredDocument | None: ...

    def store_document(self, doc: StoredDocument) -> None: ...

    def record_interaction(self, interaction: DocumentInteraction) -> None: ...

    def get_interactions(self, document_id: str) -> list[DocumentInteraction]: ...

    def record_search(self, entry: SearchLogEntry) -> None: ...


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
        self, collection: str, fingerprint: str
    ) -> StoredDocument | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id, d.collection_id, d.source_file,
                           d.content_fingerprint, d.file_type, d.engine,
                           d.markdown, d.title, d.processing_time_ms,
                           d.output_tokens_estimate, d.token_savings_ratio,
                           d.processing_chain, d.tags, d.created_at
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE col.name = %(collection)s
                      AND d.content_fingerprint = %(fp)s
                    LIMIT 1
                    """,
                    {"collection": collection, "fp": fingerprint},
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return _row_to_stored_document(row, collection)

    def store_document(self, doc: StoredDocument) -> None:
        import json as _json
        with self._pool.connection() as conn:
            self._ensure_collection(conn, doc.collection_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (
                        id, collection_id, source_file, content_fingerprint,
                        file_type, engine, markdown, title,
                        processing_time_ms, output_tokens_estimate,
                        token_savings_ratio, processing_chain, tags
                    ) VALUES (
                        %(id)s::uuid,
                        (SELECT id FROM collections WHERE name = %(collection)s),
                        %(source_file)s, %(fingerprint)s,
                        %(file_type)s, %(engine)s, %(markdown)s, %(title)s,
                        %(processing_time_ms)s, %(output_tokens_estimate)s,
                        %(token_savings_ratio)s, %(processing_chain)s::jsonb,
                        %(tags)s
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
                    },
                )
                row = cur.fetchone()
                if row:
                    # Update the doc's id to match what's actually in Postgres
                    # (may differ on conflict/force re-process)
                    doc.document_id = str(row[0])
            conn.commit()

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

    def get_document_by_id(self, document_id: str) -> StoredDocument | None:
        """Retrieve a document by its UUID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id, d.collection_id, d.source_file,
                           d.content_fingerprint, d.file_type, d.engine,
                           d.markdown, d.title, d.processing_time_ms,
                           d.output_tokens_estimate, d.token_savings_ratio,
                           d.processing_chain, d.tags, d.created_at,
                           col.name
                    FROM documents d
                    JOIN collections col ON d.collection_id = col.id
                    WHERE d.id = %(doc_id)s::uuid
                    LIMIT 1
                    """,
                    {"doc_id": document_id},
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return _row_to_stored_document(row[:14], row[14])

    def list_documents(
        self,
        collection: str | None = None,
        file_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[StoredDocument], int]:
        """List documents with pagination. Returns (docs, total_count)."""
        where_clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if collection:
            where_clauses.append("col.name = %(collection)s")
            params["collection"] = collection
        if file_type:
            ft = file_type.lstrip(".")
            where_clauses.append("d.file_type = %(file_type)s")
            params["file_type"] = ft

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

                cur.execute(
                    f"""
                    SELECT d.id, d.collection_id, d.source_file,
                           d.content_fingerprint, d.file_type, d.engine,
                           d.markdown, d.title, d.processing_time_ms,
                           d.output_tokens_estimate, d.token_savings_ratio,
                           d.processing_chain, d.tags, d.created_at,
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
                    _row_to_stored_document(row[:14], row[14])
                    for row in cur.fetchall()
                ]
        return docs, total


def _row_to_stored_document(row, collection_name: str) -> StoredDocument:
    """Convert a database row tuple to a StoredDocument."""
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
        created_at=row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13]),
    )


class InMemoryDedupStore:
    """In-memory dedup store for Phase 1 (no Postgres yet)."""

    def __init__(self) -> None:
        # Key: (collection, fingerprint) -> StoredDocument
        self._documents: dict[tuple[str, str], StoredDocument] = {}
        # Key: document_id -> list of interactions
        self._interactions: dict[str, list[DocumentInteraction]] = {}
        self._search_log: list[SearchLogEntry] = []

    def find_by_fingerprint(
        self, collection: str, fingerprint: str
    ) -> StoredDocument | None:
        return self._documents.get((collection, fingerprint))

    def store_document(self, doc: StoredDocument) -> None:
        self._documents[(doc.collection_id, doc.content_fingerprint)] = doc

    def record_interaction(self, interaction: DocumentInteraction) -> None:
        self._interactions.setdefault(interaction.document_id, []).append(interaction)

    def get_interactions(self, document_id: str) -> list[DocumentInteraction]:
        return self._interactions.get(document_id, [])

    def record_search(self, entry: SearchLogEntry) -> None:
        self._search_log.append(entry)
