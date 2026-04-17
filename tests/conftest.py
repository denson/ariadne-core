"""Shared pytest fixtures.

This module provides a `pg_dedup_store` fixture that connects to a local
Postgres instance for integration tests. It is opt-in: if no Postgres is
reachable, tests that depend on the fixture are skipped rather than
failing, so the full suite still runs cleanly on a machine without
docker compose up.

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

    def tracking_store_document(doc):
        if doc.collection_id not in created_collections:
            created_collections.append(doc.collection_id)
        return original_store_document(doc)

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
