# Ariadne Core — Code & Doc Fixes

Gap tracker between how we want the tool to work (SPEC.md is the source of truth) and how the code works today. Each section is an instruction for Claude Code: target state, current state, what to change, and how to test it.

The canonical skill at `skills/ariadne-document-intelligence/SKILL.md` describes the target behavior as if it already works. After all fixes are implemented, an agent following the skill should be able to use every feature it describes without error.

---

## 1. Config: env vars for model and base_url

**Target state:** All API configuration (keys, models, base URLs) is controlled from `.env`. The `ariadne.yaml` config file interpolates `${EMBEDDING_MODEL}`, `${EMBEDDING_BASE_URL}`, `${VISION_MODEL}`, `${VISION_BASE_URL}` from env vars so users set everything in one place.

**Current state:** ✅ Fixed. `ariadne.yaml` now uses `${VAR}` interpolation for all six values. `.env.example` updated to match.

**What was changed:**
- `config/ariadne.yaml`: replaced hardcoded `text-embedding-3-small`, `gpt-4o-mini`, and `https://api.openai.com/v1` with `${EMBEDDING_MODEL}`, `${VISION_MODEL}`, `${EMBEDDING_BASE_URL}`, `${VISION_BASE_URL}`
- `.env.example`: added `VISION_MODEL`, `VISION_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL` with sensible defaults

**How to test:**
- Set custom values in `.env` (e.g., a different model name). Start the stack. Call `/api/health` and verify `embedding_enabled` reflects the config. Ingest a document and check that the `processing_chain` shows the correct model name.
- Test that missing env vars cause a clear error on startup, not a silent `${VAR}` literal in the config.

---

## 2. Add ffmpeg to Docker image (audio support)

**Target state:** Audio files (WAV, MP3, M4A) are supported formats. MarkItDown's AudioConverter works out of the box in Docker.

