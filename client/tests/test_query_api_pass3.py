"""Query API Pass 3 — client catch-up for the Pass 2 server surface.

Covers: list_documents' new filters + include=, DocumentListPage return
shape, warnings_count parsing, and the new aggregate() / schema()
methods.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from ariadne_core_client.client import AriadneClient
from ariadne_core_client.models import (
    AggregateBucket,
    AggregateResponse,
    Document,
    DocumentListPage,
    QuerySchema,
)


def _query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def test_list_documents_new_filters(captured_http):
    captured_http.set_json_response(
        {"documents": [], "total_count": 0, "total_is_exact": True, "limit": 20, "offset": 0}
    )

    c = AriadneClient(url="http://test.invalid", api_key="test-key")
    c.list_documents(
        tag="x",
        has_warnings=True,
        has_source_reference=False,
        include=["tags", "agent_metadata"],
    )

    url = captured_http.last_json_call()["url"]
    params = _query_params(url)

    assert params["tag"] == ["x"]
    assert params["has_warnings"] == ["true"]
    assert params["has_source_reference"] == ["false"]
    assert sorted(params["include"]) == ["agent_metadata", "tags"]
    # Booleans serialize lowercase, not Python's "True"/"False".
    assert "True" not in url
    assert "False" not in url


def test_list_documents_returns_page(captured_http):
    captured_http.set_json_response(
        {
            "documents": [
                {"document_id": "a", "source_file": "a.txt", "warnings": [], "warnings_count": 0},
                {"document_id": "b", "source_file": "b.txt", "warnings": ["w"], "warnings_count": 1},
            ],
            "total_count": 42,
            "total_is_exact": False,
            "limit": 20,
            "offset": 0,
        }
    )

    c = AriadneClient(url="http://test.invalid", api_key="test-key")
    page = c.list_documents()

    assert isinstance(page, DocumentListPage)
    assert len(page) == 2
    assert page.total_count == 42
    assert page.total_is_exact is False
    assert page.limit == 20
    assert page.offset == 0
    for doc in page:
        assert isinstance(doc, Document)
    assert page[0].document_id == "a"


def test_document_warnings_count_parsed(captured_http):
    captured_http.set_json_response(
        {
            "documents": [
                {
                    "document_id": "d1",
                    "source_file": "a.txt",
                    "warnings": ["w1"],
                    "warnings_count": 1,
                },
                {
                    "document_id": "d2",
                    "source_file": "b.txt",
                    "warnings": [],
                    # no warnings_count key — older server shape
                },
            ],
            "total_count": 2,
            "total_is_exact": True,
            "limit": 20,
            "offset": 0,
        }
    )

    c = AriadneClient(url="http://test.invalid", api_key="test-key")
    page = c.list_documents()

    assert page[0].warnings == ["w1"]
    assert page[0].warnings_count == 1
    assert page[1].warnings == []
    assert page[1].warnings_count is None


def test_aggregate_basic(captured_http):
    captured_http.set_json_response(
        {
            "group_by": "collection",
            "filters": {"has_warnings": True},
            "buckets": [
                {"group": "a", "count": 3},
                {"group": "b", "count": 1},
            ],
            "total_buckets": 2,
            "total_documents": 4,
        }
    )

    c = AriadneClient(url="http://test.invalid", api_key="test-key")
    resp = c.aggregate("collection", has_warnings=True)

    url = captured_http.last_json_call()["url"]
    params = _query_params(url)
    assert url.startswith("http://test.invalid/api/documents/aggregate")
    assert params["group_by"] == ["collection"]
    assert params["has_warnings"] == ["true"]

    assert isinstance(resp, AggregateResponse)
    assert len(resp) == 2
    assert resp.buckets[0] == AggregateBucket(group="a", count=3)
    assert resp.total_buckets == 2
    assert resp.total_documents == 4


def test_schema_basic(captured_http):
    captured_http.set_json_response(
        {
            "list_endpoint": "/api/documents",
            "aggregate_endpoint": "/api/documents/aggregate",
            "filters": {
                "collection": "…",
                "file_type": "…",
                "tag": "…",
                "has_warnings": "…",
                "has_source_reference": "…",
                "include_deleted": "…",
            },
            "includes": {
                "agent_metadata": "…",
                "tags": "…",
                "last_interaction": "…",
                "markdown": "…",
            },
            "aggregatable_fields": {
                "collection": "…",
                "file_type": "…",
                "tags": "…",
            },
            "caps": {
                "list_default": 500,
                "list_with_markdown": 50,
                "aggregate_buckets_max": 1000,
            },
            "brute_force_fallback": "paginate + client-side filter",
            "deferred": {"date_range_filters": "future pass"},
        }
    )

    c = AriadneClient(url="http://test.invalid", api_key="test-key")
    sch = c.schema()

    assert isinstance(sch, QuerySchema)
    assert isinstance(sch.filters, dict)
    assert isinstance(sch.includes, dict)
    assert isinstance(sch.aggregatable_fields, dict)
    assert isinstance(sch.deferred, dict)
    assert sch.caps["list_default"] == 500
    assert sch.list_endpoint == "/api/documents"
