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
