"""Ariadne Core client data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Health:
    """Server health check response."""
    status: str = ""
    version: str = ""
    engine: str = ""
    embedding_enabled: bool = False

    def __repr__(self) -> str:
        return f"Health(status={self.status!r}, version={self.version!r}, embedding={self.embedding_enabled})"


@dataclass
class UploadResult:
    """Response from file upload."""
    path: str = ""
    filename: str = ""
    size_bytes: int = 0


@dataclass
class Interaction:
    """A single agent interaction record."""
    agent_id: str | None = None
    agent_type: str | None = None
    model: str | None = None
    initiated_by: str | None = None
    agent_notes: str | None = None
    agent_metadata: dict[str, Any] | None = None
    action: str | None = None
    was_dedup_skip: bool = False
    created_at: str | None = None


@dataclass
class Document:
    """A processed document."""
    document_id: str = ""
    source_file: str = ""
    title: str | None = None
    file_type: str | None = None
    engine: str | None = None
    content_fingerprint: str | None = None
    collection: str | None = None
    markdown: str | None = None
    chunks_count: int = 0
    was_dedup_skip: bool = False
    warnings: list[str] = field(default_factory=list)
    warnings_count: int | None = None
    processing_time_ms: int | None = None
    output_tokens_estimate: int | None = None
    token_savings_ratio: float | None = None
    token_savings: dict[str, Any] | None = None
    embedding_model: str | None = None
    store_status: str | None = None
    interactions: list[Interaction] = field(default_factory=list)
    provenance: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    # For list_documents responses (metadata only)
    chunk_count: int | None = None
    interaction_count: int | None = None
    created_at: str | None = None

    def __repr__(self) -> str:
        md_preview = ""
        if self.markdown:
            md_preview = self.markdown[:80] + "..." if len(self.markdown) > 80 else self.markdown
        return (
            f"Document(id={self.document_id!r}, file={self.source_file!r}, "
            f"collection={self.collection!r}, chunks={self.chunks_count}, "
            f"dedup={self.was_dedup_skip}, preview={md_preview!r})"
        )


@dataclass
class SearchResult:
    """A single search result (one chunk)."""
    chunk_id: str = ""
    document_id: str = ""
    collection: str | None = None
    text: str = ""
    section: str | None = None
    page: int | None = None
    token_count: int = 0
    relevance_score: float = 0.0
    embedding_model: str | None = None
    interactions: list[Interaction] = field(default_factory=list)

    def __repr__(self) -> str:
        text_preview = self.text[:80] + "..." if len(self.text) > 80 else self.text
        return (
            f"SearchResult(score={self.relevance_score:.4f}, doc={self.document_id!r}, "
            f"section={self.section!r}, text={text_preview!r})"
        )


@dataclass
class SearchResponse:
    """Full search response."""
    query: str = ""
    top_k: int = 5
    collection: str | None = None
    results_count: int = 0
    results: list[SearchResult] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"SearchResponse(query={self.query!r}, results={self.results_count})"

    def __iter__(self):
        return iter(self.results)

    def __len__(self):
        return len(self.results)


@dataclass
class Collection:
    """A document collection."""
    name: str = ""
    description: str | None = None
    document_count: int = 0

    def __repr__(self) -> str:
        return f"Collection(name={self.name!r}, docs={self.document_count})"


@dataclass
class DocumentListPage:
    """Paginated response from list_documents.

    Iterates as its `documents` list so `for d in page: ...` and
    `len(page)` work like the old `list[Document]` return type.
    """
    documents: list[Document] = field(default_factory=list)
    total_count: int = 0
    total_is_exact: bool = True
    limit: int = 0
    offset: int = 0

    def __iter__(self):
        return iter(self.documents)

    def __len__(self):
        return len(self.documents)

    def __getitem__(self, idx):
        return self.documents[idx]

    def __repr__(self) -> str:
        exact = "" if self.total_is_exact else "~"
        return (
            f"DocumentListPage(docs={len(self.documents)}, "
            f"total={exact}{self.total_count}, "
            f"limit={self.limit}, offset={self.offset})"
        )


@dataclass
class AggregateBucket:
    """One row of an aggregate response."""
    group: str | None
    count: int


@dataclass
class AggregateResponse:
    """Response from /api/documents/aggregate."""
    group_by: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    buckets: list[AggregateBucket] = field(default_factory=list)
    total_buckets: int = 0
    total_documents: int = 0

    def __iter__(self):
        return iter(self.buckets)

    def __len__(self):
        return len(self.buckets)

    def __repr__(self) -> str:
        return (
            f"AggregateResponse(group_by={self.group_by!r}, "
            f"buckets={self.total_buckets}, "
            f"docs={self.total_documents})"
        )


@dataclass
class QuerySchema:
    """Discovery response from /api/documents/schema.

    Fields are dicts of `{name: description}` as returned by the
    server. Treat this as documentation metadata — inspect it, don't
    mutate it.
    """
    list_endpoint: str = ""
    aggregate_endpoint: str = ""
    filters: dict[str, str] = field(default_factory=dict)
    includes: dict[str, str] = field(default_factory=dict)
    aggregatable_fields: dict[str, str] = field(default_factory=dict)
    caps: dict[str, int] = field(default_factory=dict)
    brute_force_fallback: str = ""
    deferred: dict[str, str] = field(default_factory=dict)


@dataclass
class Stats:
    """System statistics."""
    total_documents: int = 0
    total_chunks: int = 0
    total_collections: int = 0
    embedding_enabled: bool = False
    collections: dict[str, int] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"Stats(docs={self.total_documents}, chunks={self.total_chunks}, "
            f"collections={self.total_collections}, embedding={self.embedding_enabled})"
        )


@dataclass
class IngestSummary:
    """Batch ingestion summary."""
    files_found: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"IngestSummary(found={self.files_found}, processed={self.files_processed}, "
            f"skipped={self.files_skipped}, errored={self.files_errored})"
        )
