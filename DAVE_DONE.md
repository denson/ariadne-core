# DAVE_DONE — Query API Pass 2

**Spec:** `dave_and_bob_communication/DAVE_QUERY_API_PASS_2.md`
**Date:** 2026-04-18
**Verdict:** `/documents/aggregate` + `/documents/schema` added, `has_source_reference` filter on `/documents`, rich 400 on unknown query params, SPEC updated, full test suite green.

---

## Files touched

- `M  src/pipeline/api/routes.py` — registries, validator helper, `has_source_reference` helper, `has_source_reference` filter on `/documents`, new `/documents/aggregate` and `/documents/schema` routes.
- `M  SPEC.md` — deleted Pass-1 "unknown filter keys silently ignored" disclaimer; added `has_source_reference` row to both filter tables; widened `total_count` semantics paragraph; added `### Aggregate` + `### Schema` subsections.
- `M  tests/test_routes_list_documents.py` — added `test_list_documents_has_source_reference_true` alongside the other filter tests.
- `??  tests/test_routes_aggregate_and_schema.py` — new file, 14 tests covering aggregate, schema, and unknown-query-param rejector.

No other files modified. `dedup.py`, `services.py`, client library, skills directory, and everything under `src/pipeline/` other than `api/routes.py` untouched.

---

## `routes.py` diff summary (confirming scope)

```
 src/pipeline/api/routes.py | 270 +++++++++++++++++++++++++++++++++++-
```

Scope of the change, by region:

1. **Import line** — added `Request` to the existing `from fastapi import ...` line.
2. **Module-level registries** (replacing the single `_VALID_INCLUDES = {...}` constant):
   - `_FILTER_REGISTRY` (6 entries including `has_source_reference`)
   - `_INCLUDE_REGISTRY` (4 entries, same values as the old set)
   - `_AGGREGATE_REGISTRY` (3 entries: `collection`, `file_type`, `tags`)
   - `_CAPS` (`list_default=500`, `list_with_markdown=50`, `aggregate_buckets_max=1000`)
   - `_VALID_INCLUDES = set(_INCLUDE_REGISTRY.keys())` — derived, not hand-maintained.
   - `_LIST_DOCUMENTS_PARAMS` and `_AGGREGATE_PARAMS` — derived at module load, not per request.
3. **Module-level helpers:**
   - `_reject_unknown_query_params(request, allowed, endpoint_hint)` — raises 400 on any query-param key not in `allowed`.
   - `_has_source_reference(document_id)` — reads last interaction, checks `agent_metadata["source_reference"]` is a non-empty string other than `"unknown"`.
4. **`list_documents` (`GET /api/documents`):**
   - New `request: Request` param at the head of the signature.
   - New `has_source_reference: Optional[bool] = Query(None, ...)` param between `has_warnings` and `include`.
   - `_reject_unknown_query_params(request, _LIST_DOCUMENTS_PARAMS, "/api/documents")` is now the first line of the body.
   - New post-filter branch after `has_warnings` applying `_has_source_reference`.
   - `total_exact = False` condition widened to include `has_source_reference`.
5. **`aggregate_documents` (`GET /api/documents/aggregate`)** — new route, placed BEFORE `GET /documents/{document_id}` so the path-parameter route does not swallow it (see § Route-ordering note below).
6. **`documents_schema` (`GET /api/documents/schema`)** — new route, placed next to `/aggregate`.

