# DAVE — Phase 8 World-Bank re-ingest: **STOP — Step 4 hard gate FAILED**

Per `DAVE_PHASE_8_REINGEST.md`. Re-ingest 574 files into `world-bank-ree`
on the post-`3cd00ba` runtime. The run completed without exception, but
**the durability gate at Step 4 failed catastrophically**: 558 responses
said `store_status="stored"` and returned real `document_id`s, and then
**0 of those documents are retrievable on the server.** This is the same
failure shape the spec was written to detect, and it proves the
`3cd00ba` fix alone is not sufficient. Not declaring Phase 8 complete.
Handing back to Sam.

---

## Step 0 — pre-flight

```
$ git rev-parse HEAD
3cd00ba35a117da886ea462e8f78e2f14c4aff5d
$ git rev-parse origin/main
3cd00ba35a117da886ea462e8f78e2f14c4aff5d
$ git status --short
?? scripts/_generate_encoding_fixtures.py
?? scripts/_probe_embedder.py
?? scripts/_probe_text_encoding.py
?? scripts/_probe_vision.py
```

HEAD = origin/main = `3cd00ba` ✓. Only 4 helper scripts untracked ✓.

Health probe:
```
Health(status='healthy', version='0.1.0', embedding=True)
```
(Note: the current `Health` dataclass is `(status, version, embedding)`
— spec's `(status, version, engine, embedding_enabled)` is stale by
one model. Informational, not a blocker.)

Manifest:
```
manifest rows total: 1891  ok: 574
```
Match ✓.

Deployment-freshness note: per the spec I did not trust `git push →
Railway auto-deploy`. Step 1 proved the round-trip is live. But given
the Step 4 failure below, the deployment version could not be
independently verified from this probe — see **Anomalies** for a
follow-up hypothesis.

---

## Step 1 — 30-second liveness check (PASSED)

```
document_id=fce2b069-d495-4079-afe7-cf01650e07ae  chunks=1  store_status=stored
warnings=["No agent_notes provided. Future agents won't know why this document was processed."]
search: 1 hits
  score=0.5669 text='The company\ufffd s CEO announced a new product on April 16th, 202'
cleanup: {'collection': 'smoke_phase_8_preflight', 'documents_marked': 1, 'message': '1 document(s) scheduled for deletion. ...'}
```

All Step 1 gates green:
- `chunks_count=1` > 0 ✓
- `store_status=="stored"` ✓
- `warnings` only the benign agent_notes provenance hint ✓ (I omitted
  `agent_notes` in this probe — Step 3 always sends one)
- `hits.results_count=1` > 0 ✓
- Top score `0.5669` > 0.3 ✓

Note: the `\ufffd` in the fixture is a pre-existing mojibake in
`tests/fixtures/clean_english_sample.txt`, not a pipeline regression.
Out of scope for this task.

---

## Step 2 — snapshot + wipe `world-bank-ree`

```
stats_before: Stats(docs=10, chunks=10, collections=1, embedding=True)
world-bank-ree doc count (pre-wipe, limit=100): 0
search score sample (pre-wipe): hits=0
delete_collection: {'collection': 'world-bank-ree', 'documents_marked': 0, 'message': '...'}
world-bank-ree doc count (post-wipe): 0
```

Spec-drift: `list_documents(limit=1000)` is rejected — current API caps
`limit ≤ 100` (422 validation error). Paginated with `limit=100 + offset`.

**Evidence the old run never produced durable records:**
`world-bank-ree` returned 0 documents *before* the wipe, and
`delete_collection` marked 0 documents. The pre-`3cd00ba` bulk run
didn't leave poisoned chunks — it left **nothing at all**. The silent-
failure bug was worse than the spec assumed.

**Anomaly (pre-ingest):** `stats.docs=10` with `collections=1` while
`world-bank-ree` has 0 docs. 10 documents are in *some* collection,
but `world-bank-ree` isn't it, yet `collections=1` implies only one
collection exists. One of `stats.docs` / `stats.collections` / the
collection-filter on `list_documents` is reporting wrong. Not a blocker
for Phase 8, but should land in the backlog.

---

## Step 3 — 574-file re-ingest (COMPLETED without unrecoverable error)

Orphan check: 0 orphans (all 574 `sha1_*.txt` files join to `ok` manifest rows).

### Final counts

```
total=574  ok=558  stored=558  errored=0  fail=16  with_warnings=341
elapsed=3920.4s  avg=6.83s/file
log: phase_8_ingest_log.json (558 ok rows + 16 fail rows)
```

### Failure HTTP breakdown (16 total)

| class | count |
|---|---|
| `[500] Internal Server Error` | 11 |
| `[503] Service Unavailable`   | 4  |
| timeout (120s)                | 1  |

Non-clustered (indices: 24, 49, 67, 135, 156, 183, 209-ish, 560, 564,
and others spread across the full 574). Not a contiguous Railway
blip — intermittent upstream / server-side failures.

