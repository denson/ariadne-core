# Search Log Feature Results

**Date:** 2026-04-05

## Changes Made

### 1. Migration
- **File:** `migrations/003_search_log.sql`
- **What:** Created `search_log` table with all columns from SPEC (id, query, collection, filters, top_k, results_count, result_document_ids, agent_id, agent_type, model, initiated_by, agent_notes, agent_metadata, created_at). Added indexes on `created_at DESC`, `agent_id`, and `initiated_by`.

### 2. Store class
- **File:** `src/pipeline/dedup.py`
- **What:** Added `SearchLogEntry` dataclass. Added `record_search` method to `DedupStore` protocol, `PgDedupStore` (with try/except + warning log so failures don't block search responses), and `InMemoryDedupStore` (appends to `_search_log` list for testing).

### 3. MCP search handler
- **File:** `src/pipeline/mcp_server.py`
- **What:** After building search results, calls `_dedup_store.record_search()` with query, collection, filters, top_k, results_count, result_document_ids (in rank order), and all six caller metadata fields.

### 4. REST search endpoint
- **File:** `src/pipeline/api/routes.py`
- **What:** Same logging call after building search results, using `_resolve_agent_id` for agent_id resolution from API key.

### 5. Migration applied
- **Method:** `docker exec -i ariadne-core-postgres-1 psql -U app -d pipeline < migrations/003_search_log.sql`

## Verification Results

| # | Check | Pass/Fail | Notes |
|---|-------|-----------|-------|
| 1 | Search with full metadata including `agent_metadata` JSONB | Pass | 5 results returned, search response unchanged |
| 2 | Database row has all fields | Pass | `query: "test"`, `collection: "default"`, `top_k: 5`, `results_count: 5`, `result_document_ids` with 5 UUIDs, all 6 metadata fields present |
| 3 | `agent_metadata` JSONB stored correctly | Pass | `{"task": "test search logging", "project": "verification"}` |
| 4 | Second search creates second row | Pass | Two rows with different `agent_id` and `agent_notes` |
| 5 | Search response unchanged | Pass | No new fields in client-facing response |
