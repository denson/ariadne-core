# DAVE — BL-19: transactional ingest (no orphan rows on embed fail)

## Why

Today, `_process_single_document` writes the `documents` row at line
267 of `src/pipeline/services.py` BEFORE attempting to embed. If
embedding fails (rate limit, provider 503, transient network), the
documents row survives but has zero chunks. Symptoms:

- The row is invisible to search (no chunks to match)
- BUT visible to `list_documents` and `/api/stats` (inflates counts)
- The response is HTTP 200 with `store_status: "error"` — a half-
  success that looks like a success to uncareful callers
- Phase 8 V2 produced one such orphan (the 429-slip on sha1
  `39f52973…`); corpus-count drift of +3 versus genuinely stored
  documents traces directly to this path.

Denson picked option (a) **transactional**: either everything lands
(row + chunks + vectors + interaction) or nothing does. No
half-success, no forensic orphan row, no new schema.

Backlog refs: `docs/BACKLOG.md` BL-19 (primary) and BL-20 (subsumed
— stats counts fix naturally when the orphan-write path is closed).

---

## Scope

Exactly one file of production-code logic change, plus one SPEC.md
update, plus test updates, plus BACKLOG.md cleanup, plus a small
`.gitignore` whitelist ride-along (PROTOCOL.md). See the "What to
change, file by file" section below.

### The fix shape (do this first, everything else rides on it)

In `src/pipeline/services.py::_process_single_document`, reorder the
writes so that `_dedup_store.store_document(stored_doc)` only runs
AFTER the embed step has succeeded (for `store=True`). Sketch:

```
# unchanged lines 106–266: extract, dedup-check (early-return on skip),
#   image enrichment, tag merge, build StoredDocument in memory

# NEW BLOCK — chunk + embed BEFORE any documents-row write (store=True only).
# If embed fails here, return the error dict; no documents row is ever
# written, no interaction row is recorded, no chunks are inserted.
if store:
    chunk_cfg = None
    if chunking_config:
        chunk_cfg = ChunkingConfig(**chunking_config)

    chunks = chunk_document(
        markdown=markdown,
        document_id=result.document_id,   # reuse extractor's UUID
        collection_id=collection,
        file_type=result.file_type,
        config=chunk_cfg,
    )

    if _embedding_client.enabled and chunks:
        try:
            texts = [c.text for c in chunks]
            embed_result = _embedding_client.embed_texts(texts)
            for chunk, embedding in zip(chunks, embed_result.embeddings):
                chunk.embedding = embedding
                chunk.embedding_model = _embedding_client.model
            processing_chain.append(embed_result.processing_chain_entry)
        except RuntimeError as e:
            # Transactional: bail before ANY Postgres write for this doc.
            return {
                "error": True,
                "message": f"Embedding failed: {e}",
                "document_id": None,                # no row was written
                "source_file": result.source_file,
                "collection": collection,
                "store_status": "error",
                "chunks_count": 0,
                "warnings": warnings + [f"Embedding failed: {e}"],
            }

# Only reached when: store=False, OR (store=True AND embed succeeded),
# OR (store=True AND _embedding_client.enabled is False — vectors-disabled mode).
was_resurrected = _dedup_store.store_document(stored_doc)   # moved from line 267
doc_id = stored_doc.document_id

# (existing resurrection warning + convention warnings unchanged)

# For store=True: insert chunks + vectors (only if we got here with chunks in hand)
if store:
    if force:
        _vector_store.delete_by_document(doc_id)
    _vector_store.insert(chunks)
    response["chunks_count"] = len(chunks)
    response["embedding_model"] = _embedding_client.model if _embedding_client.enabled else None
    response["store_status"] = "stored"
else:
    response["store_status"] = "not_stored"
    response["chunks_count"] = 0

# (existing response markdown inline/preview logic unchanged)

# Interaction recorded only on the success path (line 385–398 kept, now
# only reached when we didn't early-return on embed fail)
_dedup_store.record_interaction(...)
```

This is a reorder, not a rewrite. The extraction, dedup-skip,
resurrection, image-enrichment, tag-merge, warning-append, and
response-building blocks all stay. Only the **relative position** of
`store_document` and the embed try/except changes.

---

## What to change, file by file

### 1. `src/pipeline/services.py`

