# Compliance Plan

**Date:** 2026-04-05

## Discrepancies Found

### 1. `convert_document` dedup path missing response fields

- **SPEC.md says:** `convert_document` returns `chunks_count`, `store_status`, and `embedding_model` on every response.
- **Code does:** The dedup path in `_process_single_document` (`src/pipeline/mcp_server.py` lines 638-673) omits `chunks_count`, `store_status`, and `embedding_model`. The same omission exists in the REST dedup path via `_build_document_response` (`src/pipeline/api/routes.py` lines 618-666).
- **Proposed fix:** In `mcp_server.py`, add `chunks_count` (from `_count_chunks_for_document(existing.document_id)`), `store_status: "skipped"`, and `embedding_model` (from the first chunk's `embedding_model` field, or `null` if no chunks) to the dedup return dict. Mirror the same additions in `_build_document_response` in `routes.py`.
- **Risk:** Low. Additive change — existing fields are untouched. Interacts with Discrepancy #2 (same code path).
- **Depends on:** none

### 2. `convert_document` store=false path missing `chunks_count`

- **SPEC.md says:** `chunks_count` is listed as a response field without qualification by `store` value.
- **Code does:** When `store=false`, the code skips chunking entirely (`mcp_server.py` line 734 onward) and never sets `chunks_count`. Same in `routes.py` line 209 onward.
- **Proposed fix:** Set `response["chunks_count"] = 0` on the store=false path in both `mcp_server.py` (after line 771) and `routes.py` (after line 244).
- **Risk:** Low. Additive.
- **Depends on:** none

### 3. `store_status` uses wrong values

- **SPEC.md says:** `store_status` can be `"stored"`, `"not_stored"`, or `"skipped"`. Three distinct values with implied semantics: `"stored"` = persisted this call, `"not_stored"` = store=false was set, `"skipped"` = dedup skip (already in the store).
- **Code does:** Uses `"stored"` for store=true (correct) and `"skipped"` for store=false (`mcp_server.py` line 771, `routes.py` line 244). The dedup path sets no `store_status` at all.
- **Proposed fix:** Change the store=false value from `"skipped"` to `"not_stored"` in both `mcp_server.py` and `routes.py`. Add `"store_status": "skipped"` to the dedup return path (covered by Discrepancy #1).
- **Risk:** Low, but any external consumers relying on `"skipped"` meaning store=false will break. Verify no tests or clients depend on the current value.
- **Depends on:** 1 (same dedup path)

### 4. Image enrichment not wired into pipeline

- **SPEC.md says:** Pipeline step 3 is "Image enrichment (vision API describes images found in the extracted Markdown)". This happens after fingerprinting and before chunking.
- **Code does:** `_process_single_document` (`mcp_server.py` lines 590-773) goes directly from fingerprint (line 618) to chunking (line 739). The enrichment modules exist (`src/pipeline/enrichment/images.py`, `vision.py`) but are never imported or called. Same omission in `routes.py` `submit_document`.
- **Proposed fix:** After fingerprinting and before chunking, call the image enrichment pipeline if a vision API key is configured. Add a processing_chain entry for the enrichment step. Skip if no vision API key is set (matching SPEC's warning behavior for images without a key).
- **Risk:** Medium. This adds a new API call to the processing pipeline. If the vision API is slow or fails, it could affect all document processing. Needs a config check (only run when `VISION_API_KEY` is set) and error handling that doesn't block the rest of the pipeline. Also interacts with Discrepancy #5 (pipeline order).
- **Depends on:** none, but should be ordered after #5

### 5. Interaction recorded before chunking/embedding

- **SPEC.md says:** Pipeline order is: 1. Extract, 2. Fingerprint, 3. Image enrichment, 4. Chunk, 5. Embed, 6. Store in vector DB, 7. Record interaction. Interaction recording is the last step.
- **Code does:** In `_process_single_document` (`mcp_server.py` lines 693-709), `store_document` and `record_interaction` are called at lines 693 and 696, BEFORE chunking/embedding at lines 734+. If chunking or embedding fails, the interaction is already recorded as a successful ingest. Same order in `routes.py` `submit_document` (lines 185-202 before lines 209+).
- **Proposed fix:** Move `record_interaction` to after the chunking/embedding/storage block (after line 769 in `mcp_server.py`, after line 244 in `routes.py`). Keep `store_document` where it is since the document record needs to exist before chunks can reference it.
- **Risk:** Low-medium. If chunking/embedding fails after the document is stored, no interaction will be recorded. This is arguably better than the current behavior (recording success before processing completes). The dedup path's interaction recording (line 623) should stay where it is — it correctly records before returning.
- **Depends on:** none

### 6. REST `GET /api/documents/{id}` uses `markdown` instead of `content_markdown`

- **SPEC.md says:** `get_document` returns `content_markdown`. The REST section says this endpoint is "same as MCP `get_document`".
- **Code does:** The MCP `get_document` handler (`mcp_server.py` line 311) correctly uses `content_markdown`. The REST endpoint (`routes.py` line 274) uses `markdown`.
- **Proposed fix:** Change `"markdown": doc.markdown` to `"content_markdown": doc.markdown` in `routes.py` line 274.
- **Risk:** Low, but any REST client reading the `markdown` key from this endpoint will break. The MCP path (which is what STDIO clients use) is already correct.
- **Depends on:** none

### 7. REST `GET /api/documents/{id}` missing `include_chunks` and `include_interactions` params

- **SPEC.md says:** `get_document` accepts `include_chunks` (default true) and `include_interactions` (default true) parameters. REST mirrors MCP.
- **Code does:** The MCP `get_document` handler (`mcp_server.py` lines 270-347) accepts both params and conditionally includes chunks/interactions. The REST endpoint (`routes.py` lines 249-301) always returns both — no query parameters for toggling.
- **Proposed fix:** Add `include_chunks: bool = Query(True)` and `include_interactions: bool = Query(True)` query params to the REST `get_document` endpoint. Conditionally include chunks and interactions based on these params, matching the MCP handler logic.
- **Risk:** Low. Additive — default behavior stays the same (both included).
- **Depends on:** none

### 8. REST `GET /api/documents` missing `file_type` query parameter

- **SPEC.md says:** `list_documents` accepts a `file_type` filter parameter.
- **Code does:** The MCP `list_documents` handler (`mcp_server.py` line 353) accepts `file_type` and filters by it. The REST `GET /api/documents` endpoint (`routes.py` lines 304-347) only accepts `collection`, `page`, `per_page` — no `file_type` filter. If the STDIO proxy delegates to REST, file_type filtering from MCP clients won't work.
- **Proposed fix:** Add `file_type: Optional[str] = Query(None)` to the REST `list_documents` endpoint. Apply the same `.lstrip(".")` normalization and filter logic as the MCP handler.
- **Risk:** Low. Additive.
- **Depends on:** none

### 9. REST `GET /api/documents` returns `total` instead of `total_count`

- **SPEC.md says:** `list_documents` returns `total_count`.
- **Code does:** The MCP handler (`mcp_server.py` line 391) returns `total_count`. The REST endpoint (`routes.py` line 343) returns `total`.
- **Proposed fix:** Rename `"total"` to `"total_count"` in `routes.py` line 343.
- **Risk:** Low, but REST clients reading `total` will break.
- **Depends on:** none

### 10. REST `POST /api/search` missing post-filter for InMemoryVectorStore

- **SPEC.md says:** Search supports filters for `source_file`, `file_type`, and `tags` (in addition to `collection` and `document_id`).
- **Code does:** The MCP `search` handler (`mcp_server.py` lines 220-221) calls `_post_filter_results` to handle source_file, file_type, and tags filtering when using InMemoryVectorStore (which can't filter by document metadata during search). The REST `POST /api/search` endpoint (`routes.py` lines 353-422) does NOT call `_post_filter_results`, so these three filters silently fail with InMemoryVectorStore.
- **Proposed fix:** Add the same post-filtering logic to the REST search endpoint. Either call `_mcp._post_filter_results` directly (it's importable), or add a local equivalent. In production with PgVectorStore, these filters are handled in SQL, so this only affects the InMemoryVectorStore path.
- **Risk:** Low. The PgVectorStore handles these filters in SQL already. This fix only matters for InMemoryVectorStore, which is the Phase 1 / testing path.
- **Depends on:** none

### 11. Search caller metadata accepted but unused

- **SPEC.md says:** Under "Caller metadata": "`convert_document`, `search`, and `ingest` accept these optional fields for provenance tracking. Every call creates a `document_interactions` row, even dedup skips."
- **Code does:** The MCP `search` handler (`mcp_server.py` lines 156-266) accepts all caller metadata parameters (`agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`) but never uses them. No interaction is recorded for search calls. The REST search endpoint (`routes.py` lines 353-422) similarly accepts metadata in the request body but doesn't use it.
- **Proposed fix:** This requires a design decision. Recording an interaction for search is ambiguous — search doesn't target a single document. Options: (a) record a "search" interaction on every matched document, (b) record a single "search" event in a separate search_log table, (c) accept the metadata for future use but don't record it now. Option (a) would inflate the interactions table. Option (b) requires schema changes. Option (c) means the SPEC claim "every call creates a document_interactions row" is knowingly violated for search.
- **Risk:** Option (a) could significantly increase interactions volume on high-result searches. Option (b) is a schema change. Option (c) is a documentation/spec clarification rather than a code change.
- **Depends on:** none

## Interactions and Conflicts

### Discrepancies 1 + 2 + 3: `convert_document` response completeness

These three all affect the `convert_document` response and should be fixed together. They share code paths in both `mcp_server.py` (`_process_single_document`) and `routes.py` (`_build_document_response` and `submit_document`). Fixing them separately risks inconsistent intermediate states.

Specifically:
- #1 adds fields to the dedup path
- #2 adds `chunks_count` to the store=false path
- #3 changes `store_status` values on both paths

All three touch the response-building logic. Fix them in one pass.

### Discrepancies 4 + 5: Pipeline order

Both affect the flow inside `_process_single_document`. Fixing #5 (moving interaction recording to the end) should be done before or together with #4 (wiring image enrichment), since #4 adds a new step between fingerprint and chunk — getting the order right requires both changes.

### Discrepancies 6 + 7 + 8 + 9 + 10: REST endpoint compliance

These are all independent REST-only changes in `routes.py`. They don't interact with each other or with the MCP handler. Can be fixed in any order or in a single pass through `routes.py`.

### Discrepancy 11: Design decision required

This cannot be fixed without a decision on what "search interactions" should look like. It doesn't block any other fix. The three options have meaningfully different implications:
- **(a) Record per-document:** Simple to implement but inflates `document_interactions`. A search returning 20 results creates 20 interaction rows.
- **(b) Search log table:** Cleanest design but requires a schema change and migration. Out of scope for a compliance pass.
- **(c) Accept and defer:** Acknowledge the SPEC is aspirational here. Accept the metadata for forward compatibility but don't record it yet.

**Recommendation:** Option (c) — defer. Update SPEC.md to say search metadata is accepted for forward compatibility but does not currently create interaction rows. This keeps the code simple and avoids schema changes.

### Code duplication between MCP and REST

`routes.py` `submit_document` duplicates the full pipeline logic from `mcp_server.py` `_process_single_document`. Fixes to the pipeline (discrepancies 1-5) must be applied to BOTH files. This duplication is the root cause of several discrepancies (the MCP handler was updated in prior fixes but the REST handler wasn't, or vice versa). Consider refactoring `submit_document` to call `_process_single_document` directly (the ingest endpoint already does this at `routes.py` line 470), which would eliminate the duplication and prevent future drift. This refactor would reduce the surface area for discrepancies 1, 2, 3, 4, and 5 from two files to one.

## Proposed Fix Order

1. **Discrepancies 1 + 2 + 3 — `convert_document` response completeness** (fix together)
   Both MCP and REST paths. Low risk, high impact — these are user-visible response fields that are missing or wrong.

2. **Discrepancy 5 — Move interaction recording to end of pipeline**
   Reorder `_process_single_document` in `mcp_server.py` and `submit_document` in `routes.py`. Do this before wiring image enrichment so the pipeline order is correct when the new step is added.

3. **Discrepancies 6 + 7 + 8 + 9 — REST endpoint field/param fixes** (fix together)
   All in `routes.py`, all low risk, all independent. Single pass through the file.

4. **Discrepancy 10 — REST search post-filter**
   `routes.py` only. Low risk but important for InMemoryVectorStore path.

5. **Discrepancy 4 — Wire image enrichment into pipeline**
   Medium risk, adds new API call. Do this last among the code changes since it's the most complex and has the most potential to introduce issues. Requires reading `src/pipeline/enrichment/images.py` and `vision.py` to understand the existing enrichment API.

6. **Discrepancy 11 — Search metadata** (defer — requires design decision)
   Recommend option (c): accept metadata for forward compatibility, don't record. Update SPEC.md comment only, no code change.

**Optional refactor (between steps 1 and 2):** Refactor `routes.py` `submit_document` to call `_process_single_document` instead of duplicating it. This would make fixes 2 and 4 only need to touch one file. Risk: medium — the REST endpoint has slightly different error handling (HTTPException vs error dict) and response format, so the refactor needs care. But it prevents future drift and reduces the total work for fixes 2-5.

## Questions

1. **Search interaction recording (Discrepancy 11):** Should search calls create `document_interactions` rows? If so, on which documents — all results? Only top-k? The SPEC implies "every call" but the semantics for search are unclear. I recommend deferring this and clarifying the SPEC.

2. **`store_status` value for dedup hits:** I've proposed `"skipped"` for dedup and `"not_stored"` for store=false. The SPEC lists three values but doesn't define which maps to which scenario. Confirm: `"stored"` = stored this call, `"not_stored"` = store=false, `"skipped"` = dedup skip. Or should dedup be `"stored"` (since it IS in the store, just from a prior call)?

3. **REST `submit_document` refactor:** Should we refactor `routes.py` `submit_document` to call `_process_single_document` (like the ingest endpoint does) before applying pipeline fixes, to avoid double-fixing? This would reduce fix surface area from 2 files to 1 for discrepancies 1-5, but has its own risk.

4. **REST response backward compatibility:** Discrepancies 6 and 9 change existing REST response field names (`markdown` → `content_markdown`, `total` → `total_count`). Are there any REST API consumers that would break? If so, should we support both field names temporarily?

5. **STDIO proxy pattern:** Prior session notes say "MCP STDIO proxy delegates tool calls to the REST API." If this is true, REST discrepancies (6-10) affect MCP-over-STDIO clients too. If STDIO runs MCP handlers directly, the REST discrepancies only affect REST API consumers. Which is it? The answer changes the priority of REST fixes.
