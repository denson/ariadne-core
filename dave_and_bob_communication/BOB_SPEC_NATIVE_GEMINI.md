# Review + commit: SPEC.md native-Gemini migration (phase 1 of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_SPEC_NATIVE_GEMINI.md` (Dave's instruction), `NATIVE_GEMINI_OVERVIEW.md` (umbrella context)

Dave rewrote SPEC.md's three OpenAI-compat BASE_URL defaults to native Gemini roots and replaced the old summary paragraph with a new `### Provider constraints` section documenting `batchEmbedContents` and `generateContent` contracts. No code changed. Your job: verify and push.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

`SPEC.md` must be the only tracked file modified by this phase. `DAVE_DONE.md` is expected; ignore it. Anything else under `src/`, `skills/`, `.claude/`, `client/`, `docs/`, `tests/`, `config/`, `scripts/`, `.env.example`, `README.md`, `FIXES.md` should **not** be modified — if it is, Dave went out of scope, stop and flag.

---

## Step 2: Read the diff

```bash
git diff SPEC.md
```

Check substance:

1. **Three table rows changed, not more:**
   - `### Embedding` — `ARIADNE_EMBEDDING_BASE_URL` default → `https://generativelanguage.googleapis.com/v1beta` (no `/openai`), description → `Gemini native API root. See "Provider constraints" below.`
   - `### Image enrichment` — same change for `ARIADNE_IMAGE_ENRICHMENT_BASE_URL`.
   - `### Language validation` — same change for `ARIADNE_LANGUAGE_VALIDATION_BASE_URL`.
   - Model defaults, API-key rows, extra-params row must be untouched.

2. **Summary paragraph replaced.** The old one-paragraph "All three API subsystems ... OpenAI-compatible endpoints ... point them at any provider" line is gone. In its place, a new `### Provider constraints` subsection containing:
   - Endpoint summary table (3 rows: embedding → batchEmbedContents, image enrichment → generateContent, language validation → generateContent).
   - Auth note referencing `x-goog-api-key` and the `AQ.*` shim incompatibility.
   - `#### Embedding — batchEmbedContents contract` with request/response JSON.
   - `#### Image enrichment / language validation — generateContent contract` with vision + text-only request variants and the response shape.
   - `#### Swapping providers later` — out-of-scope note, no provider abstraction.

3. **Nothing downstream edited.** REST API section, caller metadata, ingestion, search, dedup, provenance — all must be unchanged by this diff. If the diff touches anything outside `## Configuration`, flag it.

---

## Step 3: Grep sanity

```bash
cd ariadne-core
grep -n "/v1beta/openai" SPEC.md
grep -n "batchEmbedContents\|generateContent\|x-goog-api-key" SPEC.md
```

- First grep: **zero matches**. No residual `/v1beta/openai` URL defaults.
- Second grep: all three tokens appear, only inside the new "Provider constraints" section.

If the first grep returns a match inside a prose description (not a URL default), that's acceptable if it's describing the unsupported shim path — but read the context to confirm.

---

## Step 4: Commit + push

If everything checks out, commit with a short imperative subject. No co-author trailer unless existing repo convention uses one.

Suggested subject: `Document native-Gemini migration in SPEC.md`

Body should mention: OpenAI-compat shim unsupported in v1 due to `AQ.*` key incompatibility; native `batchEmbedContents` and `generateContent` contracts documented; phase 1 of the native-Gemini migration (skills and code land in later phases).

Push to default remote/branch.

---

## Step 5: Report

Write completion to `BOB_DONE.md`: commit SHA, push target (branch + remote), a one-line confirmation that only `SPEC.md` was included in the commit, and anything you flagged or cleaned up.

No env action required — Denson has already updated the Railway BASE_URLs in advance.
