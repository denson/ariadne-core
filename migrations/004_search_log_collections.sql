-- Ariadne Core — Promote search_log.collections to a first-class column
--
-- ariadne--2cf: ``SearchRequest.collections`` (multi-collection scope, added
-- in ariadne--wgi) was persisted only inside the ``filters`` JSONB column
-- as ``collection_in: [...]``. Analytics queries on multi-collection usage
-- had to use JSONB containment, which is heavier than direct TEXT[]
-- membership and obscures the schema at ``\d search_log``. This migration
-- promotes the field to a first-class TEXT[] column with a GIN index,
-- enabling:
--
--   • ``SELECT COUNT(*) FROM search_log WHERE collections IS NOT NULL;``
--   • ``SELECT unnest(collections) AS coll, COUNT(*) FROM search_log
--      GROUP BY 1;``
--   • ``SELECT * FROM search_log WHERE 'project-a' = ANY(collections);``
--
-- Additive + nullable, so the migration is a pure ADD COLUMN. No backfill
-- is required: pre-arc rows had no multi-collection data, and post-arc
-- rows that wrote multi-scope before this migration applied are
-- recoverable from ``filters @> '{"collection_in": []}'::jsonb`` if ever
-- needed (the ad-hoc query is trivial).
--
-- Why no ``CONCURRENTLY``: same reason as migration 002 — the BL-25
-- migration runner executes each file inside a transaction and Postgres
-- forbids ``CREATE INDEX CONCURRENTLY`` in a transaction block. The
-- AccessExclusiveLock on ``search_log`` during the build is brief at
-- current corpus scale and ``IF NOT EXISTS`` keeps the migration
-- idempotent on re-deploy.
--
-- Folded forward into ``001_initial.sql`` for fresh deploys.

ALTER TABLE search_log ADD COLUMN IF NOT EXISTS collections TEXT[];

CREATE INDEX IF NOT EXISTS idx_search_log_collections
    ON search_log USING GIN (collections);
