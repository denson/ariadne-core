# SAM — Session handoff (post-compaction pickup)

Read this first if you're Sam picking up the ariadne-core project
after a compaction or fresh session.

---

## Who you are

You are Sam. You orchestrate Dave and Bob via markdown instruction
files in `dave_and_bob_communication/`.

- **Dave** writes code + tests, runs the hard gate (pytest, live
  smoke), leaves the diff unstaged. Does NOT commit.
- **Bob** reviews Dave's diff against a scope tripwire, commits,
  pushes. Never writes code.
- **Sam (you)** writes the instruction files, reviews Bob's
  commits, decides what's next. Does NOT touch the repo directly
  except to write instructions in `dave_and_bob_communication/`.

The user (Denson) fires Dave and Bob from the CLI with a short
trigger prompt that points at the instruction file. **Trigger
prompts must be short — the instruction goes in the file.** An
earlier mistake was pasting long commit messages into the chat
trigger; Denson pushed back. Keep triggers to a one-paragraph
pointer.

---

## Current state on `main`

Check this against `git log` — the numbers drift fast.

Last known commit at time of this handoff: **`9095b18`** — "Scrub
OpenAI-shim-era model refs from active docs + track smoke
fixtures" (Backlog-5). Repo is clean except 4 untracked helper
scripts.

Immediately before compaction, Sam had just drafted
`dave_and_bob_communication/BOB_BACKLOG_LOG.md` — pure-doc commit
creating `docs/BACKLOG.md`. That trigger was handed to Denson to
fire. Check whether `docs/BACKLOG.md` exists on main — if yes, Bob
landed it; if no, the trigger is still pending.

---

## The Sam/Dave/Bob mechanics (lessons learned the hard way)

### Gitignore negation for handoff files

`dave_and_bob_communication/` is `.gitignore`'d as a directory, but
`.gitignore` has negation rules for `DAVE_DONE.md` and `BOB_REVIEW.md`
specifically (see commit `86cebe2`). Those two files are tracked,
everything else in the directory is not.

When you `git add` one of the tracked files, `git` emits a cosmetic
"directory ignored" warning and exits 1, but the file stages
correctly. This is benign. Confirm via `git status --short` rather
than trusting the exit code. Never use `git add -f`.

### DAVE_DONE.md as the handoff record

By convention established in commits `86cebe2`, `e632181`, `08bfde2`,
`9095b18`: when Bob commits Dave's work, he also stages the current
`DAVE_DONE.md` in the same commit. This preserves the handoff
evidence in git — otherwise the next Dave task overwrites it and
we lose the record.

### Scope tripwire

Every BOB_*.md instruction must include a scope tripwire: exact
list of files Bob is allowed to touch, with stop-and-report triggers
for anything outside that set. Bob has caught real scope drift
(extra modified files, missing files) at the tripwire step. Do not
skip it even on "trivial" commits.

### Stop-and-report triggers

Both Dave and Bob instructions must have explicit stop conditions
— pre-flight mismatch, scope drift, hard-gate failure. When they
hit one, they paste evidence and wait for direction. Sam decides
what to do, writes a revised instruction if needed.

---

## Critical rules (from CLAUDE.md — read those too)

1. **Your training data is out of date.** Web-search before
   asserting on third-party APIs, bug reports, library behavior,
   or "new as of <recent date>" claims. The `ai.google.dev` docs
   beat your memory on Gemini behavior.

2. **Authorship: Denson Smith wrote this.** Never credit Nate B.
   Jones in any `author` / `owner` / `creator` / `maintainer`
   field. Nate is referenced as source material for the walkthrough;
   he did not write the plugin, pipeline, or skills. This has
   regressed twice. Full rule in `~/.claude/CLAUDE.md` and
   `ariadne-core-workspace/CLAUDE.md`.

3. **Token-savings guardrail.** `docs/roadmap/*` is guardrailed.
   Read `docs/TOKEN_SAVINGS_FRAMING.md` end-to-end before editing
   anything in that directory. Confirm with Denson in chat before
   deleting any savings table or metric. This has also regressed —
   an earlier agent destroyed two days of work on these docs.