The reorder above. Concretely:

- DELETE the pre-embed `store_document` call + `was_resurrected` /
  `doc_id` assignments (current lines 251–268).
- KEEP the `StoredDocument(...)` construction at lines 251–266
  (it builds the in-memory object; the DB write is what moves).
- In the `if store:` block (current line 338), move the chunk +
  embed logic to the TOP of that block — BEFORE any `store_document`
  call. On embed fail, return the error dict verbatim (shape above).
- After the embed-fail guard, call `_dedup_store.store_document` once
  (formerly at line 267, now here). This single call services both
  the `store=True`-with-successful-embed and `store=False` paths.
  For `store=False`, no chunks/embed/vectors get written (current
  behavior — no orphan risk because no embed step runs).
- The `was_resurrected` warning append (currently lines 270–275)
  must run AFTER `store_document`, as it does today. Keep its
  placement relative to `store_document`; just that both have moved
  downstream of the embed attempt.
- `processing_chain.append(embed_result.processing_chain_entry)` now
  runs BEFORE `store_document`, which means the stored doc's
  `processing_chain` already contains the embed step. Good — more
  accurate. The `response["provenance"]["processing_chain"]` reflects
  the same list (it's the same `processing_chain` variable). Today's
  code mutates `response["provenance"]["processing_chain"]` at line
  379; that line becomes redundant and can be removed (the variable
  is already the same list), but if redundancy-safety feels better,
  leaving it is fine.
- Make sure the `_vector_store.insert(chunks)` call runs post-
  `store_document` so the chunks' FK to `documents.id` is valid.
  (Today's order already has this right; the reorder preserves it
  since `store_document` now precedes `vector_store.insert`.)

One tricky bit — the `embedding_failed` flag at line 353 can go away
entirely after this refactor. Its only remaining purpose today is
gating the vector insert; with the early-return on embed fail, no
gating is needed downstream. Simpler flow, fewer states.

### 2. `src/pipeline/api/routes.py` — NO CHANGE

The existing `if result.get("error"): raise HTTPException(status_code=422, ...)`
at line 258 already maps the error dict to HTTP 422. Embed failure
follows the same path as extraction failure. Do not modify routes.py.

### 3. `tests/test_services.py` — rewrite existing test + add 3 new

The existing `test_embedding_failure_sets_store_status_error_and_skips_vector_write`
captures PRE-fix behavior (200-with-`store_status="error"`) and will
fail after the fix lands. Rewrite it and add coverage for the
transactional guarantee. Use `monkeypatch` + `InMemoryDedupStore` +
`InMemoryVectorStore` as the existing test does.

Tests to have in the file after this work:

1. **`test_embedding_failure_returns_error_and_writes_no_documents_row`**
   (replaces the existing test) — stub `_embedding_client` to raise
   `RuntimeError`. Call `_process_single_document(store=True, ...)`.
   Assert:
   - `response["error"] is True`
   - `"Embedding failed" in response["message"]`
   - `response["document_id"] is None`
   - `response["store_status"] == "error"`
   - `response["chunks_count"] == 0`
   - `stub_vector._chunks == {}` (no vectors inserted)
   - `stub_dedup._documents == {}` (no documents row inserted) ← the
     BL-19 assertion. Without this, the test would still pass on the
     buggy code.
   - `stub_dedup._interactions == []` or equivalent — no interaction
     row either. Use whatever attr the `InMemoryDedupStore` exposes.

2. **`test_embedding_success_writes_documents_row_and_chunks_and_interaction`**
   — stub `_embedding_client` with a success-path `embed_texts`
   returning fake embeddings of the right shape. Call
   `_process_single_document(store=True, ...)`. Assert:
   - `response.get("error")` is falsy
   - `response["document_id"]` is a non-empty string UUID
   - `response["store_status"] == "stored"`
   - `response["chunks_count"] > 0`
   - `len(stub_vector._chunks) > 0`
   - `len(stub_dedup._documents) == 1`
   - one interaction recorded for that `document_id`

3. **`test_store_false_writes_no_documents_row`** — **NEW assertion
   that codifies intended store=False semantics** (see caveat below
   and flag if current behavior differs). Stub embedding disabled
   (or just unused). Call `_process_single_document(store=False, ...)`.
   Assert:
   - No `error` key
   - `response["store_status"] == "not_stored"`
   - `response["chunks_count"] == 0`
   - `response["markdown"]` contains the full extracted text
   - `stub_dedup._documents == {}` (the spec-correct behavior for a
     "one-time extraction")
   - `stub_vector._chunks == {}`
   - **CAVEAT** — today's code calls `store_document` unconditionally,
     meaning `store=False` also writes a documents row. That's a
     latent inconsistency. With the reorder proposed here, the
     `store_document` call moves INSIDE the post-embed block, so
     `store=False` (which skips that block) naturally no longer
     writes a row. This test asserts the fixed behavior. If you find
     during implementation that `store=False` still needs to write a
     row for some reason (e.g. routes.py depends on it somewhere),
     STOP and flag — do not silently keep the orphan-write behavior
     just to make a test pass.

4. **`test_embedding_disabled_writes_documents_row_and_chunks_without_vectors`**
   — stub `_embedding_client` with `enabled=False`. Call
   `_process_single_document(store=True, ...)`. Assert:
   - No `error` key
   - `response["store_status"] == "stored"`
   - `response["chunks_count"] > 0`
   - `len(stub_dedup._documents) == 1`
   - `len(stub_vector._chunks) > 0` (chunks exist) but all have
     `embedding is None` (no vectors)

All 4 live in `tests/test_services.py`. One concern each.

### 4. `SPEC.md` — 1 line update to the error-code table

Around line 314 (the error-code table for POST /api/documents),
current text:

```
- `422` — Extraction failed (encoding error, unsupported format, corrupt file)
```

Replace with:

```
- `422` — Extraction failed (encoding error, unsupported format, corrupt file), OR embedding failed (transient provider error). Ingest is transactional: on a 422 no document row is written.
```

Keep the rest of the table and surrounding prose unchanged. Do not
add new sections.

### 5. `docs/BACKLOG.md` — mark BL-19 and BL-20 RESOLVED

Around lines 209 and 234. Same pattern as BL-17's resolution edit:
change the heading suffix to `— RESOLVED` and rewrite the body to a
one-paragraph note naming this commit's SHA (you won't have the SHA
until Bob commits, so leave the SHA as `<this commit>` — Bob will
replace it pre-push or commit, per his prompt). Sample BL-19 body:

