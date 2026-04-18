# Review + commit: vision native-Gemini rewrite (phase 4 of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_CODE2_VISION.md`, `NATIVE_GEMINI_OVERVIEW.md`. Phases 1-3 merged (`db676b0`, `731fb49`, `e0caf2e`).

Dave rewrote `src/pipeline/enrichment/vision.py` to call Gemini's native `:generateContent` with `inlineData` image parts per SPEC.md `### Provider constraints`. Probe against live Gemini PASSed with a 173-char reply. Your job: verify and push.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

`src/pipeline/enrichment/vision.py` must be the only tracked-modified file (plus `DAVE_DONE.md`, not in the commit). `scripts/_probe_vision.py` should be untracked — **leave it untracked, do not `git add`.** Anything else tracked-modified is out of scope; stop and flag.

---

## Step 2: Read the diff

```bash
git diff src/pipeline/enrichment/vision.py
```

Verify seven substantive changes match SPEC.md's `### Provider constraints`:

1. **Module docstring** — rewritten to describe native Gemini + `inlineData`. No "OpenAI-compatible" claim.
2. **`__init__`** — endpoint now `{base}/models/{model}:generateContent`, with `models/` prefix added if the env var didn't include it.
3. **`describe_image_from_path`** — same public signature. Internally builds `(mime_type, b64)` and routes through `describe_image_from_base64`.
4. **`describe_image_from_url`** — **new behavior:** fetches the URL bytes via `urlopen`, reads `Content-Type` header (falls back to `mimetypes.guess_type` then `image/png`), base64-encodes, routes through `describe_image_from_base64`. Raises `RuntimeError` for non-http(s) schemes. This is a semantic change worth calling out — it adds a server-side outbound HTTP dependency for URL-based describes, and the failure surface now includes URL fetch errors, not just vision-API errors.
5. **`describe_image_from_base64`** — signature unchanged. Body is now a one-liner that calls `_call_vision_api(mime_type=..., b64_data=...)`.
6. **`_call_vision_api`** — full rewrite. New signature `(self, mime_type: str, b64_data: str) -> str`. Builds native payload `{"contents": [{"parts": [{"inlineData": {...}}, {"text": prompt}]}], "generationConfig": {"maxOutputTokens": 1024}}`. Response parser reads `candidates[0].content.parts[].text` and concatenates text parts. Raises on empty candidates or empty text parts.
7. **Comment block** — the old (wrong) comment from commit `0141618` is gone. New comment explains native-only, references SPEC, tells future agents to rewrite the module for different providers.

Header is `x-goog-api-key` alone — no `Authorization: Bearer`.

Public API preserved — `VisionConfig`, `VisionClient`, `DEFAULT_PROMPT`, and the three `describe_image_from_*` methods all have the same names and signatures.

---

## Step 3: Grep sanity

```bash
cd ariadne-core
grep -n "Authorization.*Bearer\|/chat/completions\|\"messages\"\|\"image_url\"\|\"max_tokens\"" src/pipeline/enrichment/vision.py
grep -n ":generateContent\|x-goog-api-key\|inlineData\|generationConfig" src/pipeline/enrichment/vision.py
```

- **First grep:** Dave flagged that `chat/completions` and `image_url` still appear in the new comment block (documenting what a future provider swap would need). Read the context of each hit — acceptable only inside the comment. Any hit in live code fails the phase. `"messages"` and `"max_tokens"` must be completely absent. The public method name `describe_image_from_url` will hit if your grep is too loose — narrow with the quote pattern `"image_url"` to catch only the payload key.
- **Second grep:** endpoint has `:generateContent`, header is `x-goog-api-key`, payload uses `inlineData`, generation config uses `generationConfig` / `maxOutputTokens`. All present.

---

## Step 4: Import + probe

```bash
cd ariadne-core
python -c "from pipeline.enrichment.vision import VisionClient, VisionConfig; print('import OK')"
```

Expect `import OK`.

Re-run Dave's probe yourself — do not trust Dave's PASS in isolation:

```bash
python scripts/_probe_vision.py
```

**Hard gate:** must print `PASS` with endpoint ending `:generateContent` and a non-empty reply. If it fails, do not commit. Report what happened.

A 1×1 PNG will produce a very short reply. That's fine — we're testing round-trip, not description quality. Dave's probe came back describing the pixel as yellow/white, which is Gemini guessing on a near-empty image — expected noise.

**If the probe 404s** with `text-embedding-*` or some other stale model name, the workspace `.env` is the cause — check that `ARIADNE_IMAGE_ENRICHMENT_MODEL` is a valid Gemini vision model (`gemini-2.0-flash` is the SPEC default, but Dave's run used a preview model from the local `.env`). Override for the probe: `ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash python scripts/_probe_vision.py`. Code correctness does not depend on which specific Gemini vision model the `.env` names.

---

## Step 5: Commit + push

If everything checks out, commit with a short imperative subject.

Suggested subject: `Rewrite vision client for native Gemini generateContent`

Body: migrates off the OpenAI-compat `/v1beta/openai/chat/completions` shim (unusable with `AQ.*` keys); now calls native `:generateContent` with `inlineData` image parts and `x-goog-api-key`; reads `candidates[0].content.parts[].text` from the response. `describe_image_from_url` now fetches URL bytes server-side because Gemini native does not accept HTTP(S) image URLs directly (public API preserved, but outbound-HTTP failure surface added). References SPEC.md `### Provider constraints`. Phase 4 of the native-Gemini migration.

Push to default branch.

---

## Step 6: Backlog items Dave flagged

Copy verbatim into `BOB_DONE.md`:

1. Workspace `.env` has `ARIADNE_IMAGE_ENRICHMENT_MODEL` pointing at a preview model (`gemini-3.1-flash-lite-preview`). SPEC default is `gemini-2.0-flash`. Denson's local `.env` choice, not a code problem; flag for awareness.
2. `src/pipeline/config.py` default for `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` unverified this phase — deferred to phase 6 (`DAVE_CODE4_CONFIG_DOCS_ENV.md`).
3. New outbound-HTTP egress dependency: `describe_image_from_url` now performs a server-side fetch of the image URL before calling Gemini. Increases attack surface (SSRF) and egress billing if the server ever handles attacker-controlled URLs. Ariadne uses this only for images referenced inside extracted documents, so the blast radius is limited, but worth an audit when we next touch the enrichment path.
4. Probe returned a reply describing the pixel as yellow/white (actual PNG is 1×1 pure white). This is Gemini hallucinating detail on a near-empty image — not a code bug, just noise worth noting in case a future agent chases the discrepancy.

Do **not** fix any of these in this commit.

---

## Step 7: Report

Write completion to `BOB_DONE.md`: commit SHA, push target, one-line confirmation that only `vision.py` was included in the commit (probe script untracked), the four backlog items verbatim, your own probe output (PASS + reply text) as independent verification.

No Railway action required — env vars already correct.
