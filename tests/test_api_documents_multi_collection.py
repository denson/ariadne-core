"""Tests for /api/documents + /api/documents/aggregate multi-collection (ariadne--vis).

Mirrors the parent ariadne--wgi precedent for /api/search:

  • Adds ``collections: list[str]`` query param alongside ``collection``.
  • Mutually exclusive at the request layer (both → 422).
  • Empty list rejected (422).
  • Per-element slug allow-list (422).
  • Single-collection backwards-compat unchanged.

In-memory store backs every assertion — no Pg required. The Pg backend
path is the same ``ANY(col.name)`` arm exercised by the wgi search
tests; the list_documents SQL builder uses the identical pattern so
shared backend coverage is sufficient.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline import services
from pipeline.api.routes import router
from pipeline.dedup import (
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
) -> StoredDocument:
    return StoredDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection,
        source_file=source_file,
        content_fingerprint=compute_fingerprint(content.encode("utf-8")),
        file_type=file_type,
        engine="markitdown",
        markdown=content,
        title=source_file,
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[],
        tags=list(tags or []),
        warnings=[],
    )


@pytest.fixture
def docs_fixture():
    """Three collections seeded with two docs each. The slug suffix
    prevents collisions across reruns / parallel workers."""
    app = _build_app()
    client = TestClient(app)
    dedup = InMemoryDedupStore()
    vector = InMemoryVectorStore()
    services.configure_stores(dedup, vector)

    suffix = uuid.uuid4().hex[:6]
    colls = {
        "a": f"coll-a-{suffix}",
        "b": f"coll-b-{suffix}",
        "c": f"coll-c-{suffix}",
    }
    for key, coll in colls.items():
        dedup.store_document(_make_doc(coll, f"{key}-1.txt", f"alpha-{key}"))
        dedup.store_document(_make_doc(coll, f"{key}-2.txt", f"beta-{key}"))

    class _Fix:
        pass

    f = _Fix()
    f.client = client
    f.dedup = dedup
    f.vector = vector
    f.colls = colls
    return f


# ── /api/documents — happy path ────────────────────────────────────────────


def test_list_documents_collections_narrows_to_listed_set(docs_fixture):
    f = docs_fixture
    resp = f.client.get(
        "/api/documents",
        params=[("collections", f.colls["a"]), ("collections", f.colls["b"])],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned_collections = {row["collection"] for row in body["documents"]}
    assert returned_collections == {f.colls["a"], f.colls["b"]}
    assert body["total_count"] == 4  # two docs per collection seeded
    assert f.colls["c"] not in returned_collections


def test_list_documents_collections_single_element_equivalent_to_collection(
    docs_fixture,
):
    """``collections=[X]`` returns the same row set as ``collection=X``."""
    f = docs_fixture
    multi = f.client.get(
        "/api/documents", params=[("collections", f.colls["a"])]
    )
    single = f.client.get(
        "/api/documents", params={"collection": f.colls["a"]}
    )
    assert multi.status_code == 200 and single.status_code == 200
    multi_ids = {d["document_id"] for d in multi.json()["documents"]}
    single_ids = {d["document_id"] for d in single.json()["documents"]}
    assert multi_ids == single_ids
    assert multi.json()["total_count"] == single.json()["total_count"] == 2


def test_list_documents_no_filter_returns_every_collection(docs_fixture):
    """Pre-vis callers send neither field → response spans every seeded
    collection (six docs total)."""
    f = docs_fixture
    resp = f.client.get("/api/documents", params={"limit": 100})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 6
    returned = {row["collection"] for row in body["documents"]}
    assert returned == set(f.colls.values())


# ── /api/documents — 422s for malformed scope ──────────────────────────────


def test_list_documents_both_collection_and_collections_returns_422(docs_fixture):
    f = docs_fixture
    resp = f.client.get(
        "/api/documents",
        params=[
            ("collection", f.colls["a"]),
            ("collections", f.colls["b"]),
        ],
    )
    assert resp.status_code == 422, resp.text
    assert "mutually_exclusive_collections" in resp.text


def test_list_documents_collections_empty_returns_422(docs_fixture):
    """The query-string surface ``collections=`` (empty value) parses as
    one-element list containing the empty string, which trips the slug
    allow-list (422 invalid_collection_slug). The strictly-empty list
    case is unreachable from the query string; the validator unit test
    below covers it directly."""
    f = docs_fixture
    resp = f.client.get("/api/documents?collections=")
    assert resp.status_code == 422, resp.text
    assert "invalid_collection_slug" in resp.text


def test_validate_collections_scope_rejects_empty_list_directly():
    """Direct call: the validator rejects ``collections=[]`` with the
    ``empty_collections_list`` error code. Query-string callers cannot
    reach this state (an empty repeat-param produces a list with one
    empty-string element, which trips invalid_collection_slug first) —
    but in-process callers (future SDK / RPC bindings) can, and the
    error path is documented in SPEC."""
    from fastapi import HTTPException

    from pipeline.api.routes import _validate_collections_scope

    with pytest.raises(HTTPException) as exc:
        _validate_collections_scope(collection=None, collections=[])
    assert exc.value.status_code == 422
    assert "empty_collections_list" in str(exc.value.detail)


@pytest.mark.parametrize(
    "bad_slug",
    [
        "UPPERCASE",
        "foo.bar",
        "foo/bar",
        "a" * 65,
        "foo@bar",
    ],
)
def test_list_documents_invalid_slug_returns_422(docs_fixture, bad_slug):
    f = docs_fixture
    resp = f.client.get(
        "/api/documents",
        params=[
            ("collections", f.colls["a"]),
            ("collections", bad_slug),
        ],
    )
    assert resp.status_code == 422, (
        f"Bad slug {bad_slug!r} should be 422; got {resp.status_code}: "
        f"{resp.text}"
    )
    assert "invalid_collection_slug" in resp.text


# ── /api/documents/schema — registry exposes new param ────────────────────


def test_documents_schema_lists_collections_filter(docs_fixture):
    resp = docs_fixture.client.get("/api/documents/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "collections" in body["filters"]
    assert "Mutually exclusive" in body["filters"]["collections"]


# ── /api/documents/aggregate — mirror the same surface ────────────────────


def test_aggregate_documents_collections_narrows_buckets(docs_fixture):
    f = docs_fixture
    resp = f.client.get(
        "/api/documents/aggregate",
        params=[
            ("group_by", "collection"),
            ("collections", f.colls["a"]),
            ("collections", f.colls["b"]),
        ],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    bucket_names = {b["group"] for b in body["buckets"]}
    assert bucket_names == {f.colls["a"], f.colls["b"]}
    assert body["total_documents"] == 4
    # applied_filters surfaces the scope the caller sent
    assert body["filters"].get("collections") == [f.colls["a"], f.colls["b"]]


def test_aggregate_documents_both_collection_and_collections_returns_422(
    docs_fixture,
):
    f = docs_fixture
    resp = f.client.get(
        "/api/documents/aggregate",
        params=[
            ("group_by", "collection"),
            ("collection", f.colls["a"]),
            ("collections", f.colls["b"]),
        ],
    )
    assert resp.status_code == 422, resp.text
    assert "mutually_exclusive_collections" in resp.text


def test_aggregate_documents_invalid_slug_returns_422(docs_fixture):
    f = docs_fixture
    resp = f.client.get(
        "/api/documents/aggregate",
        params=[
            ("group_by", "file_type"),
            ("collections", "BAD_SLUG"),
        ],
    )
    assert resp.status_code == 422, resp.text
    assert "invalid_collection_slug" in resp.text


def test_aggregate_documents_back_compat_single_collection(docs_fixture):
    """Pre-vis single-collection aggregate call keeps its prior shape."""
    f = docs_fixture
    resp = f.client.get(
        "/api/documents/aggregate",
        params={"group_by": "file_type", "collection": f.colls["a"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_documents"] == 2
    assert body["filters"].get("collection") == f.colls["a"]
    assert "collections" not in body["filters"]
