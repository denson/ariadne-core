# BOB — Create `docs/BACKLOG.md` deferred-work log

Pure-doc commit. Create one new file at `docs/BACKLOG.md` with the
exact content in Step 1 below, then commit and push. No source edits,
no other files.

**Why this exists:** across Phase 7 and the subsequent backlog sweep we
accumulated a dozen "we've explicitly decided to defer this" items with
no canonical home. They've been living in chat, in `DAVE_DONE.md`
reports, and in Sam's head. Pattern-level lesson: if the next phase
overlooks cruft it's because the cruft isn't written down anywhere
the next agent will read. `docs/BACKLOG.md` is the fix — a single file
future agents can grep for the list of known-deferred work.

---

## Step 0 — pre-flight

```
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**
- `HEAD` and `origin/main` both at `9095b18`
- Modified/staged: nothing
- Untracked: only the 4 helper scripts
  - `scripts/_generate_encoding_fixtures.py`
  - `scripts/_probe_embedder.py`
  - `scripts/_probe_text_encoding.py`
  - `scripts/_probe_vision.py`

If anything else is present, **stop and report**.

---

## Step 1 — write `docs/BACKLOG.md`

Create the file with **exactly** this content (a here-doc is easiest):

```markdown
# Backlog

Work that has been explicitly deferred — not forgotten, not out of
scope, just not now. Agents picking up this repo should read this file
before proposing new work, to avoid re-discovering items that are
already queued and to avoid stepping on items that need a planning
conversation first.

Each entry notes its blocker. An item without a blocker is ready to
schedule; an item with a blocker is waiting on that dependency.

## Tier-2 migration cleanup — blocked on provider-framing decision

### BL-5a — Tier-2 doc scrub: provider-framing rewrite

Three active docs still describe Ariadne as "any OpenAI-compatible
API" — coherent paragraphs from the pre-migration era, not simple
model-name swaps. Post-Phase-3–5 (commits through `e0ccb12`), the
runtime speaks native Gemini only, and `SPEC.md` → "Provider
constraints" documents that other providers would require forking.

- `README.md:366–387` — entire "Compatible providers" section
- `docs/docint-architecture.md` — 10 instances (lines 29, 46, 68, 70,
  289–291, 544–545, 987)
- `scripts/setup.py` — `PROVIDERS` dict + `DEFAULTS_TABLE`. Already
  carries an explicit `TODO(native-gemini migration)` at lines 40–42
  flagging this for a post-migration decision. Do not remove the
  TODO until BL-5a is addressed.

**Blocker:** product decision on the provider story. Options:
(a) native Gemini only for v1, (b) Gemini native + explicitly
forkable for others with SPEC.md as the contract, (c) restore a
provider abstraction (would re-introduce the OpenAI-compat shim
removed in Phase 3–5). The `BL-5.5` onboarding planning session is
the natural venue for this call.

---

## Onboarding / packaging — blocked on planning session

### BL-5.5 — Onboarding redesign

The current walkthrough skill assumes a user clones the repo and runs
the pipeline locally. The emerging model is different: most users
install `ariadne-core-client` and one or more skills that guide them
through setting up Railway, then talk to the deployment from Claude
Code Desktop. This changes what the walkthrough is, where it lives,
and possibly whether it belongs in the plugin at all.

Scope for the planning conversation:
- Target user path — client install + Railway-setup skills, vs
  current local-install walkthrough
- Role of `walkthrough_html/` preset + dynamic HTML pages in the new
  flow (template for Claude Code Desktop to drive onboarding)
- The `skills/ariadne-core-walkthrough/SKILL.md` (5130 bytes, plugin
  template) vs `.claude/skills/walkthrough/SKILL.md` (7726 bytes,
  runtime-customized) drift — same directory has byte-identical
  YAMLs but a substantively different SKILL.md. Needs resolution
  alongside the redesign rather than as an isolated sync pass.
- Relationship to BL-5a — "what providers do we support" and "how do
  users onboard" are arguably the same question.

**Blocker:** whiteboard-style planning session with the user. Not a
Dave/Bob delegation.

