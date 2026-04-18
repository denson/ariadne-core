# DAVE — Phase 8 V3 re-ingest (the 11 NUL-byte sha1s)

## Why

BL-17 landed in commit after `cf4d65f` and deployed. The NUL-byte
strip now runs at extraction output; Postgres no longer rejects the
11 World Bank files that failed V2 with bare HTTP 500s.

V3's job: re-ingest exactly those 11 files and confirm all 11 land
clean (status=stored, NUL-strip warning present, non-zero chunks).
This is the production validation of BL-17 at corpus scale — the
BL-17 commit already passed a single-file smoke, V3 proves the fix
holds across every file that previously hit it.

No code changes. No commit. This is a data op with a short throw-
away script.

---

## Scope

### 1. Write `scripts/_phase_8_reingest_v3.py`

Follow the shape of the existing `scripts/_phase_8_reingest_v2.py`,
but narrow to only the 11 sha1s that failed V2 with `[500] Internal
Server Error`.

The source of truth for those 11 is `phase_8_ingest_log_v2.json` at
the repo root. Extract them programmatically, not by pasting a
hardcoded list:

```python
failed_500 = [
    r for r in json.load(open("phase_8_ingest_log_v2.json"))
    if r.get("ok") is False
    and "500" in r.get("error", "")
]
# Expected: exactly 11 rows.
assert len(failed_500) == 11, f"expected 11, got {len(failed_500)}"
```

Reuse the V2 manifest join (`MANIFEST = .../docs.jsonl`) to build
each file's `agent_metadata` the same way V2 did — `source_reference`
from `profile_url`, `publication_date`, `document_type`, etc. This
keeps V3 ingests indistinguishable from V2 ingests in the corpus
except for the `phase` field.

Key deltas from V2:

- `COLLECTION = "world-bank-ree"` — same real corpus, not a throwaway.
  These are the 11 files that belong there.
- `phase` metadata key = `"phase_8_reingest_v3"` (not `v2`)
- `agent_notes` = `f"Phase 8 V3 re-ingest (BL-17 validation): {title[:80]}"`
- `force=True` on every call — these sha1s are guaranteed not in the
  DB (V2 failed before row insert), but force=True is defensive and
  idempotent on empty.
- `LOG_PATH = Path("phase_8_ingest_log_v3.json")`
- `timeout=600` in the `AriadneClient(...)` ctor. The BL-18 fix
  already floors this at 600 internally, but being explicit avoids
  confusion when someone reads the script later.
- Keep `STAGGER_MS = 1500`. Gemini embedding rate limits haven't
  changed since V2.

### 2. Run it

From the repo root with the venv active:

```bash
python scripts/_phase_8_reingest_v3.py 2>&1 | tee phase_8_ingest_stdout_v3.log
```

Expected runtime: ~25 seconds (11 files × 1.5s stagger + ingest
time). If it runs significantly longer (>60s), something's wrong —
stop and report.

### 3. Verify the log

After the script finishes, `phase_8_ingest_log_v3.json` should show:

- Exactly 11 rows
- All 11 with `ok: true`
- All 11 with `store_status: "stored"` (no `error`, no `skip`)
- All 11 with `chunks > 0`
- All 11 with at least one warning string containing `"NUL"` or
  `"0x00"` (the BL-17 strip warning). The count in the warning must
  be > 0 (the whole point is these files had NULs).

Any deviation → stop and report. Do NOT retry. If a file fails, we
need to see why before running anything again.

---

## Explicitly DEFERRED / Out of scope

- **The 2 V2 timeouts** (sha1s `67a7b480…` and `89d61066…`) — not
  this task. Those failed with the pre-BL-18 120s client default.
  BL-18 has since shipped, so they'd likely land now — but whether
  to re-run them is a separate call (Sam may schedule a narrow V3.5
  after V3 lands cleanly; or roll them into a future Phase 9).
- **The 1 V2 orphan** (sha1 `39f52973…`, document_id
  `c7913f48-4849-4716-bab9-761e653f28d7`) — BL-19 territory. Do NOT
  re-ingest it here. A re-ingest without the BL-19 transactional fix
  would either (a) dedup-skip on the existing orphan's fingerprint
  if one was written, or (b) create a duplicate row, either of which
  pollutes the corpus. Leave the orphan for a post-BL-19 cleanup op.
- **Full 574-file re-run** — unnecessary. Dedup would skip the 560
  already-landed files and we'd pay the check latency for no signal.
  The 11 are the only files we care about proving.
- **Modifying BL-17 code** — it's deployed and validated. Don't touch.
- **Any client / skill / spec change** — none needed.

---

## DO NOT list

- Do NOT commit, stage, or push. This is a data op; nothing goes to
  git. The script and both log files stay untracked per existing
  `scripts/_phase_*` and `phase_8_*` convention.
- Do NOT delete or modify `phase_8_ingest_log_v2.json` — V2's log is
  historical evidence, keep it.
- Do NOT retry any file that fails. Report and stop.
- Do NOT re-ingest the 2 timeouts or the 1 orphan. Scope is exactly 11.
- Do NOT ping prod with `/api/health` in a loop; the deploy is
  already live (Denson confirmed after BL-17's Bob push). Just run
  the script.

---

## Deliverable

Overwrite `DAVE_DONE.md` at the repo root with:

1. **Which 11 sha1s ran** — the list pulled from V2's log (first 12
   chars of each is fine for readability, full sha1 in the V3 JSON).
2. **Per-file verdict** — a small table: sha1 | stored? | chunks | NUL count
   (from the warning string). 11 rows.
3. **Aggregate** — `11/11 stored, 11/11 with NUL warning, total chunks embedded: N`.
4. **Elapsed time** — from the script's final summary line.
5. **Caveats** — anything unexpected. Zero warnings that weren't the
   NUL strip? A sha1 that landed with 0 chunks? Flag anything
   surprising, even if not a failure.
6. **Corpus-count sanity check** (optional but nice) — hit
   `GET /api/stats?collection=world-bank-ree` before and after the
   run. Expect `total_documents` to increase by exactly 11. If it
   didn't, something's off.

Hand off to Sam (no Bob this round — nothing to commit). Sam will
either greenlight BL-19 next, or ask you to re-run if V3 surfaced
anything weird.

— Sam
