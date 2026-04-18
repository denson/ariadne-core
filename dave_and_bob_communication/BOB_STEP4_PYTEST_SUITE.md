# BOB — Step 4 of 4: Phase 7 pytest suite for native Gemini contract

Final step in the split. Lands Dave's pytest suite update for native Gemini:
five modified files and one deletion. Includes a **hard gate**: bare
`python -m pytest tests/ -v` must pass green before push.

Scope:

- M: `tests/test_embedding.py`, `tests/test_enrichment.py`, `tests/test_config.py`, `tests/test_extraction.py`
- M: `FIXES.md`
- D: `tests/test_openai_live.py` (already staged-deleted from Dave's earlier work)

**Not in scope** (leave unstaged / untracked):

- `dave_and_bob_communication/DAVE_DONE.md` — Dave's Phase 7 report. Leave
  modified; we'll handle in a later hygiene sweep with `_phase1_smoke.py`.
- All 5 untracked scripts — stay untracked per established pattern.

---

## Step 0 — pre-flight (MANDATORY)

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected state:**

- `HEAD` and `origin/main` both at `e0f06b0` (from Step 3)
- Modified (unstaged): `FIXES.md`, `dave_and_bob_communication/DAVE_DONE.md`, `tests/test_config.py`, `tests/test_embedding.py`, `tests/test_enrichment.py`, `tests/test_extraction.py`
- Staged: `tests/test_openai_live.py` (deleted)
- Untracked: 5 scripts + any diagnostic `.md` files

If anything else is modified or anything expected is missing, **stop and
report**.

---

## Step 1 — verify pip environment is still clean

The pip shadow (archived `ariadne-thread` winning over current repo) must be
gone. Confirm:

```
python -c "import pipeline, sys; print(pipeline.__file__); print(sys.executable)"
```

Expected: `pipeline.__file__` points inside
`...\ariadne-core\src\pipeline\__init__.py` (forward or back slashes depend
on shell). If it points at anything under `nate_skills\ariadne-thread\...`
or similar, **stop and report** — the hard gate below will be meaningless
otherwise.

---

## Step 2 — HARD GATE: bare pytest must pass

No `PYTHONPATH=src`, no `--ignore`, no `-k`, no other flags:

```
python -m pytest tests/ -v
```

Paste the full output.

**Hard gate condition:** every test collected must pass. Expected from
Dave's DAVE_DONE.md: 174 collected, 174 passed. Exact count may vary if
Step 2's orphan deletions changed collection.

**If ANY test fails, ANY import error occurs, or collection fails, STOP.**
Do not stage anything. Do not commit. Do not push. Report the full pytest
output to Sam. We will diagnose before proceeding.

If all tests pass, continue to Step 3.

---

## Step 3 — stage the in-scope files

```
git add tests/test_embedding.py tests/test_enrichment.py tests/test_config.py tests/test_extraction.py FIXES.md
git status --short
```

Expected `git status --short` now shows:

- `M  FIXES.md` (staged)
- `M  tests/test_config.py` (staged)
- `M  tests/test_embedding.py` (staged)
- `M  tests/test_enrichment.py` (staged)
- `M  tests/test_extraction.py` (staged)
- `D  tests/test_openai_live.py` (staged delete — from Dave)
- ` M dave_and_bob_communication/DAVE_DONE.md` (unstaged, intentional)
- `??` for untracked files (unchanged)

If anything else appears in the staged set, **stop and report**.

---

## Step 4 — commit (no pathspec needed; all staged items in scope)

```
git commit -m "$(cat <<'EOF'
Phase 7: Update pytest suite for native Gemini contract

Rewrites the test suite to match the native Gemini endpoints
introduced in phases 3-6:

  tests/test_embedding.py   — native batchEmbedContents request/response
                              shapes; x-goog-api-key header
  tests/test_enrichment.py  — native generateContent with two-call
                              urlopen pattern (URL fetch + POST) for
                              describe_image_from_url
  tests/test_config.py      — Gemini defaults (gemini-embedding-001,
                              gemini-2.0-flash, generativelanguage
                              .googleapis.com/v1beta)
  tests/test_extraction.py  — processing-chain assertion relaxed from
                              == 1 to >= 1 to accommodate the new
                              encoding_detection step added in phase 5

Deletes tests/test_openai_live.py — the old OpenAI-compat live probe
no longer applies now that the runtime calls native Gemini endpoints.

Adds FIXES.md section 0 documenting the migration context and the
Phase 6a dataclass-default gap (fixed separately in e0f06b0).

Hard gate: bare `python -m pytest tests/` passes green without
PYTHONPATH overrides or --ignore flags.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Step 5 — push and verify

```
git push origin main
git log -1 --oneline
git rev-parse origin/main
git log --oneline cf04b7d..HEAD
git status --short
```

The `git log --oneline cf04b7d..HEAD` should show four commits in order:

1. `cf04b7d..` — CLAUDE.md rule propagation (Step 1)
2. `a734bf6..` — Remove orphan test files (Step 2)
3. `e0f06b0..` — Phase 6a dataclass fix (Step 3)
4. (new SHA) — Phase 7 pytest suite (Step 4)

Final `git status --short` should show only:

- ` M dave_and_bob_communication/DAVE_DONE.md`
- `??` for 5 untracked scripts + any diagnostic `.md`

---

## Report back

- Step 0 pre-flight output
- Step 1 pip-env check output
- **Step 2 full pytest output** — this is the hard gate
- Step 3 `git status --short` after staging
- New commit SHA
- `origin/main` SHA confirmation
- `git log --oneline cf04b7d..HEAD` showing all four Phase 7 commits
- Final `git status --short`

## Do NOT

- Stage `DAVE_DONE.md` — leave it modified for the hygiene sweep
- Stage or commit any of the 5 untracked scripts
- Touch `src/` files
- Add `--ignore`, `PYTHONPATH=src`, or any flags to the pytest invocation in
  Step 2 — the hard gate is "bare pytest passes"
- Push if any test fails — stop and report instead

After Sam reviews, we'll move on to Phase 7.5 (live smoke test) or the
backlog cleanup pass.
