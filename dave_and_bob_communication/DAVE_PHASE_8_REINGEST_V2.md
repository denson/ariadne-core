# DAVE — Phase 8 re-ingest, V2 (post ghost-write fix)

Re-run the World Bank REE corpus re-ingest. Supersedes
`DAVE_PHASE_8_REINGEST.md` — V1 ran into a real bug (ghost-write on
ON CONFLICT over soft-deleted rows) that's since been fixed and
deployed. This is the clean re-fire.

**Process:** you run the data operation and write a report. No code
changes. No commits, no push. Write evidence to `DAVE_DONE.md` and
stop.

---

## What changed since V1

1. **Ghost-write bug fixed.** Commit `3a5adc7` on `main` landed the
   soft-delete/upsert fix from `DAVE_SOFT_DELETE_UPSERT_FIX.md`.
   `PgDedupStore.store_document` now clears `deleted_at` /
   `deletion_scheduled_at` in the ON CONFLICT DO UPDATE clause and
   returns `was_resurrected` so a re-ingest over a soft-deleted row
   surfaces a warning to agents. `purge_deleted(0)` was also
   special-cased to purge every soft-deleted row regardless of
   same-microsecond timing.

2. **Deployed and verified on Railway.**
   - `probe_prod.py resurrection` → `[NOT REPRODUCED]` (fix is live)
   - `probe_db_state.py` → DB holds 12 smoke docs across 8 collections.
     **`world-bank-ree` does not currently exist** (neither active
     nor soft-deleted rows). Something — most likely a volume refresh
     or an earlier operator action — cleared the 2026-04-16 poison
     before this re-fire. Net result: Step 2 of V1 is mostly a no-op;
     the collection is already clean.

3. **New `?purge=true` flag** on `DELETE /api/collections/{name}` —
   idempotent hard-delete that bypasses the 48h grace window. Use it
   for the Step 2 wipe instead of the default soft-delete.

4. **Durability gate is now meaningful.** V1's gate (`durable ==
   stored`) was the right gate, but it couldn't actually distinguish
   a successful write from a ghost-write over a soft-deleted row
   until `3a5adc7` landed. It now does.

5. **NUL-byte bug still open.** Phase 8 V1 hit ~16 files with
   `psycopg.DataError: PostgreSQL text fields cannot contain NUL
   (0x00) bytes`. That's a separate bug in MarkItDown output
   pre-cleaning — **not fixed, not in scope for this task**. Expect a
   similar count of 500s on the same files. Log them and move on. Do
   NOT try to fix it.

---

## Use V1 as the technical spec — with these deltas

Re-read `DAVE_PHASE_8_REINGEST.md` for the ingest-loop mechanics
(manifest load, `by_sha1` index, per-file metadata construction, log
shape, search spot-check). Apply these deltas:

### Step 0 — pre-flight

- **Expected HEAD:** `3a5adc7` or a descendant (was `3cd00ba` in V1).
- `git log --oneline -5` — confirm the soft-delete/upsert commit
  (`Fix ghost-write on re-ingest after soft-delete`) is in the first
  few entries.
- Manifest check unchanged: total 1891, ok 574. Stop if drifted.

### Step 1 — liveness check

Unchanged. The existing hard gate still applies (top hit's
`relevance_score > 0.3`). If the smoke fails, stop and surface.

Reminder that BL-8 (embedding_enabled=True can be a false positive)
is why Step 1 is a real round-trip, not just a health ping.

### Step 2 — wipe `world-bank-ree`

**Per the prod probe, the collection is already empty.** Verify and
fire a belt-and-suspenders `?purge=true` anyway — it's idempotent and
costs nothing:

```python
# 2a. Snapshot
from ariadne_core_client import AriadneClient
client = AriadneClient(agent_type="claude-code", initiated_by="user:denson",
                      model="claude-opus-4-7", timeout=60)

existing = client.list_documents(collection="world-bank-ree", limit=1000)
print(f"pre-wipe active count: {len(existing)}")

# Also check include_deleted=true (if the client exposes it, otherwise
# hit the REST endpoint directly).
#
# Expected per 2026-04-17 probe: 0 active, 0 include_deleted. If you
# see non-zero on either, note it in the report — somebody re-poisoned
# the collection between then and now.

# 2b. Hard-purge via the new ?purge=true flag — idempotent.
import urllib.request, urllib.parse, os, json
url = f"{os.environ['ARIADNE_URL']}/api/collections/{urllib.parse.quote('world-bank-ree')}?purge=true"
req = urllib.request.Request(url, method="DELETE")
req.add_header("X-API-Key", os.environ["ARIADNE_API_KEY"])
with urllib.request.urlopen(req, timeout=600) as r:
    print(r.status, r.read().decode())

