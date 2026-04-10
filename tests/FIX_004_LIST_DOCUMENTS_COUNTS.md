# Fix 004: `list_documents` Missing `chunk_count` and `interaction_count`

## The Problem

`list_documents` returns document metadata but each entry is missing `chunk_count` and `interaction_count` fields. SPEC.md says each document in the response should have both.

From VALIDATION_RESULTS.md:
> `list_documents` entries missing `chunk_count` and `interaction_count`. SPEC says each document should have `chunk_count` and `interaction_count`. Actual response only has: `document_id`, `source_file`, `title`, `file_type`, `collection`, `content_fingerprint`, `created_at`.

## What to Fix

The `list_documents` response is serialized in two places:

1. `src/pipeline/mcp_server.py` — the MCP tool handler
2. `src/pipeline/api/routes.py` — the REST endpoint

The MCP handler in `mcp_server.py` already calls `_count_chunks_for_document()` and `_dedup_store.get_interactions()` to populate these counts (check around line 400). If these are present in the MCP handler, the bug is likely in the REST route (same pattern as Fix 003 — the REST endpoint was missing logic the MCP handler had).

If neither has the counts, both need fixing.

## How to Verify

After making the fix, restart Docker and run:

1. Call `convert_document` on `/data/fixtures/sample.txt` with `collection: "counts-test"`, `store: true`
2. Call `convert_document` on `/data/fixtures/sample.html` with `collection: "counts-test"`, `store: true`
3. Call `convert_document` on `/data/fixtures/sample.txt` again (same collection, no force) — should dedup skip, adding an interaction
4. Call `list_documents` with `collection: "counts-test"`
5. Check that each document entry has `chunk_count` (integer > 0) and `interaction_count` (integer > 0)
6. Check that sample.txt has `interaction_count` >= 2 (original ingest + dedup skip)

All 6 steps must pass.

## Rules

- Only fix `list_documents` response fields — do not change anything else
- Do not change SPEC.md, SKILL.md, or any docs
- Do not change MCP tool signatures
- Write the verification results to `tests/FIX_004_RESULTS.md`
