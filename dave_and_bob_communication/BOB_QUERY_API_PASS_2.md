# BOB — Query API Pass 2 (review, commit, STOP for deploy, smoke)

Per `DAVE_QUERY_API_PASS_2.md` (Dave's spec) and `DAVE_DONE.md`
(Dave's report). Code and tests are staged in the working tree.
Nothing committed. Your job:

1. Review the diffs.
2. Add three new backlog entries (BL-21, BL-22, BL-23 — see below).
3. Commit + push.
4. **STOP** after push. Ask Denson to trigger the Railway deploy.
5. Only after he confirms the deploy is live, run the smoke test.

See `PROTOCOL.md` → "Deploy workflow — STOP after push" if this
convention is new to you. Do not poll prod.

---

## What Dave did (read `DAVE_DONE.md` first)

| File | Status |
|---|---|
| `src/pipeline/api/routes.py` | modified — registry cluster (`_FILTER_REGISTRY`, `_INCLUDE_REGISTRY`, `_AGGREGATE_REGISTRY`, `_CAPS`), two module-level helpers (`_reject_unknown_query_params`, `_has_source_reference`), `has_source_reference` filter on `/documents`, unknown-param rejector on `/documents`, new `/documents/aggregate` and `/documents/schema` routes |
| `SPEC.md` | modified — Pass-1 "silently ignored" disclaimer deleted, `has_source_reference` added to both filter tables + total_count paragraph, two new subsections (`### Aggregate`, `### Schema`) |
| `tests/test_routes_list_documents.py` | modified — 1 new test for `has_source_reference` |
| `tests/test_routes_aggregate_and_schema.py` | new — 14 tests covering aggregate group-by variants, filter propagation, schema response shape, registry drift guards, and unknown-query-param 400s on both endpoints |

Dave's summary: 220 passed / 3 skipped (baseline 205 after BL-19 + 15
new). Test count is +1 vs. my spec's 219 estimate because Step 6b's
list actually enumerates 14 tests, not 13 — harmless miscount on my
part; 220 is the correct number.

### Dave's one deviation from spec — route ordering (intentional, correct)

My spec said "add /aggregate and /schema below `list_documents` (line
~470)." Dave moved them **above** `GET /documents/{document_id}`
instead. Reason: FastAPI matches routes in declaration order, so if
`/documents/{document_id}` is declared before `/documents/aggregate`,
a request to `/api/documents/aggregate` is routed to the param route
with `document_id="aggregate"` and returns 404 or worse. Dave's fix
is correct; my spec was wrong to wave past this. Flagged in
`DAVE_DONE.md`. Diff will show the two new routes inserted in the
middle of the existing `/documents*` block rather than at its end —
that's expected, not a scope violation.

---

## Review checklist

### Scope fences (the boring important part)

- **`src/pipeline/dedup.py`** — must be untouched. Aggregation is in-
  route Python, not SQL. If you see edits here, Dave pushed filters
  into SQL after the spec told him not to. Stop and flag.
- **`src/pipeline/services.py`** — must be untouched.
- **`client/src/ariadne_core_client/`** — must be untouched. Pass 3.
- **`skills/`** — must be untouched. Pass 3.
- **`src/pipeline/migrations/`** — must be untouched. No schema changes.

`git diff --stat` should show exactly 3 modified + 1 new source/test/
spec file:

```
SPEC.md                                   | (+~60 -~5)
src/pipeline/api/routes.py                | (+~140 -~5)
tests/test_routes_list_documents.py       | (+~25 -0)
tests/test_routes_aggregate_and_schema.py | (new, ~250 lines)
```

(Plus the docs/BACKLOG.md edit you'll make in the next section, plus
DAVE_DONE.md update and DAVE_QUERY_API_PASS_2.md new — see staging
list below.) If `git diff --stat` shows anything outside this set,
stop and check.

### Registry-as-single-source-of-truth

- `_VALID_INCLUDES` should be **derived** from `_INCLUDE_REGISTRY`
  (`_VALID_INCLUDES = set(_INCLUDE_REGISTRY.keys())`), not hardcoded
  separately. If Dave kept both a hardcoded set AND the registry,
  the drift guard is defeated. Verify.
- `_LIST_DOCUMENTS_PARAMS` should be derived from
  `_FILTER_REGISTRY.keys() | {"include", "limit", "offset"}`, not a
  hand-maintained set.
- `_AGGREGATE_PARAMS` should be derived similarly. Test #11 and #12
  in the new test file are drift guards against exactly this —
  confirm they exist.
- The `/api/documents/schema` response body should serialize the
  registry dicts directly (`dict(_FILTER_REGISTRY)`, etc.), not
  repeat them in a literal. If the response has hand-written strings
  that duplicate the registry, the drift guard is defeated.

