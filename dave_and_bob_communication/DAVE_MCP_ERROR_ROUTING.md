# Task: Smart error routing in the MCP `ingest` tool

**For:** Dave
**Phase:** 1, Step 2 (do this AFTER Step 1 is committed)
**File to edit:** `src/pipeline/mcp_server.py`

Read `PHASE1_OVERVIEW.md` first for context.

**IMPORTANT:** Before starting, read the COMMITTED version of `skills/ariadne-document-intelligence/SKILL.md` — Step 1 updated the routing decision tree. The error messages you write here must echo what the skill says. The skill is the specification; this code is the enforcement.

---

## Why

The MCP `ingest` tool is the last line of defense. When the skill didn't load, when the agent didn't read it, when it hallucinated an MCP way of uploading — the error response from `ingest` is the one thing guaranteed to be in the agent's context because it just called the tool and got a response back.

The current error message (around line 666-679) tells agents to "upload each file via POST /api/upload first, then call convert_document with the returned server-side path." This is wrong for two reasons:
1. For bulk ingestion, it's a multi-step loop through LLM context — exactly the waste Ariadne exists to prevent
2. It doesn't distinguish single file vs directory — the two cases need different tools

## What to change

### 1. Detect single file vs directory from the path string

When the path doesn't exist on the server (`not dir_path.is_dir()`), check whether the path string looks like a single file or a directory. Heuristic: if the path has a recognized file extension (`.pdf`, `.txt`, `.docx`, etc.), treat it as a single file. Otherwise, treat it as a directory.

Use the `SUPPORTED_EXTENSIONS` set that's already defined in the file for this check.

### 2. Return different error messages per case

**Single file path** (has a file extension in SUPPORTED_EXTENSIONS):

```python
return json.dumps({
    "error": True,
    "message": (
        f"Path not found on server: {path}\n\n"
        "This looks like a single file. The ingest tool only works "
        "with server-side directories.\n\n"
        "For a single local file, use convert_document:\n\n"
        "1. Upload via REST:\n"
        "   curl -s -X POST $ARIADNE_URL/api/upload \\\n"
        f'     -H "X-API-Key:$ARIADNE_API_KEY" \\\n'
        f'     -F "file=@{path}"\n'
        '2. Read the "path" field from the JSON response.\n'
        "3. Call the convert_document MCP tool with that server-side "
        f'path as the uri parameter, collection="{collection}".\n\n'
        "The upload sends bytes directly over HTTP -- they never "
        "pass through your context window."
    ),
}, indent=2)
```

**Directory path** (no recognized file extension):

```python
return json.dumps({
    "error": True,
    "message": (
        f"Path not found on server: {path}\n\n"
        "This looks like a local directory. The ingest tool only "
        "works with server-side directories.\n\n"
        "For a local directory, use the bulk_ingest CLI script:\n\n"
        f'  python ariadne-core/scripts/bulk_ingest.py "{path}" \\\n'
        f"    --collection {collection} --dry-run\n\n"
        "Remove --dry-run after confirming the file list looks right.\n"
        "The script uploads files directly via REST -- file bytes "
        "never pass through your context window."
    ),
}, indent=2)
```

### 3. Update the tool docstring

Add a note at the top of the `ingest` function's docstring:

```
This tool processes directories already on the server. For local files
on the agent's machine, the tool returns specific routing instructions
when the path is not found.
```

Keep the rest of the existing docstring (Args, Returns).

## What NOT to change

- The `convert_document` tool (don't touch it)
- The happy path of `ingest` (when the path IS found on the server)
- Any other MCP tools
- The REST API routes
- Anything outside `mcp_server.py`

## Acceptance criteria

1. Calling `ingest` with a path like `C:\docs\report.pdf` returns the single-file instructions with the actual path and collection echoed back
2. Calling `ingest` with a path like `C:\docs\reports` returns the directory/bulk instructions with the actual path and collection echoed back
3. The happy path (server-side directory exists) is unchanged
4. The error messages match what the skill says (read the skill to verify)
5. The docstring mentions that the tool is for server-side directories

## Compile / test check

```bash
cd ariadne-core
pip install -e src/ 2>&1 | tail -5   # should install clean
python -c "from pipeline.mcp_server import app; print('import ok')"
```

## Do not commit

Leave all changes for Bob. Write your completion report to `DAVE_DONE.md`.

---

## Review summary for Bob

**What changed:** The MCP `ingest` tool's error handler now detects whether the failed path looks like a single file or a directory and returns different, self-contained instructions for each case. The docstring was updated to note the tool is for server-side directories.

**Why:** This is the safety net for when agents don't read the skill. The error response is guaranteed to be in context (the agent just called the tool), so it must contain complete, actionable instructions — not "go read the docs."

**What to verify:**
- The single-file error message includes the upload curl command and convert_document instructions
- The directory error message includes the bulk_ingest.py command
- Both messages echo back the actual path and collection the agent provided
- The happy path (server-side directory exists) is untouched
- The error messages are consistent with what the skill says (read the committed Step 1 skill)
- No other tools were modified
- Import check passes
