# BOB — Backlog 1 of 4: Commit DAVE_DONE.md as Phase 7 record (+ gitignore negation)

Expanded from single-file to two-file commit. Sam discovered via Bob's first
attempt that `dave_and_bob_communication/` is in `.gitignore` (added after
`DAVE_DONE.md` and `BOB_REVIEW.md` were first committed at `57c1690` /
`4ce57f0`). `git add` refuses tracked-but-ignored files without `-f`, which
makes the "commit Dave's report each phase" convention fragile.

Fix: add explicit negation rules for the two phase-record files, then stage
both `.gitignore` and `DAVE_DONE.md`. `BOB_REVIEW.md` is currently not
modified (we reverted it in Step 1), so there's nothing to stage for that
file in this commit — but the negation establishes the convention for all
future Bob reviews.

Scope: two staged files.

---

## Step 0 — pre-flight (MANDATORY)

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected state:**

- `HEAD` and `origin/main` both at `6f2d547`
- Modified (unstaged): exactly `dave_and_bob_communication/DAVE_DONE.md`
- Staged: nothing
- Untracked: 5 scripts + any `BOB_*.md` / `DAVE_*.md` diagnostic files

If anything else is modified or staged — or `DAVE_DONE.md` is not modified —
**stop and report**.

---

## Step 1 — sanity-check the DAVE_DONE.md diff

```
git diff -- dave_and_bob_communication/DAVE_DONE.md
```

Paste first 40 lines (head) and last 20 lines (tail). Confirm the content
is Dave's Phase 7 report (174/174 pytest, native Gemini migration, orphan
tests, dataclass anomaly, pip-shadow anomaly). If it doesn't look like the
Phase 7 report, **stop and report**.

---

## Step 2 — show current `.gitignore` rule for the directory

```
git grep -n "dave_and_bob_communication" -- .gitignore
```

Expected: one match around line 41–42 showing
`dave_and_bob_communication/` as an ignored directory. If it doesn't match,
**stop and report** — the file may be in a different state than Sam expects.

---

## Step 3 — edit `.gitignore`: add negation rules after the directory-ignore line

Open `.gitignore` and, immediately after the
`dave_and_bob_communication/` line, insert these two lines (exact text,
exact leading `!`):

```
!dave_and_bob_communication/DAVE_DONE.md
!dave_and_bob_communication/BOB_REVIEW.md
```

Result should look like (surrounding comment/context preserved):

```
# Agent communication (prompts, reviews, handoffs between Dave and Bob)
dave_and_bob_communication/
!dave_and_bob_communication/DAVE_DONE.md
!dave_and_bob_communication/BOB_REVIEW.md
```

Then verify:

```
git diff -- .gitignore
```

Diff should show exactly two added lines (the two `!` negations) and
nothing else. If anything else changed in `.gitignore`, **stop and report**.

---

## Step 4 — verify negation takes effect

```
git check-ignore -v dave_and_bob_communication/DAVE_DONE.md
git check-ignore -v dave_and_bob_communication/BOB_REVIEW.md
git check-ignore -v dave_and_bob_communication/BOB_STEP4_PYTEST_SUITE.md
```

Expected:

- `DAVE_DONE.md`: no output (not ignored — negation hit)
- `BOB_REVIEW.md`: no output (not ignored — negation hit)
- `BOB_STEP4_PYTEST_SUITE.md` (or any other `BOB_*.md` scratch): output
  showing the directory rule matches (still ignored)

If any of the above is wrong, **stop and report**.

---

## Step 5 — stage and verify

```
git add .gitignore dave_and_bob_communication/DAVE_DONE.md
git status --short
```

Expected `git status --short`:

- `M  .gitignore` (staged)
- `M  dave_and_bob_communication/DAVE_DONE.md` (staged)
- `??` for 5 untracked scripts + any diagnostic `.md` files

If anything else is staged — or the `git add` refuses with the ignored-path
error again — **stop and report**.

---

## Step 6 — commit

```
git commit -m "$(cat <<'EOF'
Track DAVE_DONE.md and BOB_REVIEW.md as phase records

The dave_and_bob_communication/ directory is gitignored to keep
Sam's prompt/review/handoff scratch files out of version control.
But Dave's per-phase DAVE_DONE.md report and Bob's per-phase
BOB_REVIEW.md verification were committed once (57c1690, 4ce57f0)
before the gitignore rule existed, and are meant to be overwritten
and re-committed each phase as authoritative records of what
shipped.

Adds two negation rules to .gitignore so the two phase-record files
are tracked without requiring `git add -f` each time:

  !dave_and_bob_communication/DAVE_DONE.md
  !dave_and_bob_communication/BOB_REVIEW.md

Also commits the current DAVE_DONE.md as the Phase 7 (native-Gemini
pytest suite) record. BOB_REVIEW.md was left at its prior committed
state during Phase 7 housekeeping and is not re-committed here;
future Bob reviews will overwrite and commit it per the new
convention.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Step 7 — push and verify

```
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

Final `git status --short` should show:

- No modified, no staged
- `??` only for the 5 untracked scripts + any diagnostic `.md` files

---

## Report back

- Step 0 output
- Step 1 diff head + tail
- Step 2 `.gitignore` grep output
- Step 3 `.gitignore` diff
- Step 4 `git check-ignore` output for all three files
- Step 5 `git status --short` after staging
- New commit SHA
- `origin/main` confirmation
- Final `git status --short`

## Do NOT

- Touch any file other than `.gitignore` and `DAVE_DONE.md`
- Stage or commit any untracked scripts
- Use `git add -f` — the negation should make it unnecessary; if `git add`
  still refuses, stop and report
- Modify `BOB_REVIEW.md` (it's at the reverted committed state, leave it)

Sam will review before issuing Backlog 2 of 4 (source prose scrub).
