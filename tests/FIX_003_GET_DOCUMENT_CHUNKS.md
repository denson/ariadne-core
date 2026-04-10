# Fix 003: `get_document` Not Returning Chunks

## The Problem

`get_document` called with `include_chunks: true` does not return a `chunks` array in the response. SPEC.md says it should return all chunks with `chunk_id`, `text`, `section`, `page`, `token_count`.

From VALIDATION_RESULTS.md:
> `get_document` missing `chunks` array. Called with `include_chunks: true` but response has no `chunks` array.

We know chunks exist — `convert_document` returns a `chunks_count` value and the `search` tool finds chunks and returns them with text. The issue is specifically in `get_document`'s chunk retrieval.

## What to Fix

In `src/pipeline/mcp_server.py`, the `get_document` function has a section (around lines 314-326) that should fetch chunks when `include_chunks` is true. Trace:

1. `_get_chunks_for_document(document_id)` — does this helper function exist and work? Does it query the right table/store?
2. If using `PgVectorStore`, is there a method to get chunks by document_id? Or is it only doing similarity search?
3. If using `InMemoryVectorStore`, same question — is there a way to retrieve chunks by document_id without a query embedding?

The fix might require adding a `get_chunks_by_document` method to the vector store if one doesn't exist, or fixing the existing helper to actually call the store correctly.

## How to Verify

After making the fix, restart Docker and run:

1. Call `convert_document` on `/data/fixtures/sample.txt` with `collection: "chunks-test"`, `store: true`
2. Note the `document_id` and `chunks_count` from the response
3. Call `get_document` with that `document_id` and `include_chunks: true`
4. Check that the response has a `chunks` array
5. Check that `chunks` array length matches `chunks_count` from step 2
6. Check that each chunk has: `chunk_id`, `text`, `section`, `page`, `token_count`

All 6 steps must pass.

## Rules

- Only fix chunk retrieval in `get_document` — do not change anything else
- Do not change SPEC.md, SKILL.md, or any docs
- Do not change MCP tool signatures
- Write the verification results to `tests/FIX_003_RESULTS.md`
