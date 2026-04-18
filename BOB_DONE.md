# BOB_DONE — Query API Pass 1 (commit + push + post-deploy smoke)

**Spec:** `dave_and_bob_communication/BOB_QUERY_API_PASS_1.md`
**Date:** 2026-04-17
**Commit:** `cf4d65f` — "Query API Pass 1: /documents filters, includes, and cap raise"
**Verdict:** Green. Pushed, deployed, all three smoke curls pass.

---

## Pre-flight

- `HEAD == origin/main == 571beeb` — matched Dave's report exactly.
- Working tree: `M SPEC.md`, `M src/pipeline/api/routes.py`, `?? tests/test_routes_list_documents.py`, `?? DAVE_DONE.md`. No other modified files. No unexpected drift.
- Untracked helpers (`phase_8_*`, `scripts/_*.py`) preserved — not staged.

## Scope fences — verified via full diff review

| Fence | Result |
|---|---|
| `src/pipeline/dedup.py` untouched | ✓ (not in diff) |
| `src/pipeline/services.py` untouched | ✓ (not in diff) |
| `client/src/ariadne_core_client/` untouched | ✓ (not in diff) |
| `skills/` untouched | ✓ (not in diff) |
| Existing `HTTPException` sites in `routes.py` unchanged | ✓ (only two new 400s added) |
| `bad_includes` check runs before `cap` check | ✓ (confirmed in route body — unknown-include fires first) |
| `le=100` deliberately removed from pydantic `limit=Query` | ✓ (required for shape-dependent cap to work) |

Strictly-additive SPEC.md check: 4 lines removed, all inside the rewritten query-param table / response-shape line. No section anchors broken.

## Pytest hard gate

```
$ python -m pytest tests/
...
199 passed, 3 skipped in 21.58s
```

189 baseline + 10 new from `tests/test_routes_list_documents.py`. The 3 skipped are the same `test_dedup_resurrection::TestPgResurrection` trio that skips without local Docker Postgres — unchanged from `571beeb`. Zero regressions.

## Commit + push

Staged exactly the 4 paths per spec:
- `src/pipeline/api/routes.py`
- `SPEC.md`
- `tests/test_routes_list_documents.py`
- `DAVE_DONE.md`

```
[main cf4d65f] Query API Pass 1: /documents filters, includes, and cap raise
 4 files changed, 740 insertions(+), 19 deletions(-)
 create mode 100644 DAVE_DONE.md
 create mode 100644 tests/test_routes_list_documents.py

To https://github.com/denson/ariadne-core.git
   571beeb..cf4d65f  main -> main
```

## Post-deploy smoke — all three pass

Railway deploy took ~10 min end-to-end (slower than the spec's "typical 3-5 min" estimate — deploy was visibly mid-swap at ~9 min with a connection reset, then healthy at ~10 min). Still faster than the BL-9 no-deploy pattern; likely just queue latency. Flagging in case it repeats.

### Smoke 1 — default shape + `warnings_count` + `total_is_exact=true`

```bash
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?collection=world-bank-ree&limit=3"
```

Response (trimmed — 3 rows shown, all with the same shape):

```json
{
    "documents": [
        {
            "document_id": "fe6ce5ee-e1f7-4047-ad27-eb23489ad9e1",
            "source_file": "sha1_ff3b418f9fb973f5255a81c3ced8bef1234dcd0f.txt",
            "title": null,
            "file_type": "txt",
            "collection": "world-bank-ree",
            "content_fingerprint": "4b424b56904889c04e7b591aafa5543cdfa06ae621cea7f15209d036836de794",
            "chunk_count": 29,
            "interaction_count": 1,
            "created_at": "2026-04-18T00:38:06.239351+00:00",
            "warnings_count": 0
        },
        ...
    ],
    "total_count": 561,
    "total_is_exact": true,
    "limit": 3,
    "offset": 0
}
```

All 10 default fields present including `warnings_count` (int). `total_is_exact: true` on the no-filter call. `total_count: 561` matches the Phase 8 V2 stats reading — BL-20's orphan-row inflation is still present and expected (BL-19 lands the fix).

### Smoke 2 — `include=tags` adds the field

```bash
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?collection=world-bank-ree&include=tags&limit=3"
```

Each row gains a `tags` field:

```json
"tags": [
    "corpus:world-bank-ree",
    "type:report",
    "topic:ree",
    "language:en"
]
```

Confirms `include=` is parsed, `tags` is gated on the include set, and the thin-row default is thickened only when asked.

### Smoke 3 — `include=bogus` returns 400 with `valid_includes`

```bash
curl -sS -w "\nHTTP %{http_code}\n" -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?include=bogus&limit=3"
```

```
{"detail":{"error":"Unknown include value(s): ['bogus'].","valid_includes":["agent_metadata","last_interaction","markdown","tags"],"see":"SPEC.md § Querying documents"}}
HTTP 400
```

Validates:
- HTTP 400 (not 422, not 500)
- `detail.error` is the structured-dict shape from the new `HTTPException`
- `detail.valid_includes` lists exactly the 4 accepted values alphabetically
- `detail.see` points to the SPEC subsection

Also incidentally re-proves the BL-21 exception-handler invariant: an `HTTPException` raised in-route passes through FastAPI's HTTPException handler (dict `detail`), NOT the generic `Exception` handler added in `571beeb`.

## Notes for Sam

1. **Deploy latency.** ~10 min wall-clock from `git push` to new surface live. Spec said 3-5 min typical. Not broken — just slower than usual. If it repeats on Pass 2, it's worth a note on BL-9.

2. **`total_count: 561` on world-bank-ree.** This is the same orphan-inflated count from the Phase 8 post-mortem (558 genuine stored + 2 timeout-but-landed + 3 error rows = 563 per earlier, re-counted today as 561). BL-19 + BL-20 still own this; Pass 1 did not and should not have touched it.

3. **`default_factory=list` concern from Dave's report.** Resolved — the deployed Railway runtime happily accepts `include=` as a repeatable query param. FastAPI on prod is new enough.

4. **`DAVE_DONE.md` is now part of the commit.** Dave's report was staged as one of the 4 paths per spec. Any future Dave hand-off should clobber that file and be re-staged.

5. **No backlog entries added this round** — as the spec directed.

— Bob
