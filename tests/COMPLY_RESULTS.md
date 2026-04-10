# Compliance Execution Results

**Date:** 2026-04-05

## Changes Made

### Step 0: Refactor `routes.py` `submit_document`
- **File:** `src/pipeline/api/routes.py`
- **What:** Replaced duplicated pipeline logic in `submit_document` with a call to `_process_single_document` (same pattern as the ingest endpoint). Removed `_build_document_response` helper, `_extractor` instance, and unused imports (`ChunkingConfig`, `chunk_document`, `DocumentInteraction`, `StoredDocument`, `compute_fingerprint`, `MarkItDownExtractor`).
- **Why:** Approved decision #3 — eliminates code duplication that caused discrepancies 1-5 to require fixes in two files. Now all pipeline logic lives in `mcp_server.py`.

### Step 1: Discrepancies 1 + 2 + 3 — `convert_document` response completeness
- **File:** `src/pipeline/mcp_server.py`
- **What:** (1) Added `chunks_count`, `store_status: "skipped"`, and `embedding_model` to the dedup return path. (2) Added `chunks_count: 0` to the store=false path. (3) Changed store=false `store_status` from `"skipped"` to `"not_stored"`.
- **Why:** SPEC says `convert_document` returns `chunks_count`, `store_status`, and `embedding_model` on every response. Dedup path was missing all three, store=false was missing `chunks_count` and using the wrong `store_status` value.

### Step 2: Discrepancy 5 — Move interaction recording to end of pipeline
- **File:** `src/pipeline/mcp_server.py`
- **What:** Moved `record_interaction` call from before the response dict / chunking block to after all processing (after the store/not-store block), just before `return response`.
- **Why:** SPEC pipeline order says step 7 (record interaction) is the last step. Code was recording the interaction before chunking/embedding (steps 4-6), so a failure in chunking would still show a successful interaction.

### Step 3: Discrepancies 6 + 7 + 8 + 9 — REST endpoint fixes
- **File:** `src/pipeline/api/routes.py`
- **What:** (6) Changed `"markdown": doc.markdown` to `"content_markdown": doc.markdown` in `get_document`. (7) Added `include_chunks: bool = Query(True)` and `include_interactions: bool = Query(True)` params to `get_document`, with conditional inclusion matching MCP handler. (8) Added `file_type: Optional[str] = Query(None)` to `list_documents` with `.lstrip(".")` normalization. (9) Changed `"total": total` to `"total_count": total` in `list_documents`.
- **Why:** SPEC says REST mirrors MCP. These four fields/params were inconsistent between the REST and MCP handlers.

### Step 4: Discrepancy 10 — REST search post-filter
- **File:** `src/pipeline/api/routes.py`
- **What:** Added `_post_filter_results` call to the REST search endpoint when using `InMemoryVectorStore`, matching the MCP search handler.
- **Why:** MCP search handler post-filters for `source_file`, `file_type`, and `tags` when using InMemoryVectorStore (which can't filter by document metadata during search). REST handler was missing this, so those three filters silently failed.

### Step 5: Discrepancy 4 — Wire image enrichment into pipeline
- **File:** `src/pipeline/mcp_server.py`
- **What:** Added imports for `ImageEnricher` and `VisionConfig`. Created `_image_enricher` instance configured from `VISION_API_KEY`, `VISION_MODEL`, `VISION_BASE_URL` env vars (disabled when no API key). Added enrichment call in `_process_single_document` after fingerprinting and before `StoredDocument` creation. Enriched markdown is what gets stored and chunked. Processing chain entry is appended. Errors are added to warnings without blocking the pipeline.
- **Why:** SPEC pipeline step 3 is image enrichment. The enrichment modules existed (`images.py`, `vision.py`) but were never called.

### Step 6: Discrepancy 11 — No code change
- **What:** Search caller metadata is accepted for forward compatibility but does not create interaction rows. No code change needed.
- **Why:** Approved decision #1 — defer search interaction recording. Recording per-document interactions for search is semantically ambiguous and would inflate the interactions table.

## Verification Results

| # | Check | Pass/Fail | Notes |
|---|-------|-----------|-------|
| 1 | list_collections | Pass | 10 collections returned with correct counts |
| 2 | convert_document (new doc, store=true) | Pass | `chunks_count: 2`, `embedding_model: "text-embedding-3-small"`, `store_status: "stored"`, image_enrichment in processing_chain |
| 3 | convert_document (store=false) | Pass | `chunks_count: 0`, `store_status: "not_stored"` |
| 4 | convert_document (dedup skip) | Pass | `store_status: "skipped"`, `chunks_count: 2`, `embedding_model` present, `interactions` with 2 entries |
| 5 | convert_document (force override) | Pass | `store_status: "stored"`, re-processed with new timestamps |
| 6 | list_documents | Pass | `total_count` present, `chunk_count` and `interaction_count` correct |
| 7 | list_documents (file_type filter) | Pass | Only txt documents returned when `file_type: "txt"` |
| 8 | get_document | Pass | `content_markdown` (not `markdown`), `chunks`, `interactions` all present |
| 9 | search | Pass | Results with interactions including all metadata fields |
| 10 | search (filtered) | Pass | `file_type: "txt"` filter correctly applied |
| 11 | ingest (batch) | Pass | 5 found, 3 processed, 1 skipped (dedup), 1 errored |

## New Issues Discovered

1. **Image enrichment processing_chain entry appears even when no images were found.** The enrichment step runs and adds a chain entry with `images_processed: 0` for every document, even plain text files. This is correct behavior (the step ran, it just found nothing to do) but could be considered noisy. Not a SPEC violation — noting for awareness.

2. **`get_document` MCP handler uses `content_markdown` but `_process_single_document` response uses `markdown`.** The SPEC lists `markdown` as the `convert_document` response field name ("the full extracted text") and `content_markdown` as the `get_document` response field. These are different endpoints with different field names per spec. Both are now correct.
