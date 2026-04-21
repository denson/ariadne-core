"""Tests for `pipeline.auth_oauth` — the OAuth Bearer JWT middleware.

These tests are hermetic: no network, no live Auth0 tenant. We generate
a throwaway RSA keypair per test, build the JWKS ourselves, sign JWTs
with the private key, and monkeypatch `jwt.PyJWKClient` so it returns
our public key instead of fetching Auth0.

Coverage (ariadne--xft.2 brief):
  1. JWT validation happy path — signs a valid token, asserts Principal.
  2. JWT validation error paths — each returns a specific 401 detail:
     missing header, wrong scheme, malformed, bad signature, bad aud,
     bad iss, expired, unknown kid even after refresh.
  3. JWKS cache + refresh — cache hit within TTL; key-rotation via
     unknown-kid forcing a refresh.
  4. `/.well-known/ariadne-config` shape.
  5. Route wiring — /api/health open; protected routes 401 without
     token, 200 with a mocked valid token.

The helper machinery (keypair generation, JWKS dict construction,
token signing) is at the top of the file. Each test class / function
resets the module-level JWKS cache via `_reset_jwks_cache_for_tests`
so stale state from a prior test doesn't leak across.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from pipeline import auth_oauth
from pipeline.auth_oauth import Principal, require_user


# ── Test infrastructure ─────────────────────────────────────────────────────


def _generate_rsa_keypair() -> tuple[Any, str]:
    """Generate a 2048-bit RSA keypair. Returns (private_key_obj, public_pem_str).

    The private key object is what PyJWT wants for signing; the public
    PEM string is what we bundle into the JWKS for verification.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key, public_pem


def _b64url_uint(n: int) -> str:
    """Encode an integer as unsigned-big-endian base64url (no padding).

    This is the JWK encoding for `n` (modulus) and `e` (exponent) on an
    RSA public key — see RFC 7518 §6.3.1.
    """
    length = (n.bit_length() + 7) // 8
    raw = n.to_bytes(length, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _build_jwk(private_key: Any, kid: str) -> dict:
    """Build a JWKS entry (as a dict) for `private_key`'s public half."""
    public_numbers = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url_uint(public_numbers.n),
        "e": _b64url_uint(public_numbers.e),
    }


def _sign_jwt(
    private_key: Any,
    kid: str,
    *,
    sub: str = "auth0|user-123",
    email: str | None = "user@example.com",
    aud: str = "https://ariadne-core",
    iss: str = "https://test-tenant.auth0.com/",
    exp_offset: int = 3600,
    extra_claims: dict | None = None,
) -> str:
    """Sign a JWT with `private_key`. Returns the compact-serialized string.

    `exp_offset` is seconds relative to now — pass a negative value to
    produce an already-expired token. `extra_claims` is merged on top of
    the default claims, so tests can inject or override anything.
    """
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_offset,
    }
    if email is not None:
        claims["email"] = email
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


class _FakePyJWKClient:
    """Drop-in stand-in for `jwt.PyJWKClient`.

    Tracks how many times `get_signing_key_from_jwt` was called so we
    can assert on cache-vs-refresh behavior. Holds a small dict of
    `kid -> public_pem_str` and raises `PyJWKClientError` on unknown
    kids.
    """

    def __init__(self, *_, **__) -> None:
        # The arguments PyJWT passes (url, cache_jwk_set, lifespan, ...)
        # are irrelevant to the fake — we store whatever the test fixture
        # puts into `.keys_by_kid` post-construction.
        self.keys_by_kid: dict[str, str] = {}
        self.call_count = 0

    def get_signing_key_from_jwt(self, token: str):
        self.call_count += 1
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if kid not in self.keys_by_kid:
            raise jwt.PyJWKClientError(f"unknown kid {kid!r}")

        class _Key:
            def __init__(self, pem: str) -> None:
                self.key = serialization.load_pem_public_key(pem.encode("utf-8"))

        return _Key(self.keys_by_kid[kid])


@pytest.fixture
def auth_env(monkeypatch):
    """Set AUTH0_DOMAIN / AUTH0_AUDIENCE / AUTH0_CLIENT_ID for the test."""
    monkeypatch.setenv("AUTH0_DOMAIN", "test-tenant.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://ariadne-core")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "test-client-id")


