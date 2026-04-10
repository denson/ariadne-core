# Ariadne Core — Implementation Instructions for Claude Code

This document tells you exactly what to build, in what order, and how to verify each step. Read these files before starting:

1. **`SPEC.md`** — how the tool should behave. Source of truth.
2. **`FIXES.md`** — every gap between the spec and the current code, with target state, current state, what to change, and how to test.
3. **`skills/ariadne-document-intelligence/SKILL.md`** — the canonical skill describing target behavior as working reality. This is your acceptance test. After you finish, an agent following this skill should be able to use every feature it describes.

Do not modify `SPEC.md` or `skills/ariadne-document-intelligence/SKILL.md`. They define the target. You change the code to match them.

---

## Ground rules

- Read the full "What to change" and "How to test" sections in `FIXES.md` for each item before writing code.
- Run existing tests (`pytest tests/`) before and after each fix to make sure you don't break anything.
- Each fix should be a separate commit with a message referencing the fix number (e.g., `fix(#3): add image warning when no vision API key`).
- No local GPU dependencies, no additional extraction engines, no PyTorch in the container. Model inference is via API calls or an open model on a local GPU.
- All new dependencies must be Apache 2.0 or MIT licensed.
- No credentials or secrets in any file. Use `${VAR}` interpolation and `.env`.

---

## Phase 1: Independent fixes (do in parallel or any order)

### Task A: Dockerfile — add ffmpeg (FIXES.md #2)

**Files to change:** `src/Dockerfile`

1. Add `ffmpeg` to the `apt-get install` line alongside `libmagic1` and `poppler-utils`.
2. If audio test fixtures don't exist in `tests/fixtures/`, create minimal WAV and MP3 files for testing. A 1-second sine wave is fine.
3. Add a test in `tests/test_extraction.py` that processes a WAV file and asserts non-empty Markdown output.

**Validate:**
```bash
# Build and verify ffprobe is available
docker build -t ariadne-test -f src/Dockerfile src/
docker run --rm ariadne-test which ffprobe
# Should print a path like /usr/bin/ffprobe

# Run extraction tests
pytest tests/test_extraction.py -v -k audio
```

---

### Task B: Image warning when no vision API (FIXES.md #3)

**Files to change:** `src/pipeline/extraction/markitdown.py`

1. In the extraction method, after MarkItDown returns a result, check: if `file_type` is in `{"jpg", "jpeg", "png", "gif"}` AND the Markdown output is empty or under 20 characters, append this warning to `result.warnings`:
   ```
   Image files require a vision API key (VISION_API_KEY) for content extraction. Without it, images are accepted but produce empty output.
   ```
2. Do not raise an error — this is a warning. The extraction "succeeded," it just produced nothing useful. The document should still be stored if `store=true`.

**Validate:**
```bash
# Create a test image if none exists
python -c "
from PIL import Image
img = Image.new('RGB', (100, 100), color='red')
img.save('tests/fixtures/test_image.jpg')
"

# Run the MCP server in test mode and call convert_document on the image
# with no VISION_API_KEY set. Assert:
# - response contains 'warnings' array with vision API message
# - response['was_dedup_skip'] is false
# - response['store_status'] is 'stored' (if store=true)
# - response['markdown'] is empty or trivially short

pytest tests/ -v -k image
```

Write a test in `tests/test_extraction.py` or `tests/test_pipeline.py` that:
- Extracts a JPG with no vision config and asserts the warning is present
- Extracts a PNG and asserts the same warning
- Confirms `store_status` is `"stored"` when `store=true`

---

### Task C: Search filters — source_file, file_type, tags (FIXES.md #4)

**Files to change:** `src/pipeline/storage/base.py`, `src/pipeline/storage/pgvector.py`, and potentially `src/pipeline/mcp_server.py` (for in-memory post-filtering)

#### PgVectorStore (pgvector.py)

In the `search()` method, the WHERE clause builder currently handles `collection` and `document_id`. Add:

