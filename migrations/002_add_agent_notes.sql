-- Add agent_notes column to document_interactions.
-- The original schema stored agent_metadata in the generic 'metadata' column.
-- This migration adds the explicit agent_notes text field and renames
-- 'metadata' to 'agent_metadata' for clarity.

ALTER TABLE document_interactions
    ADD COLUMN IF NOT EXISTS agent_notes TEXT;

-- Rename the generic 'metadata' column to 'agent_metadata' for clarity.
-- Use DO block to make this idempotent (skip if already renamed).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'document_interactions' AND column_name = 'metadata'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'document_interactions' AND column_name = 'agent_metadata'
    ) THEN
        ALTER TABLE document_interactions RENAME COLUMN metadata TO agent_metadata;
    END IF;
END $$;
