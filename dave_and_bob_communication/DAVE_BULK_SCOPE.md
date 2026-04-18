# Plan: CLI scripts for bulk operations — overview

## Why

MCP tools are great for atomic operations (search, convert one doc, delete one doc) but terrible for bulk work. A 574-file ingest through MCP means 1,148 tool calls, each one forcing the LLM to think about a file it doesn't need to see. That's exactly the token waste Ariadne exists to prevent.

The fix: **CLI scripts for bulk operations, MCP for atomic operations.** The LLM uses its Bash tool to run the scripts. The skill is the routing layer — it tells the agent when to use which.

## Architecture

```
Single operations (MCP):
  - search         → mcp search
  - get_document   → mcp get_document
  - convert_document → mcp convert_document (single file)
  - update_document → mcp update_document
  - delete_document → mcp delete_document

Bulk operations (CLI via Bash):
  - bulk ingest a directory → python scripts/bulk_ingest.py <dir> --collection <name>
  - (future: bulk_export.py, bulk_update.py, purge_deleted.py, etc.)
```

## Steps (each in its own file)

| Step | File | What |
|------|------|------|
| 1 | DAVE_BULK_STEP1.md | Shared helper module `scripts/ariadne_client.py` — REST API client, auth, retries |
| 2 | DAVE_BULK_STEP2.md | `scripts/bulk_ingest.py` — directory ingest CLI using the helper |
| 3 | DAVE_BULK_STEP3.md | Update doc-intelligence skill with CLI routing guidance |

## Workflow

1. Give Dave Step 1
2. Dave implements, reports to `dave_and_bob_communication/DAVE_DONE.md`
3. Give Bob the review
4. Bob commits and pushes
5. Give Dave Step 2 (do not start until Step 1 is committed)
6. Repeat

## Do not touch (applies to ALL steps)

- `src/pipeline/` — the server code is fine as-is, the REST API already supports what we need
- SPEC.md — Sam updates after all code is committed
- `.env`, `.mcp.json`, or any config files

## The big picture

After these three steps, an agent asked to "ingest the World Bank documents" will:

1. Read the doc-intelligence skill
2. See: "for bulk ingest, use `python ariadne-core/scripts/bulk_ingest.py <dir> --collection <name>`"
3. Run it via Bash
4. Get back a summary: "574 documents ingested, 3 failed (see errors.log)"
5. Report to the user

Zero file bytes through the LLM context. The whole point of Ariadne.
