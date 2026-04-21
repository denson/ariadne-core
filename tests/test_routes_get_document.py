"""BL-26: GET /api/documents/{document_id} surfaces warnings + warnings_count.

list_documents already returned warnings_count per row; by-id was missing
both the list and the count. This test pins parity between the two shapes.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.routes import router
from pipeline.dedup import InMemoryDedupStore, StoredDocument, compute_fingerprint
from pipeline.storage.base import InMemoryVectorStore

from tests.conftest import override_auth


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    override_auth(app)
    return app


def _make_doc(
    collection: str,
    source_file: str,
    content: str,
    *,
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
        tags=[],
        warnings=list(warnings or []),
    )


def test_get_document_includes_warnings_and_count():
    app = _build_app()
    client = TestClient(app)
    dedup = InMemoryDedupStore()
    vector = InMemoryVectorStore()
    services.configure_stores(dedup, vector)
    collection = f"bl26-{uuid.uuid4().hex[:8]}"

    clean = _make_doc(collection, "clean.txt", "ok", warnings=[])
    dirty = _make_doc(
        collection,
        "dirty.txt",
        "uhoh",
        warnings=["NUL (0x00) byte stripped: count=3", "encoding fallback"],
    )
    dedup.store_document(clean)
    dedup.store_document(dirty)

    resp = client.get(f"/api/documents/{clean.document_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"] == []
    assert body["warnings_count"] == 0

    resp = client.get(f"/api/documents/{dirty.document_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"] == [
        "NUL (0x00) byte stripped: count=3",
        "encoding fallback",
    ]
    assert body["warnings_count"] == 2
