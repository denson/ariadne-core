# Review + commit: Gemini auth header switch

**For:** Bob
**From:** Sam
**Companion:** `DAVE_GEMINI_AUTH_HEADER.md` (the instructions Dave executed)

Dave changed the Gemini auth header in three urllib call sites from
`Authorization: Bearer <key>` to `x-goog-api-key: <key>`, and added an
identical LLM-readable comment block above each headers dict explaining
the provider-specific choice. No commits yet. Your job: verify and push.

---

## Step 1: Read the change

```bash
git -C ariadne-core status
git -C ariadne-core diff
```

Three files should be modified, nothing else:
- `src/pipeline/embedding/embedder.py`
- `src/pipeline/enrichment/vision.py`
- `src/pipeline/extraction/text_encoding.py`

Plus `dave_and_bob_communication/DAVE_DONE.md` (Dave's report — leave it,
we clean those up separately).

---

## Step 2: Verify the substance

Check each file:

1. The `Authorization: Bearer ...` line is gone from the live headers dict.
2. Replaced with `"x-goog-api-key": <key-expression>` using the same key
   variable the old line used (`self._config.api_key` in embedder/vision,
   `config.api_key` in text_encoding).
3. A comment block sits directly above the headers dict. It should say
   roughly: this targets Gemini's OpenAI-compat endpoint, `x-goog-api-key`
   is what new `AQ.*` keys need, other providers expect
   `Authorization: Bearer`, don't build a provider abstraction — let the
   configuring agent pick the right header.
4. The three comment blocks are **identical** across the three files
   (same lesson, same words). Diff them against each other if you want
   to be sure.

Grep sanity:

```bash
cd ariadne-core
grep -rn "x-goog-api-key" src/pipeline/       # expect 3 live header matches + 3 in comment text = 6
grep -rn "Authorization.*Bearer" src/pipeline/ # expect 0 live matches; any hits should be inside the comment block only
```

If `Authorization.*Bearer` matches a **live code line** (not a comment),
stop and flag it — Dave missed a spot.

---

## Step 3: Import sanity

```bash
cd ariadne-core
python -c "from pipeline.embedding.embedder import EmbeddingClient; print('embedder OK')"
python -c "from pipeline.enrichment.vision import VisionClient; print('vision OK')"
python -c "from pipeline.extraction.text_encoding import validate_language; print('text_encoding OK')"
```

All three must print `OK`.

---

## Step 4: Commit + push

If everything checks out, commit with a message in this repo's style —
short imperative subject, one or two lines of body pointing at the new
`AQ.*` key format. Do NOT include a co-author trailer unless you already
see that pattern in recent commits on this repo.

Suggested subject: `Switch Gemini auth to x-goog-api-key header`

Body should mention: new `AQ.*`-format Gemini keys reject
`Authorization: Bearer` on the OpenAI-compat endpoint with "Multiple
authentication credentials received"; comment block in each file tells
future agents what to do if they swap providers.

Then push to the default remote/branch.

---

## Step 5: Report

Write completion to `BOB_DONE.md`: the commit SHA, the push target
(branch + remote), and any deviation from the plan. If you skipped the
push because something looked off, say so and what you saw.

No Railway action from you — Denson updates the Railway key after your
push lands.
