# Comply: Execute the Plan

## ROLE

You are a developer executing a pre-approved fix plan.

## GOAL

Execute the fixes described in `tests/COMPLY_PLAN.md`. The plan has been reviewed and approved. Follow the proposed fix order exactly.

## REFERENCE DOCUMENTS

1. **SPEC.md** (repo root) — source of truth for behavior
2. **SKILL.md** (`skills/ariadne-document-intelligence/SKILL.md`) — how agents use the server
3. **tests/COMPLY_PLAN.md** — the approved plan. Follow it.

Read all three before starting.

## APPROVED DECISIONS

These questions from the plan have been answered:

1. **Search interaction recording (Discrepancy 11):** Defer. Accept metadata for forward compatibility, don't record interaction rows for search. No code change needed.
2. **`store_status` values:** `"stored"` = persisted this call, `"not_stored"` = store=false, `"skipped"` = dedup skip.
3. **REST `submit_document` refactor:** Yes. Refactor `submit_document` in `routes.py` to call `_process_single_document` instead of duplicating the pipeline. Do this first — it reduces the surface area for all subsequent fixes.
4. **REST backward compatibility:** No external consumers. Change field names to match SPEC.md without dual-support.
5. **STDIO proxy:** Fix the REST bugs regardless. If MCP routes through REST, the fixes help MCP clients too. If not, they still fix the REST API.

## CAPABILITIES

You MAY:
- Read any source file
- Edit source files to execute the plan
- Restart Docker to test changes
- Call MCP tools to verify
- Write results to `tests/COMPLY_RESULTS.md`

## CONSTRAINTS

You MUST NOT:
- Change SPEC.md or SKILL.md
- Fix anything not in the plan
- Add features not described in SPEC.md
- Skip the refactor step — do it first as approved

If you discover a new issue while fixing, note it in the results file but do not fix it.

## FIX ORDER (from the approved plan)

**Step 0: Refactor `routes.py` `submit_document`**
Make it call `_process_single_document` instead of duplicating the pipeline. The ingest endpoint already does this — follow the same pattern. This eliminates the duplication that caused multiple discrepancies.

**Step 1: Discrepancies 1 + 2 + 3 — `convert_document` response completeness**
- Add `chunks_count`, `store_status`, `embedding_model` to dedup path
- Set `chunks_count: 0` on store=false path
- Fix `store_status` values: `"stored"`, `"not_stored"`, `"skipped"`

**Step 2: Discrepancy 5 — Move interaction recording to end of pipeline**
Move `record_interaction` to after chunking/embedding/storage in `_process_single_document`.

**Step 3: Discrepancies 6 + 7 + 8 + 9 — REST endpoint fixes**
- `markdown` → `content_markdown` in get_document response
- Add `include_chunks` and `include_interactions` query params to REST get_document
- Add `file_type` query param to REST list_documents
- `total` → `total_count` in REST list_documents response

**Step 4: Discrepancy 10 — REST search post-filter**
Add `_post_filter_results` call to REST search endpoint for InMemoryVectorStore path.

**Step 5: Discrepancy 4 — Wire image enrichment into pipeline**
Call image enrichment after fingerprinting, before chunking, if `VISION_API_KEY` is configured. Add processing_chain entry. Skip gracefully if no key.

**Step 6: Discrepancy 11 — No code change**
Metadata accepted for forward compatibility. No interaction recording for search. Note this in results.

## VERIFICATION

After all fixes, restart Docker and verify each MCP tool:

1. `list_collections` — returns correctly
2. `convert_document` (new doc) — all response fields present including `store_status: "stored"`
3. `convert_document` (store=false) — `chunks_count: 0`, `store_status: "not_stored"`
4. `convert_document` (dedup skip) — `store_status: "skipped"`, `chunks_count` present, `interactions` present
5. `convert_document` (force override) — `store_status: "stored"`, re-processed
6. `list_documents` — `chunk_count`, `interaction_count` present
7. `list_documents` (file_type filter) — only matching type returned
8. `get_document` — `content_markdown`, `chunks`, `interactions` all present
9. `search` — results with `interactions` including all metadata fields
10. `search` (filtered) — filters work
11. `ingest` — batch works, per-file results correct

## RESULTS FORMAT

Write `tests/COMPLY_RESULTS.md`:

```markdown
# Compliance Execution Results

**Date:** YYYY-MM-DD

## Changes Made
For each change:
- **File:** path
- **What:** one-line description
- **Why:** which discrepancy it addresses

## Verification Results
| # | Check | Pass/Fail | Notes |
|---|-------|-----------|-------|

## New Issues Discovered
(anything found during execution that wasn't in the plan)
```
