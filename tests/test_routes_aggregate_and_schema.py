"""Tests for Query API Pass 2 — /documents/aggregate, /documents/schema,
and rich 400 on unknown query params.

All tests use the InMemory store path — no Postgres required.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.routes import (
    _AGGREGATE_REGISTRY,
    _FILTER_REGISTRY,
    router,
)
from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    StoredDocument,
    compute_fingerprint,
)
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
    file_type: str = "txt",
    tags: list[str] | None = None,
    warnings: list[str] | None = None,
) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint((content + source_file).encode("utf-8")),
        file_type=file_type,
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
    def __init__(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app)
        self.dedup = InMemoryDedupStore()
        self.vector = InMemoryVectorStore()
        services.configure_stores(self.dedup, self.vector)
        self.collection = f"t_{uuid.uuid4().hex[:8]}"


# ── aggregate ────────────────────────────────────────────────────────────────


def test_aggregate_group_by_file_type_returns_counts():
    f = _Fixture()
    for i in range(3):
        f.dedup.store_document(
            _make_doc(f.collection, f"a{i}.pdf", f"alpha{i}", file_type="pdf")
        )
    for i in range(2):
        f.dedup.store_document(
            _make_doc(f.collection, f"b{i}.docx", f"beta{i}", file_type="docx")
        )

    resp = f.client.get(
        f"/api/documents/aggregate?collection={f.collection}&group_by=file_type"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["group_by"] == "file_type"
    assert body["buckets"] == [
        {"group": "pdf", "count": 3},
        {"group": "docx", "count": 2},
    ]
    assert body["total_buckets"] == 2
    assert body["total_documents"] == 5


def test_aggregate_group_by_collection_respects_collection_filter():
    f = _Fixture()
    coll_a = f"a_{uuid.uuid4().hex[:6]}"
    coll_b = f"b_{uuid.uuid4().hex[:6]}"
    f.dedup.store_document(_make_doc(coll_a, "a.txt", "alpha"))
    f.dedup.store_document(_make_doc(coll_b, "b.txt", "beta"))

    resp = f.client.get(
        f"/api/documents/aggregate?group_by=collection&collection={coll_a}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["buckets"] == [{"group": coll_a, "count": 1}]
    assert body["filters"] == {"collection": coll_a}


def test_aggregate_group_by_tags_splits_multi_tag_docs():
    f = _Fixture()
    f.dedup.store_document(
        _make_doc(f.collection, "a.txt", "alpha", tags=["x", "y"])
    )
    f.dedup.store_document(
        _make_doc(f.collection, "b.txt", "beta", tags=["x"])
    )

    resp = f.client.get(
        f"/api/documents/aggregate?collection={f.collection}&group_by=tags"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["buckets"] == [
        {"group": "x", "count": 2},
        {"group": "y", "count": 1},
    ]
    # total_documents is distinct-doc count for tags, not sum-of-buckets.
    assert body["total_documents"] == 2


def test_aggregate_group_by_tags_skips_no_tag_docs():
    f = _Fixture()
    f.dedup.store_document(_make_doc(f.collection, "a.txt", "alpha"))
    f.dedup.store_document(
        _make_doc(f.collection, "b.txt", "beta", tags=["x"])
    )

    resp = f.client.get(
        f"/api/documents/aggregate?collection={f.collection}&group_by=tags"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["buckets"] == [{"group": "x", "count": 1}]
    assert body["total_buckets"] == 1
    assert body["total_documents"] == 2


def test_aggregate_has_warnings_filter_applies():
    f = _Fixture()
    f.dedup.store_document(
        _make_doc(f.collection, "clean.pdf", "ok", file_type="pdf")
    )
    f.dedup.store_document(
        _make_doc(
            f.collection, "dirty.docx", "uhoh",
            file_type="docx", warnings=["bad bytes"],
        )
    )

    resp = f.client.get(
        f"/api/documents/aggregate?collection={f.collection}"
        f"&group_by=file_type&has_warnings=true"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["buckets"] == [{"group": "docx", "count": 1}]


def test_aggregate_has_source_reference_filter_applies():
    f = _Fixture()
    coll_a = f"a_{uuid.uuid4().hex[:6]}"
    coll_b = f"b_{uuid.uuid4().hex[:6]}"
    doc_a = _make_doc(coll_a, "a.txt", "alpha")
    doc_b = _make_doc(coll_b, "b.txt", "beta")
    f.dedup.store_document(doc_a)
    f.dedup.store_document(doc_b)
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc_a.document_id,
            collection_id=coll_a,
            agent_metadata={"source_reference": "doi:10.1/abc"},
        )
    )
    f.dedup.record_interaction(
        DocumentInteraction(
            document_id=doc_b.document_id,
            collection_id=coll_b,
            agent_metadata={"source_reference": "unknown"},
        )
    )

    resp = f.client.get(
        "/api/documents/aggregate?group_by=collection&has_source_reference=true"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["buckets"] == [{"group": coll_a, "count": 1}]


def test_aggregate_missing_group_by_returns_422():
    """group_by is required; FastAPI's own validation returns 422 for missing
    required query params. This is a different layer from our 400 validator."""
    f = _Fixture()
    resp = f.client.get("/api/documents/aggregate")
    assert resp.status_code == 422, resp.text


def test_aggregate_unknown_group_by_returns_400_with_valid_list():
    f = _Fixture()
    resp = f.client.get("/api/documents/aggregate?group_by=bogus")
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert set(detail["valid_group_by"]) == set(_AGGREGATE_REGISTRY.keys())


def test_aggregate_deterministic_sort_on_tie():
    f = _Fixture()
    # Seed file types with equal counts — alphabetical tie-break expected.
    for ft in ("zeta", "alpha", "mu"):
        f.dedup.store_document(
            _make_doc(f.collection, f"{ft}.x", ft, file_type=ft)
        )

    resp = f.client.get(
        f"/api/documents/aggregate?collection={f.collection}&group_by=file_type"
    )
    assert resp.status_code == 200, resp.text
    groups = [b["group"] for b in resp.json()["buckets"]]
    assert groups == ["alpha", "mu", "zeta"]


# ── schema ───────────────────────────────────────────────────────────────────


def test_schema_returns_all_registry_keys():
    f = _Fixture()
    resp = f.client.get("/api/documents/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_top = {
        "list_endpoint", "aggregate_endpoint",
        "filters", "includes", "aggregatable_fields",
        "caps", "brute_force_fallback", "deferred",
    }
    assert expected_top.issubset(set(body.keys())), body.keys()


def test_schema_filter_keys_match_registry():
    """Meta drift guard: the schema response's filter keys are exactly the
    keys in _FILTER_REGISTRY."""
    f = _Fixture()
    resp = f.client.get("/api/documents/schema")
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["filters"].keys()) == set(_FILTER_REGISTRY.keys())


def test_schema_aggregatable_fields_match_aggregate_validator():
    """For every field advertised by the schema, the aggregate endpoint must
    accept it as a valid group_by — schema cannot promise what aggregate
    rejects."""
    f = _Fixture()
    resp = f.client.get("/api/documents/schema")
    assert resp.status_code == 200, resp.text
    for field in resp.json()["aggregatable_fields"].keys():
        r = f.client.get(f"/api/documents/aggregate?group_by={field}")
        assert r.status_code != 400, (
            f"Schema advertises group_by={field} but aggregate rejected it "
            f"with 400: {r.text}"
        )


# ── unknown-query-param rejector ─────────────────────────────────────────────


def test_list_documents_unknown_query_param_returns_400():
    f = _Fixture()
    resp = f.client.get("/api/documents?xyz=1")
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "valid_params" in detail
    assert "xyz" in detail["error"]


def test_aggregate_unknown_query_param_returns_400():
    f = _Fixture()
    resp = f.client.get("/api/documents/aggregate?group_by=collection&xyz=1")
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "valid_params" in detail
    assert "xyz" in detail["error"]
