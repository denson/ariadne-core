# Phase 1 — Unblock the Ariadne ingest pipeline

**Author:** Sam (planner)
**For:** Dave and Bob
**Date:** 2026-04-15

---

## What this phase is about

The 574-document World Bank ingest is blocked by two bugs and one missing capability. This phase fixes all three, cleans up the failed previous attempt, and retries the ingest.

## The three code tasks (in order)

| Task | File | What |
|---|---|---|
| `DAVE_SKILL_ROUTING.md` | `skills/ariadne-document-intelligence/SKILL.md` | Sharpen the ingestion routing decision tree so agents pick the right tool the first time |
| `DAVE_MCP_ERROR_ROUTING.md` | `src/pipeline/mcp_server.py` | Make the MCP `ingest` tool's error message echo the skill's routing instructions as a safety net |
| `DAVE_TEXT_ENCODING.md` | `src/pipeline/extraction/markitdown.py` + new `text_encoding.py` | Add encoding detection (charset-normalizer) + LLM language validation (Gemini flash-lite) for `.txt` files |

**Execute in this exact order.** Step 2 echoes Step 1 — Dave needs to see the final skill text before writing the MCP error messages. Step 3 is independent but ships last because it's the largest change.

After all three are committed and deployed, Denson will handle Steps 4-5 (cleanup + retry) manually.

## Key principles

1. **The skill is the specification.** It describes how things should work. The MCP server reinforces what the skill taught, as a safety net for when agents don't read the skill.

2. **Single file vs directory is the core routing decision.** One file -> upload via REST + `convert_document`. Many files / directory -> `bulk_ingest.py` via Bash. Both paths must be equally prominent and copy-paste-ready.

3. **Nothing gets rejected.** The encoding step ingests every file. Metadata and tags tell the story. Suspect files get tags (`encoding:suspect`, `status:needs-review`), not rejections.

4. **Flash-lite is the floor, not the ceiling.** The LLM validation in Step 3 uses the cheapest available model. Any future model swap only improves results.

## What NOT to touch

- `TOKEN_SAVINGS_FRAMING.md` or any pricing/savings content
- Authorship fields (must say Denson Smith)
- The search, get_document, list_documents, or delete_document tools
- The chunking or embedding pipeline (except the encoding intercept point in Step 3)
- Any file outside the specific files listed in each task

## For Bob

Each task's Dave file includes a "Review summary for Bob" section at the end. That tells you what changed, why, and what to verify. Dave will also write a `DAVE_DONE.md` after each task with his completion report.

After reviewing, commit with the standard format:
```
<commit message>

Executed-by: Dave (<session-name>)
Reviewed-by: Bob (<session-name>)
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
