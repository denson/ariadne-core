# BOB — Query API Pass 1 (review, commit, smoke test)

Per `DAVE_QUERY_API_PASS_1.md` (Dave's spec) and `DAVE_DONE.md`
(Dave's report). Code and tests are staged in the working tree.
Nothing is committed. Your job:

1. Review the diffs.
2. Commit + push.
3. Post-deploy smoke test against prod.

No backlog entries this round — deferred items already live in
`docs/BACKLOG.md` from the Phase 8 post-mortem commit.

---

## What Dave did (read `DAVE_DONE.md` first)

| File | Status |
|---|---|
| `src/pipeline/api/routes.py` | modified — added `tag`, `has_warnings`, `include=` params; shape-dependent cap (500 default / 50 when markdown); `_VALID_INCLUDES` set; `_build_row` local closure; `total_is_exact` response flag; `warnings_count` in default row |
| `SPEC.md` | modified — query-param table updated; new "Querying documents — filters, includes, and cap" subsection |
| `tests/test_routes_list_documents.py` | new — 10 tests, one concern each, InMemory path only |

Tests: 199 passed / 3 skipped (189 baseline at `571beeb` + 10 new). Zero regressions.

---

## Review checklist

### Scope fences (the boring important part)

- **`src/pipeline/dedup.py`** — must be untouched. `tag` and
  `has_warnings` run as Python post-filters over the already-paginated
  page, NOT as SQL pushdowns. This is a deliberate Pass 1 pragmatism
  documented in Dave's "Scope-fence call-outs" section. If you see
  edits to `dedup.py`, stop and flag — Dave stepped out of scope.
- **`src/pipeline/services.py`** — must be untouched. `_build_row` is
  a local closure inside the route, not a promoted helper.
- **`client/src/ariadne_core_client/`** — must be untouched. Pass 3
  handles the client library updates.
- **`skills/`** — must be untouched. Pass 3 handles skill docs.
- **Existing `HTTPException` call sites in `routes.py`** — unchanged.
  Only two new ones added (unknown `include` → 400 with
  `valid_includes`, `limit > cap` → 400 with `cap_applied` +
  `cap_rationale`). Verify no existing route's error shape changed.

### Shape-dependent cap logic

- `cap = 50 if "markdown" in include_set else 500` runs AFTER the
  unknown-include validation. If a caller sends
  `include=markdown&include=bogus`, they should get the unknown-include
  400, not the cap 400. Confirm the order in the route body.
- `le=100` is intentionally removed from the pydantic `limit=Query(...)`
  validator because pydantic validation happens before the route body
  can read `include`. The cap is validated manually in the route.
  This is correct — do not "fix" it by putting a static `le=500` back.

### `total_is_exact` honesty

- When `tag` or `has_warnings` is active, `total = len(page_docs)`
  (post-filter page size) and `total_is_exact = False`. This is the
  honest-but-imprecise answer for Pass 1. When a future pass pushes
  both filters into SQL, `total_is_exact` becomes `True` again.
- Default case (no filter) returns the unpaginated total from
  `list_documents` — `total_is_exact = True`.
- Spot-check: test #10 (`test_list_documents_total_is_exact_flag`)
  covers both branches. Confirm it's asserting `False` when
  `?tag=keep` is active and `True` on the no-filter call.

### `_build_row` closure

- Lives inside the route, closes over `include_set`. Spec said
  either local or module-level is fine; Dave chose local. That's
  correct — the function signature stays narrow (just `doc`) and the
  include logic doesn't have to be re-plumbed through call sites.
- The `get_interactions` N+1 in `_build_row` is real but gated — only
  triggers if `include=agent_metadata` or `include=last_interaction`.
  Default-path callers (no include, or only `tags` / `markdown`) pay
  zero. Flagged in Dave's report as a future bulk-fetch pass.

### SPEC.md change

- **Strictly additive.** Dave reports +81 / -4 with "no existing
  prose removed, no section boundaries moved, no cross-section
  anchors broken." Spot-check by searching the diff for lines
  starting with `-` that aren't inside a changed table — if all the
  removed lines are inside the query-param table being rewritten,
  the claim holds.
- Check the new "Querying documents — filters, includes, and cap"
  subsection lives **directly after** the existing
  `### GET /api/documents` content, not in a random place.

### Test file conventions

- Fixture pattern mirrors `tests/test_api_delete_collection.py` —
  fresh `InMemoryDedupStore` + `InMemoryVectorStore` + mounted
  `router` + `TestClient` per test. Same pattern as the Phase 8
  fix's `test_api_error_handler.py`. Confirm.
- No Postgres required — `pytest tests/test_routes_list_documents.py`
  should run green against an InMemory-only environment.
- All 10 tests are one-concern-per-test. No multi-assertion
  omnibus tests.

### Test count math

- Baseline at `571beeb`: 189 passing (after the Phase 8 post-mortem
  fixes landed +4 server-side tests). `pytest tests/ --collect-only -q`
  should show 192 collected; 3 skip without Postgres (the
  `test_dedup_resurrection::TestPgResurrection` trio).
- After this commit: 199 passing, 3 skipped. Dave's log confirms.

---

## Commit message

Suggested:

```
Query API Pass 1: /documents filters, includes, and cap raise

First of a three-pass expansion of GET /api/documents to let agents
query the corpus without fetching-and-filtering-client-side.

Scope (Pass 1 — server only):
- New filters: ?tag=<str> (single-value, exact match) and
  ?has_warnings=<bool>. Post-query Python filters for this pass;
  future pass will push them into SQL for exact total_count.
- New ?include= repeatable param: agent_metadata, tags,
  last_interaction, markdown. Default thin row stays narrow.
- Shape-dependent limit cap: 500 default, 50 when markdown is
  included. Invalid limit / unknown include values return 400 with
  structured detail (valid_includes list, cap_rationale).
- warnings_count added to every default row (no opt-in needed).
- total_is_exact boolean in response — false when post-query filter
  is active, true otherwise. Honest about Pass 1's pragmatism.

Out of scope (future passes):
- tag is single-value for now; multi-tag AND/OR lives client-side
- store_status, has_source_reference, date-range filters — Pass 2
- /documents/aggregate, /documents/schema endpoints — Pass 2
- client library + skill doc updates — Pass 3

Tests: 10 new cases in tests/test_routes_list_documents.py covering
default shape + each new surface. No changes to existing tests.
Full suite: 199 passed, 3 skipped (189 baseline + 10 new).

No schema changes. No client-visible breaking changes — existing
thin-row consumers gain warnings_count + total_is_exact; all other
fields unchanged.
```

(Omit `Co-Authored-By` unless you want Claude attribution.)

### What to stage

Exactly 4 paths (per Dave's hand-off section):

- `src/pipeline/api/routes.py`
- `SPEC.md`
- `tests/test_routes_list_documents.py`
- `DAVE_DONE.md`

Nothing else in the working tree should be in the commit. Do NOT
stage the `phase_8_*` artifacts, `smoke_bl21.py`, or any of the
`probe_*.py` helpers — all of those stay untracked per convention.

---

## Post-commit smoke test

After the push triggers the Railway deploy (typical 3-5 min), fire
one live-surface smoke to confirm the deploy succeeded and the new
surface actually works. This also shakes out the
`fastapi.Query(default_factory=list)` concern Dave flagged — we need
to prove the deployed Railway runtime has a FastAPI new enough to
support it.

Two curls against prod (use `ARIADNE_URL` and `ARIADNE_API_KEY` from
`.env`):

```bash
# 1. Default shape still works (regression guard) + warnings_count present
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?collection=world-bank-ree&limit=3" \
  | python -m json.tool | head -40
# Expect: 3 docs, each with warnings_count (int), total_is_exact=true

# 2. New include= surface works and unknown include returns 400 with valid list
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?collection=world-bank-ree&include=tags&limit=3"
# Expect: 3 docs each with "tags" field

curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?include=bogus&limit=3"
# Expect: HTTP 400 with {"detail": {"error": "Unknown include value(s): ['bogus'].",
#                                    "valid_includes": ["agent_metadata", "last_interaction",
#                                                       "markdown", "tags"], ...}}
```

If any of those fail, the commit landed but the deploy is broken.
Tell Sam — do NOT roll back without a chat.

If all three pass, Pass 1 is done. Paste the curl output into a
short post-commit note appended to `DAVE_DONE.md` (or a new
`BOB_DONE.md` if you prefer the old convention) so the evidence is
captured.

---

## Out of scope for this commit

- **Pass 2 endpoints** (`/documents/aggregate`, `/documents/schema`)
  — separate spec.
- **Client library updates** to match the new server surface — Pass 3.
- **Skill doc updates** explaining the new filters to agents — Pass 3.
- **SQL pushdown** of `tag` / `has_warnings` into `dedup.py` — future
  pragmatism-retirement pass; flagged in `DAVE_DONE.md`.
- **Any of the deferred filters** (`store_status`,
  `has_source_reference`, date ranges) — Pass 2.

— Sam
