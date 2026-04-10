# Fix 005: `convert_document` Missing `interactions` on Dedup Hits

## The Problem

When `convert_document` returns a dedup skip (`was_dedup_skip: true`), the response does not include an `interactions` field. SPEC.md says the response should include `interactions` (the full interaction history for the existing document) so the caller can see who else has touched it.

From VALIDATION_RESULTS.md:
> `convert_document` response missing `interactions` field. SPEC says response includes `interactions` (if dedup hit). The field is entirely absent from all responses.

The `interactions` field should only be present on dedup hits — when a new document is freshly processed, there's only one interaction (the current one) so it's less useful. But on a dedup skip, showing the existing interaction history tells the caller who else has worked with this document.

## What to Fix

In `src/pipeline/mcp_server.py`, the `_process_single_document` function has a dedup-skip code path (where `was_dedup_skip` is set to `true` and the existing document is returned). That path needs to fetch and include the interaction history.

Also check the REST equivalent in `src/pipeline/api/routes.py` — the `submit_document` route likely has the same dedup path.

The interactions should be fetched via `_dedup_store.get_interactions(document_id)` and serialized with all fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`, `action`, `was_dedup_skip`, `created_at`.

## How to Verify

After making the fix, restart Docker and run:

1. Call `convert_document` on `/data/fixtures/sample.txt` with `collection: "dedup-interaction-test"`, `agent_type: "claude-code"`, `initiated_by: "user:denson"`, `model: "claude-opus-4-6"`, `agent_notes: "First ingestion"`
2. Call `convert_document` again with the same file and collection but `agent_type: "ob1"`, `initiated_by: "user:nate"`, `model: "gpt-4o"`, `agent_notes: "Second touch — should be dedup skip"`
3. Check the response from step 2:
   - `was_dedup_skip: true`
   - `interactions` array is present
   - `interactions` contains at least 2 entries (the original ingest + the dedup skip just recorded)
   - Each interaction has: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `action`, `was_dedup_skip`, `created_at`
4. Call `convert_document` a third time with yet different metadata — verify `interactions` now shows 3 entries

All 4 steps must pass.

## Rules

- Only fix the dedup response path in `convert_document` (and REST equivalent) — do not change anything else
- Do not change SPEC.md, SKILL.md, or any docs
- Do not change MCP tool signatures
- Write the verification results to `tests/FIX_005_RESULTS.md`
