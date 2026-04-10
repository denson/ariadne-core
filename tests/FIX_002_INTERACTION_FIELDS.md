# Fix 002: Missing `model` and `initiated_by` on Interaction Records

## The Problem

`convert_document`, `search`, and `ingest` all accept `model` and `initiated_by` as caller metadata fields. These values are passed into the tool calls correctly, but they are not stored on `document_interactions` rows and are not returned in responses.

From VALIDATION_RESULTS.md:
> Interaction records missing `model` and `initiated_by` fields. SPEC says interactions should include `model` and `initiated_by`. In `get_document` and `search` responses, interactions only have: `agent_id`, `agent_type`, `agent_notes`, `agent_metadata`, `action`, `was_dedup_skip`, `created_at`.

The `document_interactions` table in `migrations/001_initial.sql` has both `model` and `initiated_by` columns. The MCP tools accept both fields. The bug is somewhere in between — either the values aren't being passed to the store method, or the store method isn't writing them, or the serialization isn't reading them back.

## What to Fix

Trace the path of `model` and `initiated_by` from the MCP tool parameters through to the database write and back through the response serialization:

1. `mcp_server.py` — `_process_single_document` creates a `DocumentInteraction` object. Are `model` and `initiated_by` being set on it?
2. `dedup.py` — `PgDedupStore.record_interaction()` writes the interaction to Postgres. Is it including `model` and `initiated_by` in the INSERT?
3. `dedup.py` — `PgDedupStore.get_interactions()` reads interactions back. Is it selecting `model` and `initiated_by`?
4. `mcp_server.py` — the response serialization in `get_document`, `search`, and `convert_document` (dedup path). Are `model` and `initiated_by` included in the interaction dicts?

The fix is probably one of:
- `DocumentInteraction` dataclass missing `model`/`initiated_by` fields
- INSERT statement missing those columns
- SELECT statement not fetching those columns
- Response serialization not including those fields

## How to Verify

After making the fix, restart Docker and run:

1. Call `convert_document` on `/data/fixtures/sample.txt` with `collection: "interaction-test"`, `model: "claude-opus-4-6"`, `initiated_by: "user:denson"`, `agent_type: "claude-code"`, `agent_notes: "Testing interaction field persistence"`
2. Call `get_document` on the returned `document_id` with `include_interactions: true`
3. Check the interaction record — it must have:
   - `model: "claude-opus-4-6"`
   - `initiated_by: "user:denson"`
   - `agent_type: "claude-code"`
   - `agent_notes: "Testing interaction field persistence"`
   - `was_dedup_skip: false`
4. Call `convert_document` again with the same file/collection but `model: "gpt-4o"`, `initiated_by: "user:nate"`, `agent_type: "ob1"`
5. Call `get_document` again — should now have 2 interactions, each with their own `model` and `initiated_by` values

All 5 steps must pass.

## Rules

- Only fix the interaction field storage/retrieval — do not change anything else
- Do not change SPEC.md, SKILL.md, or any docs
- Do not change MCP tool signatures
- Report what you changed and the verification results
