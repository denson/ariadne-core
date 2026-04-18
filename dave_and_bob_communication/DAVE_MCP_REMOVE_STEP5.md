# Step 5: Delete `mcp_server.py`, clean up config and deps

**For:** Dave  
**Context:** This is step 5 of 5 — the kill shot. Steps 1-4 already extracted the service layer and rewired all consumers. Nothing imports from `mcp_server.py` anymore.

---

## Changes (6 files)

### 1. Delete `src/pipeline/mcp_server.py`

Delete the entire file. It's ~1,470 lines of MCP tool wrappers that are no longer imported by anything.

### 2. Edit `src/pipeline/config.py`

- **Remove `mcp_port` from `APIConfig` dataclass** (currently line 89: `mcp_port: int = 8081`). Delete that one line.

- **Remove `MCP_PORT` env var handling** in `load_config()`. Find these lines near the bottom (around lines 330-333):
  ```python
  if env.get("MCP_PORT"):
      config.api.mcp_port = int(env["MCP_PORT"])
  elif env.get("PORT"):
      config.api.mcp_port = int(env["PORT"])
  ```
  Delete all 4 lines. The `if "PORT" in env: config.api.port = int(env["PORT"])` line above them stays.

### 3. Edit `src/pyproject.toml`

- Remove `"mcp>=1.0.0",` from the `dependencies` list.

### 4. Edit `src/pipeline/api/signing.py`

- Find the MCP reference in the docstring (line 3, something like "Agents never see the API key. Instead they call the MCP tool"). Rewrite to remove the MCP mention. Something like: "Agents never see the API key. Instead they call `request_upload_url` which returns a presigned URL."

### 5. Edit `CLAUDE.md` (repo root, NOT the workspace one)

- **Update description paragraph**: change "into clean Markdown + vector embeddings, then exposes them via MCP server and REST API" → "into clean Markdown + vector embeddings, then exposes them via a REST API"

- **Update "Running locally" section**: change `ariadne-core serve            # start MCP (:8081) + REST API (:8000)` → `ariadne-core serve            # start REST API (:8000)`

- **Delete the entire "MCP client connection" section** (the `claude mcp add ...` block and surrounding text)

### 6. Final grep

After all edits, grep the entire `src/` directory AND `CLAUDE.md` for `mcp` (case-insensitive). The only acceptable remaining references are:

- `.mcp.json` — legacy credential discovery path (in services.py or config docs). That's fine, it's a file format reference not an MCP protocol reference.
- Any test files referencing mcp — note them but don't fix (out of scope)

If you find other `mcp` references in `src/` that aren't `.mcp.json`, fix them.

## Verify

```bash
python -c "from pipeline.api.app import app; from pipeline.services import configure_stores; print('OK')"
```

Should pass with no import errors and no `mcp` package needed.

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`.
