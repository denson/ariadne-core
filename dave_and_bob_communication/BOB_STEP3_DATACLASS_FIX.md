# BOB — Step 3 of 4: Commit Phase 6a gap fix (per-module dataclass defaults)

Dave caught during Phase 7 that the per-module `EmbeddingConfig` at
`src/pipeline/embedding/embedder.py` and `VisionConfig` at
`src/pipeline/enrichment/vision.py` still held OpenAI-shim defaults after
Phase 6a updated the loader-side defaults in `src/pipeline/config.py`. Dave
fixed both dataclasses; this step commits that fix in isolation as a Phase-6a
regression patch, separate from the pytest-suite work.

Scope: commit **exactly two files** — `embedder.py` and `vision.py`. Nothing
else.

---

## Step 0 — pre-flight (MANDATORY)

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected state:**

- `HEAD` and `origin/main` both at `a734bf6` (from Step 2)
- Modified (unstaged): `FIXES.md`, `dave_and_bob_communication/DAVE_DONE.md`, `src/pipeline/embedding/embedder.py`, `src/pipeline/enrichment/vision.py`, `tests/test_config.py`, `tests/test_embedding.py`, `tests/test_enrichment.py`, `tests/test_extraction.py`
- Staged: `tests/test_openai_live.py` (deleted)
- Untracked: the 5 scripts + any `BOB_*.md` / `DAVE_*.md` diagnostics

If anything else is modified or anything expected is missing, **stop and
report**.

---

## Step 1 — show the two diffs for Sam's record

```
git diff -- src/pipeline/embedding/embedder.py src/pipeline/enrichment/vision.py
```

Paste the full diff. Confirm (visually) that the changes are limited to:

- `EmbeddingConfig` dataclass defaults in `embedder.py` (~lines 30–40)
- `VisionConfig` dataclass defaults in `vision.py` (~lines 30–40)
- No other edits to these files (no changes to the client classes, request
  shapes, or unrelated code)

If either diff shows edits outside the dataclass blocks, **stop and report**
— the scope has drifted and Sam needs to see it before committing.

---

## Step 2 — cross-check loader defaults

Confirm the new dataclass defaults match the loader-side defaults in
`src/pipeline/config.py`:

```
git grep -n "gemini-embedding-001\|gemini-2.0-flash\|generativelanguage.googleapis.com" -- src/pipeline/config.py src/pipeline/embedding/embedder.py src/pipeline/enrichment/vision.py
```

Expected: model names and base URL appear consistently across all three
files (no stale `text-embedding-3-small` / `gpt-4o-mini` /
`/v1beta/openai/` survivors). If you see any stale value in the three target
files, **stop and report**.

---

## Step 3 — stage and verify

```
git add src/pipeline/embedding/embedder.py src/pipeline/enrichment/vision.py
git status --short
```

Expected `git status --short` output:

- `M  src/pipeline/embedding/embedder.py` (staged)
- `M  src/pipeline/enrichment/vision.py` (staged)
- `D  tests/test_openai_live.py` (still staged from Dave — leave alone)
- ` M` for: `FIXES.md`, `DAVE_DONE.md`, 4× `tests/test_*.py`
- `??` for untracked scripts and diagnostic `.md`

If the staged set contains anything other than the two `src/pipeline/*.py`
files and the pre-existing `test_openai_live.py` delete, **stop and report**.

---

## Step 4 — commit with pathspec

Because `test_openai_live.py` is still staged-deleted, commit with a pathspec
so only the two source files land:

```
git commit -m "$(cat <<'EOF'
Fix Phase 6a gap: per-module dataclass defaults for Gemini native

Phase 6a updated loader-side defaults in src/pipeline/config.py
(EmbeddingConfig and ImageEnrichmentConfig loaders) to the Gemini
native values, but missed the per-module dataclasses used when the
embedder and vision clients are instantiated directly with defaults:

  src/pipeline/embedding/embedder.py  EmbeddingConfig
  src/pipeline/enrichment/vision.py   VisionConfig

Both now default to the same Gemini-native values as the loader
(base_url=https://generativelanguage.googleapis.com/v1beta,
gemini-embedding-001 for embeddings, gemini-2.0-flash for vision).

Discovered by Dave during Phase 7 pytest update when test assertions
against the module-level defaults failed. Fix is scoped to the two
dataclass blocks; no request-shape or client-logic changes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)" -- src/pipeline/embedding/embedder.py src/pipeline/enrichment/vision.py
```

---

## Step 5 — push and verify

```
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

Verify `tests/test_openai_live.py` is still staged as deleted (`D  `). If it
accidentally got committed, **stop and report**.

---

## Report back

- Step 0 output
- Full diff from Step 1 (both files)
- Step 2 grep output
- New commit SHA
- Confirmation `origin/main` matches local `HEAD`
- Final `git status --short` — should show 6 modified, 1 staged-delete
  (`test_openai_live.py`), untracked unchanged

## Do NOT

- Touch any file other than `embedder.py` and `vision.py`
- Stage or commit `FIXES.md`, `DAVE_DONE.md`, or any `tests/*`
- Unstage `test_openai_live.py` — leave it staged-deleted from Dave
- Run pytest yet (hard gate is in Step 4, not here)

Sam will review before issuing Step 4 of 4 (the pytest suite commit + hard
gate).
