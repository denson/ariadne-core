# Skill Validation Test Plan

Run these tests in order. Each test validates that the MCP server behaves the way SPEC.md and SKILL.md say it should.

## Reference Documents — READ THESE FIRST

Two documents and actual execution. That's it.

1. **SPEC.md** (repo root) — **THE source of truth.** If anything conflicts with this, SPEC.md wins.

2. **SKILL.md** (`skills/ariadne-document-intelligence/SKILL.md`) — What agents are told to do. Written against SPEC.md.

3. **Actual execution** — Call each MCP tool and see what happens.

**IGNORE everything else.** Do not read `docs/docint-architecture.md`, `README.md`, `metadata.json`, or `CLAUDE.md`. They are out of date and will be fixed after this validation.

The goal is three-way validation:
- Does the **MCP server** behave the way **SPEC.md** says it should?
- Does the **SKILL.md** accurately describe what the server actually does?
- Does the **SKILL.md** accurately reflect what **SPEC.md** specifies?

Report discrepancies in all three directions.

## CRITICAL RULES

1. **You are a tester, not a fixer.** Your job is to document what works and what doesn't. Do NOT fix code, modify Docker configs, copy files into containers, create workarounds, or change anything to make a test pass. If a test fails, record the failure with the exact error and move to the next test.

2. **Do not work around problems.** If the MCP server doesn't expose all expected tools — that's a finding, not something to route around via REST API. If a file path doesn't resolve inside Docker — that's a finding. Record it and move on.

3. **Use MCP tools only.** The SKILL.md teaches agents to use MCP tools. Test what agents would actually experience. Do not fall back to REST API or curl. If an MCP tool is missing, that's a FAIL for every test that depends on it.

4. **Stay on the test fixtures.** Use the files in `tests/fixtures/` for all file-based tests. The MCP server runs inside Docker and mounts `shared-data:/data`. The fixtures may need to be at a path the container can see. If the path doesn't work, record the error and the path you tried, then move on.