**Files in scope when BL-5.5 lands:**
- `skills/ariadne-core-walkthrough/*` (including `image_manifest.yaml`,
  `project_knowledge_graph.yaml`, `references/ConceptViz_prompts.md`,
  `SKILL.md`, `starter_deck.md`, `README.md`)
- `.claude/skills/walkthrough/*` (mirror + customized SKILL.md)
- `walkthrough_html/` (preset beats + dynamic template + PNGs + CSS)
- `docs/website-integration/README.md` (downstream use of
  `knowledge_graph_embed.html`)

Note: a few of these files contain stale `text-embedding-3-small` /
`gpt-4o-mini` references. Deliberately NOT swept in BL-5 — fold into
the redesign so we don't churn text that's about to be rewritten.

---

## Ready to schedule — no blocker

### BL-8 — `/api/health` false positive

Phase 7.5 showed `client.health()` returning `embedding=True` while
the embedding endpoint was actually 400ing (wrong model name pinned
on Railway's env vars). Health claimed healthy; pipeline was broken.

Fix candidates:
- Add a live round-trip probe (embed a 1-token sample) to health
- Or degrade the flag name to `embedding=configured` so it reflects
  what's actually being checked (presence of config, not liveness)
- Option 1 costs one API call per health check; option 2 costs
  nothing and is arguably more honest

Must-not-break: the existing no-auth contract on `/api/health` (per
`SPEC.md`).

### BL-10 — `ariadne-core serve` console-script install failure

Observed during Phase 7 prep: `pip install -e src/` fails to write
the `ariadne-core serve` console entry point. Workaround used
throughout Phase 7.5: run via `python -m pipeline.api.server` or
equivalent. Fix the packaging so the console script actually
installs.

### BL-12 — Spurious `VISION_API_KEY` warning on standalone image ingest

Phase 7.5 anomaly 4: ingesting a standalone image file with a valid
vision config still emits a "VISION_API_KEY not set" warning, even
though the vision call succeeded (produced a 1270-char Gemini
description). Warning logic is wrong somewhere.

### BL-13 — `image_enrichment.images_processed` counter semantics

Phase 7.5 anomaly 2: on a standalone image document,
`vision_extraction` runs and produces output, but
`image_enrichment.images_processed` stays at 0. The counter appears
to track only images *embedded inside* a non-image document.

Fix options:
- Rename to `embedded_images_processed` so zero isn't alarming on
  standalone images
- Increment from `vision_extraction` when the document IS an image
- Leave as-is and document the semantics clearly

### BL-14 — `scripts/_generate_encoding_fixtures.py` crashes on Windows cp1252

The generator's final preview `print()` crashes on a Windows `cp1252`
console because the mojibake string contains characters the console
can't encode. The file writes complete before the crash — operator
impact is a scary-looking traceback on success. Trivial fix: wrap
the preview in `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`
or skip the preview on Windows.

### BL-15 — `DAVE_PHASE_7_5_SMOKE_TEST.md` method-name drift

The Phase 7.5 smoke spec references client method names that don't
match the actual `ariadne-core-client` API:
- `client.ingest` → actually `client.ingest_file`
- `client.search_chunks` → actually `client.search`
- `doc.processing_chain` attribute access on the client's `Document`
  model → not present; must read from the response dict or a
  different field

Update the spec so future smoke runs don't trip on name mismatches.
(Dave worked around these live each time — the workarounds should be
the spec.)

---

## Operator / infrastructure — user-driven

### BL-9 — Railway auto-deploy diagnostic

During Phase 7.5, Railway did not auto-deploy seven successive
Phase 7 commits; the smoke only caught up after a manual redeploy.
Root cause unknown. Investigation is a Railway-dashboard task, not
an agent task.

---

## Guardrailed — requires explicit sign-off to edit

### BL-11 — Roadmap docs scrub under token-savings framing

Several `docs/roadmap/*` files reference OpenAI pricing as comparison
anchors — `docs/roadmap/pro-pricing.md`,
`docs/roadmap/pro-infrastructure-summary.md`,
`docs/roadmap/token_pricing_snapshot.md`,
`docs/roadmap/token_pricing_snapshot_update.md`.

Per `CLAUDE.md` → "Token savings guardrail", these docs must be
read end-to-end via `docs/TOKEN_SAVINGS_FRAMING.md` before any edit,
and any deletion of a savings table or metric requires explicit
user sign-off. The OpenAI references are deliberate comparison
anchors; they may or may not need to change when the provider story
is resolved in BL-5a/5.5. Do not touch without a planning pass.

---

## Explicitly NOT backlog — leave as-is

The following files contain stale refs but are historical artifacts
per the Backlog-4 precedent. Do not sweep them:

- `tests/COMPLY_*.md`, `tests/FIX_*.md`, `tests/VALIDATE_SKILL.md`,
  `tests/CHECK_SKILL_VS_SPEC_RESULTS.md` — test-investigation
  artifacts, frozen snapshots
- `docs/ariadne-document-intelligence-workspace/iteration-1/*` — eval
  snapshots, frozen
- `docs/patches/*` — historical patch records, frozen
- `FIXES.md`, `HTTP_proxy_fix.md` — historical investigation notes,
  frozen
- `walkthrough_html/*.html` — contain no stale refs; their onboarding
  role is handled under BL-5.5

---

## How to use this file

- Before proposing new work, grep this file. If your proposal matches
  a BL-* entry, continue that entry rather than starting a new one.
- When a BL-* item lands, delete its entry from this file in the same
  commit. This file shrinks over time.
- If you're adding a new deferred item, place it under the right
  section and assign the next BL-* number. The number is permanent;
  don't reuse retired numbers.
```

---

## Step 2 — stage, commit, push

```
git add docs/BACKLOG.md
git status --short
```

Expected: one staged file (`A  docs/BACKLOG.md`), nothing else. The 4
helper scripts remain `??`.

```
git commit -m "$(cat <<'EOF'
Add docs/BACKLOG.md as the canonical deferred-work log

Across Phase 7 and the post-migration backlog sweep we accumulated a
dozen explicitly-deferred items. They were living in chat, in
DAVE_DONE.md reports, and in the user's head. The "how did we
overlook cruft" process failure from earlier in Phase 7 is partly
because there was no canonical file where deferred items lived --
the next agent had no way to grep for them.

docs/BACKLOG.md is that file. Entries cover:

- BL-5a: Tier-2 doc scrub (README, docint-architecture, scripts/setup.py)
  blocked on provider-framing decision
- BL-5.5: Onboarding redesign planning session (walkthrough skill,
  walkthrough_html, .claude/ vs plugin skill drift, client-install flow)
- BL-8: /api/health false positive
- BL-9: Railway auto-deploy diagnostic (user task)
- BL-10: ariadne-core serve console-script install failure
- BL-11: Roadmap docs scrub (guardrailed)
- BL-12: Spurious VISION_API_KEY warning on standalone images
- BL-13: image_enrichment.images_processed counter semantics
- BL-14: _generate_encoding_fixtures.py Windows cp1252 crash
- BL-15: DAVE_PHASE_7_5_SMOKE_TEST.md method-name drift

Also documents the "explicitly NOT backlog" list (historical artifacts
that stay frozen per the Backlog-4 precedent) so future agents do not
spend cycles re-proposing their removal.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

Final `git status --short`: only the 4 helper scripts as `??`.

---

## Report back

- Step 0 output
- Step 1 confirmation that `docs/BACKLOG.md` was written verbatim (you
  can `diff` against the spec above if paranoid; otherwise just
  confirm word-count roughly matches — the file is ~180 lines)
- Stage-list `git status --short`
- New commit SHA
- `origin/main` confirmation
- Final `git status --short`

---

## Do NOT

- Edit any other file
- Stage any helper script
- Edit the content of `docs/BACKLOG.md` — if something looks wrong,
  stop and report rather than "improving" it
- Skip the trailing newline at the end of the file (conventional)
