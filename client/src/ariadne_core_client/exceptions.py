"""Ariadne Core client exceptions."""


class AriadneClientError(Exception):
    """Base exception for all Ariadne client errors."""

    def __init__(self, message: str, status_code: int | None = None, request_info: str | None = None):
        self.message = message
        self.status_code = status_code
        self.request_info = request_info
        super().__init__(message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.insert(0, f"[{self.status_code}]")
        return " ".join(parts)


class AriadneAuthError(AriadneClientError):
    """Authentication error (401/403)."""
    pass


class AriadneNotFoundError(AriadneClientError):
    """Resource not found (404)."""
    pass


class AriadneServerError(AriadneClientError):
    """Server error (5xx)."""
    pass


class ConfirmationRequired(AriadneClientError):
    """Source size between soft and hard cap; caller must affirm.

    Carries the structured body of the server's HTTP 413 ``confirmation_required``
    response (m5e). Re-submit the original ingest call with
    ``confirmation_token=<self.confirmation_token>`` to proceed within the
    TTL window.

    Attributes
    ----------
    soft_cap : int
        Server's soft cap in bytes (``IngestConfig.max_source_bytes``).
    hard_cap : int
        Server's hard cap in bytes (``IngestConfig.max_source_bytes_hard``).
    reported_size : int
        Size observed at probe time. From a HEAD response when available;
        otherwise the chunked-read overrun threshold.
    source : str
        The URI the server is asking the caller to confirm. Token signs
        this value; re-submitting against a different URI yields URI_MISMATCH.
    content_type : str | None
        ``Content-Type`` from the HEAD response, or local-file mime guess.
    last_modified : str | None
        ISO-8601 UTC string from the HEAD response, or the local file's mtime.
    confirmation_token : str
        Opaque HMAC-signed token. Pass back as ``confirmation_token=`` on
        the retry.
    ttl_seconds : int
        Token validity window in seconds.
    """

    def __init__(
        self,
        message: str,
        *,
        soft_cap: int,
        hard_cap: int,
        reported_size: int,
        source: str,
        content_type: str | None,
        last_modified: str | None,
        confirmation_token: str,
        ttl_seconds: int,
        request_info: str | None = None,
    ) -> None:
        super().__init__(message, status_code=413, request_info=request_info)
        self.soft_cap = soft_cap
        self.hard_cap = hard_cap
        self.reported_size = reported_size
        self.source = source
        self.content_type = content_type
        self.last_modified = last_modified
        self.confirmation_token = confirmation_token
        self.ttl_seconds = ttl_seconds
