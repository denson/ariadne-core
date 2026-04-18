# DAVE_DONE — Query API Pass 1

**Spec:** `dave_and_bob_communication/DAVE_QUERY_API_PASS_1.md`
**Date:** 2026-04-17
**Verdict:** Pass 1 lands green. 199 passed / 3 skipped in `tests/`
(baseline 189 at `571beeb` + 10 new from this pass). No existing test
regressed. Nothing committed, nothing staged — Bob handles the commit.

---

## Pre-flight

```
HEAD                = 571beeb26dd0b904a5c5f5b4d902059a7024e598
origin/main         = 571beeb26dd0b904a5c5f5b4d902059a7024e598
working tree clean (other than untracked Phase 8 artifacts + helper scripts)
```

Matches spec: `HEAD == origin/main == 571beeb`, nothing modified/staged.

---

## Files

| File | Status | Why |
|---|---|---|
| `src/pipeline/api/routes.py` | modified | Added `tag` + `has_warnings` filter params, `include=` repeatable param, shape-dependent `limit` cap (500 default / 50 when markdown included), `_VALID_INCLUDES` set, `_build_row` local helper, `total_is_exact` response flag, default-row `warnings_count`. |
| `SPEC.md` | modified | Updated the `/api/documents` query-param table, added new "Querying documents — filters, includes, and cap" subsection directly after the existing GET section. |
| `tests/test_routes_list_documents.py` | new | 10 tests covering every new surface (defaults, tag filter, has_warnings both branches, include=tags, cap 50 w/ markdown, cap 500 w/o, unknown include 400, include=agent_metadata pulls latest, total_is_exact true/false). |

Expected: 2 modified + 1 new = 3. Matches.

`git status --short` confirms:

```
 M SPEC.md
 M src/pipeline/api/routes.py
?? tests/test_routes_list_documents.py
```

Plus the existing untracked helpers (`DAVE_DONE.md`, 4 `phase_8_*`
artifacts, 6 `scripts/_*.py` helpers) — all unchanged, none touched.

---

## Diff summary — `src/pipeline/api/routes.py`

### 1. New module-level constant

```python
_VALID_INCLUDES = {"agent_metadata", "tags", "last_interaction", "markdown"}
```

### 2. Route signature — three new params, `le=100` dropped from `limit`

```diff
 @router.get("/documents")
 async def list_documents(
     collection: Optional[str] = Query(None),
     file_type: Optional[str] = Query(None),
-    limit: int = Query(20, ge=1, le=100),
+    tag: Optional[str] = Query(None, description="..."),
+    has_warnings: Optional[bool] = Query(None, description="..."),
+    include: list[str] = Query(default_factory=list, description="..."),
+    limit: int = Query(20, ge=1),   # upper bound validated below (shape-dependent)
     offset: int = Query(0, ge=0),
     include_deleted: bool = Query(False),
     api_key: APIKey | None = Depends(check_api_key),
 ):
```

`le=100` is removed from the pydantic validator because the cap is
shape-dependent (50 with markdown, 500 otherwise) and has to happen
after `include` has been read.

### 3. Validate `include` values + `limit` cap (before any DB work)

```python
bad_includes = [i for i in include if i not in _VALID_INCLUDES]
if bad_includes:
    raise HTTPException(400, detail={
        "error": f"Unknown include value(s): {bad_includes}.",
        "valid_includes": sorted(_VALID_INCLUDES),
        "see": "SPEC.md § Querying documents",
    })
include_set = set(include)

cap = 50 if "markdown" in include_set else 500
if limit > cap:
    raise HTTPException(400, detail={
        "error": f"limit={limit} exceeds cap of {cap} for this include set.",
        "cap_applied": cap,
        "cap_rationale": "50 when 'markdown' is included ...; 500 otherwise",
        "include_set": sorted(include_set),
    })
```

### 4. Post-query filters — after the page is fetched (NOT in SQL)

```python
if tag is not None:
    page_docs = [d for d in page_docs if d.tags and tag in d.tags]
if has_warnings is not None:
    page_docs = [d for d in page_docs if (bool(d.warnings) == has_warnings)]

total_exact = True
if tag is not None or has_warnings is not None:
    total = len(page_docs)
    total_exact = False
```