# 2c. Re-verify empty
remaining = client.list_documents(collection="world-bank-ree", limit=1000)
assert len(remaining) == 0, f"expected 0 post-wipe, got {len(remaining)}"
```

If the client lib already supports `purge=True` on
`delete_collection`, use that directly instead of the raw HTTP call
— grep the client package to check before writing the urllib
shim.

### Step 3 — ingest loop

Unchanged. Use the V1 loop verbatim (154-line block in V1 step 3b).
Two additions to the per-file log record:

```python
log.append({
    "path": str(fp),
    "sha1": sha1,
    "ok": True,
    "document_id": doc.document_id,
    "chunks": doc.chunks_count,
    "store_status": doc.store_status,
    "warnings": list(doc.warnings),
    "resurrected": any("resurrected" in w.lower() for w in doc.warnings),  # NEW
})
```

**`resurrected` MUST be False for every single row** in a clean
re-ingest on an empty collection. If any row has `resurrected=True`,
that means its fingerprint collided with a soft-deleted row somewhere
else in the DB — surface it in the report, because it indicates the
DB wasn't actually as clean as Step 2 implied.

### Step 4 — durability check (the real gate)

Unchanged from V1, but this is the gate we finally believe. Required
new sub-check:

```python
# NUL-byte expected failures — tally them out separately so they don't
# contaminate the durability delta interpretation.
nul_failures = [
    r for r in log if not r.get("ok")
    and "NUL" in (r.get("error") or "")
    and "0x00" in (r.get("error") or "")
]
print(f"NUL-byte failures (expected, separate bug): {len(nul_failures)}")

other_failures = [
    r for r in log if not r.get("ok")
    and r not in nul_failures
]
print(f"Other failures (unexpected): {len(other_failures)}")
```

The hard gate:

- `errored == 0` (no provider 5xx during the run)
- `durable == stored` (no silent failure, no ghost-write)
- `sum(r.get('resurrected') for r in log) == 0` (no fingerprint collision
  with soft-deleted rows — if non-zero, flag loudly)
- `len(other_failures) == 0` (all non-ok rows should be NUL-byte)
- NUL-byte count should be in the same ballpark as V1's ~16 (±3) —
  if it's wildly different, note it.

Search spot-check queries unchanged.

### Step 5 — hand off

Same sections as V1, plus:

- **Resurrection check** — total `resurrected=True` count (expected 0).
- **NUL-byte failure list** — sha1s + first 200 chars of error. These
  feed the separate backlog item.
- **Post-fix confirmation** — explicit note that this re-run lands on
  `3a5adc7`, not `3cd00ba`, and that the soft-delete/upsert fix is
  active on the deployment (cite the `probe_prod.py resurrection`
  result from 2026-04-17 15:51 UTC).

---

## Hard gate for Phase 8 V2 completion

All must hold:

1. Step 1 preflight passes (real round-trip score > 0.3)
2. Step 2 confirms empty collection and the belt-and-suspenders
   `?purge=true` returns `documents_purged: 0` (or a small count if
   something appeared between the probe and the run)
3. Step 3 ingest completes without an unrecoverable error
4. Step 4: `durable == stored` — the meaningful version
5. Step 4: `errored == 0`
6. Step 4: `resurrected == 0` across all rows
7. Step 4: non-ok rows are all NUL-byte failures (recognized
   `psycopg.DataError` shape)
8. Step 4: all three spot-check queries return plausible scores

If 4 or 6 fails, we have evidence the fix didn't fully close the
pathology. Stop and report without declaring Phase 8 complete.

---

## Do NOT

- Attempt to fix the NUL-byte `psycopg.DataError` — separate bug,
  separate task. Log the failures and move on.
- Modify any source file — this is a data op.
- Commit, push, or stage anything.
- Re-read and re-follow the old `DAVE_WORLD_BANK_RESTART.md` — it
  predates the client rewrite (see V1's diff table).
- Change the `source_reference` scheme. `row["profile_url"]` is
  canonical; local `D:/...` paths are a regression.

---

## Post-handoff (Sam's problem, not yours)

Once `DAVE_DONE.md` is written and the gate is green, Sam will decide
whether to:

- Fire a Bob pass to record backlog items (NUL-byte bug, stats
  endpoint counter drift found during the 2026-04-17 DB probe —
  `total_collections: 1` vs 8 in the same response).
- Move on to the provenance plan (`cuddly-cuddling-bubble.md`) or the
  Query API 3-pass (`DAVE_QUERY_API_PASS_1.md`) — both are parked
  until Phase 8 clears.
