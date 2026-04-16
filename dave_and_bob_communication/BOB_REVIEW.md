# Bob review — DAVE_SPEC_REST_API_FIXES

**Verdict:** Clean. All 7 fixes + NOTE #17 verified. Committed and pushed.

---

## Verification checklist

### Problem #2 — PATCH response vague
**PASS.** Line 333: Response now includes `agent_metadata` (dict, shallow-merged) and `updated_fields` typed as list with example.

### Problem #3 — DELETE/restore collection response types ambiguous
**PASS.**
- Line 476: `documents_marked` typed as `(int — count of documents soft-deleted)`, `message` added.
- Line 488: `documents_restored` typed as `(int — count of documents restored)`.

### Problem #4 — No error response format
**PASS.** Lines 198-214: `### Error responses` subsection added after endpoint summary table, before `GET /api/health`. JSON structure documented. All 8 HTTP status codes present (400, 401, 403, 404, 410, 413, 422, 503).

### Problem #11 — Nested metadata filter ambiguity
**PASS.** Line 399: `metadata` row in planned filters table explains nested key matching with concrete example.

### Problem #13 — Caller metadata inconsistent across endpoints
**PASS.**
- PATCH request body (lines 329-331): `model` and `agent_metadata` added.
- DELETE doc (line 343): All 6 fields explicitly listed.
- Restore doc (line 355): All 6 fields explicitly listed.
- DELETE collection (line 474): All 6 fields explicitly listed.
- Restore collection (line 486): All 6 fields explicitly listed.

### Problem #14 — created_by vs initiated_by
**PASS.** Line 462: `created_by` changed to `initiated_by` with description "Who created this collection".

### Problem #16 — No client method references
**PASS.** `**Client method:**` added to all 8 endpoints: health (227), PATCH (335), DELETE doc (347), restore doc (359), create collection (466), DELETE collection (478), restore collection (490), stats (503).

### NOTE #17 — collection filter precedence
**PASS.** Line 387: `collection` row in current filters table notes it's the same as top-level parameter, filter value takes precedence.

---

## Sections NOT changed (verified)
- Sections 1-3: untouched
- Configuration section: untouched
- Ingesting local files section: untouched
- Everything after REST API section: untouched

## Notes
Clean work. All fixes match the requested text exactly. No drift, no bonus edits, no regressions.
