"""API key authentication middleware.

Validates X-API-Key header against hashed keys. In Phase 1, uses an
in-memory key store. Phase 5+ will use the api_keys Postgres table.

The key's `name` field is used as the `agent_id` in provenance tracking.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class APIKey:
    """An API key record."""

    key_hash: str
    name: str
    default_collection: str | None = None
    rate_limit_per_minute: int = 100
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    revoked_at: str | None = None


def hash_api_key(raw_key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class APIKeyStore(Protocol):
    """Protocol for API key storage backends."""

    def find_by_hash(self, key_hash: str) -> APIKey | None: ...

    def create_key(self, name: str, raw_key: str) -> APIKey: ...


class InMemoryAPIKeyStore:
    """In-memory API key store for Phase 1."""

    def __init__(self) -> None:
        self._keys: dict[str, APIKey] = {}  # key_hash -> APIKey

    def find_by_hash(self, key_hash: str) -> APIKey | None:
        key = self._keys.get(key_hash)
        if key and key.revoked_at is not None:
            return None
        return key

    def create_key(self, name: str, raw_key: str) -> APIKey:
        key_hash = hash_api_key(raw_key)
        api_key = APIKey(key_hash=key_hash, name=name)
        self._keys[key_hash] = api_key
        return api_key

    def revoke_key(self, key_hash: str) -> None:
        if key_hash in self._keys:
            self._keys[key_hash].revoked_at = datetime.now(timezone.utc).isoformat()


# Shared key store instance
_key_store = InMemoryAPIKeyStore()

# Auth enforcement flag — set by app lifespan from config.api.require_auth
_require_auth: bool = False


def set_require_auth(enabled: bool) -> None:
    """Enable or disable mandatory auth. Called during app startup."""
    global _require_auth
    _require_auth = enabled


def get_key_store() -> InMemoryAPIKeyStore:
    """Get the shared API key store."""
    return _key_store


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> APIKey:
    """Dependency that requires a valid API key.

    Raises HTTPException 401 if no key provided, 403 if invalid.
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
        )

    key_hash = hash_api_key(api_key)
    stored_key = _key_store.find_by_hash(key_hash)

    if stored_key is None:
        raise HTTPException(
            status_code=403,
            detail="Invalid or revoked API key.",
        )

    return stored_key


async def optional_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> APIKey | None:
    """Dependency that optionally validates an API key.

    Returns None if no key provided, raises 403 if key is invalid.
    """
    if not api_key:
        return None

    key_hash = hash_api_key(api_key)
    stored_key = _key_store.find_by_hash(key_hash)

    if stored_key is None:
        raise HTTPException(
            status_code=403,
            detail="Invalid or revoked API key.",
        )

    return stored_key


async def check_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> APIKey | None:
    """Dynamic auth dependency — enforces or skips based on require_auth config.

    When require_auth is true: behaves like require_api_key (401/403).
    When require_auth is false: behaves like optional_api_key (pass-through).
    """
    if _require_auth:
        return await require_api_key(request, api_key)
    return await optional_api_key(request, api_key)
