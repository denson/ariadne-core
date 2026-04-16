# DAVE_DONE — SPEC.md REST API Fixes Complete

**Task:** DAVE_SPEC_REST_API_FIXES.md
**File edited:** `ariadne-core/SPEC.md`
**Status:** All 7 fixes + 1 note fix applied. Not committed (left for Bob).

---

## What was done

### Problem #2 — PATCH response vague
- Added `agent_metadata` (dict, shallow-merged) and typed `updated_fields` as list of field names with example.

### Problem #3 — DELETE/restore collection response types ambiguous
- DELETE /api/collections/{name}: `documents_marked` now typed as `(int — count of documents soft-deleted)`, added `message`.
- POST /api/collections/{name}/restore: `documents_restored` now typed as `(int — count of documents restored)`.

### Problem #4 — No error response format
- Added `### Error responses` subsection after the endpoint summary table, before `GET /api/health`.
- Documents JSON error structure and all 8 common HTTP status codes (400, 401, 403, 404, 410, 413, 422, 503).

### Problem #11 — Nested metadata filter ambiguity
- Expanded `metadata` row in planned filters table to explain nested key matching with example.

### Problem #13 — Caller metadata inconsistent across endpoints
- Added `model` and `agent_metadata` to PATCH request body table.
- Expanded all 4 endpoints (DELETE doc, restore doc, DELETE collection, restore collection) to explicitly list all 6 caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.

### Problem #14 — created_by vs initiated_by
- Changed `created_by` to `initiated_by` in POST /api/collections request body, with description "Who created this collection".

### Problem #16 — No client method references
- Added `**Client method:**` one-liner to 8 endpoints: health, PATCH, DELETE doc, restore doc, DELETE collection, restore collection, stats, create collection.

### NOTE #17 — collection filter precedence
- Added note to `collection` row in search current filters table: same as top-level parameter, filter value takes precedence if both provided.

---

## What was NOT changed
- Sections 1-3 (already approved)
- Configuration section
- Ingesting local files section
- Anything after the REST API section
