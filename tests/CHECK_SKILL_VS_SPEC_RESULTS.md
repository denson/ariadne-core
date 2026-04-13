# CHECK: Skill vs Spec Results

**Date:** 2026-04-05

**Files compared:**
- SPEC: `SPEC.md` (repo root)
- SKILL: `C:\Users\denso\claude_projects\OB1\skills\ariadne-document-intelligence\SKILL.md`

---

## Results

### 1. MCP tools — PASS

Both documents list the same tools: `convert_document`, `search`, `get_document`, `list_documents`, `list_collections`, `ingest`. Descriptions are consistent. The skill doesn't use parameter tables per tool (it covers parameters in the process sections instead), but all parameters are documented somewhere in the skill.

### 2. convert_document response fields — PASS

The skill's "Process: Ingesting a document" step 4 lists all 17 response fields from the spec: `document_id`, `source_file`, `title`, `markdown`, `file_type`, `engine`, `content_fingerprint`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `embedding_model`, `store_status`, `interactions`. All descriptions match.

### 3. search response fields — DISCREPANCY

The spec lists search response fields explicitly:

> Returns JSON with: `query`, `results_count`, and `results` array. Each result includes `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, and `interactions`.

The skill's tool description says only:

> Returns ranked chunks with source file, page, section, relevance score, and full interaction history.

Missing from the skill's explicit listing: `chunk_id`, `document_id`, `collection`, `text`, `token_count`, `embedding_model`, `query`, `results_count`. Some are mentioned elsewhere (e.g., `document_id` is used in the search process section), but the skill never enumerates the full search response shape.

### 4. search filters — PASS

Both files have identical filter tables with the same 5 keys (`collection`, `document_id`, `source_file`, `file_type`, `tags`), same types, same behavior descriptions. Both note "Unknown filter keys are silently ignored."

### 5. get_document parameters — PASS

Spec: `document_id` (required), `include_chunks` (default true), `include_interactions` (default true).

Skill: "Pass `include_chunks: false` or `include_interactions: false` to trim the response when you only need part of it." Matches.

### 6. list_documents parameters — PASS

Spec: `collection`, `file_type`, `limit` (20, max 100), `offset`.

Skill: "Browse stored documents by collection or file type. Returns metadata only. Supports `limit` (default 20, max 100) and `offset` for pagination." Matches.

### 7. ingest parameters and response — PASS

Spec parameters: `path`, `collection`, `recursive`, `file_types`, `force`, `tags`. All appear in the skill's "Process: Batch ingesting a directory" section.

Spec response: `files_found`, `files_processed`, `files_skipped`, `files_errored`, `results` array with per-file status.

Skill: "Report the summary when done: files found, files processed, files skipped (dedup), and any errors." Matches.

### 8. Caller metadata — PASS

Both list the same 6 fields: `agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`. Both say they apply to `convert_document`, `search`, and `ingest`. Descriptions and guidance match.

### 9. Dedup behavior — PASS

Spec: fingerprint before expensive processing, skip extraction/chunking/embedding on collision, always create interaction row, return existing doc, `force` overrides.

Skill notes: "Dedup is automatic. You don't need to check if a document was already ingested — just call `convert_document` and the system handles it. Use `force: true` only when the user says the document content has changed." Step 4 also documents `was_dedup_skip` behavior. Consistent with spec.

### 10. Pipeline order — PASS

The spec lists a 7-step internal pipeline order. The skill doesn't reproduce this (it describes agent-level processes, not internal engine steps), but nothing in the skill contradicts the spec's pipeline order. The skill correctly describes the external behavior that results from the pipeline.

### 11. Chunking — PASS

Both have identical auto-selection tables:

| File type | Strategy |
|-----------|----------|
| `.pptx` | `by_page` |
| `.csv`, `.xlsx` | `fixed_size` |
| `.txt` with no headings | `fixed_size` with high overlap |
| Everything else | `by_title` |

Both list the same `chunking_config` keys: `strategy`, `max_characters`, `overlap`.

### 12. Path resolution — DISCREPANCY

The spec has a "Path Resolution" section describing how the STDIO proxy auto-uploads local file paths:

> When clients connect via STDIO proxy, local file paths are automatically resolved:
> 1. Proxy detects that `uri` is a local file path (not http/https, not already a `/data/` path)
> 2. Proxy uploads the file to `POST /api/upload`
> 3. Upload endpoint saves to `/data/incoming/<uuid>_<filename>` and returns the container path
> 4. Proxy rewrites the `uri` to the container path before forwarding to the REST API

The skill makes no mention of path resolution, the upload endpoint, or STDIO proxy behavior. An OB1 agent wouldn't know that local file paths are automatically handled, or that HTTP MCP / REST API callers need to use the upload endpoint manually.

### 13. Search log — PASS (not required)

The spec documents the `search_log` table and says "Every `search` call is recorded in the `search_log` table." The skill does not mention this.

This is an internal implementation detail that doesn't change how an agent uses the `search` tool. The agent doesn't need to know about or interact with the search log. No action needed — the skill is correct to omit this.

### 14. Error handling — PASS

Both list the same 6 error cases with matching guidance:
1. Zero-byte / corrupt file
2. Password-protected document
3. Unsupported format
4. Image with no vision API key
5. Embedding not configured
6. Network / service error

### 15. Supported formats — DISCREPANCY (minor)

The spec lists image formats as:

> Images (JPG, PNG, GIF, JPEG) are supported but require a vision API key

The skill lists:

> Images (JPG, PNG, GIF) require a vision API key for content extraction.

JPEG is omitted from the skill's list. This is cosmetic (JPG and JPEG are the same format), but the spec explicitly includes both.

---

## Summary

| # | Category | Result |
|---|----------|--------|
| 1 | MCP tools | PASS |
| 2 | convert_document response fields | PASS |
| 3 | search response fields | **DISCREPANCY** |
| 4 | search filters | PASS |
| 5 | get_document parameters | PASS |
| 6 | list_documents parameters | PASS |
| 7 | ingest parameters and response | PASS |
| 8 | Caller metadata | PASS |
| 9 | Dedup behavior | PASS |
| 10 | Pipeline order | PASS |
| 11 | Chunking | PASS |
| 12 | Path resolution | **DISCREPANCY** |
| 13 | Search log | PASS (not required) |
| 14 | Error handling | PASS |
| 15 | Supported formats | **DISCREPANCY** (minor) |

**13 pass, 2 discrepancies, 1 minor discrepancy**

### Discrepancies to address:

1. **Search response fields (#3):** Add explicit search response field listing to the skill (matching spec: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, `interactions`).

2. **Path resolution (#12):** Add a note about path resolution behavior — local file paths are auto-resolved when connected via STDIO proxy, but HTTP MCP / REST API callers need to use the upload endpoint or bind mounts.

3. **Supported formats (#15):** Add "JPEG" to the image format list alongside JPG (cosmetic fix).
