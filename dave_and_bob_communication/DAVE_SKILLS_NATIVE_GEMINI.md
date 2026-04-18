# Skills — native-Gemini migration (phase 2 of 8)

**For:** Dave
**Context:** Full context in `dave_and_bob_communication/NATIVE_GEMINI_OVERVIEW.md`. Phase 1 (SPEC.md) landed in commit `db676b0`. SPEC now declares Ariadne's bundled embedding, image enrichment, and language validation subsystems use Gemini native endpoints (see `SPEC.md` → `### Provider constraints`). This phase makes the deploy skill reflect that.

One file to edit: **`skills/ariadne-core-deploy/SKILL.md`**. No `.claude/skills/` mirror exists for this skill — do not create one. Only the one file is in scope.

---

## Step 1: Read the current state

Open `skills/ariadne-core-deploy/SKILL.md`. The problems to fix are concentrated in three places:

1. **Line ~41** — prerequisite says "An API key from any OpenAI-compatible provider (OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, or local models)". This claim is now only partially true for Ariadne's bundled clients.

2. **Lines ~68-78** — step 5 of first-time deploy sets `ARIADNE_EMBEDDING_MODEL=text-embedding-3-small` and `ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o-mini`. Those are OpenAI model names and do not match SPEC.md (`gemini-embedding-001` and `gemini-2.0-flash`). The surrounding prose also still tells users to point at any OpenAI-compatible provider.

3. **Lines ~115-128** — environment variables reference table shows defaults `text-embedding-3-small`, `gpt-4o-mini`, `https://api.openai.com/v1`. These defaults are all wrong relative to SPEC.md. The "Unprefixed names also work for backward compatibility" line at the bottom is a legacy concern Bob can decide to keep or drop — leave it as-is for this phase.

---

## Step 2: Edit the prerequisite (line ~41)

Replace the current bullet:

```markdown
- An API key from any OpenAI-compatible provider (OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, or local models)
```

With:

```markdown
- A **Google Gemini API key** (format `AQ.*` or legacy `AIza*`). Ariadne's bundled embedding, image enrichment, and language validation clients call Gemini native endpoints directly — see `SPEC.md` → `### Provider constraints` for the exact endpoint/payload contracts. Get a key at https://aistudio.google.com/apikey.
```

---

## Step 3: Fix step 5 of "First-time deploy" (lines ~68-78)

Replace the whole `railway variables set ...` block plus the paragraph below it:

```markdown
5. **Set environment variables:**
   ```bash
   railway variables set ARIADNE_EMBEDDING_API_KEY=your-gemini-api-key
   railway variables set ARIADNE_IMAGE_ENRICHMENT_API_KEY=your-gemini-api-key
   railway variables set ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
   railway variables set ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
   railway variables set ARIADNE_EMBEDDING_DIMENSIONS=1536
   railway variables set ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
   railway variables set ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta
   ```

   `DB_PASSWORD` is not needed — Railway provides `DATABASE_URL` directly.

   All three base URLs point at the Gemini native API root, not the OpenAI-compat shim at `/v1beta/openai`. Google's current `AQ.*`-format API keys reject every auth variant on the shim — use native only. See `SPEC.md` → `### Provider constraints` for the full contract. Reusing the same Gemini key for both `ARIADNE_EMBEDDING_API_KEY` and `ARIADNE_IMAGE_ENRICHMENT_API_KEY` is fine; use different keys only if you want separate usage tracking.
```

Keep the numbering "5." as the existing step number.

---

## Step 4: Fix the env vars table (lines ~115-128)

Update the **Default** column for these three rows:

| Variable | Required | Description |
|----------|----------|-------------|
| `ARIADNE_EMBEDDING_MODEL` | No | Default: `gemini-embedding-001` |
| `ARIADNE_EMBEDDING_BASE_URL` | No | Default: `https://generativelanguage.googleapis.com/v1beta` (Gemini native root; see `SPEC.md` → `### Provider constraints`) |
| `ARIADNE_IMAGE_ENRICHMENT_MODEL` | No | Default: `gemini-2.0-flash` |
| `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` | No | Default: `https://generativelanguage.googleapis.com/v1beta` (Gemini native root; see `SPEC.md` → `### Provider constraints`) |

Also update the description columns for the two API-key rows so they don't claim "any OpenAI-compatible provider":

| Variable | Required | Description |
|----------|----------|-------------|
| `ARIADNE_EMBEDDING_API_KEY` | Yes | API key for chunk embeddings (Google Gemini, `AQ.*` or `AIza*` format) |
| `ARIADNE_IMAGE_ENRICHMENT_API_KEY` | Yes | API key for image descriptions (Google Gemini, `AQ.*` or `AIza*` format) |

Leave `DATABASE_URL`, `PORT`, and the "Unprefixed names..." backward-compat line untouched.

---

## Step 5: Do not touch anything else

Do not edit:

- Any other skill file (`ariadne-core-build`, `ariadne-core-install`, `ariadne-core-router`, walkthrough — all deferred or out of scope).
- Any code under `src/`, `client/`, `scripts/`, `config/`, `docs/`, `tests/`.
- `.env.example`, `README.md`, `FIXES.md`, `CLAUDE.md`.
- SPEC.md — it's already correct, don't re-touch it.
- Language-validation rows — they stay as they are in this skill (the skill doesn't enumerate them; don't add them).

If you notice anything else in this skill that looks stale (e.g., the `/mcp` reference on line ~32, the `LANGUAGE_VALIDATION_*` vars not being listed), leave it for a separate pass — do not fix inline here. Flag it in `DAVE_DONE.md` so we can backlog it.

---

## Step 6: Verify

```bash
cd ariadne-core
grep -n "text-embedding-3-small\|gpt-4o-mini\|api.openai.com" skills/ariadne-core-deploy/SKILL.md
```

Expect: **zero matches.** All OpenAI-specific defaults are gone.

```bash
grep -n "generativelanguage.googleapis.com/v1beta\|gemini-embedding-001\|gemini-2.0-flash" skills/ariadne-core-deploy/SKILL.md
```

Expect: multiple matches across step 5 of the deploy instructions and the env vars table. No match should include `/v1beta/openai`.

```bash
grep -n "/v1beta/openai" skills/ariadne-core-deploy/SKILL.md
```

Expect: **zero matches** (the only acceptable reference is inside the note saying the shim is *not* used — double-check that if it hits).

```bash
git status
```

Expect: only `skills/ariadne-core-deploy/SKILL.md` tracked-modified (plus `DAVE_DONE.md`). Nothing else.

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`. Include:

- The three before/after snippets (prereq bullet, step 5 block, env vars table rows).
- Grep outputs from step 6.
- Any staleness observations you flagged for backlog.
- `git status` showing only the one skill file modified.
