# Fix: MCP `ingest` tool routes agents to bulk_ingest.py CLI

## The problem

The MCP `ingest` tool has two places where it tells agents the wrong thing:

1. **Docstring** (`mcp_server.py` line ~647) — describes the tool as a generic "batch-ingest a directory" without mentioning that it only works for server-side paths. Agents with local files read it, try it, fail, then either debug on their own or loop individual MCP calls over each file. Both wrong.

2. **Error message when path doesn't exist on server** (line ~671-676) — points at the OLD manual upload pattern: "upload each file via POST /api/upload first, then call convert_document with the returned server-side path." That's exactly the pattern that burns LLM context on every file, which is what we built `bulk_ingest.py` to prevent.

**Observed failure (2026-04-14):** A fresh agent in the REE project tried to ingest 574 local files. It read the MCP ingest docstring, tried to use the tool, got the error message, and followed its suggestion — uploading files one at a time via MCP `request_upload_url` + `convert_document`. This is the exact anti-pattern the skill documentation tries to prevent, but the MCP tool itself actively misdirects agents.

## What to do

**File:** `ariadne-core/src/pipeline/mcp_server.py`

### Change 1: Update the `ingest` tool docstring

Add a clear block at the top explaining when NOT to use this tool. Place it as the first paragraph of the docstring so agents read it before the parameter list.

Current:

```python
"""Batch-ingest a directory of documents. Processes all supported files and returns a summary.

Args:
    path: Directory path to scan for documents.
    ...
```

Change to:

```python
"""Batch-ingest a directory of documents on the SERVER side.

IMPORTANT: This tool only works when `path` is a directory on the Ariadne
server itself, not on the calling agent's local machine. If you have local
files to ingest, use the `bulk_ingest.py` CLI script from the ariadne-core
repo instead — it uploads via REST and never burns LLM context on file
content. See the doc-intelligence skill for the full pattern.

Use this tool only when:
- The files are already on the server (e.g., via a persistent volume mount,
  or a previous upload batch), OR
- An admin is scripting against the MCP interface with server access.

For local files on the agent's machine, use:
    python ariadne-core/scripts/bulk_ingest.py <local-dir> --collection <name>

Args:
    path: Directory path to scan for documents. MUST be a path the server
          can see — NOT a local path on the agent's machine.
    ...
```

Keep the rest of the parameter list as is. Just prepend this block.

### Change 2: Update the error message when path is not a directory

Current (line ~671-676):

```python
if not dir_path.is_dir():
    return json.dumps(
        {
            "error": True,
            "message": (
                f"Path not found on server: {path}. "
                "The ingest tool only works with server-side directories. "
                "For local files, upload each file via POST /api/upload first, "
                "then call convert_document with the returned server-side path."
            ),
        },
        indent=2,
    )
```

Change to:

```python
if not dir_path.is_dir():
    return json.dumps(
        {
            "error": True,
            "message": (
                f"Path not found on server: {path}. The `ingest` MCP tool "
                "only works with server-side directories. For local files "
                "on the agent's machine, use the `bulk_ingest.py` CLI "
                "script from the ariadne-core repo:\n\n"
                "    python ariadne-core/scripts/bulk_ingest.py <local-dir> "
                "--collection <name>\n\n"
                "The script uploads files via REST directly, so file bytes "
                "never pass through the LLM context. See the "
                "doc-intelligence skill for the full pattern, including "
                "pre-flight checks to clone or refresh the ariadne-core "
                "repo as a sibling directory of your project."
            ),
        },
        indent=2,
    )
```

## Why both changes matter

- The docstring is what the agent sees when it inspects the tool schema at connection time. Most agents read it once and commit to using the tool based on that description. Fixing only the error message is too late — by then the agent has already tried and failed.
- The error message is the fallback for when an agent doesn't read the docstring carefully or encounters the tool through discovery rather than inspection.

Both need to point at `bulk_ingest.py`.

## Do not touch

- Any other MCP tool's docstring or error handling
- The actual behavior of the `ingest` tool (it still works fine for server-side paths)
- SPEC.md, skills, docs (skill already has the right pattern; it's the code that needs to match)

## Verify after editing

```bash
python -c "import ast; ast.parse(open('src/pipeline/mcp_server.py').read()); print('OK')"
```

## Do not commit

Report when done. Leave for Bob.
