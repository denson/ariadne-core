# Step 3: Store layer — collection-level soft delete and restore

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 3 of 8. Steps 1-2 must be committed first.

## What to do

Add collection-level delete and restore to the store layer.

### Methods to add

- `soft_delete_collection(collection_name: str)` — soft-deletes ALL active documents in that collection. Sets `deleted_at` and `deletion_scheduled_at` on each. Returns count of documents marked.
- `restore_collection(collection_name: str)` — restores all soft-deleted documents in that collection where `deletion_scheduled_at` is within 48 hours. Returns count of documents restored.

### Important

- Does NOT delete the collection record itself — just marks its documents
- Documents that were individually deleted before the collection delete should keep their original `deletion_scheduled_at` (don't reset the clock)
- `restore_collection` only restores documents whose `deletion_scheduled_at` is within 48 hours — expired ones stay deleted

## Do not touch

- MCP tools, REST endpoints (steps 4 and 5)
- SPEC.md, skills, docs

## Do not commit

Report what you changed. Leave for Bob.