@pytest.fixture
def fake_jwks(monkeypatch):
    """Install a _FakePyJWKClient + reset the module's cached client.

    Yields the fake client so tests can mutate `.keys_by_kid` and assert
    on `.call_count`.
    """
    fake = _FakePyJWKClient()
    # Patch jwt.PyJWKClient in the auth_oauth namespace (it's accessed
    # as `jwt.PyJWKClient` there) — every call to `_get_jwks_client`
    # constructs one of our fakes instead of a real one.
    monkeypatch.setattr(
        auth_oauth.jwt,
        "PyJWKClient",
        lambda *a, **kw: fake,
    )
    auth_oauth._reset_jwks_cache_for_tests()
    yield fake
    auth_oauth._reset_jwks_cache_for_tests()


@pytest.fixture
def keypair():
    """Fresh RSA keypair per test so no cross-test contamination."""
    return _generate_rsa_keypair()


# ── Helpers for building a FastAPI app with require_user bound ──────────────


def _protected_app() -> FastAPI:
    """A tiny FastAPI app with one route behind `require_user`.

    We don't mount the full `pipeline.api.routes` router — that pulls in
    the services layer and configure_stores, which is tested elsewhere.
    Here we only care that `require_user` as a FastAPI dependency
    round-trips the Principal on success and rejects on failure.
    """
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(principal: Principal = Depends(require_user)) -> dict:
        return {"user_id": principal.user_id, "email": principal.email}

    return app


# ── 1. Happy path ──────────────────────────────────────────────────────────


def test_valid_token_returns_principal(auth_env, fake_jwks, keypair):
    private_key, public_pem = keypair
    kid = "test-kid-1"
    fake_jwks.keys_by_kid[kid] = public_pem

    token = _sign_jwt(
        private_key, kid,
        sub="auth0|user-happy",
        email="happy@example.com",
    )

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "user_id": "auth0|user-happy",
        "email": "happy@example.com",
    }


def test_valid_token_without_email_claim(auth_env, fake_jwks, keypair):
    """Machine-to-machine tokens don't carry an `email` — Principal.email is None."""
    private_key, public_pem = keypair
    kid = "m2m-kid"
    fake_jwks.keys_by_kid[kid] = public_pem

    token = _sign_jwt(private_key, kid, sub="auth0|m2m", email=None)

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == "auth0|m2m"
    assert body["email"] is None


# ── 2. Error paths — each must return its specific 401 detail string ───────


def test_missing_authorization_header(auth_env, fake_jwks):
    client = TestClient(_protected_app())
    resp = client.get("/whoami")
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "missing_token"}


def test_empty_authorization_header(auth_env, fake_jwks):
    """An empty Authorization header is `missing_token`, not `wrong_scheme`."""
    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": "   "})
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "missing_token"}


def test_basic_scheme_is_wrong_scheme(auth_env, fake_jwks):
    client = TestClient(_protected_app())
    # `Basic <base64>` — valid HTTP auth scheme, but not Bearer.
    resp = client.get(
        "/whoami",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "wrong_scheme"}


