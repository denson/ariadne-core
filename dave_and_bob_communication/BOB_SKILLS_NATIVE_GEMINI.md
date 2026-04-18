# Review + commit: deploy skill native-Gemini update (phase 2 of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_SKILLS_NATIVE_GEMINI.md` (Dave's instruction), `NATIVE_GEMINI_OVERVIEW.md` (umbrella context). Phase 1 landed in `db676b0`.

Dave updated `skills/ariadne-core-deploy/SKILL.md` so its prereqs, first-time-deploy env vars, and env vars reference table all match SPEC.md's `### Provider constraints`. No `.claude/` mirror exists for this skill. Your job: verify and push.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

`skills/ariadne-core-deploy/SKILL.md` must be the only tracked file modified (plus `DAVE_DONE.md`, which is expected and should not be in the commit). Anything else under `src/`, `client/`, `docs/`, `tests/`, `config/`, `scripts/`, `SPEC.md`, `.env.example`, `README.md`, `FIXES.md`, `CLAUDE.md`, or any other skill should **not** be modified. If it is, stop and flag.

---

## Step 2: Read the diff

```bash
git diff skills/ariadne-core-deploy/SKILL.md
```

Check:

1. **Prereq bullet** (~line 41) now points at a Google Gemini API key (`AQ.*` or `AIza*`), references SPEC.md's Provider constraints, and includes the AI Studio link. No more "any OpenAI-compatible provider" blanket claim.

2. **First-time deploy step 5** (~lines 68-80) sets `ARIADNE_EMBEDDING_*` and `ARIADNE_IMAGE_ENRICHMENT_*` to Gemini native values (`gemini-embedding-001`, `gemini-2.0-flash`, `https://generativelanguage.googleapis.com/v1beta`, plus `ARIADNE_EMBEDDING_DIMENSIONS=1536`). The prose below the code block no longer pitches "any OpenAI-compatible provider" and explicitly says the `/v1beta/openai` shim is unusable with `AQ.*` keys.

3. **Env vars reference table** (~lines 115-128) default columns now show Gemini-native values for `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `IMAGE_ENRICHMENT_MODEL`, `IMAGE_ENRICHMENT_BASE_URL`. Description columns for the two API-key rows reference Google Gemini and the `AQ.*` / `AIza*` formats.

4. **Not touched:** `DATABASE_URL` / `PORT` rows, the "Unprefixed names..." backward-compat line, the adapting-to-other-platforms section, the `/mcp` reference on line ~32 (Dave flagged it for backlog — correct call, do not fix inline here), and any missing `LANGUAGE_VALIDATION_*` rows (also backlog).

---

## Step 3: Grep sanity

```bash
cd ariadne-core
grep -n "text-embedding-3-small\|gpt-4o-mini\|api.openai.com" skills/ariadne-core-deploy/SKILL.md
```

Expect: **zero matches.**

```bash
grep -n "generativelanguage.googleapis.com/v1beta" skills/ariadne-core-deploy/SKILL.md
grep -n "gemini-embedding-001\|gemini-2.0-flash" skills/ariadne-core-deploy/SKILL.md
```

Expect: multiple matches across step 5 and the env vars table.

```bash
grep -n "/v1beta/openai" skills/ariadne-core-deploy/SKILL.md
```

Expect: **zero matches**, or one match only inside a prose sentence explicitly saying the shim is unsupported — read the context to confirm that's the only hit.

---

## Step 4: Commit + push

If everything checks out, commit with a short imperative subject.

Suggested subject: `Update deploy skill for native-Gemini provider`

Body: match SPEC.md Provider constraints; Gemini native endpoints only for bundled clients; `AQ.*` keys reject the OpenAI-compat shim; phase 2 of the native-Gemini migration (code lands in later phases).

No co-author trailer unless existing repo convention uses one. Push to the default branch.

---

## Step 5: Backlog items Dave flagged

Dave's `DAVE_DONE.md` flagged four pre-existing stalenesses in this skill:

1. Line ~32 `/mcp` reference (MCP was removed project-wide).
2. Missing `LANGUAGE_VALIDATION_*` rows in the env vars table.
3. Fly.io block still uses legacy `sk-*` placeholders.
4. "Unprefixed names..." backward-compat line may be obsolete.

Do **not** fix any of these in this commit — they're out of scope. Copy the list verbatim into `BOB_DONE.md` so Sam can add them to workspace `BACKLOG.md` in a separate pass.

---

## Step 6: Report

Write completion to `BOB_DONE.md`: commit SHA, push target (branch + remote), one-line confirmation that only `skills/ariadne-core-deploy/SKILL.md` was included, and the four backlog items repeated verbatim.

No env action required — Railway base URLs are already updated.
