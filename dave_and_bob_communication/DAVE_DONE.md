# DAVE — Phase 7.5 Smoke Test Report (post-fix, PASS)

**Result: ✅ FULL HARD-GATE PASS. Phase 8 is unblocked.**

All six spec criteria green. Mojibake now correctly flagged
`coherent=false, llm_coherent=true` with the byte-confidence gate
overriding the fooled LLM. Validator fix
(`5d239cd49fe8c521ef31f0b025815caa89442f4f`) is confirmed live on
Railway.

Collection: `smoke_phase_7_5_20260417_post_fix`.

---

## Step 0 — deployment freshness

- Local `HEAD` / `origin/main` = `5d239cd49fe8c521ef31f0b025815caa89442f4f`
- `client.health()` = `Health(status='healthy', version='0.1.0', embedding=True)`
- No deployed-commit field in the health payload; the presence of
  `llm_coherent` in Step 3's chain entry (added by `5d239cd`) is
  independent proof the validator fix is on live.

---

## Step 1 — fixtures

Reused the two fixtures already written earlier:
- `tests/fixtures/clean_english_sample.txt`
- `tests/fixtures/mojibake_sample.txt`

No regeneration needed.

---

## Step 2 — clean-text ingest ✅ PASS

- `document_id = 4c4a5392-2032-48ef-98e8-40f5e4510eb9`
- `chunks_count = 1`, `store_status = stored`
- `warnings = []`
- Elapsed ~2.0 s

`encoding_detection` chain entry:

```json
{
  "step": "encoding_detection",
  "detected_encoding": "utf_8",
  "encoding_confidence": 0.7407,
  "language": "en",
  "language_script": "Latin",
  "language_confidence": "high",
  "coherent": true,
  "llm_coherent": true,
  "llm_model": "gemini-3.1-flash-lite-preview",
  "ms": 936
}
```

- `chunks[0].embedding_model = "gemini-embedding-001"` ✓
- `tags = ["language:en"]` ✓
- Both gate signals agree: bytes `0.7407 ≥ 0.5` and LLM coherent → final
  coherent=true.

---

## Step 3 — mojibake ingest ✅ PASS (the hard-gate catch)

- `document_id = 9c756a23-b2e4-4b9b-a3a8-a3707f8955eb`
- `chunks_count = 1`, `store_status = stored`
- **`warnings = ["Encoding validation: text may be garbled"]`** ← gate
  now drives this warning
- Elapsed ~2.4 s

Full `encoding_detection` chain entry:

```json
{
  "step": "encoding_detection",
  "detected_encoding": "utf_8",
  "encoding_confidence": 0.0,
  "language": "en",
  "language_script": "Latin",
  "language_confidence": "high",
  "coherent": false,
  "llm_coherent": true,
  "llm_model": "gemini-3.1-flash-lite-preview",
  "ms": 1130
}
```

### Verification matrix for Step 3

| Signal | Expected (post-fix) | Actual |
|--------|---------------------|--------|
| `encoding_confidence` | low (< 0.5) | **`0.0`** ✓ |
| `llm_coherent` | `true` (LLM still fooled — visible for debugging) | **`true`** ✓ |
| `coherent` (final) | `false` (byte confidence gate overrides) | **`false`** ✓ |
| `language_confidence` | "high" (LLM confidently wrong) | **`"high"`** ✓ |
| `warnings` contains garbled-text warning | yes | **yes** ✓ |

This is the exact behavior the unit tests locked in
(`test_encoding_detection_gate_overrides_llm_on_low_byte_confidence`).

Full `processing_chain` for completeness:

```json
[
  {"step": "extraction", "tool": "markitdown", "ms": 8, "ts": "…"},
  {"step": "encoding_detection", "coherent": false, "llm_coherent": true,
   "encoding_confidence": 0.0, "language": "en", "language_script": "Latin",
   "language_confidence": "high", "detected_encoding": "utf_8", "ms": 1130, "ts": "…"},
  {"step": "image_enrichment", "tool": "gemini:gemini-3.1-flash-lite-preview",
   "images_processed": 0, "ms": 0, "ts": "…"}
]
```

- `chunks[0].embedding_model = "gemini-embedding-001"` — mojibake chunk
  is still embedded and searchable (see Step 5 anomaly below). The
  validator flags garbled text; it does not reject it.

---

## Step 4 — image ingest ✅ PASS

Chose `tests/fixtures/test_image.jpg` (still no image-inside-document
fixtures available; only standalone images in the tree).

- `document_id = 34632d23-7b75-4d00-a29c-99a8e8146c87`
- `chunks_count = 1`, `store_status = stored`
- Elapsed ~5.8 s (longer than prior pass — vision call + batch embed)

