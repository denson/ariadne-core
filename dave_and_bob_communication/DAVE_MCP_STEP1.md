# Step 1: Database schema — soft delete columns

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 1 of 8.

## What to do

Add soft delete support to the documents table.

### Schema change

**File:** `ariadne-core/src/pipeline/schema.py`

Add two nullable timestamp columns to the `CHUNKS_TABLE_SQL` template... wait, the documents table is defined elsewhere. Find where the `documents` table CREATE TABLE lives (likely in a migration or in the store initialization code) and add:

```sql
deleted_at TIMESTAMPTZ DEFAULT NULL,
deletion_scheduled_at TIMESTAMPTZ DEFAULT NULL
```

- `deleted_at` — null means active, non-null means soft-deleted (timestamp of when it was deleted)
- `deletion_scheduled_at` — when the deletion was requested (used for 48hr purge window)

### Migration

**File:** `ariadne-core/migrations/` — create a new migration file (004 or whatever the next number is)

The migration should ALTER the existing `documents` table to add both columns:

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ DEFAULT NULL;
```

Look at existing migrations in that directory to match the naming convention and format.

### Update the migration runner

Make sure the migration runner in the store initialization code picks up the new migration file.

## Do not touch

- chunks table (inherits deletion from parent document)
- Any code outside schema.py and migrations/
- SPEC.md, skills, docs

## Do not commit

Report what you changed. Leave for Bob.
