# Step 3: Update doc-intelligence skill — CLI routing for bulk operations

**Context:** Read `DAVE_BULK_SCOPE.md` for the full plan. This is step 3 of 3. Steps 1 and 2 must be committed first.

## What to change

The doc-intelligence skill currently teaches agents to use MCP tools for everything. That's wrong for bulk operations — 574 files through MCP = 1,148 tool calls burning LLM context.

Add a new section that routes bulk work to CLI scripts.

**File:** `ariadne-core/skills/ariadne-document-intelligence/SKILL.md`

## Add a new section: "When to use CLI scripts vs MCP tools"

Place it after the existing tool list, before the ingestion process. Content:

### Atomic operations → MCP tools

Use the MCP tools when the work is a single operation the agent needs to reason about:
- `search` — find chunks matching a query
- `get_document` — retrieve one document's content
- `convert_document` — extract one document (when you have its content or URI)
- `update_document` — patch one document's metadata
- `delete_document` / `restore_document` — manage one document's lifecycle
- `list_collections` / `list_documents` — browse what's there

### Bulk operations → CLI scripts via Bash

Use CLI scripts when processing many files at once. The scripts use Ariadne's REST API directly, so file bytes NEVER pass through the LLM context. This is the whole point of Ariadne — don't waste tokens on data movement.

**Available CLI scripts** (in `ariadne-core/scripts/`):

| Script | Purpose | Example |
|---|---|---|
| `bulk_ingest.py` | Upload + convert a whole directory | `python ariadne-core/scripts/bulk_ingest.py data/reports --collection wb_reports --tags type:report,topic:policy` |

**When to use bulk_ingest.py:**
- User says "ingest this folder" / "process all these documents" / "load these files"
- Directory contains more than 5 files
- You don't need to see the content of each file before ingesting

**How to use it:**

1. Confirm with the user: target directory, collection name, any tags
2. Run via Bash:
   ```
   python ariadne-core/scripts/bulk_ingest.py <dir> --collection <name> --tags <tags>
   ```
3. Read the summary output
4. Report to the user: how many succeeded, how many failed, where to find errors

**DO NOT** loop over files calling `convert_document` via MCP. That defeats Ariadne's core value proposition (saving LLM tokens). One Bash call to `bulk_ingest.py` replaces N MCP calls.

## Also update the ingestion process section

Find the existing "Process: Ingesting a document" section. At the top, add:

> **Is this a single file or many files?** For bulk ingestion (more than 5 files, or a whole directory), skip this process entirely and use `scripts/bulk_ingest.py` via Bash instead. See the "CLI scripts vs MCP tools" section above.

## Don't do

- Don't touch other skills (walkthrough, install, deploy, build)
- Don't touch SPEC.md — Sam updates after code is committed
- Don't hardcode a tool count

## Do not commit

Report when done. Leave for Bob.
