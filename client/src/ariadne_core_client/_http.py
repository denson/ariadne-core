"""Low-level HTTP transport for the Ariadne client.

Stdlib-only: uses urllib.request. Maps HTTP errors to the exception classes
defined in exceptions.py and parses the server's {"detail": {"message": ...}}
error envelope.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from ariadne_core_client.exceptions import (
    AriadneAuthError,
    AriadneClientError,
    AriadneNotFoundError,
    AriadneServerError,
    ConfirmationRequired,
)


def _exception_for_status(status: int) -> type[AriadneClientError]:
    if status in (401, 403):
        return AriadneAuthError
    if status == 404:
        return AriadneNotFoundError
    if 500 <= status < 600:
        return AriadneServerError
    return AriadneClientError


def _parse_error_body(body: bytes) -> str:
    if not body:
        return ""
    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            msg = detail.get("message")
            if isinstance(msg, str):
                return msg
            return json.dumps(detail)[:500]
        if isinstance(detail, str):
            return detail
    return json.dumps(payload)[:500]


def _parse_confirmation_required_body(body: bytes) -> dict | None:
    """Return the parsed ``detail`` dict iff the body is an m5e
    ``confirmation_required`` envelope; otherwise return None.

    The m5e shape (per ``SPEC.md`` and ``tests/verification/ariadne--m5e/
    test_routes_confirmation.py``) is::

        {"detail": {
            "code": "confirmation_required",
            "message": "...",
            "soft_cap": int,
            "hard_cap": int,
            "reported_size": int,
            "source": str,
            "content_type": str | None,
            "last_modified": str | None,
            "confirmation_token": str,
            "ttl_seconds": int,
        }}

    A 413 from the legacy signed-upload path has no ``code`` /
    ``confirmation_token`` field and falls through to the generic
    ``AriadneClientError`` route.
    """
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        return None
    if detail.get("code") != "confirmation_required":
        return None
    if "confirmation_token" not in detail:
        return None
    return detail


def _raise_for_http_error(err: urllib_error.HTTPError, request_info: str) -> None:
    status = err.code
    try:
        body = err.read()
    except Exception:
        body = b""
    if status == 413:
        # m5e confirmation flow: a 413 with the structured `detail` envelope
        # raises ConfirmationRequired so the caller can surface size + token.
        # Other 413 shapes (e.g., signed-upload size cap) fall through to
        # the generic path so back-compat with pre-m5e callers is preserved.
        confirm_body = _parse_confirmation_required_body(body)
        if confirm_body is not None:
            message = confirm_body.get("message") or "Confirmation required"
            raise ConfirmationRequired(
                message,
                soft_cap=int(confirm_body["soft_cap"]),
                hard_cap=int(confirm_body["hard_cap"]),
                reported_size=int(confirm_body["reported_size"]),
                source=str(confirm_body["source"]),
                content_type=confirm_body.get("content_type"),
                last_modified=confirm_body.get("last_modified"),
                confirmation_token=str(confirm_body["confirmation_token"]),
                ttl_seconds=int(confirm_body["ttl_seconds"]),
                request_info=request_info,
            )
    message = _parse_error_body(body) or err.reason or f"HTTP {status}"
    exc_cls = _exception_for_status(status)
    raise exc_cls(message, status_code=status, request_info=request_info)


def request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict[str, str], bytes]:
    """Perform a raw HTTP request and return (status, headers, body).

    Raises AriadneAuthError / AriadneNotFoundError / AriadneServerError /
    AriadneClientError on HTTP or transport failures.
    """
    req = urllib_request.Request(url=url, data=body, method=method.upper())
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    request_info = f"{method.upper()} {url}"
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib_error.HTTPError as err:
        _raise_for_http_error(err, request_info)
    except urllib_error.URLError as err:
        reason = getattr(err, "reason", err)
        raise AriadneClientError(
            f"Connection failed: {reason}",
            request_info=request_info,
        ) from err
    except TimeoutError as err:
        raise AriadneClientError(
            f"Request timed out after {timeout}s",
            request_info=request_info,
        ) from err
    raise AriadneClientError("unreachable", request_info=request_info)  # pragma: no cover


def json_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    timeout: float = 60.0,
) -> Any:
    """Send an HTTP request with optional JSON body and parse a JSON response."""
    hdrs = dict(headers or {})
    body: bytes | None = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    hdrs.setdefault("Accept", "application/json")
    status, _, raw = request(method, url, hdrs, body, timeout)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as err:
        raise AriadneClientError(
            f"Server returned non-JSON response: {err}",
            status_code=status,
            request_info=f"{method.upper()} {url}",
        ) from err


def multipart_upload(
    url: str,
    headers: dict[str, str] | None = None,
    filepath: str | os.PathLike[str] | None = None,
    field_name: str = "file",
    extra_fields: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> Any:
    """POST a file as multipart/form-data and parse a JSON response."""
    if filepath is None:
        raise AriadneClientError("multipart_upload requires filepath")
    path = Path(filepath)
    if not path.is_file():
        raise AriadneClientError(f"File not found: {path}")

    boundary = f"----AriadneClient{uuid.uuid4().hex}"
    content_type, _ = mimetypes.guess_type(path.name)
    if content_type is None:
        content_type = "application/octet-stream"

    chunks: list[bytes] = []
    for key, value in (extra_fields or {}).items():
        chunks.append(f"--{boundary}".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"'.encode())
        chunks.append(b"")
        chunks.append(str(value).encode("utf-8"))

    chunks.append(f"--{boundary}".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"'.encode()
    )
    chunks.append(f"Content-Type: {content_type}".encode())
    chunks.append(b"")
    chunks.append(path.read_bytes())
    chunks.append(f"--{boundary}--".encode())
    chunks.append(b"")
    body = b"\r\n".join(chunks)

    hdrs = dict(headers or {})
    hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    hdrs["Content-Length"] = str(len(body))
    hdrs.setdefault("Accept", "application/json")

    status, _, raw = request("POST", url, hdrs, body, timeout)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as err:
        raise AriadneClientError(
            f"Server returned non-JSON response: {err}",
            status_code=status,
            request_info=f"POST {url}",
        ) from err
