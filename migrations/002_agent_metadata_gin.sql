-- Ariadne Core — Add GIN index on document_interactions.agent_metadata
--
-- Supports the POST /api/search ``metadata`` (JSONB containment ``@>``) and
-- ``metadata_exists`` (key existence ``?``) filter keys introduced for the
-- ariadne--8fd ticket. The search path uses a correlated subquery picking the
-- most recent interaction row per document and applies the JSONB operators
-- against its ``agent_metadata`` column — the GIN index makes those operators
-- index-eligible at scale.
--
-- Why no ``CONCURRENTLY``:
--
-- The BL-25 migration runner (src/pipeline/stores.py:_apply_migrations)
-- executes each migration file inside an implicit psycopg connection
-- transaction, then commits. ``CREATE INDEX CONCURRENTLY`` cannot run inside
-- a transaction block — Postgres raises ``25001`` if attempted. Adding a
-- runner-level ``-- @no-transaction`` directive would expand the brief's
-- scope, so this migration falls back to the standard (blocking) form.
--
-- Operational impact: a brief AccessExclusiveLock on
-- ``document_interactions`` during the build. The table is small at current
-- corpus scale, and ``IF NOT EXISTS`` makes the migration idempotent on
-- re-deploy / re-run. If the table ever grows to a scale where the lock
-- window matters in production, switch the runner to per-migration
-- autocommit mode and reintroduce ``CONCURRENTLY`` — see ariadne--8fd
-- follow-ups.

CREATE INDEX IF NOT EXISTS idx_interactions_agent_metadata
    ON document_interactions USING GIN (agent_metadata);
