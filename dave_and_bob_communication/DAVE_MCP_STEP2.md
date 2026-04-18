# Step 2: Store layer — soft delete, update metadata, search filtering

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 2 of 8. Step 1 (schema) must be committed first.

## What to do

Add three capabilities to the document store layer.

### 2a: Soft delete and restore

**File:** wherever the store interface and Postgres implementation live (`dedup.py`, `pgvector.py`, or similar)

Add these methods:

- `soft_delete_document(document_id: str)` — sets `deleted_at = now()` and `deletion_scheduled_at = now()` on the document record. Does NOT delete chunks or interactions.
- `restore_document(document_id: str)` — clears `deleted_at` and `deletion_scheduled_at`. Should fail (raise or return error) if `deletion_scheduled_at` is more than 48 hours ago.
- `purge_deleted(older_than_hours: int = 48)` — hard deletes documents where `deletion_scheduled_at` is older than the threshold, PLUS their chunks and interactions. Returns count of purged documents.

### 2b: Update metadata

Add this method:

- `update_document_metadata(document_id: str, tags: list[str] | None = None, agent_metadata: dict | None = None, collection: str | None = None)` — partial update:
  - `tags`: if provided, REPLACES the entire tag list
  - `agent_metadata`: if provided, MERGES with existing metadata (Python dict update — new keys added, existing keys overwritten, unmentioned keys preserved)
  - `collection`: if provided, moves the document to the new collection (update the `collection_id` FK)
  - Returns the updated document metadata

### 2c: Search filtering

Update ALL existing query methods that return documents or chunks to exclude soft-deleted documents by default:

- Add `WHERE documents.deleted_at IS NULL` (or equivalent join condition) to every query
- Add an `include_deleted: bool = False` parameter that, when True, removes the filter
- This affects: search, list_documents, list_collections (for counts), get_document, find_by_fingerprint (dedup check)

**Important:** Dedup should NOT match against deleted documents. A document that was soft-deleted and then re-ingested should be treated as new.

## Do not touch

- MCP tools, REST endpoints (steps 4 and 5)
- SPEC.md, skills, docs

## Do not commit

Report what you changed and which files. Leave for Bob.