Full `fail` sha1 list (for re-ingest with `force=True` once Step 4 is
resolved):

```
0dcee49de17962a574d2c35122ce7282a2c2d007  [timeout after 120s]
17a21c127e26dce69c0789ae13457f8bcdb313b9  [500]
1df84a7edfe1a6a2a4f997d63be773767768d840  [500]
3acee7b7eebe67c2f0adfc6720bb4a3830bd55b5  [500]
433721259a12fe8c7573e068f4681164a284df6c  [500]
4b4f81133f398c6b117a5d2c258715c98a3097aa  [500]
95625a0bb0dcb6caf002c31dfcc996b97608a2ce  [500]
9e8d06da73ca5ac5089900691fa460d1f67e2818  [500]
a2e7e2f6cdbcb952fe30644bac712ef9cc2fa4e6  [500]
a38622bc9f29bfb085059460a9ba3c60ff048083  [500]
c17351141ca5b1a376636a229e3773dde0831b1a  [500]
e713d2f7bd240236fe103bc071d883226f736986  [503]
eb8a2d7b0771a2e3d30d4baa9c84b1ae0a715d23  [503]
f07c8e9a469c63596e87a5125b69433069871231  [500]
fa2d82fd920dc997f98ce7c6b2be150ecf977a72  [503]
fb61c834ae03ac136f24d3ed1e74e5f68e08cd42  [503]
```

**Zero `store_status="error"` responses** across 558 "ok" rows. The
embedding-failure path landed in `3cd00ba` did not fire once during
the run.

---

## Step 4 — durability check: **HARD GATE FAILED** ❌

### Server state after ingest

```
stats_after: Stats(docs=10, chunks=10, collections=1, embedding=True)   ← UNCHANGED from stats_before
durable doc count (list_documents world-bank-ree): 0
```

**`stats.docs` did not move by a single document** across the entire
574-file bulk ingest. `list_documents(world-bank-ree)` returns 0.

### Spot-check on bulk-returned `document_id`s: 100% ghosted

Sampled 25 of the 558 `document_id`s that came back with
`store_status="stored"`:

```
sample of 25 stored doc_ids: found=0  not_found=25  other=0
```

**Every single one returns `[404] Document not found`.** The
`document_id`s the ingest API returned are real UUIDs, but the server
has no record of them. The ingest response is lying about durability —
the exact failure mode Step 4 was designed to catch.

### Search spot-checks

Skipped the three canonical queries because they are guaranteed to
return 0 hits — `list_documents` already proved nothing is there.
Ran the spec's zeroth query as confirmation:

```
global search 'World Bank rare earth mining' (no collection): 0 hits
```

### Post-mortem probe: single fresh ingest works end-to-end

To isolate whether the failure is server-wide or bulk-specific, I ran
a single fresh ingest with bulk-shape kwargs (same collection, same
3-tag list with colons, URL `source`, large `agent_metadata`) against
the same live deployment:

```
fresh ingest:         doc_id=063d4a9f-32e0-434c-88df-8a4d0c027155  chunks=1  store_status=stored  warnings=[]
immediate fetch:      FOUND (Document with collection='world-bank-ree')
immediate search:     1 hits
immediate list:       1 doc
stats after probe:    Stats(docs=11, chunks=11, collections=1, embedding=True)   ← +1, confirming the probe landed
```

Conclusion: the deployment **does** durably store single-file ingests
with exactly the same kwarg shape as Step 3. The bulk loop is the
variable that turns durable writes into ghost `store_status="stored"`
responses. See **Anomalies** for hypotheses.

---

## Hard gate evaluation (per spec Step 6)

| Gate | Status |
|---|---|
| 1. Step 1 preflight passes (round-trip score > 0.3) | ✓ PASS (0.567) |
| 2. Step 2 wipe confirms 0 remaining | ✓ PASS (was already 0) |
| 3. Step 3 ingest completes without unrecoverable error | ✓ PASS (clean exit, 558/574 "ok") |
| 4. `durable == stored` (no silent-failure delta) | ❌ **FAIL** (durable=0, stored=558, delta=-558) |
| 5. `errored == 0` | ✓ PASS (0 errored — but this is meaningless if `stored` is also unreliable) |
| 6. Three spot-check queries return hits with plausible scores | ❌ FAIL (skipped — nothing to search) |

**Phase 8 is NOT complete.** Do not treat `world-bank-ree` as populated.

---

## Anomalies / hypotheses

