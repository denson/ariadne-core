# Verify → clean → re-ingest World Bank reports

**For:** Dave
**Context:** Bob pushed the Gemini `x-goog-api-key` auth fix (commit 0141618). Denson has updated the Railway `ARIADNE_EMBEDDING_API_KEY` and `ARIADNE_IMAGE_ENRICHMENT_API_KEY` with the working `AQ.*` key and Railway has redeployed.

The previous bulk run reported 555 "successes" and 19 failures, but embedding was almost certainly failing on many of those 555 because of the `AQ.*` key / `Authorization: Bearer` mismatch — and `services.py` has a silent-failure bug that swallows embedding errors and still returns `store_status=stored`. We cannot trust the existing `world-bank-ree` contents.

This instruction has three phases, executed in order. **Do not skip ahead.** If phase 1 fails, stop and report — do not clean up or re-ingest. If phase 2 fails, stop — do not re-ingest.

---

## Phase 1 — Smoke test (verify end-to-end works)

Run the full round-trip from `DAVE_CLIENT_SMOKE_TEST.md` (11 steps: health → list → ingest URL → search → get → update → list → stats → delete → verify → CLI).

**Hard gate:** every step must PASS. Pay special attention to:

- **Step 3 (ingest URL):** `chunks_count > 0` AND `store_status == "stored"`.
- **Step 4 (search):** `results_count > 0` with non-trivial `relevance_score`. A search hit with score ~0 is a sign embeddings are zeros (silent failure).
- **Step 5 (get document):** non-empty `markdown` and at least one interaction recorded.
- **Step 8 (stats):** `docs` count increased by 1 vs. the baseline from step 2.

If search returns 0 results or scores are suspiciously uniform/near-zero, **STOP**. That means embedding is still broken on Railway even after the key rotation. Report what you saw and do not proceed to phase 2.

Report phase 1 results before starting phase 2 — write a brief "Phase 1 PASS" section to `DAVE_DONE.md` with the step-by-step pass/fail.

---

## Phase 2 — Clean up the world-bank-ree collection

Only run this after phase 1 is fully PASS.

### 2a. Record current state

```bash
python -c "
from ariadne_core_client import AriadneClient
c = AriadneClient()
print('stats:', c.stats())
docs = c.list_documents(collection='world-bank-ree', limit=1000)
print(f'world-bank-ree doc count: {len(docs)}')
"
```

Record the numbers — this tells us how many of the 555 "successes" actually made it to durable storage.

### 2b. Delete everything in world-bank-ree

Prefer the client's `delete_collection` if it exists:

```bash
python -c "
from ariadne_core_client import AriadneClient
c = AriadneClient()
result = c.delete_collection('world-bank-ree')
print('deleted:', result)
print('stats after:', c.stats())
"
```

If `delete_collection` is not available on the client, iterate:

```bash
python -c "
from ariadne_core_client import AriadneClient
c = AriadneClient(timeout=120)
docs = c.list_documents(collection='world-bank-ree', limit=1000)
print(f'deleting {len(docs)} docs...')
for d in docs:
    c.delete_document(d.document_id)
print('stats after:', c.stats())
"
```

### 2c. Verify empty

```bash
python -c "
from ariadne_core_client import AriadneClient
docs = AriadneClient().list_documents(collection='world-bank-ree', limit=1000)
print(f'world-bank-ree doc count: {len(docs)}')
"
```

Must print `0`. If not, stop and report.

Write a brief "Phase 2 PASS" section to `DAVE_DONE.md`.

---

## Phase 3 — Re-ingest all 574 World Bank reports

Only run this after phase 2 is fully PASS.

Use the same provenance ingestion script that produced the 555/574 run. Changes from last time:

- **Stagger requests** to avoid the 503 cluster we saw around file 300. 100–200ms sleep between files, or limit concurrency to 1–2.
- **Longer per-file timeout** — bump to 180s for large PDFs that hit read-timeout before embedding finishes.
- **Keep the log format identical** so we can diff against the previous run.

Run in the background via Monitor as before.

### Durability check (the important one)

After the run finishes:

```bash
python -c "
from ariadne_core_client import AriadneClient
c = AriadneClient()
print('stats:', c.stats())
docs = c.list_documents(collection='world-bank-ree', limit=1000)
print(f'durable doc count: {len(docs)}')
"
```

If `len(docs)` equals the OK count from the ingest log, durability is confirmed and the silent-failure bug was not triggered. If there's a gap, the bug is still active in `services.py` and we'll need to fix it before trusting any bulk ingest.

Also spot-check search quality:

```bash
python -c "
from ariadne_core_client import AriadneClient
r = AriadneClient().search('rare earth elements supply chain', collection='world-bank-ree', top_k=5)
print(f'{r.results_count} results')
for hit in r:
    print(f'  score={hit.relevance_score:.4f}  section={hit.section}  text={hit.text[:80]!r}')
"
```

Scores should vary and look plausible. Uniform near-zero scores = embeddings are bad.

### Final report

Write a "Phase 3 PASS" section to `DAVE_DONE.md` with:

- Total OK / FAIL / SKIP
- Breakdown of failures by HTTP code
- `stats()` docs count vs. OK count (durability delta)
- Search spot-check output
- Any surprises

---

## Do not commit anything. This is verification + data operations, not a code change.
