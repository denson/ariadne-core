# DAVE — Phase 7.5: Live smoke test against Railway

Unit tests are green (174/174 at `98964dc`) but they all mock the HTTP layer.
Phase 7.5 proves the native-Gemini runtime actually works end-to-end against
the live Railway deployment before we commit to Phase 8 (the 574-file
world-bank re-ingest).

The goal is coverage of every Gemini-calling code path once:

- Extraction + chunking + embedding (happy path, text input)
- Extraction + chunking + embedding + **language validation** on clean text (expect coherent)
- Same as above but on **mojibake** text (expect low-coherence flag)
- Extraction + chunking + embedding + **vision enrichment** on a doc with an image
- Read-back via `list_documents`, `get_document`, `search_chunks`

No Phase 8 scope here — we are not loading the full corpus. Just one
document per code path, then inspect what came back.

---

## Environment

You'll be working against the live Railway deployment, not a local server.
The console-script install failure Bob saw during Phase 7 prep
(`pip install -e src/` failed to write `ariadne-core serve`) is **not a
blocker** for this phase — Phase 7.5 only needs the Python client
(`ariadne-core-client`) and the fixtures on disk. Leave the console-script
bug in backlog.

Required:

- `ariadne-core-client` installed in the active Python environment (`pip install -e client/` from repo root — this one has not shown install issues)
- Railway deployment URL + API key available in your shell environment (same as Phase 1's `_phase1_smoke.py` used)
- `psql` or equivalent for the DB state snapshot at the end (Railway dashboard SQL tab works too)

If any of the above is missing, **stop and report** — Sam will sort it
before you proceed.

---

## Step 0 — pre-flight: confirm deployment freshness

```
git rev-parse HEAD
git rev-parse origin/main
```

Both should be `98964dc` or newer. Nothing should be modified in the working
tree except diagnostic `.md` files.

Hit the Railway deployment's health endpoint with auth:

```python
from ariadne_core_client import AriadneClient
client = AriadneClient(agent_type="claude-code", initiated_by="user:denson", model="claude-opus-4-7")
print(client.health())
```

Expected: `HealthResponse(status='healthy', ...)`. Record whatever version /
deployed-commit field the response includes (if any) so we have evidence
the server is running the expected code. If the response is stale (points
at a pre-migration commit), **stop and report** — we may need to trigger
a redeploy before proceeding.

---

## Step 1 — generate fixtures if missing

```
ls tests/fixtures/clean_english_sample.txt tests/fixtures/mojibake_sample.txt
```

If either is missing:

```
python scripts/_generate_encoding_fixtures.py
```

Then verify the mojibake file contains sequences like `â€™`, `Ã©`, `â€œ`:

```
python -c "print(open('tests/fixtures/mojibake_sample.txt', encoding='utf-8').read()[:200])"
```

If the mojibake preview doesn't show those classic patterns, the generator
failed — **stop and report**.

---

## Step 2 — clean-text ingest (embedding + language validation happy path)

Pick a fresh collection name so you're not writing into existing data:

```
COLLECTION = "smoke_phase_7_5_20260416"  # or similar date stamp
```

Ingest `tests/fixtures/clean_english_sample.txt` into that collection with
minimal agent metadata:

```python
result = client.ingest(
    path="tests/fixtures/clean_english_sample.txt",
    collection=COLLECTION,
    agent_metadata={"source": "phase_7_5_smoke", "fixture": "clean_english_sample"},
)
print(result)
```

Record:

- The returned `document_id`
- `chunks_created` count
- Any warnings in the response
- Time elapsed (rough is fine)

Then read back the stored metadata to verify language validation ran and
flagged the text as coherent:

```python
doc = client.get_document(document_id=result.document_id)
print(doc.agent_metadata)
print(doc.processing_chain)
```

**Expected:**

- `processing_chain` includes steps for extraction, encoding_detection, chunking, embedding, and language validation
- Language-validation step records `coherent=True` (or equivalently high confidence) — whatever the validator actually stores
- Embedding step's `tool` field starts with `gemini:` (not `openai:`)

If any of the above is wrong, **stop and paste the full `doc.processing_chain` and `doc.agent_metadata`** so Sam can see what the live runtime is actually producing.

---

## Step 3 — mojibake ingest (language-validator hot path)

Same as Step 2, but with the corrupted fixture:

```python
result = client.ingest(
    path="tests/fixtures/mojibake_sample.txt",
    collection=COLLECTION,
    agent_metadata={"source": "phase_7_5_smoke", "fixture": "mojibake_sample"},
)
```

Read back:

```python
doc = client.get_document(document_id=result.document_id)
print(doc.agent_metadata)
print(doc.processing_chain)
```

**Expected:**

- Ingest succeeds (we don't reject mojibake, we flag it)
- Language-validation step records `coherent=False` (or equivalently low confidence)
- Validator may also record some diagnostic text — paste whatever it stores

If the validator flags the mojibake as coherent, **that's the bug this
phase is designed to catch**. Stop, paste the full `processing_chain`, and
do not proceed — Sam will need to diagnose before Phase 8.

---

## Step 4 — image ingest (vision path)

Pick a document from the existing `tests/fixtures/` tree that contains at
least one image. If there isn't one handy, a small PDF of any image-bearing
doc will do — report what you chose.

```python
result = client.ingest(
    path="<your chosen image-bearing doc>",
    collection=COLLECTION,
    agent_metadata={"source": "phase_7_5_smoke", "fixture": "image_test"},
)
doc = client.get_document(document_id=result.document_id)
print(doc.processing_chain)
```

**Expected:**

- Processing chain includes an `image_enrichment` step
- Tool label on that step starts with `gemini:` (this is what Backlog 2 fixed — worth confirming it held up in the live deployment)
- `images_processed` count > 0 (unless your chosen doc had no images that made it through extraction, in which case pick a different doc)

If the tool label still reads `openai:`, Railway is running stale code —
trigger a redeploy and rerun Step 0. If `images_processed == 0` on a doc
you're sure has images, paste the chain and stop.

---

## Step 5 — search + list sanity check

```python
docs = client.list_documents(collection=COLLECTION)
print(f"Documents in {COLLECTION}: {len(docs)}")
for d in docs:
    print(f"  {d.document_id} — {d.path}")

hits = client.search_chunks(
    query="CEO announced new product",
    collection=COLLECTION,
    top_k=5,
)
print(f"Search hits: {len(hits)}")
for h in hits[:3]:
    print(f"  score={h.score:.3f} — {h.text[:80]!r}")
```

**Expected:**

- `list_documents` returns all three ingested docs (or however many steps succeeded)
- `search_chunks` returns at least one hit with a plausible score against the clean-English sample

If search returns zero hits or errors out, paste the full output. Vector
search failing is a sign embeddings aren't being stored / queried correctly.

---

## Step 6 — DB state snapshot

Connect to the Railway Postgres (via `psql` or the Railway dashboard SQL
tab) and capture row counts:

```sql
SELECT COUNT(*) FROM documents WHERE collection = 'smoke_phase_7_5_20260416';
SELECT COUNT(*) FROM document_chunks WHERE document_id IN (
    SELECT document_id FROM documents WHERE collection = 'smoke_phase_7_5_20260416'
);
SELECT COUNT(*) FROM agent_interactions WHERE document_id IN (
    SELECT document_id FROM documents WHERE collection = 'smoke_phase_7_5_20260416'
);
```

Also fetch one `processing_chain` to confirm it round-tripped intact:

```sql
SELECT document_id, processing_chain
FROM documents
WHERE collection = 'smoke_phase_7_5_20260416'
LIMIT 1;
```

Paste the results.

---

## Step 7 — cleanup (optional)

The smoke collection can stay — three documents is negligible. But if you
want to clean up:

```python
for d in client.list_documents(collection=COLLECTION):
    client.delete_document(document_id=d.document_id)
```

Report whether you cleaned or left it.

---

## Report back

Write your report to `dave_and_bob_communication/DAVE_DONE.md` (overwriting
the Phase 7 report — that one is preserved in git at `86cebe2`) and include:

- Step 0 deployment-freshness evidence
- Step 1 fixture generation status
- Step 2 clean-ingest document_id + processing_chain summary
- Step 3 mojibake-ingest document_id + processing_chain summary + coherent flag
- Step 4 image-ingest doc you chose + image_enrichment chain entry (including the `tool` label)
- Step 5 list + search output
- Step 6 DB row counts + one raw processing_chain
- Step 7 cleanup decision
- Anomalies list (anything that didn't match expectations)

## Hard gate for Phase 8 readiness

Phase 8 (world-bank re-ingest) only proceeds if:

1. Step 2 clean ingest returns coherent=True
2. Step 3 mojibake ingest returns coherent=False
3. Step 4 image ingest shows `gemini:` tool label and images_processed > 0
4. Step 5 search returns non-zero hits
5. Step 6 row counts are consistent (e.g., chunks > 0 for all three docs)

If any of those fail, **stop**, write the report with the failure
documented, and do not start Phase 8. Sam will diagnose.

## Do NOT

- Ingest more than the three fixtures described
- Touch production collections (e.g., the old `world-bank-ree` collection) — use the fresh `smoke_phase_7_5_*` collection name
- Attempt to fix the `ariadne-core serve` console-script install bug here — it's a backlog item, not a 7.5 blocker
- Modify any source file — this phase is pure smoke, no code edits
