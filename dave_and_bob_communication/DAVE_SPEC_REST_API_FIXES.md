# Task: Fix 7 problems in the REST API section of SPEC.md

**For:** Dave
**Context:** The REST API section of SPEC.md was just rewritten. A reviewer found 7 problems. Fix them all.

Read `ariadne-core/SPEC.md` — the REST API section starts at `## REST API` (around line 170).

---

## Problem #2 — PATCH /api/documents/{id} response is vague

The response says it returns `updated_fields` but doesn't define the type.

**Fix:** Change the response line to:
```
**Response:** JSON with `document_id`, `collection`, `tags`, `agent_metadata` (dict, shallow-merged), `updated_fields` (list of field names that were changed, e.g. `["tags", "collection"]`).
```

## Problem #3 — DELETE /api/collections/{name} and restore response types ambiguous

`documents_marked` and `documents_restored` — are these counts or lists?

**Fix:** For DELETE /api/collections/{name}, change response to:
```
**Response:** JSON with `collection`, `documents_marked` (int — count of documents soft-deleted), `message`.
```

For POST /api/collections/{name}/restore, change response to:
```
**Response:** JSON with `collection`, `documents_restored` (int — count of documents restored).
```

## Problem #4 — No error response format documented

**Fix:** Add a new subsection after the endpoint summary table (before the first endpoint detail) titled:

```markdown
### Error responses

All endpoints return errors as JSON with this structure:

\`\`\`json
{"detail": {"message": "Human-readable error description", "document_id": "uuid-if-applicable"}}
\`\`\`

Common HTTP status codes:
- `400` — Invalid request (missing required fields, malformed JSON)
- `401` — Missing API key
- `403` — Invalid API key
- `404` — Document or collection not found
- `410` — Soft-delete window expired (restore too late)
- `413` — File too large
- `422` — Extraction failed (encoding error, unsupported format, corrupt file)
- `503` — Embedding not configured (search endpoint only)
```

## Problem #11 — Nested metadata filter ambiguity

The planned `metadata` filter uses JSONB containment but doesn't say it works for nested keys.

**Fix:** In the "Planned metadata filters" section, change the `metadata` row description to:
```
JSONB containment match — find documents where `agent_metadata` contains these key-value pairs. Works for nested keys too: `{"nested": {"field": "value"}}` matches documents where `agent_metadata.nested.field == "value"`.
```

## Problem #13 — Caller metadata inconsistent across endpoints

PATCH only lists 4 fields, DELETE/restore say "Caller metadata fields" without listing them.

**Fix:** 

On PATCH /api/documents/{id}, add `model` and `agent_metadata` to the request body table:
```
| `model` | string | LLM model the caller is running |
| `agent_metadata` | dict | Structured metadata |
```

On DELETE /api/documents/{id}, POST /api/documents/{id}/restore, DELETE /api/collections/{name}, and POST /api/collections/{name}/restore — change the request body line to:
```
**Request body (JSON, optional):** Caller metadata fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`.
```

All six fields, explicitly listed, on every endpoint.

## Problem #14 — created_by vs initiated_by on POST /api/collections

**Fix:** In POST /api/collections request body table, change `created_by` to `initiated_by` with description "Who created this collection". This makes it consistent with every other endpoint.

## Problem #16 — No create_collection client method

**Fix:** This is a spec note, not a code fix. Add a one-line note after the POST /api/collections response:

```
**Client method:** `client.create_collection(name, description=None)`
```

Also add similar one-line client method notes after these endpoints that are missing them:
- PATCH: `client.update_document(document_id, tags=None, collection=None)`
- DELETE document: `client.delete_document(document_id)`
- Restore document: `client.restore_document(document_id)`
- DELETE collection: `client.delete_collection(name)`
- Restore collection: `client.restore_collection(name)`
- Stats: `client.stats()`
- Health: `client.health()`

These are forward references to the client package — they tell an agent what the client method will be called so they can plan ahead.

---

## Also fix (from reviewer NOTE #17)

In the search filters table, add a note on the `collection` filter row:
```
Same as the top-level `collection` parameter — either works. If both are provided, the filter value takes precedence.
```

---

## What NOT to change

- Sections 1-3 (already reviewed and approved)
- The Configuration section (Step 4 of the rewrite)
- The Ingesting local files section (Step 5)
- Anything after the REST API section

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.