```python
if "source_file" in filters:
    where_clauses.append(
        "d.source_file ILIKE '%%' || %(filter_source)s || '%%'"
    )
    params["filter_source"] = filters["source_file"]

if "file_type" in filters:
    where_clauses.append("d.file_type = %(filter_file_type)s")
    params["filter_file_type"] = filters["file_type"].lstrip(".")

if "tags" in filters:
    where_clauses.append("d.tags && %(filter_tags)s::text[]")
    params["filter_tags"] = filters["tags"]
```

This requires joining the `documents` table. Update the FROM clause to include:
```sql
JOIN documents d ON c.document_id = d.id
```

Make sure the join doesn't break the existing `collection` and `document_id` filters.

#### InMemoryVectorStore (base.py)

The in-memory store's chunks don't carry `source_file`, `file_type`, or `tags`. Two options:

**Option A (preferred):** Post-filter in `mcp_server.py` after search returns. After getting results from `_vector_store.search()`, filter out results whose source document (looked up via `_dedup_store` or `_find_document_by_id`) doesn't match the `source_file`, `file_type`, or `tags` filters.

**Option B:** Pass a document lookup function to the in-memory store. More invasive but cleaner long-term.

Choose whichever is simpler. The in-memory store is for testing; Postgres is production.

**Validate:**

Write tests in `tests/test_search_filters.py` (new file):

```python
# Setup: ingest 3 documents with distinct characteristics
# - report.pdf in "research", tags=["quarterly", "finance"]
# - slides.pptx in "research", tags=["quarterly", "presentations"]
# - notes.txt in "daily", tags=["meeting"]

def test_filter_source_file():
    # search with filters={"source_file": "report"}
    # assert only chunks from report.pdf

def test_filter_file_type():
    # search with filters={"file_type": "pptx"}
    # assert only chunks from slides.pptx

def test_filter_tags_single():
    # search with filters={"tags": ["finance"]}
    # assert only chunks from report.pdf

def test_filter_tags_or_logic():
    # search with filters={"tags": ["quarterly"]}
    # assert chunks from BOTH report.pdf and slides.pptx

def test_filter_combined_and():
    # search with filters={"file_type": "pdf", "tags": ["quarterly"]}
    # assert only report.pdf (AND across filter keys)

def test_filter_unknown_key_ignored():
    # search with filters={"nonexistent_key": "value"}
    # assert normal results returned, no error
```

```bash
pytest tests/test_search_filters.py -v
```

---

## Phase 2: New tools (after Phase 1, since filters should work first)

### Task D: `ingest` MCP tool (FIXES.md #5)

**Files to change:** `src/pipeline/mcp_server.py`, `src/pipeline/api/routes.py`, `src/pipeline/mcp_stdio_proxy.py`

#### mcp_server.py

Add a new `@app.tool()` function `ingest` with these parameters:

| Parameter | Type | Default | Required |
|-----------|------|---------|----------|
| `path` | str | — | yes |
| `collection` | str | `"default"` | no |
| `recursive` | bool | `True` | no |
| `file_types` | list[str] | `None` | no |
| `force` | bool | `False` | no |
| `tags` | list[str] | `[]` | no |
| `agent_id` | str | `None` | no |
| `agent_type` | str | `None` | no |
| `model` | str | `None` | no |
| `initiated_by` | str | `None` | no |
| `agent_notes` | str | `None` | no |
| `agent_metadata` | dict | `None` | no |

Implementation:

1. Get the list of supported extensions from the extractor (or hardcode the known list from SPEC.md: `pdf, docx, pptx, xlsx, xls, csv, tsv, html, htm, txt, md, json, xml, rtf, epub, eml, msg, zip, ipynb, rst, org, wav, mp3, m4a, jpg, jpeg, png, gif`).
2. Walk the directory (`os.walk` if recursive, `os.listdir` if not). Collect files whose extension (lowercase, no dot) is in the supported set.
3. If `file_types` is provided, further filter to only those extensions.
4. For each file, call the same pipeline logic used by `convert_document` — extract, fingerprint, dedup, chunk, embed, store, record interaction. Reuse the existing code, don't duplicate it. Consider extracting a shared helper function from `convert_document` that both tools call.
5. Track counts: `files_found`, `files_processed`, `files_skipped`, `files_errored`.
6. Build a `results` array with per-file entries: `document_id`, `source_file`, `was_dedup_skip`, `error` (null if success).
7. Return JSON with the counts and results.

