# BOB — BL-19: review, commit (+ PROTOCOL.md ride-along), STOP, smoke

Per `DAVE_BL19_TRANSACTIONAL.md` (spec) and `DAVE_DONE.md` (report).
Dave has code + test + doc changes staged in the working tree.
Nothing committed. Your job:

1. Review the diffs (see checklist below — the behavior change is
   real, so the scope-fence checks matter).
2. Commit + push. The commit includes **five** things:
   - the services.py reorder
   - test_services.py rewrite + additions
   - SPEC.md one-line error-code update
   - BACKLOG.md BL-19/BL-20 resolution
   - `.gitignore` + `PROTOCOL.md` ride-along whitelist
3. **STOP** after push. Ask Denson to trigger the Railway deploy.
4. After deploy-live confirmation, run the BL-19 smoke (see below).
5. After smoke passes, clean up the V2 orphan with one
   `client.delete_document(...)` call (see "Post-smoke cleanup").

See `PROTOCOL.md` → "Deploy workflow" if this cadence is new.

---

## What Dave did (read `DAVE_DONE.md` first)

| File | Status |
|---|---|
| `src/pipeline/services.py` | modified — reorder: `_dedup_store.store_document(...)` moves from pre-embed to post-embed. On embed fail, returns `{"error": True, ...}` early; no documents row, chunks, vectors, or interaction written. `embedding_failed` flag removed. |
| `tests/test_services.py` | modified — rewrote existing embed-failure test to assert no-orphan-row; added 3 new tests (happy path, store=False no-row, embed-disabled chunks-without-vectors). |
| `SPEC.md` | modified — one-line update to the 422 error-code description, noting embed-fail + transactional ingest. |
| `docs/BACKLOG.md` | modified — BL-19 and BL-20 headings + bodies rewritten as "RESOLVED" with commit-SHA placeholder. |
| `.gitignore` | modified — one-line whitelist for `PROTOCOL.md`. |
| `dave_and_bob_communication/PROTOCOL.md` | now staged (content unchanged — just newly tracked). |

---

## Review checklist

### Scope fences (strict)

- **`src/pipeline/dedup.py`** — must be untouched. `store_document`
  is called from a new location, but the function itself isn't
  modified. If you see edits here, Dave scope-crept into the store
  layer. Stop and flag.
- **`src/pipeline/storage/*`**, **`src/pipeline/chunking/*`**,
  **`src/pipeline/embedding/*`**, **`src/pipeline/extraction/*`** —
  must all be untouched.
- **`src/pipeline/api/routes.py`** — must be untouched. The existing
  `if result.get("error"): raise HTTPException(422, ...)` at line
  258 is the right mapping; Dave should not add a new error branch.
- **`client/`** — must be untouched. The client already handles 4xx
  via `_raise_for_http_error`; no Document-class change needed.
- **`skills/`** — must be untouched.
- **No new migration**, no new table, no new schema file.

`git diff --stat` should show exactly 5 modified files + 1 newly-
tracked file (after the `.gitignore` correction described below):

```
.gitignore                                                | 2 +/-   (fixes the whitelist pattern too)
SPEC.md                                                   | ~2 +/-
docs/BACKLOG.md                                           | ~20 +/-
src/pipeline/services.py                                  | ~30 +/-
tests/test_services.py                                    | ~100 +/-
dave_and_bob_communication/PROTOCOL.md                    | new (tracked)
```

If the stat shows anything else — `dedup.py`, `routes.py`, client
files, migrations — stop.

### Reorder correctness

Open `services.py` and confirm:

- The pre-embed `_dedup_store.store_document(stored_doc)` call
  (formerly line 267) is GONE from that position.
- The chunk-then-embed block now runs FIRST inside `if store:`,
  before any call to `store_document`.
- On `except RuntimeError as e:` in the embed block, Dave's code
  RETURNS EARLY with `{"error": True, "message": "Embedding failed: ...",
  "document_id": None, ...}`. Confirm `document_id` is explicitly
  `None` (not the UUID from `result.document_id`) — the whole point
  is "no row was written, caller shouldn't think one was."
- `store_document` is called once, post-embed, for both the
  store=True happy path AND the store=False path. The resurrection
  warning at (new) location runs AFTER that call, as today.
- `_vector_store.insert(chunks)` runs AFTER `store_document` so the
  chunks' FK into `documents.id` is valid.
- `record_interaction` runs LAST on the success path and does NOT
  run on the embed-fail early-return.
- The `embedding_failed` flag variable is gone (no longer needed
  with early-return).
- The `response["provenance"]["processing_chain"] = processing_chain`
  line near the end is either removed or kept as a harmless no-op —
  either is fine, Dave's report should say which.

### Test correctness

- **`test_embedding_failure_returns_error_and_writes_no_documents_row`**
  (rewritten) asserts `response["error"] is True`,
  `response["document_id"] is None`, `stub_dedup._documents == {}`,
  `stub_vector._chunks == {}`. The `_documents == {}` assertion is
  the BL-19 canary. Without it the test passes on the buggy code.