```markdown
### BL-19 — `store_status="error"` writes a metadata-only documents row — RESOLVED

Resolved in <this commit>. `_process_single_document` now attempts
embed BEFORE any documents-row write. On embed failure the function
returns an error dict (HTTP 422 at the route) and no documents row,
chunks, vectors, or interaction are written. Ingest is transactional:
either everything lands or nothing does. Closes the BL-20 stats-
count drift as a side effect (no orphan rows to count).

Note: this is a client-visible change — embed-fail responses are now
HTTP 422 instead of HTTP 200 with `store_status="error"`. Existing
callers that wrap ingest calls in try/except continue to work; any
caller relying on the 200 shape needs to move handling into the
except branch.
```

Sample BL-20 body:

```markdown
### BL-20 — `/api/stats` counts orphan rows as documents — RESOLVED

Resolved by BL-19 in <this commit>. Orphan rows no longer exist, so
stats and list_documents naturally return correct counts. No
standalone fix was needed.
```

### 6. `.gitignore` — ride-along whitelist for PROTOCOL.md

Current:

```
dave_and_bob_communication/
!dave_and_bob_communication/DAVE_DONE.md
!dave_and_bob_communication/BOB_REVIEW.md
```

Add one line:

```
!dave_and_bob_communication/PROTOCOL.md
```

Bob handles staging PROTOCOL.md alongside the code changes.

---

## Explicitly DEFERRED / Out of scope

- **True cross-table BEGIN/COMMIT/ROLLBACK transaction** (atomic
  `store_document` + `vector_store.insert` + `record_interaction`).
  The reorder above eliminates the common failure mode (embed fail
  before any write). A post-embed crash between the three writes is
  a much rarer scenario and is explicit future-hardening backlog
  fodder if/when we see it in the wild. Do not introduce a shared
  connection / psycopg `with conn.transaction():` block in this
  pass — it touches multiple store modules and balloons the diff.
