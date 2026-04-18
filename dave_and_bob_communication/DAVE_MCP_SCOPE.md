# Plan: CRUD operations + soft delete for Ariadne Core — Overview

## What we're building

Full CRUD for documents and collections. Currently we have Create and Read. Adding:
- **Update** — change tags, agent_metadata, collection on existing documents
- **Delete** — soft delete with 48hr grace period, excluded from search by default
- **Restore** — undo a soft delete within the grace window

Plus three bug fixes found during testing.

## Steps (each has its own file)

| Step | File | What | Dave prompt |
|------|------|------|-------------|
| 1 | DAVE_MCP_STEP1.md | Database schema — soft delete columns | Migration + schema.py |
| 2 | DAVE_MCP_STEP2.md | Store layer — soft delete, update metadata, search filtering | dedup.py / store interface |
| 3 | DAVE_MCP_STEP3.md | Store layer — collection-level soft delete + restore | Same files |
| 4 | DAVE_MCP_STEP4.md | MCP tools — update, delete, restore, delete_collection | mcp_server.py |
| 5 | DAVE_MCP_STEP5.md | REST endpoints — mirror MCP tools | routes.py |
| 6 | DAVE_MCP_STEP6.md | Bug fix — empty fingerprint dedup | mcp_server.py |
| 7 | DAVE_MCP_STEP7.md | Bug fix — ingest error message for local paths | mcp_server.py |
| 8 | DAVE_MCP_STEP8.md | Bug fix — standalone image ingestion | mcp_server.py |

## Workflow

1. Give Dave step N
2. Dave implements, reports done (does NOT commit)
3. Give Bob the review — Bob commits and pushes
4. Give Dave step N+1
5. Repeat

Steps 1-3 are the foundation (store layer). Steps 4-5 are the API surface. Steps 6-8 are bug fixes.

After all 8 steps are pushed, Sam updates SPEC.md and skills.

## Do not touch (applies to ALL steps)

- SPEC.md — Sam updates after all code is reviewed
- Skills — Sam updates after SPEC is frozen
- Any docs outside `src/pipeline/` and `migrations/`
- `.env`, `.mcp.json`, or any config files