Catch exceptions per-file so one corrupt file doesn't abort the whole batch.

The docstring should say:
```
Batch-ingest a directory of documents. Processes all supported files and returns a summary.
```

#### routes.py

Add `POST /api/ingest` endpoint that accepts the same parameters as the MCP tool (as a JSON body) and returns the same response shape. Follow the same pattern as `POST /api/documents`.

#### mcp_stdio_proxy.py

Add an `ingest` tool that POSTs to `http://localhost:8000/api/ingest` with the parameters and returns the response. Follow the same pattern as the existing `convert_document` proxy.

**Validate:**

Write tests in `tests/test_ingest.py` (new file):

```python
def test_ingest_basic():
    # Create temp dir with 5 test files (2 PDF, 2 DOCX, 1 TXT)
    # Call ingest
    # Assert files_found == 5, files_processed == 5, files_skipped == 0
    # Verify all 5 appear in list_documents

def test_ingest_dedup():
    # Ingest same dir again
    # Assert files_found == 5, files_processed == 0, files_skipped == 5

def test_ingest_file_type_filter():
    # Call with file_types=["pdf"]
    # Assert files_found == 2

def test_ingest_force():
    # Call with force=true after initial ingest
    # Assert files_processed == 5

def test_ingest_non_recursive():
    # Put a file in a subdirectory
    # Call with recursive=false
    # Assert the subdir file is not found

def test_ingest_corrupt_file():
    # Include a corrupt/zero-byte file
    # Assert files_errored == 1, others still processed

def test_ingest_caller_metadata():
    # Call with full caller metadata
    # Check document_interactions for each processed file
```

```bash
pytest tests/test_ingest.py -v
```

---

### Task E: `list_collections` MCP tool (FIXES.md #6)

**Files to change:** `src/pipeline/mcp_server.py`, `src/pipeline/api/routes.py`, `src/pipeline/mcp_stdio_proxy.py`

#### mcp_server.py

Add a new `@app.tool()` function `list_collections` with no parameters. Returns:

```json
{
  "collections": [
    {"name": "default", "description": "...", "document_count": 12},
    {"name": "research", "description": "...", "document_count": 5}
  ]
}
```

To get `document_count`, count documents in the dedup store grouped by collection. For `InMemoryDedupStore`, iterate `_documents` and count per `collection_id`. For `PgDedupStore`, run a SQL query grouping by `collection_id`.

The docstring should say:
```
List all collections with document counts.
```

#### routes.py

Update `GET /api/collections` to include `document_count` in each collection entry. Currently it only returns `name` and `description`.

#### mcp_stdio_proxy.py

Add a `list_collections` tool that GETs `http://localhost:8000/api/collections` and returns the response.

**Validate:**

```python
def test_list_collections_with_documents():
    # Create "research" and "daily" collections, ingest docs into each
    # Call list_collections
    # Assert both appear with correct document_count

def test_list_collections_empty():
    # Fresh state, call list_collections
    # Assert returns empty array or just "default"

def test_list_collections_rest_endpoint():
    # Hit GET /api/collections directly
    # Assert document_count is present in response
```

```bash
pytest tests/ -v -k list_collections
```

---

## Phase 3: String and doc cleanup (after Phase 2)

### Task F: Format count strings (FIXES.md #7)

**Files to change:** See the table in FIXES.md #7

Replace every instance of `"25+"` with `"over 20"` in these files:
- `src/pipeline/mcp_server.py` (instructions block line 36, docstring line 113)
- `src/pipeline/mcp_stdio_proxy.py` (docstring line 70)
- `src/pipeline/api/app.py` (FastAPI description line 71)

Delete the old skill directory:
```bash
rm -rf skills/ariadne-core-integration/
```