- **Cleanup of the 1 existing V2 orphan** (document_id
  `c7913f48-4849-4716-bab9-761e653f28d7`, sha1 `39f52973…`). This
  is a data op, not code. After BL-19 lands and deploys, the orphan
  can be purged with a one-shot `client.delete_document(...)` —
  that's a separate short task.
- **Failed-attempt forensic log** (new `ingest_attempts` table or
  file log). Railway logs + BL-21's structured 500 body already give
  the signal; don't introduce schema for a nice-to-have.
- **`convert_document` (store=False) documents-row writes** — the
  reorder naturally stops writing a row for store=False. If you
  discover a caller that depends on the old behavior, flag it; do
  NOT preserve the orphan-write as a workaround.
- **Migration, schema change, new column** — none of these. Existing
  schema is fine.
- **Client library changes** — none. The client's
  `_raise_for_http_error` already handles 4xx. No Document-class
  change needed.
- **Skill doc updates** — none. Agents calling `ingest_*` already
  wrap in try/except per the generic doc-intelligence skill.
- **Retry logic on embed fail** — not this task. Current behavior
  (caller retries at their own pace) is fine.

---

## DO NOT list

- Do NOT commit, stage, or push. Bob handles that.
- Do NOT touch `src/pipeline/dedup.py`, `src/pipeline/storage/*`,
  `src/pipeline/chunking/*`, `src/pipeline/embedding/*`,
  `src/pipeline/extraction/*`, `client/`, `skills/`.
- Do NOT add a new table, migration, or schema change.
- Do NOT change the routes.py error mapping — 422 is the right
  status for a transient upstream failure that blocked the write.
- Do NOT introduce a shared DB transaction (see DEFERRED). Reorder
  only.
- Do NOT "preserve backwards compatibility" by also returning a 200
  with `store_status="error"` alongside the 422. Pick one. The fix
  IS the behavior change; half-measures leave the ambiguity in
  place.
- Do NOT amend the existing soft-delete / resurrection logic in
  `dedup.py::store_document`. The reorder changes WHEN that function
  is called, not WHAT it does.
- Do NOT touch PROTOCOL.md itself beyond whitelisting it — it's
  already complete content-wise; Bob just stages it.

---

## Deliverable

Overwrite `DAVE_DONE.md` with:

1. **Diff summary** — for each of:
   - `src/pipeline/services.py` — show the before/after shape of the
     reordered block (don't paste the full 300 lines; show the
     moved-call deltas).
   - `tests/test_services.py` — describe the 1 rewrite + 3 new tests.
   - `SPEC.md` — the one-line error-code change.
   - `docs/BACKLOG.md` — BL-19 and BL-20 headings + bodies (with
     `<this commit>` placeholder for the SHA).
   - `.gitignore` — the one-line whitelist addition.
2. **Test results** —
   - `pytest tests/test_services.py -v` output (all 4 tests pass)
   - `pytest tests/ -q` summary line (expect ~203 passed, 3
     skipped = 202 baseline at BL-17-commit + 1 net new test. The
     existing test gets rewritten, not added, so net +3 additions
     and -1 rewrite doesn't change the count beyond +3. Report the
     actual number.)
3. **Scope-fence confirmation** — `git diff --stat` output. Should
   show exactly:
   ```
   .gitignore                          | 1 +
   SPEC.md                             | 2 +- (or similar)
   docs/BACKLOG.md                     | N +/- (two entries rewritten)
   src/pipeline/services.py            | N +/-
   tests/test_services.py              | N +/-
   ```
   No other production files touched. Flag if anything else shows.
4. **Caveats** —
   - Confirm the store=False test (#3) passed with
     `stub_dedup._documents == {}`. If you had to relax that
     assertion for any reason, explain.
   - Note whether the redundant
     `response["provenance"]["processing_chain"] = processing_chain`
     line was removed or left as a no-op.
   - Any other surprise.
5. **Local smoke (optional)** — write a ~30-line script that
   monkeypatches the embedding client to raise, then calls the
   `_process_single_document` directly against `sample.txt`, then
   queries the InMemory dedup store to confirm zero rows. Paste the
   output. (This is the same shape as the main unit test — it's
   fine to skip if the test suite is conclusive.)

Hand off to Bob when `DAVE_DONE.md` is written.

— Sam
