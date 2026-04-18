# BOB — Backlog 4 of 4: Archive IMPLEMENT.md + drop stale SKILL.md row

Two edits in one commit.

1. `git mv IMPLEMENT.md docs/archive/IMPLEMENT_pre_rest_migration.md` — preserves the pre-REST-migration implementation plan as historical record instead of carrying stale `pipeline.mcp_server` references in an active root-level doc.
2. `skills/ariadne-core-build/SKILL.md` — delete the table row at line 128 describing `src/pipeline/mcp_server.py`. The module was removed in `e0ccb12`; the row is stale.

Backlog 3 (`_phase1_smoke.py`) was skipped — the script is the natural starting point for Phase 7.5 and stays untracked where it is.

---

## Step 0 — pre-flight

```
git status
git rev-parse HEAD
```

`HEAD` = `dfa53af`. Modified/staged: nothing. Untracked: 5 scripts + any diagnostic `.md`. Stop if otherwise.

---

## Step 1 — create `docs/archive/` if missing

```
mkdir -p docs/archive
```

(No-op if it already exists.)

---

## Step 2 — `git mv` IMPLEMENT.md

```
git mv IMPLEMENT.md docs/archive/IMPLEMENT_pre_rest_migration.md
git status --short
```

Expected staged:
- `R  IMPLEMENT.md -> docs/archive/IMPLEMENT_pre_rest_migration.md` (rename)

If git records it as a `D` + `A` (delete + add) rather than an `R` (rename), that's fine — similarity threshold may not trigger on long docs. Note it in the report.

---

## Step 3 — edit `skills/ariadne-core-build/SKILL.md` line 128

Current line 128:

```
| `src/pipeline/mcp_server.py` | MCP tool implementations | Must match SPEC tool signatures |
```

Delete the entire line. Surrounding rows stay. The table header and other rows (`SPEC.md`, `skills/.../SKILL.md`, `src/pipeline/api/routes.py`, etc.) remain unchanged.

Verify:

```
git diff -- skills/ariadne-core-build/SKILL.md
```

Diff should show exactly one line removed, nothing added. Stop if scope drifts.

---

## Step 4 — stage and verify

```
git add skills/ariadne-core-build/SKILL.md
git status --short
```

Expected:
- `R  IMPLEMENT.md -> docs/archive/IMPLEMENT_pre_rest_migration.md` (or `D`+`A` pair)
- `M  skills/ariadne-core-build/SKILL.md`
- `??` for untracked files (unchanged)

---

## Step 5 — commit and push

```
git commit -m "$(cat <<'EOF'
Archive IMPLEMENT.md and drop stale mcp_server doc references

The mcp_server module was removed in e0ccb12 (step 5 of 5 MCP
removal) but two active docs still referenced it:

- IMPLEMENT.md: pre-REST-migration implementation plan with 6
  references to src/pipeline/mcp_server.py. Moved to
  docs/archive/IMPLEMENT_pre_rest_migration.md to preserve as
  historical record instead of carrying stale references in an
  active root-level doc.

- skills/ariadne-core-build/SKILL.md: table row at line 128
  described src/pipeline/mcp_server.py as "MCP tool
  implementations" alongside SPEC.md and routes.py. Removed — the
  file doesn't exist and agents building on this repo shouldn't
  be pointed at it.

Other stale references (docs/patches/001, docs/patches/003,
tests/COMPLY*.md, tests/FIX_*.md) are historical investigation
artifacts and stay as-is.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

---

## Report back

- Step 0 output
- Step 2 `git status --short` after `git mv`
- Step 3 diff of SKILL.md
- Step 4 `git status --short` after staging
- New commit SHA
- `origin/main` confirmation
- Final `git status --short`

## Do NOT

- Touch any other doc file (leave `docs/patches/*`, `tests/COMPLY*.md`, `tests/FIX_*.md`, `docs/mcp-setup.md` alone for now)
- Rewrite any part of `IMPLEMENT.md` during the move — pure rename
- Touch other rows in the SKILL.md table