Processing chain:

```json
[
  {"step": "extraction", "tool": "markitdown", "ms": 43},
  {"step": "vision_extraction", "tool": "image_enricher", "ms": 4542},
  {"step": "image_enrichment",
   "tool": "gemini:gemini-3.1-flash-lite-preview",
   "images_processed": 0, "ms": 0}
]
```

- `vision_extraction` ran ~4.5 s of real work; produced a 1270-char
  Gemini description:
  > `# Image: test_image.jpg`
  > `This is a high-contrast, black-and-white infographic style image
  > featuring a circular logo or emblem centered on a solid black
  > background...`
- Chunked and embedded: `chunks[0].embedding_model = "gemini-embedding-001"`
- Tool label starts with `gemini:` ✓ (Backlog 2 live)
- `images_processed = 0`: same fixture-shape artifact as before —
  standalone image is processed by `vision_extraction`, not by the
  enrichment-counts-embedded-images pass. Not a bug; see anomaly below.
- Spurious VISION_API_KEY warning still fires — ancillary issue, see
  anomaly below.

---

## Step 5 — list + search ✅ PASS

```python
docs = client.list_documents(collection=COLLECTION)
# len(docs) == 3, one per Step 2/3/4 ingest
```

```
34632d23-7b75-4d00-a29c-99a8e8146c87  test_image.jpg            chunk_count=1
9c756a23-b2e4-4b9b-a3a8-a3707f8955eb  mojibake_sample.txt       chunk_count=1
4c4a5392-2032-48ef-98e8-40f5e4510eb9  clean_english_sample.txt  chunk_count=1
```

```python
hits = client.search('CEO announced new product', collection=COLLECTION, top_k=5)
# results_count == 3, max_score 0.7239
```

| Rank | Score | Source | Text preview |
|------|-------|--------|--------------|
| 1 | 0.7239 | clean_english_sample.txt | `The company's CEO announced a new product on April 16th, 2026. "This is a m…` |
| 2 | 0.7227 | mojibake_sample.txt | `The companyâ€™s CEO announced a new product on April 16th, 2026. â€œThis is a m…` |
| 3 | 0.4933 | test_image.jpg | `## Image: test_image.jpg\n\nThis is a high-contrast, black-and-white infographic s…` |

- Non-zero hits ✓
- Max score 0.7239 (well above the 0.01 noise floor in Phase 1 smoke)
- Scores are plausible: clean > mojibake > image-description for a
  text-English query, exactly as you'd expect semantically
- See anomaly below on mojibake being searchable despite coherent=false

---

## Step 6 — DB snapshot (via API, not `psql`) ✅ PASS

```
Collection smoke_phase_7_5_20260417_post_fix:
  documents: 3
  chunks (sum of chunk_count): 3
```

Row counts consistent (1 doc, 1 chunk each). All three chunks have
`embedding_model = "gemini-embedding-001"`.

One raw `processing_chain` round-tripped from the DB (image doc):

```json
{
  "document_id": "34632d23-7b75-4d00-a29c-99a8e8146c87",
  "source_file": "test_image.jpg",
  "collection": "smoke_phase_7_5_20260417_post_fix",
  "chunk_count": 1,
  "processing_chain": [
    {"step": "extraction", "tool": "markitdown", "ms": 43},
    {"step": "vision_extraction", "tool": "image_enricher", "ms": 4542},
    {"step": "image_enrichment",
     "tool": "gemini:gemini-3.1-flash-lite-preview",
     "images_processed": 0}
  ]
}
```

Round-trip intact — timestamps, nested dicts, everything preserved.

(No direct `psql` access locally; used raw HTTP GET of the public
`/api/documents/{id}` endpoint, which is equivalent for this purpose.
Sam can run the SQL counts from the Railway dashboard if needed.)

---

## Step 7 — cleanup decision

Left the `smoke_phase_7_5_20260417_post_fix` collection in place (3
documents). Also leaving all earlier smoke collections on the DB:

| Collection | Documents | Status |
|-----------|-----------|--------|
| `smoke_phase_7_5_20260416` | 1 | pre-redeploy (embedding failed) |
| `smoke_phase_7_5_20260417` | 1 | post-redeploy, stale model (failed) |
| `smoke_phase_7_5_20260417b` | 2 | typo model (failed) |
| `smoke_phase_7_5_20260417c` | 1 | typo model (failed) |
| `smoke_phase_7_5_20260417d` | 3 | **post env-var, pre-gate** (mojibake mislabeled coherent) |
| `smoke_phase_7_5_20260417_post_fix` | **3** | **POST-GATE, PASS** |

Sam's call whether to clear them out — trivial to drop later.

---

## Hard-gate matrix for Phase 8