This is a **deliberate Pass-1 pragmatism**: `dedup.py` signatures are
not touched (scope fence), so the filter runs in Python over the
already-paginated slice. `total_count` is only exact when neither
filter is active — the new `total_is_exact` flag in the response
surfaces that to the caller. Flagged for a future SQL-push pass.

### 5. New `_build_row` local helper

Row defaults (always returned, 10 fields):

```
document_id, source_file, title, file_type, collection,
content_fingerprint, chunk_count, interaction_count, created_at,
warnings_count                                                 ← NEW
```

Conditionally added by `include=`:

```
tags                → if "tags" in include_set
markdown            → if "markdown" in include_set
agent_metadata      → if "agent_metadata" in include_set
last_interaction    → if "last_interaction" in include_set
```

`_build_row` is defined as a local closure inside the route so it
closes over `include_set` — cleaner than a module-level helper with a
wider signature, and aligned with spec guidance ("either is fine;
pick the one that reads cleanest").

### 6. Response shape

```diff
 return {
     "documents": [_build_row(d) for d in page_docs],
     "total_count": total,
+    "total_is_exact": total_exact,
     "limit": limit,
     "offset": offset,
 }
```

---

## Diff summary — `SPEC.md`

One new subsection (`### Querying documents — filters, includes, and cap`)
inserted right after the existing `### GET /api/documents` section
content. The query-parameter table and response-shape line in the
existing section were updated to reflect the new surface (dropped
"max 100", added `tag`, `has_warnings`, `include`, mentioned
`total_is_exact` and `warnings_count`).

Net: +81 / −4. Strictly additive — no existing prose removed, no
section boundaries moved, no cross-section anchors broken.

---

## Test file — `tests/test_routes_list_documents.py`

10 tests. One concern per test, InMemory store path only (no Postgres).
All pass.

| # | Test | Covers |
|---|---|---|
| 1 | `test_list_documents_default_shape_has_warnings_count` | Default row has exactly the 10 expected fields; `warnings_count == 0` on clean doc |
| 2 | `test_list_documents_tag_filter_matches_only_tagged` | `?tag=keep` on 3 docs returns only the tagged one |
| 3 | `test_list_documents_has_warnings_true` | `?has_warnings=true` returns only the warned doc |
| 4 | `test_list_documents_has_warnings_false` | `?has_warnings=false` returns only the clean doc |
| 5 | `test_list_documents_include_tags_adds_field` | Without `include=tags`, `tags` absent; with it, list is present |
| 6 | `test_list_documents_include_markdown_caps_limit_at_50` | `include=markdown&limit=51` → 400 with `cap_applied=50`; `limit=50` → 200 |
| 7 | `test_list_documents_without_markdown_allows_limit_500` | `limit=500` → 200; `limit=501` → 400 with `cap_applied=500` |
| 8 | `test_list_documents_unknown_include_returns_400_with_valid_list` | `include=bogus` → 400 with `valid_includes` listing the 4 accepted values |
| 9 | `test_list_documents_include_agent_metadata_pulls_from_latest_interaction` | Two interactions seeded; returned metadata is the second |
| 10 | `test_list_documents_total_is_exact_flag` | Without filters `true`; with `tag=keep` `false` |

Fixture pattern mirrors `tests/test_api_delete_collection.py` — fresh
`InMemoryDedupStore` + `InMemoryVectorStore` + mounted `router` +
`TestClient` per test, wrapped in a small `_Fixture` helper so each
test case sets up independently.

---

## Test results

### New tests in isolation

```
$ python -m pytest tests/test_routes_list_documents.py -v
...
tests/test_routes_list_documents.py::test_list_documents_default_shape_has_warnings_count PASSED [ 10%]
tests/test_routes_list_documents.py::test_list_documents_tag_filter_matches_only_tagged PASSED [ 20%]
tests/test_routes_list_documents.py::test_list_documents_has_warnings_true PASSED [ 30%]
tests/test_routes_list_documents.py::test_list_documents_has_warnings_false PASSED [ 40%]
tests/test_routes_list_documents.py::test_list_documents_include_tags_adds_field PASSED [ 50%]
tests/test_routes_list_documents.py::test_list_documents_include_markdown_caps_limit_at_50 PASSED [ 60%]
tests/test_routes_list_documents.py::test_list_documents_without_markdown_allows_limit_500 PASSED [ 70%]
tests/test_routes_list_documents.py::test_list_documents_unknown_include_returns_400_with_valid_list PASSED [ 80%]
tests/test_routes_list_documents.py::test_list_documents_include_agent_metadata_pulls_from_latest_interaction PASSED [ 90%]
tests/test_routes_list_documents.py::test_list_documents_total_is_exact_flag PASSED [100%]

============================== 10 passed in 2.41s ==============================
```

### Full suite — HARD GATE

```
$ python -m pytest tests/
...
tests\test_routes_list_documents.py ..........                           [ 84%]
tests\test_schema.py ............                                        [ 90%]
tests\test_services.py .                                                 [ 90%]
tests\test_storage.py ...................                                [100%]

======================= 199 passed, 3 skipped in 25.49s =======================
```

Baseline check: `pytest tests/ --collect-only -q` → 192 tests
collected. 3 are `test_dedup_resurrection::TestPgResurrection` which
skip without a running Postgres → 189 passing baseline at `571beeb`.
189 + 10 new = 199. Matches spec ("`199 passed` expected").

No existing test regression. Zero changes in any test file other than
the new one.

---

## Scope-fence call-outs for Bob

### What was NOT touched (by design, per spec)

1. **`src/pipeline/dedup.py`** — zero changes. The `tag` and
   `has_warnings` filters are post-query in Python, not pushed into
   SQL. Spec explicitly calls this out as Pass-1 pragmatism; flagged
   below for a future SQL-push pass.
2. **`src/pipeline/services.py`** — zero changes. `_build_row` is
   presentation logic and lives in `routes.py`; spec says not to
   promote it to `services.py`.
3. **`client/src/ariadne_core_client/`** — zero changes. Client
   timeout fixes from Phase 8 still in place; no new `tag=` /
   `include=` plumbing on the client side. Pass 3.
4. **`skills/`** — zero changes. No skill-doc updates describing the
   new filters. Pass 3.
5. **No `HTTPException` call sites in `routes.py`** were modified
   other than the two new ones this pass adds (unknown include, cap
   exceeded). The Phase 8 BL-21 global handler at `app.py` still
   runs last and doesn't reshape these — verified implicitly by the
   existing `test_api_error_handler.py::test_existing_http_exception_routes_still_work_through_real_router`
   still passing.

### Explicit Pass-1 limitations (flagged for future passes)

1. **`total_count` is not whole-collection-exact when `tag` or
   `has_warnings` is active.** The filter runs post-pagination, so
   the pre-filter DB COUNT is wrong. We return the page size as
   `total` in that case and set `"total_is_exact": false` so the
   caller knows. Future SQL-push pass restores exact totals by
   moving both filters into the `list_documents` WHERE clause in
   `dedup.py`.
2. **`get_interactions` is N+1 in `_build_row` when `include=`
   contains `agent_metadata` or `last_interaction`.** Called per
   document in the page. Default callers (no include, or only
   `tags` / `markdown`) pay zero — the call is gated on the include
   set. At `limit=500` with `include=agent_metadata` this is 500
   round-trips; fine for Pass 1 but flagged for a future
   batch-fetch pass (`get_interactions_bulk(doc_ids=[...])`).
3. **Tag matching is exact only.** No wildcard, no case-insensitive,
   no `NOT` semantics. A doc with `tags=["KEEP"]` is not returned by
   `tag=keep`. Matches current `dedup.py` behavior.

### Deferred filters flagged during implementation (per spec — do not squeeze in)

- `store_status` — persist-as-column-vs-derive decision still open.
- `has_source_reference` — lives on `DocumentInteraction`, needs an
  interaction-join design.
- Date ranges (`created_after` / `created_before`) — not in this pass.
- `/documents/aggregate` and `/documents/schema` endpoints — Pass 2.

None were touched. None will be touched in Pass 1 follow-ups.

### Surprises / drift

None. Spec line numbers matched within 5 lines. SPEC section location
matched exactly. Pg-integration skip count (3) matched baseline.
No unexpected test failures.

One small note: `fastapi.Query(default_factory=list)` works on the
installed version (0.135.3) — confirmed by a quick smoke test before
writing the route. Older FastAPI versions that predate `default_factory`
support on `Query` would fail at import; not an issue here, just noting
in case the production Railway runtime ever lags.

---

## Hand-off

Bob: stage `src/pipeline/api/routes.py`, `SPEC.md`,
`tests/test_routes_list_documents.py`, and `DAVE_DONE.md`, commit,
push. Nothing else in the working tree should be in the commit.

— Dave
