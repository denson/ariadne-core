"""Ariadne Core client — Python SDK for the Ariadne Core REST API."""

from ariadne_core_client.client import AriadneClient
from ariadne_core_client.exceptions import (
    AriadneAuthError,
    AriadneClientError,
    AriadneNotFoundError,
    AriadneServerError,
    ConfirmationRequired,
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
    # Client
    "AriadneClient",
    # Exceptions
    "AriadneClientError",
    "AriadneAuthError",
    "AriadneNotFoundError",
    "AriadneServerError",
    "ConfirmationRequired",
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