### Route ordering (Dave's fix)

Open `routes.py` and confirm route declarations appear in this
order (earlier = matched first by FastAPI):

1. `@router.post("/documents")` (existing, ~line 233)
2. `@router.get("/documents/aggregate")` (new — must be before `{document_id}`)
3. `@router.get("/documents/schema")` (new — must be before `{document_id}`)
4. `@router.get("/documents/{document_id}")` (existing, was line 271 — still exists, just later now)
5. `@router.get("/documents")` (existing `list_documents`, line ~337)
6. `@router.patch("/documents/{document_id}")`, `@router.delete(...)`, `@router.post(".../restore")` — unchanged

If `/aggregate` or `/schema` is declared **after** `/documents/{document_id}`,
the routing is broken and test #10/#12 probably caught it — but also
verify by eye.

### `has_source_reference` helper

- Lives at module level in `routes.py` (not inside any route).
- Pulls `get_interactions(document_id)` and inspects the **latest**
  entry (not the first, not all). `interactions[-1]` is correct if
  the list is oldest-first; confirm by reading the surrounding
  `get_interactions` implementation briefly.
- Treats missing / empty / `"unknown"` / whitespace-only values as
  "no source_reference" — returns `False` in those cases.
- Handles `agent_metadata is None`, `agent_metadata` not a dict, and
  `source_reference` not a string, without crashing.

### Aggregate response shape

- `buckets` sorted by `count` DESC, then `group` ASC (deterministic).
  Test #9 pins this.
- For `group_by=tags`: `total_documents` is **distinct-doc count**,
  not `sum(counter.values())`. A doc with 3 tags contributes 3 to
  the sum-of-buckets but 1 to total_documents. Test #3 pins this.
  If the implementation returns `sum(counter.values())` unconditionally,
  the test should fail — if it's passing, check that the test actually
  asserts `total_documents == 2` for the 2-doc / 3-tag setup.
- 1000-bucket cap raises 400, not 500. You won't see it exercised in
  tests (per my explicit note in the spec), but the code path must
  exist in the route body.

### SPEC.md change

- **Strictly additive apart from the one-paragraph deletion** of
  Pass 1's "silently ignored" disclaimer. Spot-check the diff: the
  only `-` lines should be that paragraph. Everything else is `+`.
- Check the two new subsections live **directly after** the existing
  `### Querying documents — filters, includes, and cap` content,
  not in a random place.
- `has_source_reference` should appear in the filter table **and**
  in the total_count-exactness paragraph (Pass 1's paragraph that
  listed `tag | has_warnings` as invalidating `total_is_exact`
  needs `| has_source_reference` added).

### Test file conventions

- `tests/test_routes_aggregate_and_schema.py` uses the same fixture
  pattern as `tests/test_routes_list_documents.py` — fresh
  `InMemoryDedupStore` + `InMemoryVectorStore`, mounted router,
  `TestClient` per test. If the new file reinvents the pattern, ask
  why — probably a sign Dave was fighting a leak.
- All tests are single-concern. If any test makes more than ~2–3
  assertions on the same response, question whether it should split.
- No Postgres required — `pytest tests/test_routes_aggregate_and_schema.py`
  should run green against an InMemory-only environment.

### Test count math

