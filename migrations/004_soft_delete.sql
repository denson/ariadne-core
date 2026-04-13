-- Add soft delete columns to the documents table.
-- deleted_at: null = active, non-null = soft-deleted (timestamp of deletion).
-- deletion_scheduled_at: when the deletion was requested (used for the 48hr
-- purge window).
--
-- Both columns are nullable and default NULL so existing rows remain active.
-- Idempotent via IF NOT EXISTS.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ DEFAULT NULL;