5. **Fill in the summary table at the end.** Every test gets a Pass/Fail/Blocked. "Blocked" means a prerequisite failed (e.g., can't test dedup if convert_document never worked). The summary table and discrepancy list are the deliverables — not workarounds.

6. **Write the results to a file.** When all tests are done, write the completed summary table and all discrepancies to `tests/VALIDATION_RESULTS.md`. That file is the deliverable.

---

## Test 1: list_collections

Call `list_collections` with no arguments.

**SPEC.md says:** Returns `collections` array, each with `name`, `description`, `document_count`.

**SKILL.md says:** "See all collections with document counts. Use before choosing a collection for ingestion."

**Verify:**
- Response contains a `collections` array
- Each entry has `name`, `description`, and `document_count`
- No error

---

## Test 2: convert_document — single file with full caller metadata

Call `convert_document` with:
```
uri: tests/fixtures/sample.txt
store: true
collection: skill-validation
tags: ["test", "validation"]
agent_type: "claude-code"
initiated_by: "user:denson"
model: "claude-sonnet-4-6"
agent_notes: "Skill validation test — ingesting sample.txt to verify convert_document works per SKILL.md spec"
agent_id: "claude-code-skill-validation"
agent_metadata: {"purpose": "skill-validation", "test_run": 1}
```

**SPEC.md says:** Returns JSON with `document_id`, `markdown`, `file_type`, `content_fingerprint`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `interactions`.

**SKILL.md says** (step 4 of ingestion process): Response includes `document_id`, `markdown`, `file_type`, `content_fingerprint`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `interactions`.

**Verify:**
- Response is valid JSON (not an error)
- Has `document_id` (a UUID)
- Has `markdown` with extracted text from sample.txt
- Has `file_type`
- Has `content_fingerprint`
- Has `chunks_count`
- Has `was_dedup_skip: false` (first ingestion)
- Has `provenance`
- Has `warnings` array (may be empty)
- Record the `document_id` — needed for later tests

---

## Test 3: convert_document — HTML file

Call `convert_document` with:
```
uri: tests/fixtures/sample.html
store: true
collection: skill-validation
tags: ["test", "html"]
agent_type: "claude-code"
initiated_by: "user:denson"
model: "claude-sonnet-4-6"
agent_notes: "Testing HTML extraction"
agent_id: "claude-code-skill-validation"
```

**Verify:**
- Succeeds without error
- Extracted markdown preserves HTML structure (headings, paragraphs, links)
- Same response fields as Test 2
- Stored in `skill-validation` collection

---

## Test 4: Dedup — send same document again

Call `convert_document` again with the exact same parameters as Test 2 (same uri, same collection, no `force`).

**SPEC.md says:** "If the fingerprint already exists in the target collection: extraction, chunking, and embedding are skipped. A `document_interactions` row is still created. The existing document is returned to the caller."

**SKILL.md says:** `was_dedup_skip: true` means already ingested. Tell user: "This document was already in the [collection] collection."

**Verify:**
- Response has `was_dedup_skip: true`
- Response returns the existing `document_id` (same UUID as Test 2)
- No re-processing occurred
- An interaction was still recorded (verify via get_document in Test 8)

---

## Test 5: Force override — re-ingest with force=true

Call `convert_document` with the same parameters as Test 2 but add `force: true`.

**SPEC.md says:** "The `force` flag on `convert_document` and `ingest` overrides this when you know a document has changed."

**SKILL.md says:** "Use `force: true` only when the user says the document content has changed."

**Verify:**
- Response has `was_dedup_skip: false` (re-processed despite matching fingerprint)
- Got a `document_id` back
- Processing actually ran again (check `provenance` for new timestamps)

---

## Test 6: list_documents

Call `list_documents` with:
```
collection: skill-validation
```

**SPEC.md says:** Returns `total_count`, `documents` array with `document_id`, `collection`, `source_file`, `file_type`, `title`, `chunk_count`, `interaction_count`, `created_at`.

**SKILL.md says:** "Returns metadata only. Supports `limit` (default 20, max 100) and `offset` for pagination."

**Verify:**
- Response has `total_count` >= 2 (sample.txt + sample.html)
- Response has `documents` array
- Each document has: `document_id`, `collection`, `source_file`, `file_type`, `chunk_count`, `interaction_count`
- Has `limit` and `offset` in response
- sample.txt should have `interaction_count` >= 3 (Test 2 + Test 4 dedup + Test 5 force)

---

## Test 7: list_documents with file_type filter

Call `list_documents` with:
```
collection: skill-validation
file_type: txt
```

**Verify:**
- Only returns .txt documents
- sample.html is NOT in results

---

## Test 8: get_document — full retrieval

Use the `document_id` for sample.txt from Test 2. Call `get_document` with:
```
document_id: <the UUID from Test 2>
include_chunks: true
include_interactions: true
```

**SPEC.md says:** Returns full `content_markdown`, `processing_chain`, `chunks` array, `interactions` array, and all document metadata.

**SKILL.md says:** "Get the full Markdown content and all chunks for a document by ID." Pass `include_chunks: false` or `include_interactions: false` to trim.

**Verify:**
- Response has `content_markdown` with the full extracted text
- Response has `chunks` array with each chunk having: `chunk_id`, `text`, `section`, `page`, `token_count`
- Response has `interactions` array with each interaction having: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `action`, `was_dedup_skip`
- There should be at least 3 interactions (Test 2 ingest, Test 4 dedup skip, Test 5 force)
- At least one interaction has `was_dedup_skip: true`
- Interactions have the caller metadata we passed (agent_type: "claude-code", initiated_by: "user:denson")
- Response has: `source_file`, `file_type`, `collection`, `content_fingerprint`, `tags`, `processing_chain`

---

## Test 9: search

Call `search` with:
```
query: "document extraction pipeline"
top_k: 5
collection: skill-validation
agent_type: "claude-code"
initiated_by: "user:denson"
model: "claude-sonnet-4-6"
agent_notes: "Testing search over ingested validation docs"
```

**SPEC.md says:** Returns `query`, `results_count`, `results` array. Each result: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, `interactions`.

**SKILL.md says:** "Semantic search over stored documents. Returns ranked chunks with source file, page, section, relevance score, and full interaction history."

**Verify:**
- Response has `results` array
- Each result has: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `relevance_score`, `interactions`
- Results are ranked by `relevance_score` (descending)
- `interactions` array is present on each result
- If embedding is not configured, the response should return an error message saying search is unavailable — note it as a configuration issue, not a code bug, and move on

---

## Test 10: search with filters

If Test 9 succeeded (embedding is configured), call `search` with:
```
query: "testing"
top_k: 5
collection: skill-validation
filters: {"file_type": "txt"}
```

**SPEC.md says:** Supported filters: `collection`, `document_id`, `source_file` (substring, case-insensitive), `file_type` (exact match without dot), `tags` (OR logic). Unknown keys silently ignored.

**SKILL.md says:** Same filter table with same behaviors.

**Verify:**
- Only returns chunks from .txt files
- No .html chunks in results

---

## Test 11: ingest — batch directory

Call `ingest` with:
```
path: tests/fixtures
collection: batch-validation
recursive: false
tags: ["batch-test"]
agent_type: "claude-code"
initiated_by: "user:denson"
model: "claude-sonnet-4-6"
agent_notes: "Batch ingestion test of fixtures directory"
agent_id: "claude-code-skill-validation"
```

**SPEC.md says:** Returns `files_found`, `files_processed`, `files_skipped`, `files_errored`, `results` array with per-file status (`document_id`, `source_file`, `was_dedup_skip`, error message).

**SKILL.md says:** "Returns files found, files processed, files skipped (dedup), and any errors."

**Verify:**
- Response has `files_found`, `files_processed`, `files_skipped`, `files_errored`
- Response has `results` array with per-file status
- Each result has `source_file`, `document_id`, `was_dedup_skip`, `error`
- Dedup is per-collection, so sample.txt should process as NEW here (different collection than skill-validation)
- Image files (test_image.jpg, test_image.png) should either process with a warning or succeed if vision is configured
- Audio file (test_audio.wav) should either process or error gracefully

---

## Test 12: ingest with file_types filter

Call `ingest` with:
```
path: tests/fixtures
collection: batch-validation-filtered
file_types: ["txt", "html"]
recursive: false
tags: ["filtered-batch"]
agent_type: "claude-code"
initiated_by: "user:denson"
model: "claude-sonnet-4-6"
agent_notes: "Filtered batch ingestion — only txt and html"
```

**Verify:**
- `files_found` only counts .txt and .html files
- No image or audio files were processed
- Results only contain txt and html files

---

## Test 13: list_collections — verify new collections exist

Call `list_collections` again.

**Verify:**
- Now includes `skill-validation`, `batch-validation`, and `batch-validation-filtered` collections
- Document counts match expectations from previous tests

---

## Test 14: Multi-agent provenance

Call `convert_document` on sample.txt again but with DIFFERENT caller metadata:
```
uri: tests/fixtures/sample.txt
store: true
collection: skill-validation
agent_type: "ob1"
initiated_by: "user:nate"
model: "gpt-4o"
agent_notes: "Second agent touching the same document for provenance test"
agent_id: "ob1-test-agent"
```

Then call `get_document` on the sample.txt document_id with `include_interactions: true`.

**SPEC.md says:** "Every agent call creates a record, even dedup skips. When you search and get a result, you also get the full history of who has touched that document."

**SKILL.md says:** "Search results include interaction history — which agents have previously touched each document."

**Verify:**
- The dedup skip happened (same content, same collection)
- Interactions now include BOTH agent_types ("claude-code" AND "ob1")
- Interactions include BOTH initiated_by values ("user:denson" AND "user:nate")
- Each interaction preserves its own agent_notes

---

## Summary Checklist

After all tests, fill in this table and write it to `tests/VALIDATION_RESULTS.md`:

| # | Test | Pass/Fail/Blocked | Notes |
|---|------|-------------------|-------|
| 1 | list_collections | | |
| 2 | convert_document (txt) | | |
| 3 | convert_document (html) | | |
| 4 | dedup skip | | |
| 5 | force override | | |
| 6 | list_documents | | |
| 7 | list_documents (filtered) | | |
| 8 | get_document | | |
| 9 | search | | |
| 10 | search (filtered) | | |
| 11 | ingest (batch) | | |
| 12 | ingest (filtered) | | |
| 13 | list_collections (updated) | | |
| 14 | multi-agent provenance | | |

## Discrepancy Report

After the summary table, list every discrepancy found in three categories:

### Server vs SPEC.md
(Where the MCP server behavior doesn't match what SPEC.md says)

### Server vs SKILL.md
(Where the MCP server behavior doesn't match what SKILL.md tells agents to expect)

### SKILL.md vs SPEC.md
(Where SKILL.md says something different from SPEC.md — should be none after the recent sync, but verify)
