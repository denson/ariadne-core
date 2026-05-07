"""Client-side auth wiring tests — Pass 3 (ariadne--xft.5.5).

Covers the contract between ``AriadneClient`` and
``ariadne_core_client.auth``:

* ``Authorization: Bearer <jwt>`` is attached on every authenticated
  request; ``X-API-Key`` is never sent.
* ``/api/health`` is the sole unauth endpoint (matches the server's
  open-endpoint list).
* Fail-closed-on-IdP: if ``auth.get_access_token`` raises, the client
  raises ``AriadneAuthError`` BEFORE issuing any network request.
* ``ARIADNE_ACCESS_TOKEN`` env var bypasses the keyring entirely —
  even with a keyring that would raise.
* Constructor rejects the dropped ``url=`` / ``api_key=`` params
  (breaking change is intentional).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ariadne_core_client import _http
from ariadne_core_client import auth as _auth
from ariadne_core_client.client import AriadneClient
from ariadne_core_client.exceptions import AriadneAuthError


# ========================================================================== helpers

def _canned_health_response() -> dict:
    return {
        "status": "ok",
        "version": "0.0.0",
        "engine": "test",
        "embedding_enabled": False,
    }


def _canned_document_response(document_id: str = "doc-1") -> dict:
    return {
        "document_id": document_id,
        "source_file": "t.txt",
        "chunk_count": 1,
        "store_status": "stored",
        "warnings": [],
    }


def _canned_upload_response(path: str = "/tmp/t.txt") -> dict:
    return {"path": path}


# ========================================================== constructor signature

class TestConstructorSignature:
    """The breaking change: url= and api_key= are gone."""

    def test_legacy_url_kwarg_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            AriadneClient(url="http://localhost")  # type: ignore[call-arg]

    def test_legacy_api_key_kwarg_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            AriadneClient(api_key="test-key")  # type: ignore[call-arg]

    def test_host_kwarg_supported(self) -> None:
        c = AriadneClient(host="http://localhost")
        assert c.host == "http://localhost"

    def test_positional_host_supported(self) -> None:
        # Preserving positional API for ``AriadneClient("https://...")``
        # is convenient; the brief does not require it but we keep it
        # for ergonomics since the old signature had url positional.
        c = AriadneClient("http://localhost")
        assert c.host == "http://localhost"

    def test_no_host_anywhere_raises_auth_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Override the autouse ARIADNE_HOST fixture to simulate "nothing
        # configured" and point the default-host file at a missing path.
        monkeypatch.delenv("ARIADNE_HOST", raising=False)
        monkeypatch.setattr(
            _auth, "DEFAULT_HOST_CONFIG_PATH", tmp_path / "nope"
        )
        with pytest.raises(AriadneAuthError) as exc:
            AriadneClient()
        # Message must point the user at the three resolution sources.
        assert "--host" in str(exc.value)
        assert "ARIADNE_HOST" in str(exc.value)

    def test_self_api_key_attribute_removed(self) -> None:
        # A test harness that tries to read ``c.api_key`` should fail —
        # guarantees we don't silently regain a legacy code path.
        c = AriadneClient(host="http://localhost")
        assert not hasattr(c, "api_key")
        assert not hasattr(c, "url")


# ======================================================== bearer header on calls

class TestBearerHeaderWiring:
    """Every authed request carries Authorization: Bearer; no X-API-Key."""

    TOKEN = "env-token-xyz"

    @pytest.fixture(autouse=True)
    def _set_env_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Override the autouse conftest token so we can assert on a
        # specific value and prove the env var reaches the header.
        monkeypatch.setenv("ARIADNE_ACCESS_TOKEN", self.TOKEN)

    def _assert_bearer_no_apikey(self, headers: dict[str, str]) -> None:
        assert headers.get("Authorization") == f"Bearer {self.TOKEN}"
        # Case-insensitive check: never send X-API-Key under any casing.
        for k in headers:
            assert k.lower() != "x-api-key", (
                f"Unexpected X-API-Key-shaped header {k!r} — legacy path must stay dead"
            )

    def test_search_sends_bearer_not_apikey(self, captured_http) -> None:
        captured_http.set_json_response(
            {"query": "q", "top_k": 5, "results": [], "results_count": 0}
        )
        c = AriadneClient(host="http://localhost")
        c.search("q")
        self._assert_bearer_no_apikey(captured_http.last_json_call()["headers"])

    def test_list_documents_sends_bearer_not_apikey(self, captured_http) -> None:
        captured_http.set_json_response(
            {"documents": [], "total_count": 0, "total_is_exact": True, "limit": 20, "offset": 0}
        )
        c = AriadneClient(host="http://localhost")
        c.list_documents()
        self._assert_bearer_no_apikey(captured_http.last_json_call()["headers"])

    def test_stats_sends_bearer_not_apikey(self, captured_http) -> None:
        captured_http.set_json_response({})
        c = AriadneClient(host="http://localhost")
        c.stats()
        self._assert_bearer_no_apikey(captured_http.last_json_call()["headers"])

    def test_ingest_bytes_sends_bearer_on_both_upload_and_post(
        self,
        captured_http,
    ) -> None:
        captured_http.set_upload_response(_canned_upload_response())
        captured_http.set_json_response(_canned_document_response())
        c = AriadneClient(host="http://localhost")
        c.ingest_bytes(b"hello", "hello.txt", collection="t")
        # Bearer must be present on BOTH the upload (multipart) and the
        # subsequent POST /api/documents.
        self._assert_bearer_no_apikey(captured_http.last_upload_call()["headers"])
        self._assert_bearer_no_apikey(captured_http.last_json_call()["headers"])

    def test_health_does_not_send_authorization(self, captured_http) -> None:
        """/api/health is unauth on the server; client mirrors by omitting the header."""
        captured_http.set_json_response(_canned_health_response())
        c = AriadneClient(host="http://localhost")
        c.health()
        headers = captured_http.last_json_call()["headers"]
        assert "Authorization" not in headers
        for k in headers:
            assert k.lower() != "x-api-key"


# ================================================================= fail-closed

class TestFailClosedOnIdPFailure:
    """If get_access_token raises, the client must raise AriadneAuthError
    WITHOUT issuing any network request."""

    def test_autherror_maps_to_ariadne_auth_error_no_http_call(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Remove the escape-hatch token so get_access_token would normally
        # consult the keyring, then patch it to raise.
        monkeypatch.delenv("ARIADNE_ACCESS_TOKEN", raising=False)

        def boom(host: str, **kwargs: Any) -> str:
            raise _auth.AuthError("refresh token revoked; run 'ariadne login'")

        # Patch the reference the client module holds, not the original
        # definition, to match how client.py imports ``auth``.
        from ariadne_core_client import client as client_module

        monkeypatch.setattr(client_module._auth, "get_access_token", boom)
        c = AriadneClient(host="http://localhost")
        with pytest.raises(AriadneAuthError) as exc:
            c.search("anything")
        assert "refresh token revoked" in str(exc.value)
        # CRITICAL: no HTTP call went out. VERA/CATO-security will
        # audit the fail-closed posture by running this specific
        # assertion; any regression that issues an unauthenticated
        # network call must break this test.
        assert captured_http.json_calls == []
        assert captured_http.upload_calls == []

    def test_keyring_backend_unavailable_maps_to_ariadne_auth_error(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ARIADNE_ACCESS_TOKEN", raising=False)

        def boom(host: str, **kwargs: Any) -> str:
            raise _auth.KeyringBackendUnavailable(
                "Could not access Windows Credential Manager (simulated)."
            )

        from ariadne_core_client import client as client_module

        monkeypatch.setattr(client_module._auth, "get_access_token", boom)
        c = AriadneClient(host="http://localhost")
        with pytest.raises(AriadneAuthError) as exc:
            c.list_documents()
        assert "Credential Manager" in str(exc.value)
        assert captured_http.json_calls == []

    def test_ingest_file_fail_closed_before_upload(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Fail-closed must trip before the multipart upload — never
        send the file bytes over the wire with a missing auth context."""
        monkeypatch.delenv("ARIADNE_ACCESS_TOKEN", raising=False)

        def boom(host: str, **kwargs: Any) -> str:
            raise _auth.AuthError("no cached refresh; run 'ariadne login'")

        from ariadne_core_client import client as client_module

        monkeypatch.setattr(client_module._auth, "get_access_token", boom)
        fp = tmp_path / "hello.txt"
        fp.write_text("hello")

        c = AriadneClient(host="http://localhost")
        with pytest.raises(AriadneAuthError):
            c.ingest_file(str(fp), collection="t")
        assert captured_http.upload_calls == []
        assert captured_http.json_calls == []