- Baseline at `2c9bace`: 205 passed / 3 skipped (per BL-19's gate).
- After this commit: 220 passed / 3 skipped (205 + 1 new in
  list_documents test file + 14 new in aggregate_and_schema test
  file). Dave's log reports 220; math checks.
- If the actual pytest summary is not `220 passed, 3 skipped`, ask
  Dave to re-run and verify before committing.

---

## Before committing — add backlog entries

`docs/BACKLOG.md` needs three new entries for items flagged during
Pass 2 that are real latent issues, not Pass-2 scope. Add these to
the **"Active backlog"** section (wherever the active entries live —
between BL-15 and the `### BL-9` resolved/diagnostic entries). Follow
the existing entry shape (heading, 2–3 lines of context, a Fix-direction
line, a Blocker line).

```markdown
### BL-21 — Query API filters + include=agent_metadata are post-query / N+1

`tag`, `has_warnings`, and `has_source_reference` are applied as
route-level Python post-filters over the already-paginated page.
Consequence: `total_count` is wrong whenever any of them is active
(we return `len(page_docs)` and set `total_is_exact=false`). Separately,
`include=agent_metadata` and `include=last_interaction` trigger an
N+1 on `get_interactions` — one query per row returned. Both
deliberately accepted for Pass 1/2 pragmatism; both want a single
"push filters into SQL + batch-fetch interactions" pass.

Fix direction: extend `PgDedupStore.list_documents` signature to
accept the new filters and build a SQL WHERE clause; add a
`get_latest_interactions_batch(doc_ids)` method returning a dict
keyed by document_id. Both are moderate SQL work, no schema change.

Blocker: none — ready to schedule. Good candidate for "Pass 2.5" or
a dedicated server-performance pass after Pass 3 lands.

### BL-22 — `has_warnings` filter is a no-op against Postgres

`StoredDocument.warnings` is populated at ingest time (it's a field
on the dataclass), but `_row_to_stored_document` in `dedup.py` never
pulls warnings out of the database — because there's no `warnings`
column on the `documents` table. So against Pg, every loaded
`StoredDocument.warnings` is `[]`, and `?has_warnings=true` silently
returns nothing. The filter still works correctly against the
InMemoryDedupStore (where warnings live on the Python object), which
is why unit tests pass.

Fix direction: either add a `warnings TEXT[]` column to `documents`
and persist on write + re-hydrate on read, OR persist warnings in
the existing `metadata JSONB` column and project out on read. Column
is cleaner for indexing; JSONB is zero-migration. Either way,
Pass 1's `has_warnings` filter becomes real.

Blocker: none — ready to schedule. Worth catching before the next
corpus of >100 ingested docs lands if any operator expects to query
by warnings.

### BL-23 — `agent_metadata.*` as `group_by` / `has_*` filters

The schema's `deferred` block names this explicitly. Useful queries
("how many docs per source_reference prefix?") need grouping by a
JSON path inside the latest interaction's `agent_metadata`. Pass 2
only aggregates over columns (`collection`, `file_type`, `tags`).

Fix direction: lateral-join the latest interaction per doc at the SQL
level (already partly needed for BL-21's batch-fetch), then
`jsonb_path_query_first` for the path. Start with two concrete
group_by values (`agent_metadata.source_reference`,
`agent_metadata.docty`) rather than a general JSON-path interface.

Blocker: probably waits for BL-21's SQL refactor to avoid double-
writing the latest-interaction subquery.
```

Stage `docs/BACKLOG.md` as part of this commit. The BL-21/22/23
entries are **part of this commit**, not a follow-up.

---

## Commit message

Suggested:

```
Query API Pass 2: /documents/aggregate + /documents/schema

Second of a three-pass expansion of GET /api/documents. Pass 1 shipped
filters, includes, and the cap in cf4d65f; Pass 2 adds the group-by
and discovery surfaces.

Scope (Pass 2 — server only):
- New endpoint GET /api/documents/aggregate with group_by in
  {collection, file_type, tags}. Reuses all /documents filters as
  WHERE. 1000-bucket cap with a narrow-with-filters hint on exceed.
- New endpoint GET /api/documents/schema returning a single-source-
  of-truth JSON blob (filters, includes, aggregatable_fields, caps,
  deferred items). Agents call this once, then query correctly.
- has_source_reference filter on /documents — previously deferred in
  Pass 1 pending interaction-join design; implemented as a route-
  level post-filter against the latest interaction's agent_metadata.
- Rich 400 on unknown top-level query params (not just unknown
  include= values) for both /documents and /aggregate. Pass 1's
  "silently ignored" disclaimer in SPEC is deleted accordingly.

Single source of truth:
  _FILTER_REGISTRY, _INCLUDE_REGISTRY, _AGGREGATE_REGISTRY drive
  both the runtime validators and the /schema response. Drift guards
  in the new tests (schema keys == registry keys) pin this down.

Route-ordering note: /aggregate and /schema are declared BEFORE
/documents/{document_id} so FastAPI's first-match routing doesn't
interpret "aggregate" as a document_id.

Tests: 15 new — 1 in tests/test_routes_list_documents.py
(has_source_reference), 14 in new tests/test_routes_aggregate_and_schema.py
covering each group_by, each filter passthrough, unknown-param 400s,
and the schema ↔ registry drift guards. Suite: 220 passed, 3 skipped
(205 baseline at 2c9bace + 15 new).

Backlog: BL-21 (SQL-push + batch-fetch for filters/interactions),
BL-22 (has_warnings no-op against Pg — warnings not persisted),
BL-23 (agent_metadata.* group_by) recorded alongside this commit.

Scope fence: no changes to dedup.py, services.py, client/, skills/,
or migrations. Out of scope for Pass 2 and intentionally absent.
```

(Omit `Co-Authored-By` unless you want Claude attribution.)

### What to stage

Exactly 6 paths:

- `src/pipeline/api/routes.py`
- `SPEC.md`
- `tests/test_routes_list_documents.py`
- `tests/test_routes_aggregate_and_schema.py`
- `docs/BACKLOG.md`  *(the BL-21/22/23 edits you just made)*
- `DAVE_DONE.md`  *(root — overwritten by Dave this cycle; already tracked)*

Plus the instruction file itself — it's already in
`dave_and_bob_communication/` which is now tracked territory:

- `dave_and_bob_communication/DAVE_QUERY_API_PASS_2.md`
- `dave_and_bob_communication/BOB_QUERY_API_PASS_2.md`  *(this file)*

Do NOT stage any of the `phase_8_*` artifacts, `scripts/_probe_*`,
`scripts/_phase_8_reingest*`, or `scripts/_generate_encoding_fixtures.py`
— all untracked by convention, all outside scope.

---

## Post-commit: STOP

1. Confirm push succeeded. Cite the new commit hash.
2. **STOP.** Tell Denson:

   > Commit <sha> is on `origin/main`. Please trigger the Railway
   > deploy (Deployments tab → Deploy). Ping me when it's live and
   > I'll run the Pass-2 smoke.

3. Do nothing else. Do not curl `/api/health`. Do not curl anything.
   Wait for Denson's confirmation.

---

## Smoke test (ONLY after Denson confirms deploy is live)

Four curls against prod (use `ARIADNE_URL` and `ARIADNE_API_KEY`
from `.env`). These exercise the new surface end-to-end and catch
deploy-vs-commit drift.

```bash
# 1. Schema endpoint returns the registry. Should list all filters,
#    includes, aggregatable_fields, and the deferred block.
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents/schema" \
  | python -m json.tool
# Expect: top-level keys include list_endpoint, aggregate_endpoint,
# filters, includes, aggregatable_fields, caps, brute_force_fallback,
# deferred. filters.has_source_reference present. aggregatable_fields
# lists exactly {collection, file_type, tags}.

# 2. Aggregate by file_type across world-bank-ree. After BL-19 + V3,
#    world-bank-ree has 571 docs.
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents/aggregate?group_by=file_type&collection=world-bank-ree" \
  | python -m json.tool
# Expect: sum of bucket counts == 571 (since world-bank-ree has no
# multi-tag docs grouped here). total_buckets likely 1 or 2 (mostly
# .txt / .pdf). total_documents == 571.

# 3. Unknown group_by returns 400 with the valid list.
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents/aggregate?group_by=nope"
# Expect: HTTP 400 with {"detail": {"error": "Unknown group_by 'nope'.",
# "valid_group_by": ["collection", "file_type", "tags"], "see": "..."}}

# 4. Unknown query param on /documents returns 400 (the Pass-2
#    validator hardening).
curl -sS -H "X-API-Key: $ARIADNE_API_KEY" \
  "$ARIADNE_URL/api/documents?collecton=world-bank-ree"
# (Note the typo in 'collecton'.)
# Expect: HTTP 400 with {"detail": {"error": "Unknown query param(s):
# ['collecton'].", "valid_params": [...], "endpoint": "/api/documents",
# "see": "/api/documents/schema"}}
```

Success: all four return the expected shapes, and #2's
`total_documents` matches `world-bank-ree` stats (571).

Failure modes:
- `/schema` returns 404 → new routes not deployed. Stale image? Ask
  Denson to re-check the deploy.
- `/aggregate` returns 500 → a real bug slipped through; grab the
  response body + any Railway logs and report to Sam. Do NOT retry
  in a loop.
- `/aggregate?group_by=nope` returns 200 with empty buckets → the
  whitelist check isn't running. Check the registry wiring.
- `/documents?collecton=...` returns 200 (silently ignored) → the
  unknown-param validator isn't wired into the route. Check that
  `_reject_unknown_query_params` is called at the top of
  `list_documents`.

Paste the smoke output into a new `BOB_DONE.md` in
`dave_and_bob_communication/` — or append to the existing one if it
still has Pass-1 content. Your call.

---

## Out of scope for this commit

- **BL-21 / BL-22 / BL-23 themselves** — recorded in BACKLOG as part
  of this commit; not fixed here.
- **Client library + skill doc updates** — that's Pass 3.
- **Root `BOB_DONE.md`** — doesn't exist anymore (deleted in BL-19's
  commit). If you want to capture smoke evidence, write it in
  `dave_and_bob_communication/BOB_DONE.md` (also scratch, also fine).
- **Stale `DAVE_DONE.md` convention** — PROTOCOL.md says DAVE_DONE.md
  is "untracked scratch," but it's been tracked since Pass 1's
  commit. Don't try to "fix" the inconsistency in this commit; it's
  its own conversation with Denson.

— Sam