- **`test_embedding_success_writes_documents_row_and_chunks_and_interaction`**
  new — success path proves the write still happens after embed.
- **`test_store_false_writes_no_documents_row`** new — codifies the
  intended store=False semantics (no row written for one-time
  extraction). If this test is failing or was dropped, see Dave's
  CAVEAT handling. DO NOT merge if this test was silently removed
  or relaxed; flag to Sam.
- **`test_embedding_disabled_writes_documents_row_and_chunks_without_vectors`**
  new — covers the "embedding provider not configured" mode. Row +
  chunks written, but chunks have `embedding is None`.

Run `pytest tests/test_services.py -v` locally once to verify before
committing. All 4 should pass.

### SPEC.md change

Strictly additive to the 422 error-code line around SPEC.md:314.
Should NOT have moved other lines, renumbered other codes, or added
new subsections. If Dave expanded this into a full "Transactional
ingest" paragraph, that's scope creep — a minimal 1-line update is
what the spec asked for.

### BACKLOG.md resolution edits

Two edits:
- `### BL-19` heading → `### BL-19 — ... — RESOLVED`
- `### BL-20` heading → `### BL-20 — ... — RESOLVED`

Each body rewritten to a one-paragraph resolution note referencing
this commit. Dave leaves the SHA as `<this commit>`; you replace it
after committing. See "Post-commit SHA backfill" below.

### `.gitignore` + entire `dave_and_bob_communication/` dir — SCOPE CHANGED

**Denson's call: stop treating the communications folder as private
scratch. Push the whole thing. Sam already did the mechanical part.**

When you open the working tree you'll see:

- `.gitignore` — the entire 5-line block for
  `dave_and_bob_communication/` is gone (the directory-ignore + its
  three `!`-whitelists). Sam removed it; Dave's original 1-line
  whitelist addition was subsumed by the larger block-removal.
- Root `BOB_DONE.md` — **deleted** (`git rm` already done; shows as
  `D` in `git status`). It was stale content from a prior session;
  Denson asked for it gone.
- `dave_and_bob_communication/` — every file in the directory now
  shows as untracked (`??` in `git status`). There are ~96 of them:
  historical `DAVE_*.md` / `BOB_*.md` prompts, `PROTOCOL.md`,
  `README.md`, `SAM_HANDOFF.md`, the Phase-era overview docs,
  review logs, etc. All get added to the commit as the audit trail.

You do NOT need to re-edit `.gitignore` to whitelist PROTOCOL.md.
That concern is retired. `git check-ignore -v dave_and_bob_communication/PROTOCOL.md`
now returns nothing — the file is no longer ignored, and neither is
anything else in the directory.

Sanity-check before staging:

```bash
# confirm the block is gone
grep -n "dave_and_bob_communication" .gitignore
# → no matches expected

# confirm nothing in the dir is still ignored
git check-ignore -v dave_and_bob_communication/*.md 2>&1 | head -5
# → no matches expected (one "(not ignored)" line per file in some shells)
```