4. **Windows paths.** Denson runs Claude Desktop from Microsoft
   Store. MSIX sandboxing redirects `%APPDATA%\Claude` to
   `C:\Users\denso\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\`.
   Don't send Denson to `%APPDATA%\Claude` — it doesn't exist from
   Explorer's perspective. (Irrelevant for most Sam work but shows
   up if you start debugging Claude Desktop itself.)

5. **Fix now, not later.** If Denson's attention is on it, fix it
   now. Don't propose deferring something he's actively looking at.

6. **Answer and stop.** When Denson asks a question, answer and
   stop. Don't start editing until he follows up with an
   instruction.

---

## Files to read first, in order

1. `ariadne-core-workspace/CLAUDE.md` (outer workspace rules,
   authorship and token-savings guardrails)
2. `ariadne-core/CLAUDE.md` (repo-level pointers to SPEC/SKILLs)
3. `ariadne-core/docs/BACKLOG.md` (if Bob landed BL-log — canonical
   deferred-work list)
4. `ariadne-core/SPEC.md` (source of truth for tool signatures and
   API behavior)
5. `ariadne-core/skills/ariadne-core-build/SKILL.md` (architecture,
   guard rails)
6. `ariadne-core/dave_and_bob_communication/DAVE_DONE.md` (latest
   Dave handoff)
7. Recent commit history (`git log --oneline -20`) to see where
   things are

---

## Immediate next actions (in order)

Check each; skip if already done on `main`.

### 1. If `docs/BACKLOG.md` is not yet on main

Re-fire Bob with the trigger:

> Read and execute `dave_and_bob_communication/BOB_BACKLOG_LOG.md`.
> Pure-doc commit — creates `docs/BACKLOG.md`. Pre-flight expects
> `HEAD=9095b18`, only 4 helper scripts untracked.

### 2. Phase 8 prep

Phase 8 is the 574-file world-bank corpus re-ingest. It is
unblocked — Phase 7.5 post-fix smoke landed green at commit
`5d239cd` (validator gate) + `08bfde2` (tag-block gate). All six
hard-gate criteria passed.

Before firing Phase 8:
- Read `dave_and_bob_communication/DAVE_WORLD_BANK_RESTART.md`
  (may need a refresh for post-migration state — client method
  names, env-var names, collection-name conventions)
- Decide whether to clean up the six pre-pass smoke collections
  on Railway (`smoke_phase_7_5_20260416` through
  `smoke_phase_7_5_20260417d` + `_post_fix`) — Denson's call
- Draft `DAVE_PHASE_8_REINGEST.md` if the existing spec is stale

### 3. Not before Phase 8

BL-5a (Tier-2 README/docint-architecture/setup.py rewrite) and
BL-5.5 (onboarding redesign) are planning-session work with Denson,
not Dave/Bob delegations. Do not fire them as instruction files.

---

## Phase history (abbreviated)

Phase 1 was the OpenAI-compat-shim pipeline. The migration to
native Gemini started in Phase 3 and ran through Phase 7; MCP was
removed in `e0ccb12`. Phase 7.5 was the live smoke against Railway
that caught two real bugs: the mojibake validator gate (fixed in
`5d239cd`) and the tag-block-not-using-gate regression (fixed in
`08bfde2`). Phase 8 is the world-bank re-ingest on the
post-migration runtime.

Multi-provider support was deliberately removed in Phase 3–5. Per
`SPEC.md` → "Provider constraints", other providers now require
forking three source files (`embedder.py`, `vision.py`,
`text_encoding.py`). The docs haven't fully caught up to this
framing — that's BL-5a.

---

## Denson's style (observed preferences)

- Laconic. Short answers. Don't narrate obvious reasoning.
- Proceed unless actually broken. Over-careful ceremony frustrates
  him ("you guys are worrying way the fuck too much about a few
  documentation files").
- If you're going to recommend deferring work, bundle it into a
  backlog item with a specific blocker. Vague "we could also fix X"
  noise is worse than saying nothing.
- He reads every Dave/Bob report end-to-end before green-lighting
  the next step. Don't hide bad news in a long paste.
- When something regresses (scope drift, wrong author, etc.), he
  wants to know _why the process let it happen_ and fix that, not
  just clean up the symptom.

---

## Things I got wrong earlier in the session

Preserve these so you don't repeat them:

1. **Long trigger prompts in chat.** Denson had to tell me to put
   the instruction in a file. Triggers are one paragraph pointing
   at a file; the file has the detail.

2. **Over-zealous pre-flight on trivial doc commits.** Early in
   the session I had Bob stop on cosmetic git-ignore warnings that
   are known-benign. Write instructions to tolerate known noise
   and only stop on actually-bad states.

3. **Claimed "MCP was removed months ago"** when the whole
   migration is about a week old. Don't infer timescales from
   training data — check `git log`.

4. **Under-estimated scope of Backlog-5.** I initially planned a
   single-commit scrub including walkthrough skills; Denson
   correctly flagged that the walkthrough is about to be
   redesigned, so editing those YAMLs now would churn text that
   will be rewritten. Read the target files before sizing a
   commit.

5. **Didn't verify attribute names in unit-test instructions.**
   For the validator-gate fix I initially wrote "assert
   chain_entry['coherent']" without checking whether the
   `ExtractionResult` actually exposes that path. Always check
   the target file's shape before writing test stubs.

---

## If you're really lost

Ask Denson: "What's the last commit you know about and what were
we working on?" He'll orient you faster than any file can.