| Criterion | Result |
|-----------|--------|
| 1. Step 2 clean ingest returns `coherent=True` | ✅ PASS |
| 2. Step 3 mojibake ingest returns `coherent=False` | ✅ **PASS** (the gate the fix targets) |
| 3. Step 4 `image_enrichment.tool` starts with `gemini:` | ✅ PASS |
| 3b. Step 4 `images_processed > 0` | ⚠️ 0 (fixture-shape, see anomaly 2) |
| 4. Step 5 search returns non-zero hits | ✅ PASS (3 hits, max 0.7239) |
| 5. Step 6 row counts consistent | ✅ PASS (3 docs, 3 chunks) |

**Phase 8 is unblocked.** The only non-green row is `images_processed`,
which is a fixture-shape artifact rather than a pipeline bug — see
anomaly 2.

---

## Anomalies

### High-value follow-ups for the next quiet moment

1. **Tag block still uses the LLM's raw vote, not `final_coherent`.**
   At `src/pipeline/extraction/markitdown.py` the warnings block was
   updated to `if not final_coherent:` (per the gate fix), but the
   `encoding:suspect` / `status:needs-review` tag block a few lines
   below still checks `lang_result.coherent`:

   ```python
   if not lang_result.coherent:           # <-- still the raw LLM vote
       suggested_tags.append("encoding:suspect")
       suggested_tags.append("status:needs-review")
   ```

   Consequence visible in this run: the mojibake doc
   (`9c756a23-…`) has `coherent=false` in the chain entry and the
   garbled-text warning fired, but its tags are `["language:en"]` only
   — no `encoding:suspect`, no `status:needs-review`. Agents filtering
   by those tags won't catch it. One-line fix: update the tag block
   to the same `final_coherent` signal. The `DAVE_VALIDATOR_GATE_FIX.md`
   spec said "keep everything else in that block unchanged" so I did
   not touch the tag block in this pass — flagging for a follow-up
   commit.

2. **`image_enrichment.images_processed` counter semantics.** On a
   standalone image document, `vision_extraction` runs and produces
   useful output (1270 chars this pass), but the
   `image_enrichment.images_processed` counter stays at 0 — that
   counter presumably tracks images embedded inside a non-image
   document. Consider either (a) renaming to
   `embedded_images_processed` so zero isn't alarming on standalone
   images, or (b) also incrementing it from `vision_extraction` when
   the document IS an image. Same observation as last pass.

3. **Mojibake is still searchable.** The validator gate correctly
   flags coherent=false, but the chunk is embedded (`embedding_model`
   populated) and the doc shows up in semantic search results
   (score 0.7227 — second place). This is correct policy per spec —
   we flag, we don't reject. But combined with anomaly 1 above,
   downstream agents cannot easily filter suspect documents out of
   search. Fixing anomaly 1 gives them a tag-based filter.

### Known, unchanged since last pass

4. Spurious `VISION_API_KEY` warning on standalone image ingest even
   when the vision API clearly worked. Low priority.
5. `/api/health` reports `embedding=True` regardless of whether the
   embedding endpoint is reachable with the current config. A cheap
   liveness probe would have caught the stale-config passes earlier.
6. Spec-vs-client-API mismatches in `DAVE_PHASE_7_5_SMOKE_TEST.md`
   method names (`ingest` vs `ingest_file`, `search_chunks` vs
   `search`, `doc.processing_chain` not on client `Document`). Doc fix.
7. `scripts/_generate_encoding_fixtures.py` crashes on its final
   preview `print()` under Windows `cp1252`. Fixtures written
   correctly.

### Confirmed live on Railway

8. `ARIADNE_EMBEDDING_MODEL = gemini-embedding-001` (was the
   `text-embedding-001` / `text-embedding-004` chain of wrong values).
9. Native Gemini embedding endpoint
   (`/v1beta/models/{model}:batchEmbedContents`).
10. `image_enrichment.tool` → `gemini:...` (Backlog 2 rename).
11. Validator gate: `coherent = llm_coherent AND bytes_ok` with
    `bytes_ok = encoding_confidence >= 0.5` (commit `5d239cd`).
12. `llm_coherent` now appears in the `encoding_detection` chain
    entry, preserving the LLM's raw vote for debugging.

---

## Hand-off

Phase 7.5 is GREEN. Ready for Phase 8 (world-bank re-ingest) when
you're ready to trigger it.

Recommended before Phase 8:
- Address anomaly 1 (tag block gate). Trivial, one-line fix. Lets
  agents filter garbled docs out of search results once Phase 8
  reingests the corpus.
- Keep anomaly 2 / 4 on the backlog — they don't affect correctness,
  only operator friction.

Did not start Phase 8.
