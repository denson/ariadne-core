# Validation Results

**Date:** 2026-04-05
**MCP tools available:** `convert_document`, `search`, `get_document`, `list_documents`, `list_collections`, `ingest`

## Summary

| # | Test | Result | Finding |
|---|------|--------|---------|
| 1 | list_collections | Pass | — |
| 2 | convert_document (txt) | Pass | — |
| 3 | convert_document (html) | Pass | — |
| 4 | Dedup skip | Pass | — |
| 5 | Force override | Pass | — |
| 6 | list_documents | Pass | — |
| 7 | list_documents (filtered) | Pass | — |
| 8 | get_document | Pass | — |
| 9 | search | Pass | — |
| 10 | search (filtered) | Pass | — |
| 11 | ingest (batch) | Pass | — |
| 12 | ingest (filtered) | Pass | — |
| 13 | list_collections (updated) | Pass | — |
| 14 | Multi-agent provenance | Pass | — |

## Findings

No findings — all 14 tests passed.

---

## Test Details

### Test 1: list_collections
Called `list_collections` with no arguments.
- `collections` array returned with 7 entries (pre-existing collections from prior test runs)
- Each entry has `name`, `description`, `document_count`

### Test 2: convert_document (txt)
Called `convert_document` with `/data/fixtures/sample.txt`, `collection: "detect-run"`, `agent_type: "claude-code"`, `initiated_by: "user:denson"`, `model: "claude-sonnet-4-6"`, `agent_notes: "Phase 1 detect — Test 2"`, `agent_id: "detect-run"`.
- `document_id`: `69240cd0-673d-44d4-8e53-7c2bfec57e9b`
- `markdown`: present (103 estimated tokens)
- `file_type`: `txt`
- `content_fingerprint`: `ff48cccf3b25b1489a3fc62451bfe0bbd4a1b46777ae05e19c86339add71cfe7`
- `chunks_count`: 2
- `was_dedup_skip`: false
- `provenance`: present with `processing_chain` (extraction + embedding)
- `warnings`: `[]`

### Test 3: convert_document (html)
Called `convert_document` with `/data/fixtures/sample.html`, same collection.
- `document_id`: `cd1fdf8d-3575-4759-a2d7-4402490106d5`
- HTML structure preserved: headings (`# Test HTML Document`, `## Features`) and list items (`* PDF extraction`, etc.)
- All expected fields present

### Test 4: Dedup skip
Called `convert_document` with identical parameters to Test 2.
- `was_dedup_skip`: true
- `document_id`: `69240cd0-673d-44d4-8e53-7c2bfec57e9b` (same as Test 2)
- `interactions`: 2 entries (original ingest + dedup skip)
- Interaction recorded with `was_dedup_skip: true`

### Test 5: Force override
Called `convert_document` with `force: true`, same parameters as Test 2.
- `was_dedup_skip`: false
- Document re-processed (new extraction timestamp: `2026-04-05T19:12:54`)
- New embedding step recorded in `provenance.processing_chain`

### Test 6: list_documents
Called `list_documents` with `collection: "detect-run"`.
- `total_count`: 2
- `limit`: 20, `offset`: 0
- Each document has: `document_id`, `collection`, `source_file`, `file_type`, `chunk_count`, `interaction_count`
- sample.txt: `chunk_count: 2`, `interaction_count: 3`
- sample.html: `chunk_count: 1`, `interaction_count: 1`

### Test 7: list_documents (filtered)
Called `list_documents` with `collection: "detect-run"`, `file_type: "txt"`.
- `total_count`: 1
- Only `sample.txt` returned

### Test 8: get_document
Called `get_document` with document_id from Test 2, `include_chunks: true`, `include_interactions: true`.
- `content_markdown`: present
- `chunks`: 2 entries, each with `chunk_id`, `text`, `section`, `page`, `token_count`
- `interactions`: 3 entries (Test 2 ingest, Test 4 dedup skip, Test 5 force re-process)
- Each interaction has all required fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `action`, `was_dedup_skip`, `created_at`

### Test 9: search
Called `search` with `query: "document extraction"`, `collection: "detect-run"`, `top_k: 5`, caller metadata.
- `results_count`: 3
- Each result has: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `relevance_score`, `interactions`
- Top result: Section Two of sample.txt (`relevance_score: 0.6043`)
- Interactions correctly attached to each result

### Test 10: search (filtered)
Called `search` with `query: "testing"`, `collection: "detect-run"`, `filters: {"file_type": "txt"}`.
- `results_count`: 2
- Both results from `sample.txt` (document_id `69240cd0...`)
- No HTML chunks returned — filter working correctly

### Test 11: ingest (batch)
Called `ingest` with `path: "/data/fixtures"`, `collection: "detect-batch"`, `recursive: false`, `tags: ["batch"]`.
- `files_found`: 5
- `files_processed`: 3 (sample.html, test_image.png, sample.txt)
- `files_skipped`: 1 (test_image.jpg — dedup of test_image.png)
- `files_errored`: 1 (test_audio.wav — AudioConverter error)
- `results` array: 5 entries with `source_file`, `document_id`, `was_dedup_skip`, `error`

### Test 12: ingest (filtered)
Called `ingest` with `path: "/data/fixtures"`, `collection: "detect-batch-filtered"`, `file_types: ["txt", "html"]`, `recursive: false`.
- `files_found`: 2
- `files_processed`: 2 (sample.html, sample.txt)
- No non-txt/html files processed

### Test 13: list_collections (updated)
Called `list_collections`.
- `detect-run`: `document_count: 2` — correct
- `detect-batch`: `document_count: 3` — correct (3 unique docs after dedup)
- `detect-batch-filtered`: `document_count: 2` — correct

### Test 14: Multi-agent provenance
Called `convert_document` on sample.txt in `detect-run` with `agent_type: "ob1"`, `initiated_by: "user:nate"`, `model: "gpt-4o"`.
- `was_dedup_skip`: true
- `interactions`: 4 entries
  - 3 from `claude-code` / `user:denson` (Tests 2, 4, 5)
  - 1 from `ob1` / `user:nate` / `gpt-4o` (Test 14)
- Verified via `get_document`: same 4 interactions with both agent types and their respective metadata
