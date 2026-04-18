# MCP Removal — Step Plan

**Goal:** Extract the service layer out of `mcp_server.py`, rewire REST routes to use it, then delete the MCP wrappers and dependency.

The REST routes (`routes.py`) currently reach into `mcp_server.py` for everything — stores, embedding client, `_process_single_document`, helper functions. The MCP file IS the service layer with MCP tool decorators on top. So this is really: extract the real code, delete the MCP shell.

## Steps (one Dave instruction file per step, Bob review after each)

### Step 1 — Create `pipeline/services.py`

Copy these out of `mcp_server.py` into a new `pipeline/services.py`:

- All shared state: `_extractor`, `_dedup_store`, `_vector_store`, `_embedding_client`, `_image_enricher`
- `configure_embedding()`, `configure_image_enrichment()`, `configure_stores()`
- `SUPPORTED_EXTENSIONS`, `_STANDALONE_IMAGE_EXTENSIONS`
- `_process_single_document()`
- `_find_document_by_id()`
- `_get_chunks_for_document()`
- `_count_chunks_for_document()`
- `_post_filter_results()`

Keep all imports these functions need. Do NOT modify `mcp_server.py` yet — both files will coexist temporarily. Do NOT touch `routes.py` or `app.py` yet.

**Test:** `python -c "from pipeline.services import _process_single_document, configure_stores"` should import without error.

---

### Step 2 — Rewire `routes.py` to use `services.py`

Change `import pipeline.mcp_server as _mcp` → `import pipeline.services as _svc`.

Replace every `_mcp.` reference with `_svc.`:
- `_mcp._dedup_store` → `_svc._dedup_store`
- `_mcp._vector_store` → `_svc._vector_store`
- `_mcp._embedding_client` → `_svc._embedding_client`
- `_mcp._find_document_by_id` → `_svc._find_document_by_id`
- `_mcp._get_chunks_for_document` → `_svc._get_chunks_for_document`
- `_mcp._count_chunks_for_document` → `_svc._count_chunks_for_document`
- `_mcp._post_filter_results` → `_svc._post_filter_results`
- `from pipeline.mcp_server import _process_single_document` → `from pipeline.services import _process_single_document`
- `from pipeline.mcp_server import SUPPORTED_EXTENSIONS` → `from pipeline.services import SUPPORTED_EXTENSIONS`

Also update the module docstring (line 1): remove "mirrors MCP tool functionality".

**Test:** The REST API should still work with the same behavior. No MCP imports remain in `routes.py`.

---

### Step 3 — Rewire `app.py` and remove MCP middleware

In `app.py`:
- Change `from pipeline.mcp_server import configure_embedding, configure_image_enrichment, configure_stores` → `from pipeline.services import configure_embedding, configure_image_enrichment, configure_stores`
- Delete the entire `MCPAuthMiddleware` class (lines 91-110)
- Delete `app.add_middleware(MCPAuthMiddleware)` (line 124)
- Update the module docstring (line 1-5): remove "The app uses the same shared services... as the MCP server"

**Test:** `python -c "from pipeline.api.app import app"` should import without error. No MCP imports remain in `app.py`.

---

### Step 4 — Simplify `__main__.py` (REST-only)

Rewrite `__main__.py` to only run the FastAPI app on one port. Remove:
- All MCP server imports and startup
- The dual-port / single-port branching logic
- MCP session manager lifecycle
- `mcp_port` references

The new `_run_serve()` should just:
1. Load config
2. Set up logging
3. Run `uvicorn` with the FastAPI app on `config.api.port`

Update the module docstring: "serve — Start the REST API" (no MCP mention).

**Test:** `python -m pipeline serve` should start only the REST API on one port.

---

### Step 5 — Delete `mcp_server.py`, clean up config and deps

1. **Delete `pipeline/mcp_server.py`** entirely.

2. **In `config.py`:**
   - Remove `mcp_port` from the `APIConfig` dataclass (line 89)
   - Remove the `MCP_PORT` env var handling (lines 330-333: the `elif env.get("MCP_PORT")` block and the `elif env.get("PORT")` fallback for mcp_port)

3. **In `pyproject.toml`:**
   - Remove `"mcp>=1.0.0"` from `dependencies`

4. **In `CLAUDE.md` (repo root):**
   - Remove the "MCP client connection" section (`claude mcp add ...`)
   - Update description: remove "MCP server and" — it's just "REST API"
   - Update "Running locally": remove "MCP (:8081) +" — just "REST API (:8000)"
   - Keep `ariadne-core serve` as the command

5. **Grep the entire `src/` directory** for any remaining `mcp` references (case-insensitive). The only acceptable ones are:
   - `.mcp.json` (legacy credential discovery in the client — that's fine)
   - The signing.py docstring mention of "MCP tool" (update that too)
   
   Fix any others found.

**Test:** `python -c "from pipeline.api.app import app; from pipeline.services import configure_stores"` — no import errors, no MCP dependency needed.

---

## Notes for Dave

- Each step should be a clean, reviewable commit
- After each step, the server should still work (no broken imports)
- Steps 1-4 keep `mcp_server.py` alive but progressively remove dependencies on it
- Step 5 is the kill shot — delete it and clean up everything that referenced it
- The `mcp` Python package will no longer be imported anywhere after step 5