**Current state:** The Dockerfile (`src/Dockerfile`) only installs `libmagic1` and `poppler-utils`. MarkItDown's AudioConverter calls `ffprobe` (from the ffmpeg package) and fails with `FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe'`. Eval confirmed WAV fails.

**What to change:**
- Add `ffmpeg` to the `apt-get install` line in `src/Dockerfile`
- Re-run the eval harness against audio test files to confirm they process

**How to test:**
- Build the Docker image and run: `docker exec ariadne-core-api-1 which ffprobe` — should return a path
- Submit a WAV file via `convert_document` and verify it returns non-empty Markdown
- Submit an MP3 file the same way
- Add audio files to `tests/fixtures/` if none exist and add a test to `test_extraction.py` that processes them

---

## 3. Standalone image handling without vision API

**Target state:** Images (JPG, PNG, GIF, JPEG) are listed as "supported (requires vision API key)". When someone sends an image and no vision key is configured, the tool returns a clear warning explaining what's needed — not empty Markdown with no explanation.

**Current state:** MarkItDown accepts image files and returns empty Markdown silently. No error, no warning, no indication that anything went wrong. The caller gets back a document with zero useful content.

**What to change:**
- In the extraction wrapper (`src/pipeline/extraction/markitdown.py`), after extraction, check: if the file type is an image format (`jpg`, `jpeg`, `png`, `gif`) AND the extracted Markdown is empty or trivially short (< 20 characters), add a warning to the result: `"Image files require a vision API key (VISION_API_KEY) for content extraction. Without it, images are accepted but produce empty output."`
- In `mcp_server.py` `convert_document`, if the result has this warning and `store=true`, still store the document (so it exists in the system) but include the warning prominently in the response
- The warning should appear in the `warnings` array of the response, not as an error — the extraction technically succeeded, it just produced nothing useful

**How to test:**
- With no VISION_API_KEY set: submit a JPG via `convert_document`. Assert the response contains a warning about needing a vision API key. Assert the Markdown is empty or minimal. Assert `store_status` is still `"stored"` if `store=true`.
- With VISION_API_KEY set: submit the same JPG. Assert the response has non-empty Markdown and no vision-related warning.
- Test with PNG, GIF, JPEG extensions too.

---

## 4. Search filters: `source_file`, `file_type`, `tags`

**Target state:** The `search` tool's `filters` parameter supports `collection` (already works), `document_id` (already works), `source_file` (substring match, case-insensitive), `file_type` (exact match, no leading dot), and `tags` (array overlap / OR logic). Unknown filter keys are silently ignored.

**Current state:** Only `collection` and `document_id` are implemented in both `InMemoryVectorStore._apply_filters()` (`storage/base.py`) and `PgVectorStore.search()` (`storage/pgvector.py`). The `source_file`, `file_type`, and `tags` filter keys are silently ignored.

**What to change:**

In `storage/base.py` `_apply_filters()`:
- `source_file`: the in-memory store doesn't have direct access to the document metadata from chunks. Post-filter at the search call site in `mcp_server.py` is acceptable — after getting results back, filter out chunks whose source document doesn't substring-match (case-insensitive). Alternatively, pass a document lookup function to the store.
- `file_type`: same approach — look up the source document's file type from the dedup store
- `tags`: same — look up the source document's tags, keep chunk if any tag matches any filter tag (OR logic)

In `storage/pgvector.py` `search()`:
- `source_file`: add WHERE clause joining chunks → documents table, using `d.source_file ILIKE '%' || %(filter_source)s || '%'` for case-insensitive substring match
- `file_type`: add WHERE clause `d.file_type = %(filter_file_type)s` (exact match, without leading dot)
- `tags`: add WHERE clause `d.tags && %(filter_tags)s::text[]` for PostgreSQL array overlap

In `mcp_server.py` and `mcp_stdio_proxy.py`: no changes needed — they already pass the `filters` dict through to the store.

**How to test:**

Setup: ingest three documents with distinct characteristics:
- `report.pdf` in collection `"research"`, tags `["quarterly", "finance"]`
- `slides.pptx` in collection `"research"`, tags `["quarterly", "presentations"]`
- `notes.txt` in collection `"daily"`, tags `["meeting"]`

Tests:
1. `filters: {"source_file": "report"}` → only chunks from `report.pdf`
2. `filters: {"file_type": "pptx"}` → only chunks from `slides.pptx`
3. `filters: {"tags": ["finance"]}` → only chunks from `report.pdf`
4. `filters: {"tags": ["quarterly"]}` → chunks from both `report.pdf` and `slides.pptx` (OR logic)
5. `filters: {"file_type": "pdf", "tags": ["quarterly"]}` → only `report.pdf` (AND across filter keys)
6. `filters: {"nonexistent_key": "value"}` → silently ignored, normal results returned
7. Run all tests against both `InMemoryVectorStore` and `PgVectorStore`

---

## 5. `ingest` MCP tool (batch directory processing)

**Target state:** An `ingest` tool exists in the MCP server, STDIO proxy, and REST API. Accepts a directory path, processes all supported files sequentially, returns a summary. Processing is synchronous — returns the full result when done.

**Current state:** Does not exist anywhere — not as MCP tool, not as REST endpoint.

**What to change:**

Add `ingest` tool to `mcp_server.py`:

Parameters:
- `path` (required): directory path to scan
- `collection` (default `"default"`): collection for all documents
- `recursive` (default `true`): recurse subdirectories
- `file_types` (default `null`): filter to specific extensions, e.g. `["pdf", "docx"]`
- `force` (default `false`): dedup override
- `tags` (default `[]`): applied to all documents
- All 6 caller metadata fields (`agent_id`, `agent_type`, `model`, `initiated_by`, `agent_notes`, `agent_metadata`)

Behavior:
1. Scan directory for files matching supported extensions (use the same extension list the extractor supports)
2. If `file_types` specified, filter to only those
3. Process each file through the same pipeline as `convert_document` (extract → fingerprint → dedup check → chunk → embed → store → record interaction)
4. Return JSON with: `files_found`, `files_processed`, `files_skipped` (dedup), `files_errored`, and `results` array with per-file status (`document_id`, `source_file`, `was_dedup_skip`, `error` message if any)

Processing is synchronous. For large directories this may take minutes. Returns the full summary when done. No async job_id, no polling.

Add matching REST endpoint `POST /api/ingest` in `routes.py` with the same parameters and response shape.

Add proxy version to `mcp_stdio_proxy.py` that calls the REST endpoint.

**How to test:**
1. Create temp dir with 5 test files (2 PDF, 2 DOCX, 1 TXT). Call `ingest`. Assert: `files_found == 5`, `files_processed == 5`, `files_skipped == 0`. Verify all 5 in `list_documents`.
2. Call `ingest` again same dir. Assert: `files_found == 5`, `files_processed == 0`, `files_skipped == 5`. Verify interactions count increased.
3. Call with `file_types: ["pdf"]`. Assert: `files_found == 2`.
4. Call with `force: true`. Assert: `files_processed == 5` (all re-processed).
5. Call with `recursive: false`, file in subdir. Assert subdir file not found.
6. Include a corrupt file. Assert: `files_errored == 1`, others still processed.
7. Test REST endpoint `POST /api/ingest` with same scenarios.
8. Test STDIO proxy delegates to REST correctly (mock in unit tests).

---

## 6. `list_collections` MCP tool

**Target state:** A `list_collections` MCP tool exists so agents can discover what collections are available before choosing one for ingestion or scoping a search. Returns collection name, description, and document count.

**Current state:** `GET /api/collections` exists as a REST endpoint (in `routes.py`), but there is no MCP tool for it. The REST endpoint only returns `name` and `description` — no `document_count`. Agents connected via MCP have no way to see what collections exist.

**What to change:**

Add `list_collections` tool to `mcp_server.py`:
- No parameters
- Returns JSON with: `collections` array, each with `name`, `description`, `document_count`
- For `document_count`: count documents in the dedup store grouped by `collection_id`

Add matching proxy version to `mcp_stdio_proxy.py` that calls `GET /api/collections`.

Update the REST endpoint `GET /api/collections` (in `routes.py`) to also return `document_count` per collection. Count from the dedup store or documents table.

**How to test:**
1. Create two collections, ingest documents into each. Call `list_collections`. Assert both collections appear with correct document counts.
2. Call `list_collections` with no collections created. Assert it returns at least the `"default"` collection (or empty array if none created yet — match the behavior of the REST endpoint).
3. Test via MCP (`mcp_server.py`) and STDIO proxy (`mcp_stdio_proxy.py`).
4. Test that the REST endpoint also returns `document_count`.

---

## 7. Format count and listing across all docs

**Target state:** All docs and code say "over 20 formats" — not "25+". Image formats noted as requiring vision API key. Audio listed as supported (after ffmpeg fix in #2).

**Current state:** Multiple files say "25+ formats" or list formats imprecisely.

**Files to update:**

| File | What to change |
|------|----------------|
| `mcp_server.py` line 36 (instructions block) | Change `"any of 25+ supported formats"` → `"over 20 supported formats"` |
| `mcp_server.py` line 113 (convert_document docstring) | Change `"Supports 25+ formats: PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, images, and more."` → `"Supports over 20 formats including PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, and more."` |
| `mcp_stdio_proxy.py` line 70 (convert_document docstring) | Same change as mcp_server.py |
| `api/app.py` line 71 (FastAPI description) | Change `"25+ formats"` → `"over 20 formats"` |
| `skills/ariadne-core-integration/` | Delete this entire directory (replaced by `skills/ariadne-document-intelligence/`) |

**Do NOT change:** `docs/docint-architecture.md` — it's the architecture vision doc. Leave as-is.

---

## 8. MCP server instructions block update

**Target state:** The `instructions` string in the `FastMCP()` constructor reflects all seven tools and correct format count. It should mention `ingest` and `list_collections` and stop telling agents to use the REST API for batch operations.

**Current state:** The instructions block in `mcp_server.py` lines 29-73:
- Says "25+ supported formats" (should be "over 20")
- Tells agents "For large batch operations, suggest the user use the REST API's ingest endpoint or the CLI" — this is wrong once the `ingest` MCP tool exists
- Does not mention `list_collections` or `ingest` tools

**What to change:**

Rewrite the `instructions` parameter of `FastMCP()` in `mcp_server.py`. The updated instructions should:
- Say "over 20 supported formats"
- Mention all seven tools: `convert_document`, `upload_and_convert`, `search`, `get_document`, `list_documents`, `list_collections`, `ingest`
- Tell agents to use `ingest` for batch/directory operations (not the REST API)
- Tell agents to call `list_collections` before choosing a collection
- Remove the line about suggesting the REST API for batch operations

Similarly update the instructions block in `mcp_stdio_proxy.py` if it has one.

**How to test:**
- Start the MCP server. Connect a client. Verify the instructions block appears in the server capabilities and mentions all seven tools.
- Manually review the text for accuracy against SPEC.md.

---

## 9. Merge skills — delete old `ariadne-core-integration` directory

**Target state:** One skill package at `skills/ariadne-document-intelligence/` inside the ariadne-core repo. The old `skills/ariadne-core-integration/` directory is deleted. The OB1 repo's copy (`OB1/skills/ariadne-document-intelligence/`) is replaced with a pointer to the ariadne-core repo as the canonical source.

**Current state:** Two skill directories exist in the ariadne-core repo:
- `skills/ariadne-document-intelligence/` (v2.0.0) — the new canonical skill ✅ already updated
- `skills/ariadne-core-integration/` (v0.1.0) — the old one, should be deleted

The OB1 repo at `OB1/skills/ariadne-document-intelligence/` has a v1.1.0 copy that describes async job_id behavior, filters that don't exist, and an `output_dir` parameter that was never built.

**What to change:**
- Delete `skills/ariadne-core-integration/` entirely from the ariadne-core repo
- In the OB1 repo: replace `skills/ariadne-document-intelligence/SKILL.md` with a pointer noting the canonical source is in the ariadne-core repo, and copy the current v2.0.0 SKILL.md content
- Update `skills/ariadne-document-intelligence/README.md` and `metadata.json` in OB1 to match

**This depends on:** fixes #4, #5, and #6 being done first (so the skill describes features that actually work).

---

## 10. Scope language: "personal use" not "personal/SMB"

**Target state:** All user-facing docs say "personal use." The architecture doc can keep aspirational Team Edition language since it's the vision doc.

**Current state:** ✅ Already fixed. README.md says "personal use."

---

## Order of operations

1. **Config env vars** (#1) — ✅ already fixed
2. **Dockerfile fix** (#2) — unblocks audio format support
3. **Image warning** (#3) — small code change in extraction wrapper, no dependencies
4. **Search filters** (#4) — code change in both storage backends
5. **`ingest` tool** (#5) — new feature, MCP + REST + proxy. Depends on the pipeline already working (it does)
6. **`list_collections` tool** (#6) — new MCP tool + REST endpoint update
7. **Format/count string updates** (#7) — doc/code string changes, depends on #2 being done
8. **MCP instructions block** (#8) — depends on #5 and #6 existing
9. **Merge skills / delete old directory** (#9) — depends on #4, #5, #6 being done
10. **Scope language** (#10) — ✅ already done

Fixes #2, #3, and #4 can be done in parallel. Fix #5 and #6 can be done in parallel after #4. Fix #7 and #8 come after #5 and #6. Fix #9 is last.
