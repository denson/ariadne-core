"""Tests for Query API Pass 1 — filters, includes, cap on GET /api/documents.

Covers the new surfaces added in this pass:
  - `tag` and `has_warnings` filter params
  - `include=` repeatable query param (agent_metadata, tags, last_interaction, markdown)
  - Shape-dependent limit cap (50 with markdown, 500 otherwise)
  - New cheap default-row field: `warnings_count`
  - `total_is_exact` response flag

All tests use the InMemory store path — no Postgres required.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.auth import set_require_auth
from pipeline.api.routes import router
from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.storage.base import InMemoryVectorStore


def _build_app() -> FastAPI:
    set_require_auth(False)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _make_doc(
    collection: str,
    source_file: str,
    content: str,
    *,
    tags: list[str] | None = None,
    warnings: list[str] | None = None,
) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint(content),
        file_type="txt",
        engine="markitdown",
        markdown=content,
        title=source_file,
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[],
        tags=list(tags or []),
        warnings=list(warnings or []),
    )


class _Fixture:
    """Per-test harness — fresh in-memory stores + mounted FastAPI + TestClient."""

    def __init__(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app)
        self.dedup = InMemoryDedupStore()
        self.vector = InMemoryVectorStore()
        services.configure_stores(self.dedup, self.vector)
        self.collection = f"t_{uuid.uuid4().hex[:8]}"


def test_list_documents_default_shape_has_warnings_count():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha"))

    resp = f.client.get(f"/api/documents?collection={f.collection}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["documents"]) == 1
    row = body["documents"][0]
    expected_fields = {
        "document_id", "source_file", "title", "file_type", "collection",
        "content_fingerprint", "chunk_count", "interaction_count",
        "created_at", "warnings_count",
    }
    assert set(row.keys()) == expected_fields, row
    assert row["warnings_count"] == 0


def test_list_documents_tag_filter_matches_only_tagged():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha", tags=["keep"]))
    f.dedup.store_document(_make_doc(f.collection, "b.txt", "beta", tags=["drop"]))
    f.dedup.store_document(_make_doc(f.collection, "c.txt", "gamma"))

    resp = f.client.get(f"/api/documents?collection={f.collection}&tag=keep")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sources = [d["source_file"] for d in body["documents"]]
    assert sources == ["a.txt"]


def test_list_documents_has_warnings_true():
    f = _Fixture()
    f.dedup.store_document(
        _make_doc(f.collection, "clean.txt", "ok", warnings=[])
    )
    f.dedup.store_document(
        _make_doc(f.collection, "dirty.txt", "uhoh", warnings=["bad bytes"])
    )

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&has_warnings=true"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sources = [d["source_file"] for d in body["documents"]]
    assert sources == ["dirty.txt"]


def test_list_documents_has_warnings_false():
    f = _Fixture()
    f.dedup.store_document(
        _make_doc(f.collection, "clean.txt", "ok", warnings=[])
    )
    f.dedup.store_document(
        _make_doc(f.collection, "dirty.txt", "uhoh", warnings=["bad bytes"])
    )

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&has_warnings=false"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sources = [d["source_file"] for d in body["documents"]]
    assert sources == ["clean.txt"]


def test_list_documents_has_source_reference_true():
    """has_source_reference filter returns only docs whose latest interaction
    carries a non-empty source_reference (not the literal 'unknown')."""
    f = _Fixture()
    doc_a = _make_doc(f.collection, "a.txt", "alpha")
    doc_b = _make_doc(f.collection, "b.txt", "beta")
    f.dedup.store_document(doc_a)
    f.dedup.store_document(doc_b)
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc_a.document_id,
            collection_id=f.collection,
            agent_metadata={"source_reference": "doi:10.1/abc"},
        )
    )
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc_b.document_id,
            collection_id=f.collection,
            agent_metadata={"source_reference": "unknown"},
        )
    )

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&has_source_reference=true"
    )
    assert resp.status_code == 200, resp.text
    sources = [d["source_file"] for d in resp.json()["documents"]]
    assert sources == ["a.txt"]

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&has_source_reference=false"
    )
    assert resp.status_code == 200, resp.text
    sources = [d["source_file"] for d in resp.json()["documents"]]
    assert sources == ["b.txt"]


def test_list_documents_include_tags_adds_field():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha", tags=["x", "y"]))

    # Without include → tags field is absent.
    resp = f.client.get(f"/api/documents?collection={f.collection}")
    assert "tags" not in resp.json()["documents"][0]

    # With include=tags → tags field present and populated.
    resp = f.client.get(
        f"/api/documents?collection={f.collection}&include=tags"
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()["documents"][0]
    assert row["tags"] == ["x", "y"]


def test_list_documents_include_markdown_caps_limit_at_50():
    f = _Fixture()
    # One doc is enough — the cap validation fires before any row work.
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha"))

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&include=markdown&limit=51"
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["cap_applied"] == 50
    assert "markdown" in detail["include_set"]

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&include=markdown&limit=50"
    )
    assert resp.status_code == 200, resp.text


def test_list_documents_without_markdown_allows_limit_500():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha"))

    resp = f.client.get(f"/api/documents?collection={f.collection}&limit=500")
    assert resp.status_code == 200, resp.text

    resp = f.client.get(f"/api/documents?collection={f.collection}&limit=501")
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["cap_applied"] == 500


def test_list_documents_unknown_include_returns_400_with_valid_list():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha"))

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&include=bogus"
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "valid_includes" in detail
    assert set(detail["valid_includes"]) == {
        "agent_metadata", "tags", "last_interaction", "markdown"
    }


def test_list_documents_include_agent_metadata_pulls_from_latest_interaction():
    f = _Fixture()
    doc = _make_doc(f.collection, "a.txt", "alpha")
    f.dedup.store_document(doc)

    # Two interactions — the second one's metadata is what the caller should see.
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=f.collection,
            agent_metadata={"step": "first"},
        )
    )
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc.document_id,
            collection_id=f.collection,
            agent_metadata={"step": "second"},
        )
    )

    resp = f.client.get(
        f"/api/documents?collection={f.collection}&include=agent_metadata"
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()["documents"][0]
    assert row["agent_metadata"] == {"step": "second"}


def test_list_documents_total_is_exact_flag():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha", tags=["keep"]))
    f.dedup.store_document(_make_doc(f.collection, "b.txt", "beta"))

    # No filter → total_is_exact is true.
    resp = f.client.get(f"/api/documents?collection={f.collection}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_is_exact"] is True

    # Pass 4: filters are pushed into the store, so total_is_exact stays true
    # even under a tag filter (or any other filter).
    resp = f.client.get(f"/api/documents?collection={f.collection}&tag=keep")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_is_exact"] is True
    assert body["total_count"] == 1
    assert [d["source_file"] for d in body["documents"]] == ["a.txt"]


def test_list_documents_pagination_under_filter():
    """Pass 4 pin: with filters pushed into the store, total_count reflects
    the full filtered size (not the page), pagination is honored, and
    total_is_exact is true."""
    f = _Fixture()
    # 30 docs total, 10 of them with warnings.
    for i in range(30):
        warnings = ["bad"] if i < 10 else []
        f.dedup.store_document(
            _make_doc(
                f.collection,
                f"doc_{i:02d}.txt",
                f"content {i}",
                warnings=warnings,
            )
        )

    resp = f.client.get(
        f"/api/documents?collection={f.collection}"
        "&has_warnings=true&limit=5&offset=5"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 10
    assert body["total_is_exact"] is True
    assert len(body["documents"]) == 5
    for row in body["documents"]:
        assert row["warnings_count"] >= 1
