"""Shared pytest fixtures.

This module provides a `pg_dedup_store` fixture that connects to a local
Postgres instance for integration tests. It is opt-in: if no Postgres is
reachable, tests that depend on the fixture are skipped rather than
failing, so the full suite still runs cleanly on a machine without
docker compose up.

It also provides `override_auth(app)` — a helper that installs a
dependency override so route tests can use `TestClient(app)` without
a real Auth0 token. See the "OAuth override helper" section below.

To run the Pg integration tests locally:
    docker compose up -d postgres
    export DB_PASSWORD=local-dev-only  # or whatever is in .env
    pytest tests/test_dedup_resurrection.py -v

Or to point at an arbitrary Pg (e.g. CI):
    export ARIADNE_TEST_DATABASE_URL=postgresql://user:pw@host:5432/db
    pytest tests/test_dedup_resurrection.py -v
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI


# ── OAuth override helper ────────────────────────────────────────────────────
#
# Route tests construct a fresh FastAPI and include the production
# router, but they do not have a real Auth0 token — and spinning up
# the JWKS client + signing fresh JWTs for every route test would be
# overkill. `test_auth_oauth.py` is the one place that exercises the
# real token-validation path; every other route test just needs the
# routes to be reachable.
#
# FastAPI's standard escape hatch for this is `app.dependency_overrides`:
# we register a fake that returns a fixed Principal, so `require_user`
# resolves to that Principal without ever calling PyJWKClient.

def override_auth(app: FastAPI, user_id: str = "test-user") -> None:
    """Install a dependency override so TestClient requests authenticate
    as a fixed test Principal instead of validating an Auth0 token.

    Use this in any route-level test fixture that doesn't specifically
    exercise auth. test_auth_oauth.py does NOT use this helper — it
    drives the real require_user through a mocked JWKS.
    """
    from pipeline.auth_oauth import Principal, require_user

    def _fake_principal() -> Principal:
        return Principal(user_id=user_id, email=None)

    app.dependency_overrides[require_user] = _fake_principal


def _default_test_db_url() -> str:
    explicit = os.environ.get("ARIADNE_TEST_DATABASE_URL")
    if explicit:
        return explicit
    pw = os.environ.get("DB_PASSWORD", "local-dev-only")
    return f"postgresql://app:{pw}@localhost:5432/pipeline"


@pytest.fixture(scope="session")
def pg_pool():
    """Shared psycopg connection pool for the test session.

    Skips the test module if Postgres is unreachable. Applies migrations
    once per session so PgDedupStore can operate on a schema that matches
    production.
    """
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        pytest.skip("psycopg_pool not installed — skipping Pg integration tests")

    url = _default_test_db_url()

    # Parse the URL into kwargs so passwords with special chars survive.
    from pipeline.stores import _parse_db_url, _apply_migrations, _ensure_schema
    from pipeline.config import load_config

    try:
        pool = ConnectionPool(
            conninfo=_parse_db_url(url),
            min_size=1,
            max_size=3,
            open=True,
            timeout=5,
        )
    except Exception as e:
        pytest.skip(f"Postgres not reachable at {url!r}: {e}")

    try:
        # Re-use the production migration bootstrap so schema matches.
        cwd = Path.cwd()
        _apply_migrations(pool)
        cfg = load_config()
        _ensure_schema(pool, cfg.embedding.dimensions)
    except Exception as e:
        pool.close()
        pytest.skip(f"Could not apply migrations / ensure schema: {e}")

    yield pool
    pool.close()


@pytest.fixture
def pg_dedup_store(pg_pool):
    """A PgDedupStore bound to the session pool.

    The fixture does not truncate tables — instead, each test should use a
    unique collection name (include ``uuid.uuid4().hex`` in it) so rows
    from different tests do not collide. The test teardown purges that
    collection hard to avoid polluting the dev DB.
    """
    from pipeline.dedup import PgDedupStore

    store = PgDedupStore(pg_pool)
    created_collections: list[str] = []

    original_store_document = store.store_document

    def tracking_store_document(doc, **kwargs):
        # Forward kwargs (e.g. ariadne--5f2's ``agent_metadata=``) so the
        # fixture wrapper stays transparent to signature additions.
        if doc.collection_id not in created_collections:
            created_collections.append(doc.collection_id)
        return original_store_document(doc, **kwargs)

    store.store_document = tracking_store_document  # type: ignore[method-assign]

    yield store

    # Teardown: hard-purge every test-created collection so repeated runs
    # stay clean. We call soft_delete_collection + purge_deleted(0) —
    # same path the new ?purge=true route uses.
    for coll in created_collections:
        try:
            store.soft_delete_collection(coll)
            store.purge_deleted(older_than_hours=0)
        except Exception:
            pass


@pytest.fixture
def unique_collection():
    """Returns a fresh collection name unique to this test run."""
    return f"test_{uuid.uuid4().hex[:12]}"


# ── m5e: confirmation-secret isolation ───────────────────────────────────────
#
# Tests that exercise the confirmation flow need a deterministic HMAC secret
# so token-equivalence assertions are reproducible AND so a prior test that
# mutates the secret cannot leak into a subsequent test. The secret is per-
# process (no shared store), so this fixture is per-worker when pytest-xdist
# is in use — each worker has its own confirmation module state and the
# autouse fixture handles isolation within each worker. Cross-worker
# contamination is structurally impossible.
#
# Tests that need a different secret value (e.g., to assert HMAC mismatch
# across rotations) call ``configure_confirmation(secret=b"other-secret")``
# inside the test body — the fixture's teardown still restores the saved-
# at-setup value at the end.

@pytest.fixture(autouse=True)
def _confirmation_secret_isolation():
    """Save/restore the m5e confirmation secret around each test."""
    from pipeline.api import confirmation
    saved = getattr(confirmation, "_CONFIRMATION_SECRET", None)
    confirmation.configure_confirmation(secret=b"test-secret-do-not-ship")
    try:
        yield
    finally:
        # Restore the saved-at-setup value (which may itself be None if
        # the test session had not yet configured a secret). Direct
        # attribute write rather than a fresh call to configure_confirmation
        # so a saved=None state is preserved exactly.
        confirmation._CONFIRMATION_SECRET = saved
