# Phase 1: Detect

## ROLE

You are a QA tester. You run tests, observe results, and write findings.

## GOAL

Run every test in the test plan below. For each failure, write a finding with the exact error and a one-paragraph recommendation for how to fix it. Produce a results file.

## CONTEXT

- SPEC.md (repo root) is the source of truth for expected behavior
- SKILL.md (skills/ariadne-document-intelligence/SKILL.md) describes the expected agent experience
- The MCP server is running in Docker. Six tools should be available: `convert_document`, `search`, `get_document`, `list_documents`, `list_collections`, `ingest`
- Test fixtures are in `tests/fixtures/`. Inside the Docker container they are at `/data/fixtures/`

## CAPABILITIES

You MAY:
- Call MCP tools
- Read SPEC.md and SKILL.md
- Write results to `tests/VALIDATION_RESULTS.md`

## CONSTRAINTS

You MUST NOT:
- Fix code, modify source files, or change Docker configuration
- Create workarounds (copying files into containers, falling back to REST API, retrying with different paths)
- Read or modify any file other than SPEC.md, SKILL.md, and the results file
- Run more than the tests listed below

If a test fails, record the failure and move on. Do not attempt to make it pass.

## VALUE HIERARCHY

Accurate reporting takes priority over a clean scorecard. A failure you record honestly is more valuable than a pass you achieved through workarounds.

## ESCALATION

- If the MCP server is unreachable, record that as the result for all tests and stop
- If a tool is missing from the MCP connection, mark every test that depends on it as BLOCKED
- If you are unsure whether something is a failure or expected behavior, record it as a finding and note your uncertainty

## SUCCESS CRITERIA

You are done when:
1. Every test has a Pass / Fail / Blocked result
2. Every failure has a one-paragraph fix recommendation
3. Results are written to `tests/VALIDATION_RESULTS.md`

## OUTPUT FORMAT

Write `tests/VALIDATION_RESULTS.md` with this structure:

```markdown
# Validation Results

**Date:** YYYY-MM-DD
**MCP tools available:** [list the tools you can see]

## Summary

| # | Test | Result | Finding |
|---|------|--------|---------|
| 1 | ... | Pass/Fail/Blocked | one-line summary or "—" for pass |

## Findings

### Finding N: [short title]
**Test:** N
**Expected:** [what SPEC.md / SKILL.md says should happen]
**Actual:** [what actually happened — include the exact error or response]
**Recommended fix:** [one paragraph — be specific about what code to change and where, but do NOT make the change]
```

---

## Tests

### Test 1: list_collections
Call `list_collections` with no arguments.
**Expected:** `collections` array, each entry has `name`, `description`, `document_count`.

### Test 2: convert_document (txt)
Call `convert_document` with:
- `uri`: `/data/fixtures/sample.txt`
- `store`: true
- `collection`: `detect-run`
- `tags`: ["test"]
- `agent_type`: "claude-code"
- `initiated_by`: "user:denson"
- `model`: "claude-sonnet-4-6"
- `agent_notes`: "Phase 1 detect — Test 2"
- `agent_id`: "detect-run"

**Expected (per SPEC.md):** Response has `document_id`, `markdown`, `file_type`, `content_fingerprint`, `chunks_count`, `was_dedup_skip` (false), `provenance`, `warnings`. Record the `document_id` for later tests.

### Test 3: convert_document (html)
Same as Test 2 but with `/data/fixtures/sample.html`. Same collection.
**Expected:** Same response fields. HTML structure preserved in markdown.

### Test 4: Dedup skip
Call `convert_document` with the exact same parameters as Test 2 (same uri, same collection, no `force`).
**Expected:** `was_dedup_skip: true`, same `document_id` as Test 2, interaction recorded.

### Test 5: Force override
Same as Test 2 but with `force: true`.
**Expected:** `was_dedup_skip: false`, document re-processed.

### Test 6: list_documents
Call `list_documents` with `collection: "detect-run"`.
**Expected:** `total_count` >= 2, each document has `document_id`, `collection`, `source_file`, `file_type`, `chunk_count`, `interaction_count`, `limit`, `offset`.

### Test 7: list_documents (filtered)
Call `list_documents` with `collection: "detect-run"`, `file_type: "txt"`.
**Expected:** Only .txt documents returned.

### Test 8: get_document
Call `get_document` with the `document_id` from Test 2, `include_chunks: true`, `include_interactions: true`.
**Expected:** `content_markdown`, `chunks` array (each with `chunk_id`, `text`, `section`, `page`, `token_count`), `interactions` array (each with `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `action`, `was_dedup_skip`, `created_at`). At least 3 interactions from Tests 2, 4, 5.

### Test 9: search
Call `search` with `query: "document extraction"`, `collection: "detect-run"`, `top_k: 5`, caller metadata.
**Expected:** `results` array, each with `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `relevance_score`, `interactions`. If embedding not configured, error message is acceptable — record it.

### Test 10: search (filtered)
If Test 9 passed, call `search` with `query: "testing"`, `collection: "detect-run"`, `filters: {"file_type": "txt"}`.
**Expected:** Only .txt chunks returned.

### Test 11: ingest (batch)
Call `ingest` with `path: "/data/fixtures"`, `collection: "detect-batch"`, `recursive: false`, `tags: ["batch"]`, caller metadata.
**Expected:** `files_found`, `files_processed`, `files_skipped`, `files_errored`, `results` array with per-file `source_file`, `document_id`, `was_dedup_skip`, `error`.

### Test 12: ingest (filtered)
Call `ingest` with `path: "/data/fixtures"`, `collection: "detect-batch-filtered"`, `file_types: ["txt", "html"]`, `recursive: false`, caller metadata.
**Expected:** Only .txt and .html files processed.

### Test 13: list_collections (updated)
Call `list_collections`.
**Expected:** Includes `detect-run`, `detect-batch`, `detect-batch-filtered` with correct document counts.

### Test 14: Multi-agent provenance
Call `convert_document` on `/data/fixtures/sample.txt`, `collection: "detect-run"`, but with `agent_type: "ob1"`, `initiated_by: "user:nate"`, `model: "gpt-4o"`, `agent_notes: "Different agent for provenance test"`.
Then call `get_document` on the same document_id with `include_interactions: true`.
**Expected:** `was_dedup_skip: true`. Interactions include both "claude-code" and "ob1" agent_types with their respective metadata.
