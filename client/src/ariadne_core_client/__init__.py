"""Ariadne Core client — Python SDK for the Ariadne Core REST API."""

from ariadne_core_client.exceptions import (
    AriadneAuthError,
    AriadneClientError,
    AriadneNotFoundError,
    AriadneServerError,
)
from ariadne_core_client.models import (
    Collection,
    Document,
    Health,
    IngestSummary,
    Interaction,
    SearchResponse,
    SearchResult,
    Stats,
    UploadResult,
)

__all__ = [
    # Client (added in step 3)
    # "AriadneClient",
    # Exceptions
    "AriadneClientError",
    "AriadneAuthError",
    "AriadneNotFoundError",
    "AriadneServerError",
    # Models
    "Collection",
    "Document",
    "Health",
    "IngestSummary",
    "Interaction",
    "SearchResponse",
    "SearchResult",
    "Stats",
    "UploadResult",
]