One artifact worth noting: `dave_and_bob_communication/BOB_DONE.md`
contains stale content from Phase 6b (commit `6db1663` era). It
rides along as historical context, not as current evidence. The
root `DAVE_DONE.md` (Dave's BL-19 report) is the active evidence
for this commit.

### Test count math

- Baseline at BL-17-commit: 202 passed / 3 skipped.
- After this: expect **205 passed, 3 skipped** (202 + 3 net new —
  the existing embed-fail test is rewritten, not added, so the
  count goes up by the 3 new tests). If Dave's report shows a
  different number, ask him to re-run and verify.

---

## Commit message

Suggested:

```
Make ingest transactional: no documents row on embed fail (BL-19 / BL-20)

Previously, `_process_single_document` wrote the `documents` row BEFORE
attempting to embed. On transient embed failure (provider 503, rate
limit, etc.) the row survived with zero chunks — invisible to search,
but visible to list_documents and /api/stats, inflating counts. One
such orphan traced to the Phase 8 V2 run.

Fix: reorder so chunk + embed run BEFORE any write to Postgres (for
store=True). On embed failure, return an error dict (HTTP 422 at the
route) with no documents row, chunks, vectors, or interaction written.
Either everything lands or nothing does.

Client-visible change: embed failures are now HTTP 422 instead of
HTTP 200 with store_status="error". Callers that wrap ingest in
try/except (standard) keep working; callers relying on the 200 shape
need to move handling into the except branch. SPEC.md's error-code
table updated accordingly.

Side effect: closes BL-20 — `/api/stats` counts naturally stop
including orphan rows because they no longer exist.

Tests: tests/test_services.py — existing embed-fail test rewritten to
assert no-orphan-row; 3 new tests for happy path, store=False no-row,
and embedding-disabled (chunks written without vectors). 205 passed,
3 skipped (202 baseline + 3 net new).

Also whitelists dave_and_bob_communication/PROTOCOL.md in .gitignore
and tracks the file — it's the Sam/Dave/Bob delegation meta-protocol,
worth shipping with the repo.
```

(Omit Co-Authored-By unless you want Claude attribution.)

### What to stage

Exactly 6 paths:

- `src/pipeline/services.py`
- `tests/test_services.py`
- `SPEC.md`
- `docs/BACKLOG.md`
- `.gitignore`
- `dave_and_bob_communication/PROTOCOL.md` (now whitelisted — git
  will let you add it)

Nothing else. Do NOT stage `DAVE_DONE.md`, `BOB_DONE.md`, the
`phase_8_*` artifacts, `scripts/_probe_*`, `scripts/_phase_8_*`,
`smoke_bl21.py`, or `phase_8_ingest_log_v3.json`.

### Post-commit SHA backfill

Dave leaves `<this commit>` in the BL-19 and BL-20 resolution notes.
You have two clean options:

**Option A — pre-commit edit.** Before running `git commit`, stage
`BACKLOG.md` but don't commit; `git commit --dry-run` won't give you
a SHA either. Skip this option.

**Option B — amend once, cleanly.** Create the commit normally with
`<this commit>` in place. Immediately `git show HEAD --stat` to get
the SHA. Edit `BACKLOG.md` to replace both `<this commit>` strings
with the SHA. `git add docs/BACKLOG.md && git commit --amend --no-edit`
(only the backlog edit, message unchanged). Push the amended
commit. This is the intended flow — one push, not two.

If Denson's convention recently shifted to "never amend after push"
the fallback is a follow-up one-line commit "Backfill BL-19/BL-20
commit SHA in BACKLOG.md". Pre-push amend is cleaner.

---

## Post-commit: STOP

1. Confirm push succeeded. Cite the commit hash.
2. **STOP.** Tell Denson:

   > Commit <sha> is on `origin/main` (BL-19 transactional ingest +
   > PROTOCOL.md ride-along). Please trigger the Railway deploy.
   > Ping me when it's live and I'll run the BL-19 smoke.

3. Do nothing else. Don't curl `/api/health`. Don't curl prod. Wait.

---

## Smoke test (ONLY after Denson confirms deploy is live)

Three curls against prod. Use `ARIADNE_URL` and `ARIADNE_API_KEY`
from the workspace `.env`.

### 1. Happy path (regression guard)

Upload and ingest `tests/fixtures/sample.txt` or any small text
file. Expect HTTP 200, `store_status: "stored"`, non-zero
`chunks_count`, a `document_id`.

```bash
# (upload sample.txt → capture server_path, then:)
curl -sS -X POST "$ARIADNE_URL/api/documents" \
  -H "X-API-Key: $ARIADNE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"uri": "<server_path>",
       "collection": "smoke-bl19-<random>",
       "agent_type": "smoke-test",
       "initiated_by": "user:denson",
       "agent_notes": "BL-19 smoke: happy path regression guard",
       "force": true}'
```

### 2. Embed-fail guard (if you can trigger it)

Triggering a real embed fail against prod is hard — the provider's
usually up. Skip this curl unless there's a trivial way to induce
it (e.g. a feature flag). The InMemory test suite is the real
evidence for this branch. Flag that you skipped it.

### 3. Stats count sanity

`GET /api/stats?collection=world-bank-ree`. Confirm
`total_documents` matches the V3-post-ingest count Dave reported
(`572` per his V3 log). If it's higher, there's a rogue write path.
If it's lower, the orphan may have been cleaned up already (it
shouldn't be — that's step 5 below).

---

## Post-smoke cleanup — delete the V2 orphan

After the smoke passes, clean up the 1 surviving V2 orphan. This
isn't part of the commit; it's a one-shot data op.

```python
# Run once from the workspace root.
from ariadne_core_client import AriadneClient
c = AriadneClient(agent_type="cleanup", initiated_by="user:denson")
c.delete_document("c7913f48-4849-4716-bab9-761e653f28d7")
# Confirm: c.get_document(...) should raise / 404
```

After the delete, hit stats again — `world-bank-ree` should drop by
exactly 1 (572 → 571). Paste the before/after counts into the
post-commit note.

If the orphan is GONE already (delete fails with 404), it was
either already cleaned up or the dedup-skip path on some re-ingest
merged it. Note that and move on.

---

## Out of scope for this commit

- **True cross-table DB transaction** (shared `BEGIN/COMMIT` across
  `store_document` + `vector_insert` + `record_interaction`). The
  reorder kills the common failure mode; atomicity across the three
  writes is nice-to-have and explicit future hardening backlog.
- **Retry logic on embed fail** — caller's responsibility.
- **Phase 9 full re-ingest** — separate op, not triggered by this.
- **Client library Document class change** — none needed. Client
  already raises on 4xx.
- **Skill doc update about 422 semantics** — existing skills already
  say "handle errors from ingest_*"; the 422 ride inside that
  generic error-handling contract without a skill rewrite.

— Sam
