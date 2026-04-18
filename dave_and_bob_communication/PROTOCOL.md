# PROTOCOL — Sam / Dave / Bob delegation

Meta-doc on how tasks flow through this directory. Read once when
you're new to the pattern; it won't change often.

This file exists because conventions kept accumulating in individual
prompts (launch prompt shape, deploy handoff, scope-fence wording).
Better to record them once here than re-derive them every task.

---

## The three roles

| Role | Who | Scope |
|---|---|---|
| **Sam** | Claude session that talks directly to Denson | Plans tasks, writes `DAVE_*.md` and `BOB_*.md` instruction files, fires the launch prompts, reviews outputs, manages the backlog |
| **Dave** | Fresh Claude Code session, fired by pasting a launch prompt | Implements code changes per the `DAVE_*.md` spec. Writes evidence to `DAVE_DONE.md`. **Never commits, stages, or pushes.** |
| **Bob** | Fresh Claude Code session, fired by pasting a launch prompt | Reviews Dave's working-tree changes per the `BOB_*.md` spec, commits, pushes. Runs post-deploy smoke tests after Denson confirms the deploy is live. Logs deferred items in `docs/BACKLOG.md`. |

Dave and Bob are fresh sessions with no memory of prior conversations.
The instruction file in this directory is the only context they have.

---

## Launch prompts

What you paste into Dave's or Bob's terminal to kick off a task.

Conventions:

1. **Address the target by name as the first word.** "Dave — read..."
   or "Bob — read...". Dave/Bob sessions don't know they're "Dave" or
   "Bob" unless the prompt tells them; filename alone is too implicit.
2. **The prompt is a pointer, not a spec.** Point at the instruction
   file, state the scope in one line, name the deliverable. That's it.
   Details live in the instruction file — don't re-state them inline.
3. **Under 6 lines.** If you're tempted to add more, put it in the
   instruction file instead.

Example:

```
Dave — read `dave_and_bob_communication/DAVE_QUERY_API_PASS_1.md` and execute it.

Query API Pass 1: server-side filters, includes, and cap raise on GET /api/documents.
No client or skill changes (those are Pass 3). No commit — write evidence to DAVE_DONE.md.
```

---

## Instruction files (`DAVE_*.md` / `BOB_*.md`)

The spec itself. Lives in this directory. Read top-to-bottom by the
target before they do any work.

Every DAVE_*.md should have:

- **Scope** — exactly what to do, usually as a bullet list
- **Explicitly DEFERRED / Out of scope** — what NOT to do, with the
  reason. Dave/Bob have no way to guess what's in scope from general
  principles; they need this enumerated.
- **DO NOT list** — at minimum: "do not commit, stage, or push."
  Usually also pointers to known-adjacent bugs we're not fixing, files
  that look related but must not be touched, etc.
- **Deliverable** — usually "write evidence to `DAVE_DONE.md` with
  diff summary, test results, scope-fence call-outs, caveats."

Every BOB_*.md should have:

- **What Dave did** — one-paragraph summary, then a file table.
  Point Bob at `DAVE_DONE.md` for the full story.
- **Review checklist** — the specific things Bob should verify that
  Dave claims but couldn't self-enforce (scope fences, test counts,
  DO-NOT-touch files staying untouched, etc.).
- **Commit message** — suggested full message, usually pre-drafted.
- **Post-commit** — staging list (exact paths), push instruction,
  **STOP-and-ask-Denson step** (see below), smoke test.
- **Out of scope for this commit** — what Bob should NOT add, even
  if it seems related.

---

## DAVE_DONE.md and BOB_DONE.md

- **`DAVE_DONE.md`** lives at the repo root (untracked). Dave
  overwrites it each task with a fresh report. Sam reads it to decide
  whether to fire Bob.
- **`BOB_DONE.md`** is optional. Bob writes it only if there's
  post-commit evidence worth capturing (smoke test transcripts, deploy
  notes, anything Sam might want to reference later).

Neither is committed. They're working-tree scratch.

---

## Deploy workflow — STOP after push, do not poll prod

**Railway is NOT configured to auto-deploy on push.** The `ariadne-core`
service is in template-tracking mode (upstream repo = `denson/ariadne-core`
with an "Eject" button in Service Settings → Source). Pushes land on
`origin/main` but do not trigger a build. Denson triggers the deploy
manually via the Railway dashboard Deployments tab.

**Therefore, after Bob pushes:**

1. Report that the commit is on `origin/main` (cite the commit hash).
2. **STOP.** Tell Denson the commit is pushed and ask him to trigger
   the deploy.
3. Wait for Denson to confirm the deploy is live.
4. Only then run the smoke test.

**Never poll `/api/health` or the new endpoint in a loop waiting for
the deploy to swap in.** It won't. A 7-minute poll loop is pure
context-burn.

This rule goes away if/when Railway auto-deploy is wired up (either by
ejecting to a normal GitHub-connected service, or by adding a webhook).
Until then, the manual-trigger convention stands.

---

## Backlog protocol

Deferred items get recorded in `docs/BACKLOG.md`, NOT scattered across
`DAVE_DONE.md` or inline in closed tasks.

- Dave can **identify** backlog items during a task and flag them in
  `DAVE_DONE.md`.
- Bob **records** them in `docs/BACKLOG.md` as part of his commit,
  per the specific `BOB_*.md` prompt's backlog section.
- Each entry gets a `BL-N` id (monotonically increasing), a one-line
  title, a few lines of context, a fix direction, and an explicit
  **Blocker** line (or "none — ready to schedule").

See existing entries in `docs/BACKLOG.md` for the format.

---

## What Dave and Bob should NEVER do

- Commit or push during a Dave task. Dave never commits.
- Poll prod in a loop waiting for a Railway deploy. See Deploy
  workflow above.
- Touch files outside the explicit scope of their instruction file,
  even if the fix seems "obvious." Flag for a future task instead.
- Rewrite authorship fields, even to "fix" what looks like a wrong
  name. See `CLAUDE.md` at the repo root — authorship errors must be
  surfaced to Denson, not silently corrected.
- Remove or change savings-framing anchor numbers in
  `docs/TOKEN_SAVINGS_FRAMING.md` or the pricing/roadmap docs that
  reference it. See the guardrail in `CLAUDE.md`.

---

## Amending this protocol

Add new rules when a lesson-learned emerges. Keep entries short —
one paragraph each. If a rule needs more than that, it probably
belongs in its own doc with a one-line pointer from here.

When Denson says "make this a rule going forward," it goes here.