**Validate:**
```bash
# Should return zero results
grep -r "25+" src/ --include="*.py"

# Should not exist
ls skills/ariadne-core-integration/
# Expected: No such file or directory
```

---

### Task G: MCP server instructions block (FIXES.md #8)

**Files to change:** `src/pipeline/mcp_server.py`, `src/pipeline/mcp_stdio_proxy.py`

Rewrite the `instructions` string in the `FastMCP()` constructor in `mcp_server.py`. The new instructions should:

1. Say "over 20 supported formats" (not "25+")
2. List all six tools with brief descriptions:
   - `convert_document` — single file extraction + storage
   - `search` — semantic search with filters
   - `get_document` — full document by ID
   - `list_documents` — browse by collection/type
   - `list_collections` — see what collections exist (call before choosing one)
   - `ingest` — batch directory processing
3. Tell agents to use `ingest` for batch/directory operations
4. Tell agents to call `list_collections` before choosing a collection
5. Remove the line telling agents to use the REST API for batch operations
6. Keep the existing guidance about: always using `store=true`, passing caller metadata, dedup being automatic

If `mcp_stdio_proxy.py` has a similar instructions block, update it the same way.

**Validate:**

Read the instructions block and verify it mentions all six tools and doesn't say "25+" or reference the REST API for batch operations.

```bash
python -c "
from pipeline.mcp_server import app
print(app.settings.instructions)
" | grep -c "ingest\|list_collections\|convert_document\|search\|get_document\|list_documents"
# Should print 6 (one match per tool name)
```

---

## Phase 4: Final validation

After all tasks are complete, run the full validation:

### 1. Full test suite
```bash
pytest tests/ -v
```
All tests should pass, including the new ones you wrote.

### 2. Skill-based acceptance test

Read `skills/ariadne-document-intelligence/SKILL.md`. Walk through each process it describes and verify the tool supports it:

**Ingesting a document (skill section "Process: Ingesting a document"):**
```python
# Call list_collections — should return without error
# Call convert_document with a PDF, collection="test-validation",
#   tags=["validation"], all caller metadata populated
# Response should have: document_id, markdown (non-empty),
#   chunks_count, was_dedup_skip=false, store_status="stored",
#   warnings (array, possibly empty), provenance with processing_chain
# Call convert_document again with same file — should get was_dedup_skip=true
# Call convert_document with force=true — should re-process
```

**Batch ingesting (skill section "Process: Batch ingesting a directory"):**
```python
# Call ingest with path=tests/fixtures/, collection="test-batch"
# Response should have: files_found > 0, files_processed,
#   files_skipped, files_errored, results array
```

**Searching (skill section "Process: Searching documents"):**
```python
# Call search with a query relevant to the ingested test docs
# Response should have: results array with chunk text,
#   relevance_score, interactions array
# Test each filter type:
#   filters={"source_file": "partial-name"}
#   filters={"file_type": "pdf"}
#   filters={"tags": ["validation"]}
```

**Browsing (skill section "Process: Browsing the store"):**
```python
# Call list_collections — should show "test-validation" and "test-batch"
#   with document_count > 0
# Call list_documents with collection="test-validation"
# Call get_document with a document_id from the list
```

**Image warning (skill section on error handling):**
```python
# Call convert_document with a JPG, no vision API key
# Response should contain warning about VISION_API_KEY in warnings array
```

### 3. String audit
```bash
# No "25+" in source code
grep -rn "25+" src/ --include="*.py"
# Should return nothing

# Old skill directory deleted
test -d skills/ariadne-core-integration && echo "FAIL: old skill dir still exists" || echo "PASS"

# All six tools exist in MCP server
python -c "
from pipeline.mcp_server import app
tools = [t.name for t in app._tools.values()]
expected = {'convert_document', 'search', 'get_document', 'list_documents', 'list_collections', 'ingest'}
missing = expected - set(tools)
if missing:
    print(f'FAIL: missing tools: {missing}')
else:
    print(f'PASS: all 6 tools registered: {sorted(expected)}')
"
```

### 4. Commit
After all validation passes, commit all changes with a summary message referencing which FIXES.md items were implemented.
