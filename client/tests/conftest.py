"""Shared fixtures for the ariadne_core_client test suite.

Provides a `captured_http` fixture that monkeypatches the module-level
`json_request` and `multipart_upload` attributes on `ariadne_core_client._http`
so tests can observe what the client sends without touching the network.

The client in `client.py` imports the module (`from ariadne_core_client import _http`)
and calls `_http.json_request(...)` / `_http.multipart_upload(...)`, so replacing
attributes on the module is enough — no monkeypatching of every call site needed.

Also exports `_confirm_required_body` (importable factory, not a fixture)
that mints the ``detail`` dict the m5e flow returns inside a 413 body.
Hoisted from per-file copies in test_confirmation_client.py + test_confirmation_cli.py
per ariadne--tjw.2 f3.
"""

from __future__ import annotations

from typing import Any

import pytest

from ariadne_core_client import _http


# ── m5e confirmation-required body factory (hoisted per tjw.2 f3) ────────────


def _confirm_required_body(
    *,
    confirmation_token: str = "tok-test",
    soft_cap: int = 1024,
    hard_cap: int = 1_073_741_824,
    reported_size: int = 4096,
    source: str = "https://example.org/big.pdf",
    content_type: str | None = "application/pdf",
    last_modified: str | None = "2026-05-08T00:00:00Z",
    ttl_seconds: int = 300,
    message: str = "Source size exceeds soft cap; confirm to proceed.",
) -> dict[str, Any]:
    """Build the ``detail`` dict the server returns inside the 413 body.

    Default ``confirmation_token="tok-test"`` is a placeholder; call sites
    that assert on the literal string pass an explicit ``confirmation_token=``
    kwarg.
    """
    return {
        "code": "confirmation_required",
        "message": message,
        "soft_cap": soft_cap,
        "hard_cap": hard_cap,
        "reported_size": reported_size,
        "source": source,
        "content_type": content_type,
        "last_modified": last_modified,
        "confirmation_token": confirmation_token,
        "ttl_seconds": ttl_seconds,
    }


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
    """Ensure the client picks up a deterministic host + escape-hatch token.

    Sets:
    - ``ARIADNE_HOST`` so ``auth.resolve_host`` produces a stable value
      without reading the developer's ``~/.config/ariadne/default``.
    - ``ARIADNE_ACCESS_TOKEN`` so ``auth.get_access_token`` skips the
      keyring entirely (tests don't touch the OS keychain). Individual
      tests that need to exercise the fail-closed path use
      ``monkeypatch.delenv("ARIADNE_ACCESS_TOKEN", raising=False)``
      plus a mocked ``auth.get_access_token``.
    """
    monkeypatch.setenv("ARIADNE_HOST", "http://localhost")
    monkeypatch.setenv("ARIADNE_ACCESS_TOKEN", "test-bearer-token")
    # Unset the legacy vars so we fail loudly if any stale test path
    # still depends on them.
    monkeypatch.delenv("ARIADNE_URL", raising=False)
    monkeypatch.delenv("ARIADNE_API_KEY", raising=False)