1. **`store_status="stored"` is still unreliable under bulk conditions.**
   The `3cd00ba` fix only covered the `_embedding_client.embed_texts`
   `RuntimeError` branch. Something else on the vector-store insert
   path (or after it) can fail silently without ever hitting the new
   error branch. Candidates to investigate:
   - Server-side async work happening after the HTTP response is sent
     (the response says "stored" but the actual DB write hasn't
     happened yet and later fails / is dropped)
   - A write-buffer or queue somewhere that's being dropped on
     deploy / worker restart / memory pressure
   - A per-collection tombstone left by `delete_collection` that
     silently rejects writes for some window (but the post-bulk
     probe succeeded, so this would have to time-out or be
     count-based, not time-based)
   - Something in the specific combination of (larger file size,
     rapid cadence, specific tag shape) that triggers a code path
     the single-file probe doesn't reach

2. **`collections=1` / `docs=10` accounting drift** — pre-bulk
   `stats.docs=10` while `list_documents(world-bank-ree)=0`, and
   `stats.collections=1`. Either there's a tombstoned collection
   that still counts toward `docs` but not `list_documents`, or
   stats has a known lag. Independent from the Step 4 failure but
   worth a backlog entry.

3. **`Health` dataclass spec drift** — `(status, version, embedding)`,
   not `(status, version, engine, embedding_enabled)`. BL-8's
   "`embedding_enabled=True` can be a false positive" framing still
   applies but the field name is now `embedding`. Minor.

4. **Orphan check noise** — none found, but the spec's `ok` count
   (574) and the disk count (574) matched exactly. The `ok` filter
   on the manifest is clean.

5. **Post-probe residue** — one test doc (`063d4a9f-...`) and the
   smoke-test's residue (now soft-deleted, 48-hr purge window) are
   currently in the system. Leaving them in place so a follow-up
   can reproduce the fetch-vs-ghost disparity. They are NOT part
   of the World Bank corpus.

6. **`warnings` rate is very high** — 341 of 558 "ok" rows
   (61%) carried at least one warning. None were `"Embedding
   failed"` (confirmed by the `errored=0` count and by grepping
   the log — all "Embedding failed" hits would have produced
   `store_status="error"`). Most are likely the benign
   agent-notes / provenance hints, but given the durability
   failure, these should be cross-checked after the real bug is
   fixed, not before.

---

## What Sam needs to decide

1. **Reproducibility:** the single-file post-mortem probe succeeded;
   the 574-file loop fails. That's a testable regression — a small
   bulk repro (e.g. 30 files with real provenance shape) would confirm
   whether this is bulk-rate-dependent or something else. Worth a Bob
   task before any more re-ingests.

2. **`3cd00ba` fix status:** the test added in `3cd00ba`
   (`test_embedding_failure_sets_store_status_error_and_skips_vector_write`)
   proves the embedding-failure branch now writes
   `store_status="error"`. But it does *not* prove that
   `store_status="stored"` means "actually stored." Step 4 shows
   that claim is still false in bulk. Need a new test that
   asserts post-ingest `list_documents`/`get_document` visibility,
   not just the ingest-response status. Candidate file:
   `tests/test_services.py` (same module as the `3cd00ba` test).

3. **Do not re-ingest blindly.** Until the ghost-write root cause is
   understood, another 574-file run will produce the same outcome:
   558 lies, 0 durable. The `fail=16` list of sha1s is also not
   retry-ready — they may succeed on retry, but retry into a collection
   that silently drops writes is pointless.

4. **Embedding provider is healthy** — 0 `store_status="error"`
   responses across 558 embedding calls, and the fresh probe
   search scored 0.57. The upstream (Gemini native) is not the
   blocker.

---

## Artifacts left behind (not staged, not committed)

- `phase_8_ingest_log.json` — full 574-row log (558 ok + 16 fail)
- `phase_8_ingest_stdout.log` — full stdout of the run
- `scripts/_phase_8_reingest.py` — purpose-built ingest loop (ignore;
  not intended for reuse without the durability bug being fixed first)

Nothing staged. Nothing committed. Nothing pushed. No source files
modified — this was a pure data op.

---

## Final working-tree state

```
$ git status --short
 M dave_and_bob_communication/DAVE_DONE.md          # this file (regenerated for this run)
?? phase_8_ingest_log.json                          # artifact
?? phase_8_ingest_stdout.log                        # artifact
?? scripts/_generate_encoding_fixtures.py           # pre-existing
?? scripts/_phase_8_reingest.py                     # new helper, intentionally untracked
?? scripts/_probe_embedder.py                       # pre-existing
?? scripts/_probe_text_encoding.py                  # pre-existing
?? scripts/_probe_vision.py                         # pre-existing
```

No source-code modifications — the only `M` is this hand-off doc.

---

## Hand-off

**Sam:** the gate the spec was written to detect is firing. The
`3cd00ba` fix is necessary but not sufficient. Recommend a Bob task
to (a) reproduce the bulk-ingest ghost-write with a 30-file repro
script, (b) identify the actual failure point on the services /
storage side (likely not in `_embedding_client.embed_texts` since
`errored=0`), and (c) extend `tests/test_services.py` to assert
post-ingest visibility. Do not declare Phase 8 complete. Do not
retry the 16 failures yet.

— Dave
