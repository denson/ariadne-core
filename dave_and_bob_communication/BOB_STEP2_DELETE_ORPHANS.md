# BOB — Step 2 of 4: Delete 4 orphan test files

The MCP server module was removed in `e0ccb12` (2026-04-16). Four test files
still import from the deleted `pipeline.mcp_server` and fail at pytest
collection. Delete them.

Scope: `git rm` exactly four files. Nothing else.

---

## Step 0 — pre-flight (MANDATORY)

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected state:**

- `HEAD` and `origin/main` both at `cf04b7d` (from Step 1)
- Modified (unstaged): `FIXES.md`, `dave_and_bob_communication/DAVE_DONE.md`, `src/pipeline/embedding/embedder.py`, `src/pipeline/enrichment/vision.py`, `tests/test_config.py`, `tests/test_embedding.py`, `tests/test_enrichment.py`, `tests/test_extraction.py`
- Staged: `tests/test_openai_live.py` (deleted)
- Untracked: `_phase1_smoke.py`, `scripts/_generate_encoding_fixtures.py`, `scripts/_probe_embedder.py`, `scripts/_probe_text_encoding.py`, `scripts/_probe_vision.py`, plus whatever `BOB_*.md` / `DAVE_*.md` diagnostic files are present

If anything else appears modified or anything expected is missing, **stop and
report**.

---

## Step 1 — grep-for-importers sanity check (MANDATORY)

Before deleting, prove these four files are the only remaining importers of
`pipeline.mcp_server`:

```
git grep -n "pipeline.mcp_server\|from pipeline import mcp_server\|import mcp_server"
```

**Expected output:** matches ONLY in the four files we're about to delete:
- `tests/test_api.py`
- `tests/test_ingest.py`
- `tests/test_mcp.py`
- `tests/test_search_filters.py`

If any other file — `src/**`, `client/**`, other `tests/**`, `scripts/**`,
docs, anything — contains a reference, **stop and report**. We may have found
additional cleanup the MCP removal missed and Sam needs to see it before
proceeding.

---

## Step 2 — verify the four target files exist and are not already modified

```
git status -- tests/test_api.py tests/test_ingest.py tests/test_mcp.py tests/test_search_filters.py
ls -la tests/test_api.py tests/test_ingest.py tests/test_mcp.py tests/test_search_filters.py
```

Expected: `git status` reports nothing (files are tracked and unmodified);
`ls` shows all four files exist.

If any file is missing or already modified, stop and report.

---

## Step 3 — git rm the four files

```
git rm tests/test_api.py tests/test_ingest.py tests/test_mcp.py tests/test_search_filters.py
git status --short
```

Expected `git status --short` now shows:

- `D  tests/test_api.py` (staged delete)
- `D  tests/test_ingest.py` (staged delete)
- `D  tests/test_mcp.py` (staged delete)
- `D  tests/test_search_filters.py` (staged delete)
- `D  tests/test_openai_live.py` (staged delete — from Dave, leave alone)
- ` M` for the 8 unstaged-modified files (FIXES.md, DAVE_DONE.md, embedder.py, vision.py, 4× tests/test_*.py)
- `??` for the 5 untracked scripts + any diagnostic .md files

If anything else is staged, stop and report.

---

## Step 4 — commit the four deletions only

Because `tests/test_openai_live.py` is also staged as deleted (from Dave's
Phase 7 work), we must pathspec the commit to include only the four orphan
files:

```
git commit -m "$(cat <<'EOF'
Remove orphan test files importing removed pipeline.mcp_server

The mcp_server module was removed in e0ccb12 (step 5 of 5 MCP removal)
but four test files still imported from it and blocked pytest
collection. These tests covered MCP-specific surface area that no
longer exists in the codebase (MCP server → REST-only in this repo).

Deletes:
  tests/test_api.py
  tests/test_ingest.py
  tests/test_mcp.py
  tests/test_search_filters.py

After this commit, bare `python -m pytest tests/` should collect
without import errors (some tests may still fail pending step 3 and
step 4 of the phase-7 commit split).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)" -- tests/test_api.py tests/test_ingest.py tests/test_mcp.py tests/test_search_filters.py
```

---

## Step 5 — push and verify

```
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

Verify `tests/test_openai_live.py` is still staged as deleted (`D  `) — we'll
commit that in Step 4. If it accidentally got committed here, stop and
report.

---

## Report back

- Step 0 and Step 1 (grep) output
- New commit SHA
- Confirmation `origin/main` is at the new SHA
- Final `git status --short` — should show the 8 modified, 1 staged-delete
  (`test_openai_live.py`), and 5+ untracked

## Do NOT

- Touch any file other than the four orphan test deletions
- Unstage `test_openai_live.py` — leave it staged-deleted from Dave
- Stage or commit `FIXES.md`, `embedder.py`, `vision.py`, or any other `tests/*`
- Clean up untracked files
- Run pytest yet (we'll gate on it after Step 4)

Sam will review before issuing Step 3 of 4.
