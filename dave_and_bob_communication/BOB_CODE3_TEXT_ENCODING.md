# Review + commit: text-encoding language-validator native-Gemini rewrite (phase 5 of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_CODE3_TEXT_ENCODING.md`, `NATIVE_GEMINI_OVERVIEW.md`. Phases 1-4 merged (`db676b0`, `731fb49`, `e0caf2e`, `c5e923e`).

Dave rewrote `src/pipeline/extraction/text_encoding.py` so `validate_language` calls Gemini's native `:generateContent` per SPEC.md `### Provider constraints`. Dave ran a live probe (good English + mojibake garbage) and it PASSed. Your job: verify and push.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

`src/pipeline/extraction/text_encoding.py` must be the only tracked-modified file (plus `DAVE_DONE.md`, not in the commit). `scripts/_probe_text_encoding.py` should be untracked — **leave it untracked, do not `git add`.** Anything else tracked-modified is out of scope; stop and flag.

---

## Step 2: Read the diff

```bash
git diff src/pipeline/extraction/text_encoding.py
```

Verify six substantive changes match SPEC.md's `### Provider constraints`:

1. **Module docstring** — rewritten to describe native Gemini text-only call and the config-reuse of `ImageEnrichmentConfig`. No "OpenAI-compatible" claim.
2. **Endpoint construction** — now `{base}/models/{model}:generateContent`, with `models/` prefix added if the model env var didn't include it. Old `{base}/chat/completions` gone.
3. **Payload** — `{"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 256}}`. No `"messages"`, no `"max_tokens"` at top level, no `"model"` field in the body.
4. **Comment block** — the old (wrong) comment from commit `0141618` is gone. New comment explains native-only, references SPEC, tells future agents to rewrite for different providers.
5. **Response parser** — reads `candidates[0].content.parts[].text` and joins text parts. Old `result["choices"][0]["message"]["content"]` path must be gone. Empty-candidates and empty-text-parts raise `RuntimeError` (caught by the surrounding try/except that returns `coherent=True` with an error note — graceful-degradation path preserved).
6. **Fence-stripping** — before `json.loads`, strip `` ```json ... ``` `` markdown fence if present. Gemini sometimes wraps JSON replies that way.

Public API preserved — `detect_and_decode`, `LanguageValidation`, `_VALIDATION_PROMPT`, and `validate_language` all have the same names and signatures. `_VALIDATION_PROMPT` content must not have changed.

Header is `x-goog-api-key` alone — no `Authorization: Bearer`.

Graceful-degradation behavior preserved: on API errors the function still returns `LanguageValidation(coherent=True, ..., notes="LLM API call failed: ...")` so ingest never breaks on validator failure.

---

## Step 3: Grep sanity

```bash
cd ariadne-core
grep -n "Authorization.*Bearer\|/chat/completions\|\"messages\"\|\"max_tokens\"\|choices\[0\]" src/pipeline/extraction/text_encoding.py
grep -n ":generateContent\|x-goog-api-key\|generationConfig\|candidates" src/pipeline/extraction/text_encoding.py
```

- **First grep:** `Authorization.*Bearer` and `chat/completions` may appear only inside the new comment block (read context of each hit). `"messages"`, `"max_tokens"`, and `choices[0]` must be **completely absent** — these have no legitimate reason to appear in live code or comments. Any hit fails the phase.
- **Second grep:** endpoint has `:generateContent`, header is `x-goog-api-key`, payload uses `generationConfig`, parser references `candidates`. All present.

---

## Step 4: Import + probe

```bash
cd ariadne-core
python -c "from pipeline.extraction.text_encoding import detect_and_decode, validate_language, LanguageValidation; print('import OK')"
```

Expect `import OK`.

Re-run Dave's probe yourself — do not trust Dave's PASS in isolation:

```bash
python scripts/_probe_text_encoding.py
```

**Hard gate:** must print `PASS`. The good English paragraph must come back `coherent=True`; the mojibake sample must come back either `coherent=False` or `confidence=="low"`. Neither may come back `skipped=True` (that means the API key didn't load). If the probe fails, do not commit. Report what happened.

**If the probe 404s** with a stale model name, the workspace `.env` is the cause — `ARIADNE_IMAGE_ENRICHMENT_MODEL` must be a valid Gemini model. Override for the probe: `ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash python scripts/_probe_text_encoding.py`. Code correctness does not depend on which specific Gemini model the `.env` names.

---

## Step 5: Commit + push

If everything checks out, commit with a short imperative subject.

Suggested subject: `Rewrite language validator for native Gemini generateContent`

Body: migrates `validate_language` off the OpenAI-compat `/chat/completions` shim (unusable with `AQ.*` keys); now calls native `:generateContent` with a text-only part and `x-goog-api-key`; reads `candidates[0].content.parts[].text` from the response and strips `` ```json `` fences before parsing. Graceful-degradation behavior preserved — API failures still return `coherent=True` with an error note so ingest never blocks on validator failure. References SPEC.md `### Provider constraints`. Phase 5 of the native-Gemini migration.

Push to default branch.

---

## Step 6: Backlog items Dave flagged

Copy verbatim into `BOB_DONE.md` (whatever Dave listed in `DAVE_DONE.md` under "flagged for Sam/Bob" — if nothing flagged, write "none flagged by Dave").

Do **not** fix any flagged items in this commit.

---

## Step 7: Report

Write completion to `BOB_DONE.md`: commit SHA, push target, one-line confirmation that only `text_encoding.py` was included in the commit (probe script untracked), any Dave-flagged items verbatim, your own probe output (good + bad `LanguageValidation` lines + `PASS`) as independent verification.

No Railway action required — env vars already correct.
