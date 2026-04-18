# Review + commit: embedder native-Gemini rewrite (phase 3 of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_CODE1_EMBEDDER.md` (Dave's instruction), `NATIVE_GEMINI_OVERVIEW.md` (umbrella). Phases 1 (`db676b0`) and 2 (`731fb49`) are merged.

Dave rewrote `src/pipeline/embedding/embedder.py` to call Gemini's native `:batchEmbedContents` per SPEC.md `### Provider constraints`. He ran a live probe against Gemini and got a 1536-dim embedding back with `gemini:` tool label. Your job: verify and push.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

`src/pipeline/embedding/embedder.py` must be the only tracked-modified file (plus `DAVE_DONE.md`, not in the commit). `scripts/_probe_embedder.py` should be listed as untracked — **leave it untracked, do not `git add`.** Anything else tracked-modified is out of scope; stop and flag.

---

## Step 2: Read the diff

```bash
git diff src/pipeline/embedding/embedder.py
```

Verify six substantive changes match SPEC.md's `### Provider constraints`:

1. **Module docstring** — rewritten to describe native Gemini; no "OpenAI-compatible" claim.
2. **`__init__`** — endpoint now built as `{base}/models/{model}:batchEmbedContents`, with `models/` prefix added if the env var didn't include it. Stores `self._model_path` for use in the payload.
3. **Payload** — shape is `{"requests": [{"model": "models/...", "content": {"parts": [{"text": t}]}, "outputDimensionality": N}, ...]}` per SPEC. `outputDimensionality` is only set if `config.dimensions` truthy.
4. **Request headers + comment block** — the old (wrong) comment from commit `0141618` is gone. The new comment explains native-only, references SPEC, tells future agents to rewrite the module if swapping providers. Header is `x-goog-api-key` alone — no `Authorization: Bearer`, no both-headers.
5. **Response parser** — reads `result["embeddings"][i]["values"]`. Old `result["data"][i]["embedding"]` path must be gone. `total_tokens = 0` with a comment explaining native endpoint doesn't return usage.
6. **`chain_entry["tool"]`** — both call sites (`embed_texts` and `_embed_in_batches`) say `f"gemini:{model}"`, not `f"openai:{model}"`.

Public API unchanged — `EmbeddingConfig`, `EmbeddingResult`, `EmbeddingClient`, `embed_texts`, `embed_query`, `MAX_BATCH_SIZE = 100`, retry logic, `_embed_in_batches`, `enabled`, `model`, `dimensions` all preserved.

---

## Step 3: Grep sanity

```bash
cd ariadne-core
grep -n "Authorization.*Bearer\|openai:" src/pipeline/embedding/embedder.py
grep -n ":batchEmbedContents\|x-goog-api-key\|gemini:" src/pipeline/embedding/embedder.py
grep -n '"input"\|"data"' src/pipeline/embedding/embedder.py
```

- First grep: **zero matches** (no residual Bearer, no `openai:` tool label).
- Second grep: endpoint has `:batchEmbedContents`, header is `x-goog-api-key`, two `gemini:` tool labels.
- Third grep: **zero matches** for the OpenAI-compat payload keys (`"input"`, `"data"`). If either appears, the rewrite is incomplete.

---

## Step 4: Import + probe

```bash
cd ariadne-core
python -c "from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig; print('import OK')"
```

Expect `import OK` with no traceback.

Re-run Dave's probe yourself against live Gemini — do not trust Dave's PASS in isolation:

```bash
python scripts/_probe_embedder.py
```

**Hard gate:** must print `PASS` with endpoint ending `:batchEmbedContents`, three embeddings, dimension matching `ARIADNE_EMBEDDING_DIMENSIONS`, tool prefix `gemini:`. If it fails — 400, 401, import error, anything — do not commit. Report what happened.

**Note on `.env`:** Dave flagged that the workspace `.env` had `ARIADNE_EMBEDDING_MODEL=text-embedding-004` (stale OpenAI-era value) which 404s on native. If your probe fails with a 404 and the error mentions `text-embedding-004`, the cause is the local `.env`, not Dave's code. Denson will fix that separately — but the code still has to pass with a correct `.env`. If you need to override just for the probe: `ARIADNE_EMBEDDING_MODEL=gemini-embedding-001 python scripts/_probe_embedder.py`.

---

## Step 5: Commit + push

If everything checks out, commit with a short imperative subject.

Suggested subject: `Rewrite embedder for native Gemini batchEmbedContents`

Body: migrates off the OpenAI-compat `/v1beta/openai/embeddings` shim (unusable with `AQ.*` keys); now calls native `:batchEmbedContents` with `x-goog-api-key`; reads `embeddings[].values` from the response; `total_tokens` reported as 0 since the native endpoint omits usage. References SPEC.md `### Provider constraints`. Phase 3 of the native-Gemini migration.

Push to default branch.

---

## Step 6: Backlog items Dave flagged

Copy verbatim into `BOB_DONE.md`:

1. Workspace `.env` has stale `ARIADNE_EMBEDDING_MODEL=text-embedding-004` — must be `gemini-embedding-001` for native. Denson needs to update his local `.env`. (Railway `.env` values are already correct; this is the workspace-only copy used by local probes.)
2. `src/pipeline/config.py` default for `ARIADNE_EMBEDDING_BASE_URL` may still point at `https://api.openai.com/v1` — **unverified this phase, do not fix here.** Phase 6 (`DAVE_CODE4_CONFIG_DOCS_ENV.md`) covers config.py + all defaults + env templates.
3. `total_tokens` from embedding now always 0 because native `:batchEmbedContents` omits `usage` in the response. No known consumer breaks, but telemetry / billing dashboards that read this field will see zeros. Flagged for awareness, not action.

Do **not** fix any of these in this commit.

---

## Step 7: Report

Write completion to `BOB_DONE.md`: commit SHA, push target, one-line confirmation that only `embedder.py` was included in the commit (probe script stayed untracked), the three backlog items verbatim, and your own probe output (PASS + dimensions) as independent verification.

No Railway action required — env vars are already correct there.
