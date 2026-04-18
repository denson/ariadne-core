# BOB — Backlog 6+7 combined: Commit Phase 7.5 record + delete `_phase1_smoke.py`

Two hygiene operations in one commit.

1. **Backlog-6:** Commit the current `dave_and_bob_communication/DAVE_DONE.md` as the Phase 7.5 record. Same convention as `86cebe2` (Phase 7 record).
2. **Backlog-7:** Delete `_phase1_smoke.py` from the repo root. Phase 7.5 established the pattern of ad-hoc smoke via `AriadneClient` in the Dave session; the Phase 1 standalone script is redundant.

---

## Step 0 — pre-flight (MANDATORY)

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected state:**

- `HEAD` and `origin/main` both at `5d239cd`
- Modified (unstaged): exactly `dave_and_bob_communication/DAVE_DONE.md`
- Staged: nothing
- Untracked: `_phase1_smoke.py`, `scripts/_generate_encoding_fixtures.py`, `scripts/_probe_embedder.py`, `scripts/_probe_text_encoding.py`, `scripts/_probe_vision.py`, plus any `BOB_*.md` / `DAVE_*.md` diagnostic files

If anything else is modified or staged — or `DAVE_DONE.md` is not modified —
**stop and report**.

---

## Step 1 — sanity-check DAVE_DONE.md content

```
git diff -- dave_and_bob_communication/DAVE_DONE.md
```

Paste first 40 lines (head) and last 20 lines (tail). Confirm it's the
Phase 7.5 post-fix smoke report (references: clean coherent=True, mojibake
coherent=False + llm_coherent=True showing gate overrode, gemini: labels,
search hits, DB counts).

If the content is something else — for instance, still showing Phase 7 or
an intermediate pre-fix state — **stop and report**.

---

## Step 2 — delete `_phase1_smoke.py`

Since it's untracked, this is a plain `rm`, not a `git rm`:

```
rm _phase1_smoke.py
git status --short
```

Expected after `rm`: `_phase1_smoke.py` no longer appears as `??`. Other
untracked scripts remain.

If for any reason the file was actually tracked and `rm` shows it as
modified/deleted in `git status`, **stop and report** — our working
assumption (untracked) would be wrong.

---

## Step 3 — stage and verify

```
git add dave_and_bob_communication/DAVE_DONE.md
git status --short
```

Expected:

- `M  dave_and_bob_communication/DAVE_DONE.md` (staged)
- `??` for 4 remaining untracked scripts + any diagnostic `.md` files

If anything else is staged, **stop and report**.

Note: git will warn about the `dave_and_bob_communication/` directory
being gitignored — same cosmetic quirk as Backlog-1. The negation rule
from `86cebe2` still means the file stages successfully. If `git status`
confirms it's staged, proceed.

---

## Step 4 — commit

```
git commit -m "$(cat <<'EOF'
Record Dave's Phase 7.5 report + delete _phase1_smoke.py orphan

Dave's DAVE_DONE.md report documents the Phase 7.5 live smoke test
against the Railway deployment (post-validator-gate fix). Key
findings: clean ingest coherent=True, mojibake ingest coherent=False
with llm_coherent=True (confirming the byte-confidence gate at
markitdown.py line ~177 overrode the LLM's fooled vote), image
enrichment labeled gemini:, search returned 3/3 hits, DB row counts
consistent. Hard gate for Phase 8 cleared.

Also deletes _phase1_smoke.py from the repo root — a standalone
Phase 1 client-roundtrip script that's redundant after Phase 7.5
established the pattern of ad-hoc smoke via AriadneClient in the
Dave session.

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
git status --short
```

Final `git status --short` should show:

- No modified, no staged
- `??` only for 4 untracked scripts (down from 5 — `_phase1_smoke.py` is gone) + any diagnostic `.md` files

---

## Report back

- Step 0 output
- Step 1 diff head + tail
- Step 2 `git status --short` after rm
- Step 3 `git status --short` after staging
- New commit SHA
- `origin/main` confirmation
- Final `git status --short`

## Do NOT

- Stage any untracked scripts (they stay per the helper-pattern convention)
- Touch `BOB_REVIEW.md` (convention established but not re-committing here)
- Use `git add -f` (negation rule handles it)
- Delete any file other than `_phase1_smoke.py`

Sam will review before issuing Backlog-5 (doc scrub).
