"""Tests for the FastAPI REST endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline.api.app import app
from pipeline.api.auth import get_key_store, set_require_auth
from pipeline.api.routes import CollectionResponse, _collections
from pipeline.mcp_server import _dedup_store, _vector_store

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_stores():
    """Reset all stores between tests."""
    _dedup_store._documents.clear()
    _dedup_store._interactions.clear()
    _vector_store._chunks.clear()
    _collections.clear()
    _collections["default"] = CollectionResponse(
        name="default", description="Default collection"
    )
    # Clear API key store and reset auth enforcement
    get_key_store()._keys.clear()
    set_require_auth(False)
    yield
    set_require_auth(False)


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.1.0"
        assert data["engine"] == "markitdown"

    def test_health_no_auth_required(self):
        # No X-API-Key header — should still work
        resp = client.get("/api/health")
        assert resp.status_code == 200


class TestDocumentEndpoints:
    def test_submit_document(self):
        resp = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "markdown" in data
        assert "Ariadne Core Test Document" in data["markdown"]
        assert data["was_dedup_skip"] is False
        assert data["store_status"] == "stored"

    def test_submit_document_with_metadata(self):
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(FIXTURES / "sample.txt"),
                "agent_id": "test-agent",
                "agent_type": "pytest",
                "model": "test-model",
                "initiated_by": "user:test",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        prov = data["provenance"]
        assert prov["agent_id"] == "test-agent"
        assert prov["agent_type"] == "pytest"

    def test_submit_document_store_false(self):
        resp = client.post(
            "/api/documents",
            json={
                "uri": str(FIXTURES / "sample.txt"),
                "store": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["store_status"] == "skipped"
        assert _vector_store.count() == 0

    def test_submit_nonexistent_file(self):
        resp = client.post(
            "/api/documents",
            json={"uri": "/nonexistent/file.pdf"},
        )
        assert resp.status_code == 422

    def test_dedup_on_second_submit(self):
        client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        resp = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        data = resp.json()
        assert data["was_dedup_skip"] is True

    def test_force_bypasses_dedup(self):
        first = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        ).json()
        second = client.post(
            "/api/documents",
            json={
                "uri": str(FIXTURES / "sample.txt"),
                "force": True,
            },
        ).json()
        assert first["was_dedup_skip"] is False
        assert second["was_dedup_skip"] is False
        assert first["document_id"] != second["document_id"]

    def test_get_document_by_id(self):
        submit = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        ).json()
        doc_id = submit["document_id"]

        resp = client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == doc_id
        assert "markdown" in data
        assert len(data["interactions"]) >= 1

    def test_get_document_not_found(self):
        resp = client.get("/api/documents/nonexistent-id")
        assert resp.status_code == 404

    def test_list_documents_empty(self):
        resp = client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["documents"] == []

    def test_list_documents_after_submit(self):
        client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        resp = client.get("/api/documents")
        data = resp.json()
        assert data["total"] == 1
        assert len(data["documents"]) == 1

    def test_list_documents_filter_by_collection(self):
        client.post(
            "/api/documents",
            json={
                "uri": str(FIXTURES / "sample.txt"),
                "collection": "alpha",
            },
        )
        client.post(
            "/api/documents",
            json={
                "uri": str(FIXTURES / "sample.html"),
                "collection": "beta",
            },
        )

        resp_alpha = client.get("/api/documents?collection=alpha")
        assert resp_alpha.json()["total"] == 1
        assert resp_alpha.json()["documents"][0]["collection"] == "alpha"

        resp_beta = client.get("/api/documents?collection=beta")
        assert resp_beta.json()["total"] == 1

    def test_list_documents_pagination(self):
        # Submit two different docs
        client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.html")},
        )

        resp = client.get("/api/documents?per_page=1&page=1")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["documents"]) == 1
        assert data["page"] == 1

        resp2 = client.get("/api/documents?per_page=1&page=2")
        data2 = resp2.json()
        assert len(data2["documents"]) == 1
        assert data2["page"] == 2


class TestSearchEndpoint:
    def test_search_no_embedding(self):
        resp = client.post(
            "/api/search",
            json={"query": "test"},
        )
        assert resp.status_code == 503


class TestCollectionEndpoints:
    def test_list_collections(self):
        resp = client.get("/api/collections")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data["collections"]]
        assert "default" in names

    def test_create_collection(self):
        resp = client.post(
            "/api/collections",
            json={"name": "research", "description": "Research docs"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "research"
        assert data["status"] == "created"

        # Verify it shows in list
        list_resp = client.get("/api/collections")
        names = [c["name"] for c in list_resp.json()["collections"]]
        assert "research" in names

    def test_create_duplicate_collection(self):
        client.post(
            "/api/collections",
            json={"name": "dupe"},
        )
        resp = client.post(
            "/api/collections",
            json={"name": "dupe"},
        )
        assert resp.status_code == 409


class TestStatsEndpoint:
    def test_stats_empty(self):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 0
        assert data["total_chunks"] == 0

    def test_stats_after_ingest(self):
        client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        resp = client.get("/api/stats")
        data = resp.json()
        assert data["total_documents"] == 1
        assert data["total_chunks"] > 0


class TestAuthIntegration:
    def test_valid_api_key(self):
        store = get_key_store()
        store.create_key("test-agent", "valid-key-123")

        resp = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
            headers={"X-API-Key": "valid-key-123"},
        )
        assert resp.status_code == 200

    def test_invalid_api_key(self):
        resp = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
            headers={"X-API-Key": "bad-key"},
        )
        assert resp.status_code == 403

    def test_no_api_key_still_works(self):
        """Phase 1: auth is optional by default."""
        resp = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
        )
        assert resp.status_code == 200

    def test_api_key_infers_agent_id(self):
        store = get_key_store()
        store.create_key("my-bot", "bot-key-456")

        resp = client.post(
            "/api/documents",
            json={"uri": str(FIXTURES / "sample.txt")},
            headers={"X-API-Key": "bot-key-456"},
        )
        data = resp.json()
        assert data["provenance"]["agent_id"] == "api-key:my-bot"

    def test_explicit_agent_id_overrides_key(self):
        store = get_key_store()
        store.create_key("key-agent", "key-789")

        resp = client.post(
            "/api/documents",
            json={
                "uri": str(FIXTURES / "sample.txt"),
                "agent_id": "explicit-agent",
            },
            headers={"X-API-Key": "key-789"},
        )
        data = resp.json()
        assert data["provenance"]["agent_id"] == "explicit-agent"


class TestRequireAuth:
    """Tests for require_auth enforcement."""

    def test_require_auth_rejects_no_key(self):
        set_require_auth(True)
        resp = client.get("/api/documents")
        assert resp.status_code == 401

    def test_require_auth_rejects_invalid_key(self):
        set_require_auth(True)
        resp = client.get("/api/documents", headers={"X-API-Key": "bad"})
        assert resp.status_code == 403

    def test_require_auth_accepts_valid_key(self):
        set_require_auth(True)
        store = get_key_store()
        store.create_key("agent", "good-key")
        resp = client.get(
            "/api/documents", headers={"X-API-Key": "good-key"}
        )
        assert resp.status_code == 200

    def test_require_auth_health_exempt(self):
        """Health endpoint never requires auth."""
        set_require_auth(True)
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_require_auth_search_rejects_no_key(self):
        set_require_auth(True)
        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 401

    def test_require_auth_collections_rejects_no_key(self):
        set_require_auth(True)
        resp = client.get("/api/collections")
        assert resp.status_code == 401
