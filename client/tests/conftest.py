"""Shared fixtures for the ariadne_core_client test suite.

Provides a `captured_http` fixture that monkeypatches the module-level
`json_request` and `multipart_upload` attributes on `ariadne_core_client._http`
so tests can observe what the client sends without touching the network.

The client in `client.py` imports the module (`from ariadne_core_client import _http`)
and calls `_http.json_request(...)` / `_http.multipart_upload(...)`, so replacing
attributes on the module is enough — no monkeypatching of every call site needed.
"""

from __future__ import annotations

from typing import Any

import pytest

from ariadne_core_client import _http


class HttpCapture:
    """Records calls to _http.json_request / _http.multipart_upload."""

    def __init__(self) -> None:
        self.json_calls: list[dict[str, Any]] = []
        self.upload_calls: list[dict[str, Any]] = []
        self.json_response: Any = None
        self.upload_response: Any = None

    def set_json_response(self, response: Any) -> None:
        self.json_response = response

    def set_upload_response(self, response: Any) -> None:
        self.upload_response = response

    def last_json_call(self) -> dict[str, Any]:
        assert self.json_calls, "no json_request calls recorded"
        return self.json_calls[-1]

    def last_upload_call(self) -> dict[str, Any]:
        assert self.upload_calls, "no multipart_upload calls recorded"
        return self.upload_calls[-1]


@pytest.fixture
def captured_http(monkeypatch: pytest.MonkeyPatch) -> HttpCapture:
    capture = HttpCapture()

    def fake_json_request(
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        timeout: float = 60.0,
    ) -> Any:
        capture.json_calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json_body": json_body,
                "timeout": timeout,
            }
        )
        return capture.json_response

    def fake_multipart_upload(
        url: str,
        headers: dict[str, str] | None = None,
        filepath: Any = None,
        field_name: str = "file",
        extra_fields: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> Any:
        capture.upload_calls.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "filepath": filepath,
                "field_name": field_name,
                "extra_fields": dict(extra_fields or {}),
                "timeout": timeout,
            }
        )
        return capture.upload_response

    monkeypatch.setattr(_http, "json_request", fake_json_request)
    monkeypatch.setattr(_http, "multipart_upload", fake_multipart_upload)
    return capture


@pytest.fixture(autouse=True)
def _client_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the client picks up a dummy URL/key without reading user env."""
    monkeypatch.setenv("ARIADNE_URL", "http://test.invalid")
    monkeypatch.setenv("ARIADNE_API_KEY", "test-key")
