# Step 5: REST API endpoints — mirror MCP tools

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 5 of 8. Steps 1-4 must be committed first.

## What to do

Add REST endpoints that mirror every new MCP tool from Step 4.

**File:** `ariadne-core/src/pipeline/api/routes.py`

### New endpoints

- `PATCH /api/documents/{document_id}` — update metadata
  - Body: `{ "tags": [...], "agent_metadata": {...}, "collection": "..." }` (all optional)
  - Plus standard caller metadata fields (agent_id, agent_type, etc.)
  - Returns: updated document metadata

- `DELETE /api/documents/{document_id}` — soft delete
  - Body (optional): `{ "agent_id": "...", "initiated_by": "...", "agent_notes": "..." }`
  - Returns: `{ "document_id": "...", "status": "scheduled_for_deletion", "deletion_scheduled_at": "...", "message": "Will be purged after 48 hours." }`

- `POST /api/documents/{document_id}/restore` — restore
  - Body (optional): caller metadata
  - Returns: `{ "document_id": "...", "status": "restored" }` or 410 Gone if past 48hr

- `DELETE /api/collections/{collection_name}` — soft delete all docs in collection
  - Body (optional): caller metadata
  - Returns: `{ "collection": "...", "documents_marked": N, "message": "..." }`

- `POST /api/collections/{collection_name}/restore` — restore collection
  - Body (optional): caller metadata
  - Returns: `{ "collection": "...", "documents_restored": N }`

### Update existing endpoints

- `POST /api/search` — add `include_deleted: bool` to request body (default false)
- `GET /api/documents` — add `include_deleted` query parameter (default false)
- `GET /api/collections` — counts exclude deleted by default
- `GET /api/stats` — counts exclude deleted by default

### Auth

All new endpoints require API key auth (same as existing endpoints, except `/api/health`).

## Do not touch

- MCP server (already done in step 4)
- SPEC.md, skills, docs

## Do not commit

Report what you changed. Leave for Bob.
