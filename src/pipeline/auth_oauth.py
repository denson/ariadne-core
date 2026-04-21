"""OAuth 2.1 Bearer JWT authentication middleware.

Replaces the prior X-API-Key path (archived on `legacy/api-key` branch
and the `v0.x-legacy-api-key` tag at commit 14782a9). This module:

- Reads `AUTH0_DOMAIN` and `AUTH0_AUDIENCE` from the environment on
  first use. Neither is read at import time so tests stay hermetic
  and so the module can be imported in environments without Auth0
  configured (e.g. a config-loading utility).
- Fetches Auth0's JWKS from `https://{AUTH0_DOMAIN}/.well-known/jwks.json`
  using PyJWT's `PyJWKClient`, which handles cache + TTL refresh
  internally. We lift the default TTL from 300s to 600s (10 min) to
  match the brief and to reduce JWKS hits in steady state. Explicit
  key-rotation path: on `PyJWKClientError` (unknown `kid`) we force
  one refresh, which covers the "Auth0 rotated signing keys and we
  haven't picked up the new set yet" window without the caller having
  to wait for the TTL to elapse.
- Validates JWTs: RS256 signature against the JWKS, `iss` match
  (`https://{AUTH0_DOMAIN}/` — trailing slash, which is what Auth0
  emits), `aud` match, `exp` in the future. Each distinct failure maps
  to a specific short, structured 401 body (e.g. `{"detail":
  "invalid_signature"}`) — no token echo, no Auth0 payload reflected,
  no header values in the body. This is the env-isolation discipline
  applied to auth.
- Exposes `require_user` as a FastAPI dependency that yields a
  `Principal{user_id, email}` on success and raises `HTTPException(401)`
  with the specific reason on failure.

Logging: `user_id` (the `sub` claim) may be logged to stdout. `email`
is PII and is NOT logged — it flows through `Principal` to callers
that use it at the request boundary and nowhere else.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("ariadne.auth")

# The Bearer header extractor. auto_error=False so we can return our
# own specific 401 body (`missing_token`) rather than FastAPI's default
# generic "Not authenticated" string, and so OPTIONS / CORS preflights
# don't get a 403 before the route's own 401 fires.
_bearer = HTTPBearer(auto_error=False)

# JWT signing algorithm we accept from Auth0. RS256 is asymmetric —
# Auth0 signs with its private key and we verify with the public key
# in the JWKS. We do NOT accept symmetric algorithms (HS256) — that
# would require sharing a secret with Auth0, which we are not doing.
_ALGORITHMS = ["RS256"]

# JWKS cache / key-rotation state. Per-process, reset on server restart.
_jwks_lock = threading.Lock()
_jwks_client: jwt.PyJWKClient | None = None
_jwks_client_domain: str | None = None


@dataclass(frozen=True)
class Principal:
    """The authenticated subject of a request.

    `user_id` is the Auth0 `sub` claim — stable across token refreshes.
    Use this for agent_id attribution in interaction logs.

    `email` is the `email` claim if the token was issued with the
    `openid profile email` scope. May be `None` for tokens from
    machine-to-machine clients that don't have an associated user.
    Do NOT log this to stdout — it's PII.
    """

    user_id: str
    email: str | None = None


def _read_auth0_env() -> tuple[str, str]:
    """Read AUTH0_DOMAIN and AUTH0_AUDIENCE from the process environment.

    Raises HTTPException(500) — not 401 — if either is unset, because
    that's a server-misconfiguration signal, not a client-auth failure.
    We want the request to fail loudly with a 500 so deploy logs catch
    it, rather than returning a spurious 401 that makes clients think
    their token is bad.
    """
    domain = os.environ.get("AUTH0_DOMAIN")
    audience = os.environ.get("AUTH0_AUDIENCE")
    if not domain or not audience:
        logger.error(
            "Auth0 misconfigured: AUTH0_DOMAIN=%r AUTH0_AUDIENCE=%r",
            bool(domain),
            bool(audience),
        )
        raise HTTPException(
            status_code=500,
            detail="auth_misconfigured",
        )
    return domain, audience


def _get_jwks_client(domain: str) -> jwt.PyJWKClient:
    """Lazily build (and cache) the PyJWKClient for the current domain.

    If AUTH0_DOMAIN ever changes at runtime (it won't in normal
    operation, but tests may monkeypatch it), we rebuild the client so
    the JWKS URL matches. The lock protects the rare concurrent
    first-use case.

    `lifespan=600` is the cache TTL in seconds. `max_cached_keys=16`
    is the upper bound on distinct signing keys we cache across
    Auth0 rotations; 16 covers months of rotations comfortably.
    """
    global _jwks_client, _jwks_client_domain
    with _jwks_lock:
        if _jwks_client is None or _jwks_client_domain != domain:
            jwks_url = f"https://{domain}/.well-known/jwks.json"
            _jwks_client = jwt.PyJWKClient(
                jwks_url,
                cache_jwk_set=True,
                lifespan=600,
                max_cached_keys=16,
            )
            _jwks_client_domain = domain
        return _jwks_client


def _reset_jwks_cache_for_tests() -> None:
    """Drop the module-level JWKS client. Tests call this in setup.

    Not part of the public runtime API — it exists so tests can rebind
    AUTH0_DOMAIN/AUTH0_AUDIENCE via monkeypatch.setenv and be sure
    that a stale client from a previous test doesn't serve the next.
    """
    global _jwks_client, _jwks_client_domain
    with _jwks_lock:
        _jwks_client = None
        _jwks_client_domain = None


def _get_signing_key(token: str, domain: str) -> Any:
    """Fetch the signing key matching `token`'s `kid`.

    Tries the cache first. On `PyJWKClientError` (kid not in cached
    JWKS), forces one re-fetch of the JWKS — this covers the explicit
    key-rotation path the brief calls out, where Auth0 has rotated and
    our cached set doesn't yet include the new key but the TTL hasn't
    expired. If the second fetch still doesn't have the key, we fail
    the request.

    Using `get_signing_key_from_jwt` (singular) is the current
    canonical API per the PyJWT 2.x docs.
    """
    client = _get_jwks_client(domain)
    try:
        return client.get_signing_key_from_jwt(token).key
    except jwt.PyJWKClientError:
        # Force a JWKS re-fetch. PyJWKClient exposes this via
        # `get_jwk_set(refresh=True)` on recent versions, but the
        # portable escape hatch (works on 2.8+) is to drop our
        # in-memory client and rebuild — next call hits the network.
        with _jwks_lock:
            global _jwks_client, _jwks_client_domain
            _jwks_client = None
            _jwks_client_domain = None
        client = _get_jwks_client(domain)
        # Second attempt. If this still raises PyJWKClientError the
        # caller converts it to a 401 `unknown_kid`.
        return client.get_signing_key_from_jwt(token).key


def _decode_token(token: str) -> dict[str, Any]:
    """Validate and decode a Bearer JWT. Returns the claims dict on
    success; raises HTTPException(401) with a specific detail string
    on any failure.

    The detail strings are part of the contract — test_auth_oauth
    asserts on them. Keep them short, snake_case, no trailing
    punctuation, and do NOT include any token content.
    """
    domain, audience = _read_auth0_env()
    issuer = f"https://{domain}/"

    # Extract signing key by kid. get_signing_key_from_jwt itself
    # parses the token header to find `kid`, so a token with no
    # recognizable header will raise DecodeError here rather than
    # reaching `jwt.decode`. We catch both.
    try:
        signing_key = _get_signing_key(token, domain)
    except jwt.PyJWKClientError:
        raise HTTPException(status_code=401, detail="unknown_kid")
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="malformed_token")

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=_ALGORITHMS,
            audience=audience,
            issuer=issuer,
            # options: PyJWT validates exp/iat/nbf by default. We do
            # NOT set require=[...] beyond what Auth0 emits — that
            # would couple us to specific claim names that may change
            # across Auth0 plans.
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="expired_token")
    except jwt.InvalidSignatureError:
        raise HTTPException(status_code=401, detail="invalid_signature")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="wrong_audience")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="wrong_issuer")
    except jwt.DecodeError:
        # Catches structural problems jwt.decode surfaces after kid
        # extraction (not-three-parts, base64 padding, etc.).
        raise HTTPException(status_code=401, detail="malformed_token")
    except jwt.InvalidTokenError:
        # Catch-all for any other InvalidTokenError subclass — unlikely
        # given the explicit branches above, but safer to 401 than to
        # let the exception bubble and turn into a 500. Specific string
        # so it's distinguishable from signature / audience / issuer
        # cases in tests and in production logs.
        raise HTTPException(status_code=401, detail="invalid_token")

    return claims


async def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """FastAPI dependency — yields the authenticated Principal.

    Raises HTTPException(401) with a specific `detail` string on any
    auth failure. The response body is always of the form
    `{"detail": "<reason>"}` — no token content, no header values, no
    Auth0 error payload leaks through.

    Cases:
    - `missing_token` — no Authorization header.
    - `wrong_scheme` — Authorization header present but not `Bearer`.
    - `malformed_token` — JWT structurally invalid (not three base64
      parts, bad header, bad kid claim type).
    - `invalid_signature` — signature doesn't verify against the JWKS.
    - `expired_token` — `exp` claim is in the past.
    - `wrong_audience` — `aud` claim doesn't match AUTH0_AUDIENCE.
    - `wrong_issuer` — `iss` claim doesn't match `https://{AUTH0_DOMAIN}/`.
    - `unknown_kid` — kid in token header not present in JWKS even
      after a forced refresh.
    - `missing_sub_claim` — token is valid but has no `sub`, which
      shouldn't happen for Auth0 tokens but is defensive.
    """
    # credentials is None when the Authorization header is absent or
    # uses a non-Bearer scheme (HTTPBearer(auto_error=False) returns
    # None in both cases). Distinguish them by re-reading the raw
    # header so we can return `missing_token` vs `wrong_scheme`
    # specifically.
    if credentials is None:
        # Distinguish missing header from wrong scheme. If the client
        # sent an Authorization header with a non-Bearer scheme
        # (e.g. `Basic`, `Digest`), HTTPBearer returns None too — so
        # we read the raw header to tell the two cases apart.
        raw = request.headers.get("Authorization")
        if raw is None or raw.strip() == "":
            raise HTTPException(status_code=401, detail="missing_token")
        raise HTTPException(status_code=401, detail="wrong_scheme")

    # Redundant safety: credentials.scheme should always be "Bearer"
    # when HTTPBearer returned non-None, but assert rather than assume.
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="wrong_scheme")

    token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="missing_token")

    claims = _decode_token(token)

    user_id = claims.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="missing_sub_claim")

    email = claims.get("email") if isinstance(claims.get("email"), str) else None

    # Log user_id only. email is PII — it flows to callers via the
    # Principal but does not reach stdout.
    logger.debug("authenticated user_id=%s", user_id)

    return Principal(user_id=user_id, email=email)


__all__ = ["Principal", "require_user"]
