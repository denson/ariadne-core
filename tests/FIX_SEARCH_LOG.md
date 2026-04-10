# Fix: Add Search Log

## ROLE

You are a developer adding a new feature.

## GOAL

Record every `search` call in a `search_log` table. One row per search, not per result. Store the query, filters, results summary, and all caller metadata including `agent_metadata` (JSONB).

## REFERENCE

Read the "Search Log" section in SPEC.md for the full table schema.

## WHAT TO DO

### 1. Migration

Add a `search_log` table to the database. Create `migrations/002_search_log.sql`:

```sql
CREATE TABLE IF NOT EXISTS search_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    collection TEXT,
    filters JSONB,
    top_k INTEGER,
    results_count INTEGER,
    result_document_ids UUID[],
    agent_id TEXT,
    agent_type TEXT,
    model TEXT,
    initiated_by TEXT,
    agent_notes TEXT,
    agent_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_search_log_created_at ON search_log (created_at DESC);
CREATE INDEX idx_search_log_agent_id ON search_log (agent_id);
CREATE INDEX idx_search_log_initiated_by ON search_log (initiated_by);
```

### 2. Store class

Add a method to write search log entries. This can go in `dedup.py` on `PgDedupStore` (it already has the DB connection), or as a new small class — your call on what's cleanest. The `InMemoryDedupStore` should also get a search log list for testing.

### 3. MCP search handler

In `mcp_server.py`, after the search completes and results are built, record the search log entry with:
- The query, collection, filters, top_k
- `results_count` from the actual results
- `result_document_ids` — the document IDs from the results, in rank order
- All six caller metadata fields

### 4. REST search endpoint

In `routes.py`, same thing — record the search log entry after search completes. Since the STDIO proxy routes through REST, this covers all clients.

### 5. Apply migration

The migration needs to run against the running Postgres. Either:
- Add it to the Docker init scripts (but the container may already be initialized)
- Run it manually: `docker exec -i ariadne-core-postgres-1 psql -U app -d pipeline < migrations/002_search_log.sql`

## CONSTRAINTS

- Do NOT change SPEC.md or SKILL.md
- Do NOT change any MCP tool signatures or response formats
- Do NOT add search log data to search responses — it's backend-only logging
- Search logging must not block or slow down the search response. If the log write fails, log a warning and return the search results anyway.

## VERIFICATION

After making the changes, restart Docker, apply the migration, and verify:

1. Call `search` with `query: "test"`, `collection: "default"`, full caller metadata including `agent_metadata: {"project": "verification", "task": "test search logging"}`
2. Check the database directly: `docker exec -i ariadne-core-postgres-1 psql -U app -d pipeline -c "SELECT * FROM search_log ORDER BY created_at DESC LIMIT 1;"`
3. Verify the row has: `query`, `collection`, `top_k`, `results_count`, `result_document_ids`, all six metadata fields including the JSONB `agent_metadata`
4. Call `search` again with different metadata — verify a second row appears
5. Verify the search response itself is unchanged (no new fields added to what the client sees)

All 5 steps must pass. Write results to `tests/FIX_SEARCH_LOG_RESULTS.md`.
