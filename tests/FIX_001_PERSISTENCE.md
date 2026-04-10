# Fix 001: Document Persistence

## The Problem

`convert_document` and `ingest` run the full extraction pipeline and return `store_status: "stored"` with a valid `document_id`, but documents are NOT persisted to Postgres. Evidence:

- `list_documents` returns 0 documents for any collection created during testing
- `get_document` returns 404 for every `document_id` returned by `convert_document`
- `list_collections` never shows new collections
- Dedup never triggers because there's nothing in the database to match against

The one document that IS persisted (a README.md in `default` from a prior run) works correctly through `get_document`, `search`, and `list_documents`. This confirms the retrieval code is fine. The bug is in the write path.

## What to Fix

Find where `convert_document` and `ingest` are supposed to persist the document record, chunks, and interaction to Postgres, and fix whatever is preventing the commit from happening.

The relevant code path is in `_process_single_document` in `src/pipeline/mcp_server.py`. It calls the extraction, chunking, and embedding steps, then is supposed to store the result via the dedup store and vector store. Trace the write path from there.

Look at:
- `src/pipeline/mcp_server.py` — `_process_single_document` function
- `src/pipeline/dedup.py` — `PgDedupStore` vs `InMemoryDedupStore` — which one is being used at runtime?
- `src/pipeline/storage/pgvector.py` — `PgVectorStore` vs `InMemoryVectorStore` — which one is being used at runtime?
- The startup/initialization code — are the Postgres-backed stores being wired in, or is it falling back to in-memory stores that get lost between requests?
- Docker entrypoint — is the API process connecting to Postgres at all?
- `migrations/001_initial.sql` — verify the schema is applied

Common causes for this pattern:
- In-memory stores used instead of Postgres-backed stores (stores initialized at module level before DB connection is ready)
- Transaction not committed (missing `conn.commit()` or context manager issue)
- Store initialized once per import but Docker workers are separate processes
- Connection pool exhaustion or silent connection failure

## How to Verify the Fix

After making the fix, restart Docker (`docker compose down && docker compose up -d`) and then run these checks in order:

1. Call `convert_document` on `/data/fixtures/sample.txt` with `collection: "persistence-test"` and `store: true`
2. Call `list_collections` — `persistence-test` should appear with `document_count: 1`
3. Call `list_documents` with `collection: "persistence-test"` — should return the document
4. Call `get_document` with the `document_id` from step 1 — should return full content
5. Call `convert_document` again with the same file, same collection, NO `force` flag — should get `was_dedup_skip: true` with the SAME `document_id`
6. Call `get_document` again — should now show 2 interactions (the original ingest + the dedup skip)

All 6 steps must pass. If any fail, the fix is incomplete.

## Rules

- Read SPEC.md (repo root) if you need to understand the expected behavior
- Do not change SPEC.md, SKILL.md, or any docs — only fix the code
- Do not change the MCP tool signatures or response formats — only fix persistence
- Run the 6 verification steps above and report the results
- If you discover the root cause, explain it clearly so we understand what went wrong
