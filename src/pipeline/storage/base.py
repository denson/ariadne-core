"""Vector store abstraction layer.

Defines the VectorStore protocol and provides an InMemoryVectorStore
for Phase 1 (before Postgres/pgvector is wired in Step 5).

The protocol supports insert, search, delete, and count operations.
Implementations: InMemoryVectorStore (Phase 1), PgVectorStore (Phase 5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipeline.chunking.chunker import Chunk


@dataclass
class SearchResult:
    """A single search result with relevance score."""

    chunk: Chunk
    score: float
    document_id: str
    collection_id: str


class VectorStore(Protocol):
    """Protocol for vector store backends."""

    def insert(self, chunks: list[Chunk]) -> None: ...

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
    ) -> list[SearchResult]: ...

    def delete(self, chunk_ids: list[str]) -> None: ...

    def delete_by_document(self, document_id: str) -> None: ...

    def count(
        self,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
    ) -> int: ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    """In-memory vector store for Phase 1.

    Stores chunks in a dict and performs brute-force cosine similarity
    search. Suitable for development and testing. Phase 5 swaps this
    for PgVectorStore.
    """

    def __init__(self) -> None:
        # chunk_id -> Chunk
        self._chunks: dict[str, Chunk] = {}

    def insert(self, chunks: list[Chunk]) -> None:
        """Insert chunks into the store."""
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
    ) -> list[SearchResult]:
        """Search for chunks similar to the query embedding.

        Args:
            query_embedding: The query vector.
            top_k: Maximum number of results.
            filters: Optional filters (collection, document_id, file_type).
            include_deleted: In-memory store has no soft-delete concept,
                so this flag is a no-op for parity with PgVectorStore.

        Returns:
            List of SearchResult sorted by descending similarity.
        """
        candidates = self._apply_filters(filters)

        scored: list[tuple[float, Chunk]] = []
        for chunk in candidates:
            if chunk.embedding is None:
                continue
            score = _cosine_similarity(query_embedding, chunk.embedding)
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(
                chunk=chunk,
                score=score,
                document_id=chunk.document_id,
                collection_id=chunk.collection_id,
            )
            for score, chunk in scored[:top_k]
        ]

    def delete(self, chunk_ids: list[str]) -> None:
        """Delete chunks by ID."""
        for cid in chunk_ids:
            self._chunks.pop(cid, None)

    def delete_by_document(self, document_id: str) -> None:
        """Delete all chunks belonging to a document."""
        to_delete = [
            cid
            for cid, chunk in self._chunks.items()
            if chunk.document_id == document_id
        ]
        for cid in to_delete:
            del self._chunks[cid]

    def count(
        self,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count chunks matching optional filters.

        `include_deleted` is a no-op for the in-memory store.
        """
        return len(self._apply_filters(filters))

    def _apply_filters(self, filters: dict[str, Any] | None) -> list[Chunk]:
        """Apply filters to the chunk collection."""
        candidates = list(self._chunks.values())

        if not filters:
            return candidates

        if "collection" in filters:
            candidates = [
                c for c in candidates if c.collection_id == filters["collection"]
            ]

        if "document_id" in filters:
            candidates = [
                c for c in candidates if c.document_id == filters["document_id"]
            ]

        return candidates
