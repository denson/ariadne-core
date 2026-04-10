# Patch 002: Path Resolution — Document STDIO Proxy Auto-Upload in Skill

**Resolves:** CHECK_SKILL_VS_SPEC_RESULTS.md — Discrepancy #12 (Path resolution)

**Problem:** The SPEC.md documents how the STDIO proxy automatically uploads local files to the container before forwarding the request. The code implements this (`mcp_stdio_proxy.py` lines 34–69). But the SKILL.md — the document an OB1 agent actually reads — says nothing about it. An agent wouldn't know:

1. Local file paths "just work" when connected via STDIO proxy (the proxy auto-uploads).
2. HTTP MCP / REST API callers must use the `POST /api/upload` endpoint manually, or use bind mounts.
3. The `ingest` tool does NOT auto-upload — it requires bind mounts for local directories.

This matters because an agent connected via HTTP MCP (the Docker default) that tries to pass a local path like `/Users/denson/Downloads/report.pdf` will get a "file not found" error from inside the container.

---

## Files to patch (1)

### `skills/ariadne-document-intelligence/SKILL.md` (OB1 repo)

**Location:** After the "Process: Ingesting a document" section's step 1 ("Get the file path or URL"), insert a new callout block. The agent needs to know about path resolution *before* it calls `convert_document`.

**Insert after line 173** (after `1. **Get the file path or URL** from the user's message or context.`):

```markdown

   **Path resolution — how file paths work across transports:**

   - **STDIO proxy** (local connection): Local file paths and `file://` URIs are
     automatically uploaded to the container. Just pass the path as-is — the proxy
     handles it. HTTP/HTTPS URLs also work and pass through directly.
   - **HTTP MCP / REST API** (Docker/network connection): The container cannot see
     the host filesystem. You must either:
     - Pass an HTTP/HTTPS URL the container can fetch
     - Upload the file first via `POST /api/upload`, then use the returned container
       path as the `uri`
     - Use a bind mount configured in `docker-compose.yml` (paths under `/data/` are
       already container paths)
   - **`ingest` (directories):** The STDIO proxy does NOT auto-upload directories.
     For batch ingestion of local directories, the directory must be bind-mounted
     into the container. The `ingest` tool only works with paths the container can
     access directly.

   If you're unsure which transport you're using: if your `convert_document` calls
   with local paths work without errors, you're on STDIO. If they fail with "file
   not found", you're on HTTP MCP and need to upload first or use URLs.

```

**Also insert a brief note in the "Tools available" section** to surface this at the top level. After line 43 (end of `convert_document` tool description), append:

**Current (lines 41–43):**
```markdown
- **`convert_document`** — Convert a single document to Markdown. Chunks, embeds, and
  stores it by default. Use for any individual file the user uploads or references.
  Accepts optional `chunking_config` to override the auto-selected chunking strategy.
```

**Replace with:**
```markdown
- **`convert_document`** — Convert a single document to Markdown. Chunks, embeds, and
  stores it by default. Use for any individual file the user uploads or references.
  Accepts optional `chunking_config` to override the auto-selected chunking strategy.
  Accepts local file paths (auto-uploaded via STDIO proxy), HTTP/HTTPS URLs, or
  container paths (`/data/...`).
```

**Also add a note to the `ingest` tool description.** After line 65 (end of `ingest` description), append:

**Current (lines 64–65):**
```markdown
- **`ingest`** — Batch-ingest a directory of files. Use when the user says "process
  this folder" or "ingest everything in here".
```

**Replace with:**
```markdown
- **`ingest`** — Batch-ingest a directory of files. Use when the user says "process
  this folder" or "ingest everything in here". Directory must be accessible from inside
  the container (bind mount or `/data/` path) — local directory paths are NOT
  auto-uploaded.
```

---

## Verification

After patching, confirm:

1. **SKILL.md mentions all three transport cases:** STDIO auto-upload, HTTP MCP manual upload, bind mount.
2. **SKILL.md mentions the `ingest` limitation:** no auto-upload for directories.
3. **Consistency with SPEC.md:** The SPEC's "Path Resolution" section (lines 289–304) describes the same four-step flow. The skill's wording should be consistent but doesn't need to reproduce the implementation detail (step numbers, UUID naming, etc.) — agents need to know the *behavior*, not the mechanism.
4. **No new info in SPEC.md or code:** This patch only updates the skill. The SPEC and code are already correct.

## What this patch does NOT change

- SPEC.md — already has the full path resolution section.
- `mcp_server.py` — no path resolution needed (runs inside the container).
- `mcp_stdio_proxy.py` — code is already correct.
- `docint-architecture.md` — already documents the transport behavior.
- `routes.py` — upload endpoint already exists and works.
