# BOB — Step 1 of 4: Clean tree + commit CLAUDE.md rule propagation

Small, isolated scope. Two actions only:
(a) revert the orphan `BOB_REVIEW.md` working-tree content (no commit)
(b) commit the CLAUDE.md "search the web" rule propagation

Do **not** touch any other file. Do **not** delete test files. Do **not** stage
`embedder.py`, `vision.py`, `FIXES.md`, or any of the `tests/*` files. Those
are later steps.

---

## Step 0 — pre-flight (MANDATORY)

```
git status
git diff --stat
git rev-parse HEAD
git rev-parse origin/main
```

**Expected state:**

- `HEAD` and `origin/main` both at `6db1663`
- Modified (unstaged): `CLAUDE.md`, `FIXES.md`, `dave_and_bob_communication/BOB_REVIEW.md`, `dave_and_bob_communication/DAVE_DONE.md`, `src/pipeline/embedding/embedder.py`, `src/pipeline/enrichment/vision.py`, `tests/test_config.py`, `tests/test_embedding.py`, `tests/test_enrichment.py`, `tests/test_extraction.py`
- Staged: `tests/test_openai_live.py` (deleted)
- Untracked: `_phase1_smoke.py`, `scripts/_generate_encoding_fixtures.py`, `scripts/_probe_embedder.py`, `scripts/_probe_text_encoding.py`, `scripts/_probe_vision.py`, plus any `dave_and_bob_communication/BOB_DIAGNOSTIC_PHASE7*.md` and `BOB_STEP1_CLAUDEMD.md` files

If anything else appears — or anything expected is missing — **stop and report
before doing anything**.

---

## Step 1 — revert the orphan `BOB_REVIEW.md`

```
git checkout -- dave_and_bob_communication/BOB_REVIEW.md
```

Then verify the revert landed:

```
git status -- dave_and_bob_communication/BOB_REVIEW.md
```

Expected: file no longer appears in `git status`. If it still shows modified,
stop and report.

---

## Step 2 — stage CLAUDE.md only and commit

```
git add CLAUDE.md
git status --short
```

Expected `git status --short` output now shows:

- `A ` or `M ` for `CLAUDE.md` (staged)
- `D ` for `tests/test_openai_live.py` (still staged from Dave's earlier work — leave it, we'll commit that in Step 4)
- `M ` (working tree, not staged) for: `FIXES.md`, `dave_and_bob_communication/DAVE_DONE.md`, `src/pipeline/embedding/embedder.py`, `src/pipeline/enrichment/vision.py`, `tests/test_config.py`, `tests/test_embedding.py`, `tests/test_enrichment.py`, `tests/test_extraction.py`
- Untracked files as before

If the staged set contains anything other than `CLAUDE.md` (add) and
`tests/test_openai_live.py` (delete), **stop and report**. Do not proceed to
commit.

Then commit **only `CLAUDE.md`** using `git commit -- CLAUDE.md` so the staged
delete of `test_openai_live.py` is not included:

```
git commit -- CLAUDE.md -m "$(cat <<'EOF'
Propagate "search the web" rule to repo CLAUDE.md

Adds Denson's global guidance about not trusting training data for
third-party API/library behavior to the Ariadne Core CLAUDE.md so it
propagates to every agent scope working in this repo. Rule text
matches the canonical version in ~/.claude/CLAUDE.md verbatim.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Step 3 — push and verify

```
git push origin main
git log -1 --oneline
git rev-parse origin/main
```

Report:

- The new commit SHA
- Confirmation `origin/main` is at the new SHA
- `git status --short` output (should still show the same unstaged modifications and staged delete as before the commit, minus `CLAUDE.md`)

---

## Do NOT

- Touch any file other than `CLAUDE.md` and the `git checkout --` on `BOB_REVIEW.md`
- Delete any test files
- Stage `FIXES.md`, `embedder.py`, `vision.py`, or any `tests/*.py`
- Unstage the `tests/test_openai_live.py` delete (leave it as-is)
- Clean up untracked files

Report back with Step 0 output, the new commit SHA, and the final
`git status --short`. Sam will review before issuing Step 2 of 4.
