# Step 7: Bug fix — ingest error message for local paths

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 7 of 8. Steps 1-6 must be committed first.

## The bug

When an agent calls `ingest` with a local Windows path like `D:/video_projects/...`, the error says "Not a directory" which is misleading. The real issue is that the path is local to the agent's machine, not on the server.

## What to do

**File:** `ariadne-core/src/pipeline/mcp_server.py` — in the `ingest` tool function

Find the error handling for when the path doesn't exist or isn't a directory. Change the error message to:

```
"Path not found on server: {path}. The ingest tool only works with server-side directories. For local files, upload each file via POST /api/upload first, then call convert_document with the returned server-side path."
```

This tells the agent exactly what to do instead of just saying the path is wrong.

## Do not commit

Report what you changed. Leave for Bob.