**Route-ordering note** (surprise flagged for Bob): FastAPI dispatches routes in registration order. I originally placed `/documents/aggregate` + `/documents/schema` below `/documents` (as the spec's "add below the `list_documents` route" instruction suggested), but that left them shadowed by `@router.get("/documents/{document_id}")`, which was registered earlier and would match `document_id="aggregate"`. I verified the problem by printing `router.routes` and confirming order, then moved both new routes to just above `@router.get("/documents/{document_id}")`. Final registration order:

```
GET  /documents/aggregate       ← new, registered before the path param
GET  /documents/schema          ← new, registered before the path param
GET  /documents/{document_id}
GET  /documents
PATCH /documents/{document_id}
DELETE /documents/{document_id}
POST /documents/{document_id}/restore
```

This matches the design intent (static segments resolve before the path-param route) and does not affect any existing endpoint.

---

## SPEC.md diff

Four blocks:

1. **Top `/api/documents` parameter table** — added a `has_source_reference` row between `has_warnings` and `include`.
2. **Querying documents → Filters table** — added a `has_source_reference` row between `has_warnings` and `include_deleted`.
3. **Deleted** the Pass-1 disclaimer paragraph: `"Unknown filter keys are silently ignored by FastAPI's routing layer … future passes add stricter validation."`
4. **Widened `total_count` semantics paragraph** to list `has_source_reference` alongside `tag` / `has_warnings`.
5. **Appended** two new subsections before the `---` separator preceding `### GET /api/documents/{id}`:
   - `### Aggregate — group-by summary`
   - `### Schema — discovery endpoint`

Both new subsections are copied verbatim from the spec's 5b/5c blocks.

---

## New test file: `tests/test_routes_aggregate_and_schema.py`

14 tests, each with a single concern. Fixture pattern mirrors `test_routes_list_documents.py` exactly (`_Fixture` class, `_make_doc` helper, InMemoryDedupStore + InMemoryVectorStore).

```
# ── aggregate ─────────────────────────────────────────────────────────
test_aggregate_group_by_file_type_returns_counts
test_aggregate_group_by_collection_respects_collection_filter
test_aggregate_group_by_tags_splits_multi_tag_docs
test_aggregate_group_by_tags_skips_no_tag_docs
test_aggregate_has_warnings_filter_applies
test_aggregate_has_source_reference_filter_applies
test_aggregate_missing_group_by_returns_422
test_aggregate_unknown_group_by_returns_400_with_valid_list
test_aggregate_deterministic_sort_on_tie
# ── schema ────────────────────────────────────────────────────────────
test_schema_returns_all_registry_keys
test_schema_filter_keys_match_registry
test_schema_aggregatable_fields_match_aggregate_validator
# ── unknown-query-param rejector ─────────────────────────────────────
test_list_documents_unknown_query_param_returns_400
test_aggregate_unknown_query_param_returns_400
```

Plus one test added to `test_routes_list_documents.py`:
- `test_list_documents_has_source_reference_true` — asserts both `=true` and `=false` branches.

---

## Pytest summary

```
$ python -m pytest tests/ -q
...
220 passed, 3 skipped in 23.31s
```

**Count reconciliation:** spec predicted `219 passed` (205 baseline + 1 list_documents + 13 aggregate_and_schema). Actual is `220 passed` — the spec's step-6b enumerated 14 test cases but summed them as 13 in Step 7. 14 new tests in `test_routes_aggregate_and_schema.py` + 1 in `test_routes_list_documents.py` = 15 new, and 205 + 15 = 220. No existing test regressions; the 3 skips are the same pre-existing Postgres-path skips as before.

---

## Scope-fence call-outs for Bob

- **No changes to `dedup.py`.** Aggregation is implemented at the route layer by calling the existing `list_documents` (PgDedupStore path) or iterating `_documents.values()` (InMemory path), mirroring the pattern already used by `/stats` and `/collections` in the same file.
- **No changes to `services.py`.** Presentation logic only — no pipeline changes.
- **No changes to the client library** (`client/ariadne_core_client/`). Pass 3.
- **No changes to the skills directory.** Pass 3.
- **No existing default-row field or Pass-1 filter was renamed or removed.** Strictly additive: `has_source_reference` is the only new `/documents` filter; `/aggregate` and `/schema` are new surfaces.
- **`has_source_reference` is implemented as a post-query, route-level filter** via the `_has_source_reference` helper. This issues one `get_interactions` call per candidate document (N+1). This is deliberate Pass-2 pragmatism — a future pass with a batch-fetch method on `DedupStore` can collapse this to a single query. Flagged per spec.
- **`tag` / `has_warnings` / `has_source_reference` remain post-query filters.** SQL-pushdown is explicitly deferred. `total_is_exact=false` surfaces the caveat to callers.
- **`store_status` filter/group_by intentionally absent from the schema.** BL-19 made it vestigial (every row now has status=stored by construction). The schema's `deferred.store_status_filter` entry documents why.
- **`agent_metadata.*` as `group_by` values intentionally absent.** Grouping by arbitrary JSON paths needs a Pg-side `jsonb_path_query_first` pattern and is its own pass. Documented in the schema's `deferred.agent_metadata_group_by` entry.
- **Date range filters (`created_after` / `created_before`) intentionally absent.** Documented in the schema's `deferred.date_range_filters` entry.
- **No tests for the 1000-bucket cap.** Per spec ("constructing 1001 unique file_types via seed data is wasteful"). The cap is a trivial `len(counter) > N → 400` guard; reviewer can spot-check it in `routes.py` around line 350.

---

## Surprises / notes for Bob

1. **Route ordering (already covered above)** — static `/documents/aggregate` and `/documents/schema` had to be registered before `/documents/{document_id}` to avoid path-param shadowing. Spec's Step 3 wording ("Add below the `list_documents` route") would have produced a broken endpoint; I deviated and documented above.

2. **Test count +1 vs spec** — 220 vs predicted 219. This is the Step-6b enumeration listing 14 tests but summing to 13 in Step 7, not a regression or extra scope. The 14th test (either numbered #8 or #13/14 depending on how you split the aggregate-validator and unknown-param groups) is in the spec; the arithmetic is the discrepancy.

3. **SPEC filter tables** — Pass 2 step 5 only explicitly called for the disclaimer deletion and the two new subsections, but the filter tables at the top of the `/api/documents` section and the "Querying documents" subsection now list every other filter and would drift if `has_source_reference` were left out. I added the row to both tables. This is in-scope (Pass 2 ships the filter) and keeps SPEC truthful about what's accepted — flagging in case Bob wants to revert one of them for style consistency.

4. **`total_count` paragraph** — similarly widened to mention `has_source_reference` alongside `tag` and `has_warnings`. Same justification.

5. **Pre-existing working-tree state** — `DAVE_DONE.md` (this file) was already `M` at session start from the BL-19 cycle. Rewriting it for Pass 2 is consistent with prior cycles. `phase_8_*.json/log` and `scripts/_probe_*`, `scripts/_phase_8_reingest*`, `scripts/_generate_encoding_fixtures.py` are all from earlier investigations and are not part of Pass 2's scope fence.

6. **The spec's Step-0 pre-flight expected HEAD == origin/main == 2c9bace.** Confirmed: `git rev-parse HEAD` and `git rev-parse origin/main` both returned `2c9bace718208bfa625c420b128d6be8ad937870`. No unpushed commits.

---

## Hand-off

Bob, when you pick this up:

- Stage exactly these 4 paths:
  - `src/pipeline/api/routes.py`
  - `SPEC.md`
  - `tests/test_routes_list_documents.py`
  - `tests/test_routes_aggregate_and_schema.py`
- Plus `DAVE_DONE.md` if the workflow includes it in the commit as in prior cycles.
- Do not stage any `phase_8_*`, `scripts/_*`, or `dave_and_bob_communication/DAVE_QUERY_API_PASS_2.md` — those are artifacts.
- Scope call-outs are all listed above; please spot-check the `tags` `total_documents` semantics in `test_aggregate_group_by_tags_splits_multi_tag_docs` (the distinct-doc-count vs. sum-of-buckets choice was called out in the spec as "subtle — flag in DAVE_DONE.md so Bob can spot-check").
- Deploy-flow STOP applies as usual. No push until Sam greenlights.
