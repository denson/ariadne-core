-- Add a warnings column to the documents table so the Pass-1
-- has_warnings filter actually queries persisted data. Prior to this
-- migration, StoredDocument.warnings was populated at ingest but
-- dropped on the floor at the INSERT; every row round-tripped as
-- warnings=[]. The filter silently matched nothing against prod.
--
-- Historical rows (pre-migration) get the default '{}' and will
-- appear warning-free forever unless backfilled from processing_chain
-- in a future task. Going forward, ingest persists warnings correctly.
--
-- Idempotent via IF NOT EXISTS — the migration runner re-applies
-- migrations on each boot, so this must be safe to run repeatedly.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS warnings TEXT[] NOT NULL DEFAULT '{}';