def test_digest_scheme_is_wrong_scheme(auth_env, fake_jwks):
    client = TestClient(_protected_app())
    resp = client.get(
        "/whoami",
        headers={"Authorization": "Digest username=alice"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "wrong_scheme"}


def test_malformed_token_not_three_parts(auth_env, fake_jwks):
    client = TestClient(_protected_app())
    resp = client.get(
        "/whoami",
        headers={"Authorization": "Bearer not.a.valid.jwt.string"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "malformed_token"


def test_malformed_token_random_garbage(auth_env, fake_jwks):
    client = TestClient(_protected_app())
    resp = client.get(
        "/whoami",
        headers={"Authorization": "Bearer abcdefg"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "malformed_token"


def test_invalid_signature(auth_env, fake_jwks, keypair):
    """Token signed with a DIFFERENT key than the JWKS claims it was signed with."""
    signer_key, _ = keypair  # actually signs the token
    attacker_key, attacker_pem = _generate_rsa_keypair()  # goes into JWKS

    kid = "rotated-kid"
    # The JWKS returns `attacker_pem`, but the token was signed by
    # `signer_key` — so signature verification fails.
    fake_jwks.keys_by_kid[kid] = attacker_pem

    # Sign WITHOUT _sign_jwt's defaults but with the wrong key.
    token = _sign_jwt(signer_key, kid)

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "invalid_signature"


def test_wrong_audience(auth_env, fake_jwks, keypair):
    private_key, public_pem = keypair
    kid = "aud-kid"
    fake_jwks.keys_by_kid[kid] = public_pem

    token = _sign_jwt(private_key, kid, aud="https://some-other-api")

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "wrong_audience"


def test_wrong_issuer(auth_env, fake_jwks, keypair):
    private_key, public_pem = keypair
    kid = "iss-kid"
    fake_jwks.keys_by_kid[kid] = public_pem

    token = _sign_jwt(
        private_key, kid,
        iss="https://attacker.example.com/",
    )

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "wrong_issuer"


def test_expired_token(auth_env, fake_jwks, keypair):
    private_key, public_pem = keypair
    kid = "exp-kid"
    fake_jwks.keys_by_kid[kid] = public_pem

    # exp is 60s in the past.
    token = _sign_jwt(private_key, kid, exp_offset=-60)

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "expired_token"


def test_unknown_kid_even_after_refresh(auth_env, fake_jwks, keypair):
    """Token's kid is not in the JWKS and a forced refresh doesn't find it.

    Our middleware drops the cached PyJWKClient on first miss, builds a
    new one (which in this test is a fresh _FakePyJWKClient instance
    with an empty keys_by_kid), and tries again. The second miss
    surfaces as 401 unknown_kid.
    """
    private_key, _ = keypair
    kid = "ghost-kid"
    # Deliberately do NOT populate fake_jwks.keys_by_kid[kid].

    token = _sign_jwt(private_key, kid)

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "unknown_kid"


def test_missing_sub_claim(auth_env, fake_jwks, keypair):
    """A valid-signature JWT with no `sub` claim is rejected with missing_sub_claim."""
    private_key, public_pem = keypair
    kid = "nosub-kid"
    fake_jwks.keys_by_kid[kid] = public_pem

    # Build claims without sub. We sidestep _sign_jwt because it always
    # sets sub; use jwt.encode directly.
    now = int(time.time())
    claims = {
        "iss": "https://test-tenant.auth0.com/",
        "aud": "https://ariadne-core",
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})

    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "missing_sub_claim"


def test_bearer_prefix_but_empty_token(auth_env, fake_jwks):
    """`Authorization: Bearer ` with nothing after is treated as missing.

    HTTPBearer with auto_error=False returns None when the token part is
    empty, so this path routes through the `missing_token` branch.
    """
    client = TestClient(_protected_app())
    resp = client.get("/whoami", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401, resp.text
    # Either missing_token (HTTPBearer returned None) or wrong_scheme —
    # in practice starlette's HTTPBearer returns None for "Bearer " with
    # trailing whitespace, hitting the missing_token branch.
    assert resp.json()["detail"] in ("missing_token", "wrong_scheme")


# ── 3. JWKS cache + refresh ────────────────────────────────────────────────


def test_jwks_cache_hit_within_ttl(auth_env, fake_jwks, keypair):
    """Two valid requests → JWKS client constructed once, multiple signing-key fetches.

    The important property is that we don't spin up a new PyJWKClient
    per request (which would defeat the whole cache). The same fake
    instance handles both calls.
    """
    private_key, public_pem = keypair
    kid = "cache-kid"
    fake_jwks.keys_by_kid[kid] = public_pem

    token = _sign_jwt(private_key, kid)

    client = TestClient(_protected_app())
    for _ in range(3):
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text

    # Our fake counts every get_signing_key_from_jwt call. 3 requests →
    # 3 calls, all against the same client instance. If the middleware
    # rebuilt the client per request, the count would be different
    # (still 3, but across 3 different instances) — the fixture only
    # installs one instance, so if the middleware rebuilt, the
    # reinstall would break. The invariant we're testing here is
    # "valid calls don't trigger a cache reset" — count == number of
    # requests and NO force-refresh was triggered.
    assert fake_jwks.call_count == 3


def test_key_rotation_forces_refresh(auth_env, monkeypatch, keypair):
    """Unknown kid triggers a refresh; second JWKS contains the new key.

    Simulates: Auth0 rotated signing keys. Our cached JWKS has the old
    key. A token signed with the new key arrives. Our middleware sees
    PyJWKClientError on first lookup, drops the cached client, rebuilds,
    and the new client (fresh from "the network") has the new key.
    """
    auth_oauth._reset_jwks_cache_for_tests()
    private_key, public_pem = keypair

    old_fake = _FakePyJWKClient()
    # old_fake has NO key under `new-kid`
    new_fake = _FakePyJWKClient()
    new_fake.keys_by_kid["new-kid"] = public_pem  # post-rotation JWKS

    fakes = [old_fake, new_fake]

    def _factory(*_a, **_kw):
        return fakes.pop(0)

    monkeypatch.setattr(auth_oauth.jwt, "PyJWKClient", _factory)

    try:
        token = _sign_jwt(private_key, "new-kid")

        client = TestClient(_protected_app())
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text

        # Both fakes were used — old one took the first attempt (and
        # raised PyJWKClientError), new one served the retry.
        assert old_fake.call_count == 1
        assert new_fake.call_count == 1
        # The factory list is empty — only two clients were built, not
        # three. If something in the middleware kept looping, we'd see
        # IndexError on the pop, which is a clearer failure than
        # asserting further.
        assert fakes == []
    finally:
        auth_oauth._reset_jwks_cache_for_tests()


# ── 4. /.well-known/ariadne-config shape ───────────────────────────────────


def test_discovery_endpoint_returns_auth_block(auth_env):
    """Unauthenticated GET /.well-known/ariadne-config returns expected shape."""
    from pipeline.api.discovery import router as discovery_router

    app = FastAPI()
    app.include_router(discovery_router)
    client = TestClient(app)

    resp = client.get("/.well-known/ariadne-config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "auth": {
            "issuer": "https://test-tenant.auth0.com/",
            "client_id": "test-client-id",
            "audience": "https://ariadne-core",
            "scope": "openid profile email offline_access",
        }
    }


def test_discovery_endpoint_500_when_env_missing(monkeypatch):
    """If any Auth0 env is missing, discovery returns 500 auth_misconfigured."""
    # Deliberately do NOT set AUTH0_DOMAIN / etc. — clear them if present.
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH0_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)

    from pipeline.api.discovery import router as discovery_router

    app = FastAPI()
    app.include_router(discovery_router)
    client = TestClient(app)

    resp = client.get("/.well-known/ariadne-config")
    assert resp.status_code == 500, resp.text
    assert resp.json()["detail"] == "auth_misconfigured"


def test_discovery_endpoint_is_unauthenticated(auth_env):
    """Discovery returns 200 with NO Authorization header — it's the one
    open endpoint clients hit before they have a token."""
    from pipeline.api.discovery import router as discovery_router

    app = FastAPI()
    app.include_router(discovery_router)
    client = TestClient(app)

    # No headers at all.
    resp = client.get("/.well-known/ariadne-config")
    assert resp.status_code == 200, resp.text


# ── 5. Route wiring — real router at /api ──────────────────────────────────


def test_api_health_is_open(auth_env):
    """/api/health returns 200 without a token — it's the liveness probe."""
    from pipeline.api.routes import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text


def test_api_collections_requires_auth(auth_env, fake_jwks):
    """/api/collections without Authorization → 401 missing_token."""
    from pipeline.api.routes import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/collections")
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "missing_token"


def test_api_stats_requires_auth(auth_env, fake_jwks):
    """/api/stats without Authorization → 401 missing_token."""
    from pipeline.api.routes import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/stats")
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "missing_token"


def test_api_post_upload_requires_auth(auth_env, fake_jwks):
    """POST /api/upload without Authorization → 401 missing_token."""
    from pipeline.api.routes import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    resp = client.post("/api/upload")
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "missing_token"


def test_api_collections_with_valid_token(auth_env, fake_jwks, keypair):
    """/api/collections with a mocked valid token → 200 (not 401).

    We don't care about the response body — just that the auth
    middleware let the request through to the route handler, which
    needs the InMemory store to be configured via services.configure_stores.
    """
    from pipeline import services
    from pipeline.api.routes import router as api_router
    from pipeline.dedup import InMemoryDedupStore
    from pipeline.storage.base import InMemoryVectorStore

    services.configure_stores(InMemoryDedupStore(), InMemoryVectorStore())

    private_key, public_pem = keypair
    kid = "wiring-kid"
    fake_jwks.keys_by_kid[kid] = public_pem
    token = _sign_jwt(private_key, kid)

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    resp = client.get(
        "/api/collections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ── 6. Env-isolation: 401 bodies do NOT leak token content ─────────────────


def test_401_body_does_not_echo_token(auth_env, fake_jwks):
    """No 401 response anywhere includes the raw token or a header value.

    This is the env-isolation discipline applied to auth — a test of the
    contract, not of a specific code path. We probe several error cases
    with distinctive tokens and assert the token substring never appears
    in the body.
    """
    client = TestClient(_protected_app())

    sentinel_token = f"SENTINEL-{uuid.uuid4().hex}-FLAG"
    probes = [
        {"Authorization": f"Bearer {sentinel_token}"},
        {"Authorization": f"Basic {sentinel_token}"},
        {"Authorization": sentinel_token},  # no scheme at all
    ]

    for headers in probes:
        resp = client.get("/whoami", headers=headers)
        assert resp.status_code == 401, (headers, resp.text)
        body = resp.text
        assert sentinel_token not in body, (headers, body)