# =================================================== ARIADNE_ACCESS_TOKEN escape

class TestAccessTokenEnvEscape:
    """Env var bypasses the keyring entirely — even when the keyring
    would raise."""

    def test_env_token_bypasses_broken_keyring(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the KeyringStore() constructor to raise — simulating a
        # LOCAL SYSTEM service account on Windows or a headless Linux
        # without gnome-keyring. The env token must still win.
        class BrokenStore:
            def __init__(self, *args, **kwargs):
                raise _auth.KeyringBackendUnavailable(
                    "Simulated broken keyring — env escape must win"
                )

        monkeypatch.setattr(_auth, "KeyringStore", BrokenStore)
        # Env token already set by the autouse fixture; we verify it
        # reaches the wire.
        monkeypatch.setenv("ARIADNE_ACCESS_TOKEN", "env-escape-hatch-tk")

        captured_http.set_json_response(_canned_health_response())
        captured_http.set_json_response(
            {"query": "q", "top_k": 5, "results": [], "results_count": 0}
        )
        c = AriadneClient(host="http://localhost")
        c.search("q")
        headers = captured_http.last_json_call()["headers"]
        assert headers["Authorization"] == "Bearer env-escape-hatch-tk"

    def test_env_token_used_verbatim_not_logged(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Token must reach the header; never appear on stdout/stderr.

        This is a coarse but important check: no log / print line should
        echo the token value. It does not prove the token is
        never-logged under every error path; it confirms the happy path
        is quiet.
        """
        monkeypatch.setenv("ARIADNE_ACCESS_TOKEN", "never-log-me-plz")
        captured_http.set_json_response(
            {"query": "q", "top_k": 5, "results": [], "results_count": 0}
        )
        c = AriadneClient(host="http://localhost")
        c.search("q")
        out = capsys.readouterr()
        assert "never-log-me-plz" not in out.out
        assert "never-log-me-plz" not in out.err


# =================================================================== host plumbing

class TestHostPlumbing:
    def test_host_override_wins_over_env(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Use http://127.0.0.1 for env and http://localhost for explicit
        # so the predicate (loopback-only for http://) allows both while
        # giving them distinguishable URLs in assertions.
        monkeypatch.setenv("ARIADNE_HOST", "http://127.0.0.1")
        monkeypatch.setenv("ARIADNE_ACCESS_TOKEN", "tk")
        captured_http.set_json_response(
            {"query": "q", "top_k": 5, "results": [], "results_count": 0}
        )
        c = AriadneClient(host="http://localhost")
        c.search("q")
        # The URL in the recorded HTTP call must reflect the explicit
        # host, not the env value.
        assert captured_http.last_json_call()["url"].startswith(
            "http://localhost/api/"
        )

    def test_host_env_used_when_none(
        self,
        captured_http,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARIADNE_HOST", "http://127.0.0.1")
        monkeypatch.setenv("ARIADNE_ACCESS_TOKEN", "tk")
        captured_http.set_json_response(
            {"query": "q", "top_k": 5, "results": [], "results_count": 0}
        )
        c = AriadneClient()
        c.search("q")
        assert captured_http.last_json_call()["url"].startswith(
            "http://127.0.0.1/api/"
        )
