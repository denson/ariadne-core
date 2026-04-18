# DAVE — Query API Pass 2: `/documents/aggregate` + `/documents/schema`

**Pass 1 is closed** — filters (`tag`, `has_warnings`), `include=`, the
shape-dependent cap, and the `warnings_count` default-row field all
shipped in `cf4d65f`. BL-17 and BL-19 landed on top (`ff62e7b`,
`5b91150`, `2c9bace`). You're clear to touch `routes.py` again.

Design context lives in `dave_and_bob_communication/SAM_QUERY_API_DESIGN.md`
but **don't read it directly** — this instruction is self-contained. All
design decisions are baked into the scope below.

**Scope of Pass 2:**

- Add `has_source_reference` filter to `GET /api/documents` (the filter
  deferred from Pass 1 pending interaction-join design — resolved).
- Add new endpoint `GET /api/documents/aggregate` with `group_by` in
  `{collection, file_type, tags}`, reusing all `/documents` filters as
  the WHERE clause. 1000-bucket cap.
- Add new endpoint `GET /api/documents/schema` that serializes a
  single source-of-truth registry of filters / includes /
  aggregatable_fields / caps. The registry feeds the validators on
  `/documents` and `/aggregate` so it cannot drift.
- Add rich 400 on unknown top-level query params (not just unknown
  `include=` values) for `/documents` and `/aggregate`.
- SPEC updates: two new subsections (`§ Aggregate`, `§ Schema`) plus
  a one-line delete of Pass 1's "unknown filter keys are silently
  ignored" disclaimer (no longer true after this pass).
- Tests for each new surface.

**Explicitly DEFERRED to a later pass** — do not try to squeeze these
in:

- `store_status` filter / group_by. BL-19 made this vestigial — every
  row in `documents` now has status=stored by construction, because
  failed ingests no longer write a row. Mention in `DAVE_DONE.md` that
  this field is intentionally absent from the schema, not forgotten.
- `agent_metadata.docty` and `agent_metadata.source_reference` as
  `group_by` values. The `has_source_reference` filter is cheap because
  it's a boolean; grouping by arbitrary JSON paths needs a Pg-side
  `jsonb_path_query_first` pattern and is its own pass.
- Date range filters (`created_after`, `created_before`).
- Pushing `tag` / `has_warnings` / `has_source_reference` down into
  the SQL `WHERE`. They remain post-query route-level filters for now,
  same as Pass 1. Flag in `DAVE_DONE.md` for a future SQL-push pass.
- Client library updates (that's Pass 3).
- Skill doc updates (that's Pass 3).

If any of these feel obvious while you're in the file, **do not do
them.** Flag in `DAVE_DONE.md`. Scope discipline matters.

---

## Step 0 — pre-flight

```
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**

- `HEAD == origin/main == 2c9bace` (BL-19 SHA backfill, the current
  tip after BL-19 landed) or a descendant of it. If `HEAD` is ahead
  of `origin/main`, **stop and report** — there shouldn't be unpushed
  commits.
- Nothing modified/staged. Untracked items expected: top-level
  `DAVE_DONE.md` from the last cycle, plus any `phase_8_*` / helper
  scripts still lying around.

If anything else is modified or staged, **stop and report**.

---

## Step 1 — Registries + shared validator helper

File: `src/pipeline/api/routes.py`.

The existing `_VALID_INCLUDES` constant (line ~334) is the start of
what the schema endpoint will serialize. Expand it into a small
cluster of registries near the top of the module-level section
(right above the existing `_VALID_INCLUDES` declaration).

### 1a. Registries

Place these as module-level constants. These are the **single source
of truth** — the schema endpoint serializes them verbatim, and the
validators at the top of each route read from them. Adding a filter
in one place, it shows up in the schema automatically.

```python
# ── Query API registries (single source of truth for /schema) ────────────────

_FILTER_REGISTRY: dict[str, str] = {
    "collection": "Exact match on collection name.",
    "file_type": "Exact match (leading dot stripped — 'pdf' and '.pdf' both match).",
    "tag": "Docs whose tag list contains this tag (single-value, OR-semantics across repeated calls).",
    "has_warnings": "true → only docs with >=1 warning; false → only clean docs.",
    "has_source_reference": (
        "true → latest interaction's agent_metadata has a non-empty "
        "'source_reference' value that is not literally 'unknown'. "
        "false → inverse."
    ),
    "include_deleted": "Include soft-deleted docs (default false).",
}

_INCLUDE_REGISTRY: dict[str, str] = {
    "agent_metadata": "Adds the latest interaction's agent_metadata dict per row.",
    "tags": "Adds the full tag list per row.",
    "last_interaction": "Adds {agent_notes, action, created_at} of the latest interaction.",
    "markdown": "Adds the full markdown body per row (caps limit at 50).",
}

_AGGREGATE_REGISTRY: dict[str, str] = {
    "collection": "One bucket per collection name.",
    "file_type": "One bucket per file type.",
    "tags": "One bucket per distinct tag. Docs with multiple tags contribute to multiple buckets. Docs with no tags contribute to nothing.",
}

_CAPS = {
    "list_default": 500,
    "list_with_markdown": 50,
    "aggregate_buckets_max": 1000,
}

_VALID_INCLUDES = set(_INCLUDE_REGISTRY.keys())  # replaces the existing constant
```

**Delete** the existing `_VALID_INCLUDES = {"agent_metadata", "tags",
"last_interaction", "markdown"}` line — the new registry-derived
version replaces it. Verify by running the tests after Step 6 that
nothing regressed because of the move.

### 1b. Unknown-param rejector

FastAPI silently ignores query params it doesn't declare. Design doc
§ Layer 1 explicitly calls for rich 400s on unknown top-level keys.
Add this module-level helper just below the registries:

```python
def _reject_unknown_query_params(
    request: "Request",
    allowed: set[str],
    endpoint_hint: str,
) -> None:
    """Raise 400 if the request has query params not in `allowed`.

    FastAPI's declarative Query params silently drop unknown keys by
    design. For agent-facing endpoints we want a loud failure so an
    agent that typos `collecton=` gets an immediate, specific error
    instead of a silent full-corpus scan.
    """
    got = set(request.query_params.keys())
    unknown = got - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown query param(s): {sorted(unknown)}.",
                "valid_params": sorted(allowed),
                "endpoint": endpoint_hint,
                "see": "/api/documents/schema",
            },
        )
```

Import `Request` from `fastapi` at the top of the file (it's not
imported yet — add it to the existing `from fastapi import ...` line).

### 1c. `has_source_reference` predicate helper

The check is reused in both `/documents` (as a filter) and
`/aggregate` (as a WHERE-equivalent). Factor out now, at the
module level near the other helpers:

```python
def _has_source_reference(document_id: str) -> bool:
    """True iff the latest interaction's agent_metadata has a
    non-empty source_reference that isn't literally 'unknown'.

    Matches the semantic documented in the schema endpoint. Pulls the
    interaction list per doc (N+1 — acknowledged, Pass-2 pragmatism,
    flagged for a future batch-fetch pass).
    """
    interactions = _svc._dedup_store.get_interactions(document_id)
    if not interactions:
        return False
    md = interactions[-1].agent_metadata or {}
    if not isinstance(md, dict):
        return False
    val = md.get("source_reference", "")
    if not isinstance(val, str):
        return False
    val = val.strip()
    return bool(val) and val != "unknown"
```

---

## Step 2 — Extend `GET /api/documents` with `has_source_reference`

Add the new filter to the route signature (right after `has_warnings`):

```python
has_source_reference: Optional[bool] = Query(
    None,
    description="Filter by presence of a non-empty, non-'unknown' source_reference in the latest interaction's agent_metadata.",
),
```

Add the param-validator call as the **very first** line of the route
body (before the existing `include` validation):

```python
_LIST_DOCUMENTS_PARAMS = set(_FILTER_REGISTRY.keys()) | {"include", "limit", "offset"}

async def list_documents(
    request: Request,
    ...
):
    _reject_unknown_query_params(request, _LIST_DOCUMENTS_PARAMS, "/api/documents")
    ...
```

`_LIST_DOCUMENTS_PARAMS` goes at module level alongside the
registries — do NOT rebuild it inside the function body on every
request.

Then apply the new filter **alongside** the existing `tag` /
`has_warnings` post-filters (same block, same `total_is_exact = False`
consequence if active):

```python
if has_source_reference is not None:
    page_docs = [
        d for d in page_docs
        if _has_source_reference(d.document_id) == has_source_reference
    ]

total_exact = True
if tag is not None or has_warnings is not None or has_source_reference is not None:
    total = len(page_docs)
    total_exact = False
```

Note the expanded condition on `total_exact` — all three post-filters
invalidate the pre-page `total`.

---

## Step 3 — New endpoint `GET /api/documents/aggregate`

Add below the `list_documents` route (~line 470, after the existing
`return` block). Self-contained, uses the same validator + registries.

```python
_AGGREGATE_PARAMS = (set(_FILTER_REGISTRY.keys()) | {"group_by"}) - {"include"}
# include= doesn't make sense for aggregate — the response is buckets, not rows.


@router.get("/documents/aggregate")
async def aggregate_documents(
    request: Request,
    group_by: str = Query(..., description="Field to group by. See /api/documents/schema for valid values."),
    collection: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    has_warnings: Optional[bool] = Query(None),
    has_source_reference: Optional[bool] = Query(None),
    include_deleted: bool = Query(False),
    api_key: APIKey | None = Depends(check_api_key),
):
    """Group-by summary over /documents filters. Returns [{group, count}, ...]."""
    from pipeline.dedup import PgDedupStore
    import collections as _py_collections

    _reject_unknown_query_params(request, _AGGREGATE_PARAMS, "/api/documents/aggregate")

    if group_by not in _AGGREGATE_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unknown group_by '{group_by}'.",
                "valid_group_by": sorted(_AGGREGATE_REGISTRY.keys()),
                "see": "/api/documents/schema",
            },
        )

    # Pull all matching docs. Use the same backend branching as list_documents;
    # 100000 matches the ceiling the stats endpoint already uses in this file.
    if isinstance(_svc._dedup_store, PgDedupStore):
        all_docs, _ = _svc._dedup_store.list_documents(
            collection=collection, file_type=file_type,
            limit=100000, offset=0,
            include_deleted=include_deleted,
        )
    else:
        docs = list(_svc._dedup_store._documents.values())
        if not include_deleted:
            docs = [d for d in docs if d.document_id not in _svc._dedup_store._deletions]
        if collection:
            docs = [d for d in docs if d.collection_id == collection]
        if file_type:
            ft = file_type.lstrip(".")
            docs = [d for d in docs if d.file_type == ft]
        all_docs = docs

    # Apply the post-filters — same semantics as /documents.
    if tag is not None:
        all_docs = [d for d in all_docs if d.tags and tag in d.tags]
    if has_warnings is not None:
        if has_warnings:
            all_docs = [d for d in all_docs if d.warnings]
        else:
            all_docs = [d for d in all_docs if not d.warnings]
    if has_source_reference is not None:
        all_docs = [
            d for d in all_docs
            if _has_source_reference(d.document_id) == has_source_reference
        ]

    # Group.
    counter: _py_collections.Counter[str] = _py_collections.Counter()
    if group_by == "collection":
        for d in all_docs:
            counter[d.collection_id] += 1
    elif group_by == "file_type":
        for d in all_docs:
            counter[d.file_type] += 1
    elif group_by == "tags":
        for d in all_docs:
            for t in (d.tags or []):
                counter[t] += 1

    if len(counter) > _CAPS["aggregate_buckets_max"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": (
                    f"Aggregate produced {len(counter)} buckets, "
                    f"exceeds cap of {_CAPS['aggregate_buckets_max']}. "
                    "Narrow with a filter (collection, file_type, etc.)."
                ),
                "cap_applied": _CAPS["aggregate_buckets_max"],
                "see": "/api/documents/schema",
            },
        )

    # Sort: count desc, then group name asc (deterministic tie-break).
    buckets_sorted = sorted(
        counter.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )

    applied_filters = {
        k: v for k, v in {
            "collection": collection,
            "file_type": file_type,
            "tag": tag,
            "has_warnings": has_warnings,
            "has_source_reference": has_source_reference,
            "include_deleted": include_deleted,
        }.items() if v is not None and v is not False
    }

    return {
        "group_by": group_by,
        "filters": applied_filters,
        "buckets": [{"group": g, "count": c} for g, c in buckets_sorted],
        "total_buckets": len(buckets_sorted),
        "total_documents": sum(counter.values()) if group_by != "tags" else len(all_docs),
    }
```

**Note on `total_documents` under `group_by=tags`:** because a multi-
tagged doc contributes N buckets, `sum(counter.values())` overcounts
vs. distinct docs. We return distinct-doc count for `tags` and
sum-of-buckets for the other fields (where they're equivalent). This
is subtle — flag it in `DAVE_DONE.md` so Bob can spot-check the test
that pins this behavior.

---

## Step 4 — New endpoint `GET /api/documents/schema`

Add directly below `/aggregate`. This one is pure serialization of
the registries — no logic, cannot drift.

```python
@router.get("/documents/schema")
async def documents_schema(
    api_key: APIKey | None = Depends(check_api_key),
):
    """Return the list/aggregate query surface. Call this first from an agent."""
    return {
        "list_endpoint": "/api/documents",
        "aggregate_endpoint": "/api/documents/aggregate",
        "filters": dict(_FILTER_REGISTRY),
        "includes": dict(_INCLUDE_REGISTRY),
        "aggregatable_fields": dict(_AGGREGATE_REGISTRY),
        "caps": {
            "list_default": _CAPS["list_default"],
            "list_with_markdown": _CAPS["list_with_markdown"],
            "aggregate_buckets_max": _CAPS["aggregate_buckets_max"],
        },
        "brute_force_fallback": (
            "If a question can't be expressed with these filters, "
            "paginate /api/documents with include=[...] covering the "
            "fields you need, then filter client-side."
        ),
        "deferred": {
            "store_status_filter": "BL-19 made store_status vestigial (failed ingests no longer write rows). Not planned.",
            "agent_metadata_group_by": "Grouping by arbitrary JSON paths in agent_metadata is a future pass.",
            "date_range_filters": "created_after / created_before are a future pass.",
        },
    }
```

No validator needed — schema takes no query params other than the
API key dep.

---

## Step 5 — SPEC update

File: `SPEC.md`. Find the existing `/api/documents` GET section (the
one Pass 1 updated with filters/includes/cap). Add two new subsections
**after** its end, before the next top-level `##` heading.

### 5a. Delete the Pass-1 disclaimer

In Pass 1's `### Querying documents — filters, includes, and cap`
subsection, find this paragraph:

```
Unknown filter keys are silently ignored by FastAPI's routing layer
(per its standard behavior for query params not declared on the
route). Future passes add stricter validation.
```

Delete it. Pass 2 adds the validation, so the disclaimer is now false.

### 5b. New `### Aggregate` subsection

```markdown
### Aggregate — group-by summary

`GET /api/documents/aggregate` returns per-group document counts.

**Required:** `group_by` (one of `collection`, `file_type`, `tags`).

**Optional filters** (same semantics as `/api/documents`, applied as
a WHERE clause before grouping): `collection`, `file_type`, `tag`,
`has_warnings`, `has_source_reference`, `include_deleted`.

**Response shape:**

```json
{
  "group_by": "file_type",
  "filters": {"collection": "world-bank-ree"},
  "buckets": [
    {"group": "pdf", "count": 450},
    {"group": "docx", "count": 100},
    {"group": "txt", "count": 22}
  ],
  "total_buckets": 3,
  "total_documents": 572
}
```

**Ordering:** `buckets` is sorted by `count` descending, tie-broken
by `group` ascending (deterministic).

**`tags` special case:** docs with multiple tags contribute to
multiple buckets. Docs with no tags contribute to none. For
`group_by=tags`, `total_documents` is the count of distinct docs in
the filter scope, NOT the sum of bucket counts.

**Cap:** if a query would produce more than 1000 buckets, returns
`400` with a hint to narrow via filters.

**Unknown `group_by` value** returns `400` with the list of valid
values.
```

### 5c. New `### Schema` subsection

```markdown
### Schema — discovery endpoint

`GET /api/documents/schema` returns the complete query surface as a
single JSON blob. Agents should call this once at the start of a
reasoning session to know what filters, includes, and group_by
values are valid without probing.

**Response fields:**

- `filters` — map of filter-name → human description. Every key here
  is accepted on `/api/documents` and (minus `include`) on
  `/api/documents/aggregate`.
- `includes` — map of include-value → description. Every key is
  accepted as a repeated `include=` query param on `/api/documents`.
- `aggregatable_fields` — map of group_by-value → description.
  Exactly the values accepted by `/api/documents/aggregate`'s
  `group_by` param.
- `caps` — numeric limits: `list_default` (max rows per list call
  without markdown), `list_with_markdown` (max rows with markdown),
  `aggregate_buckets_max` (max buckets per aggregate call).
- `brute_force_fallback` — prose explanation of how to handle
  questions the filters can't express.
- `deferred` — fields/filters intentionally not implemented, with
  brief reasons.

The registries that back the filter / include / group_by validators
also drive this response — the schema cannot drift from the
validators by construction.
```

---

## Step 6 — Tests

File: `tests/test_routes_aggregate_and_schema.py` (new). Same fixture
pattern as `tests/test_routes_list_documents.py` — copy its imports
and the in-memory-store setup block verbatim and adapt.

Also add ONE test to the existing `tests/test_routes_list_documents.py`
for the new `has_source_reference` filter (it belongs with the other
list_documents filter tests, not in the new file).

### 6a. In `tests/test_routes_list_documents.py`

Add one test — keep it adjacent to the other filter tests:

```python
def test_list_documents_has_source_reference_true():
    """has_source_reference=true returns only docs whose latest interaction has a real source_reference."""
    # Seed: 2 docs. Doc A gets an interaction with agent_metadata {source_reference: "doi:10.1/abc"}.
    # Doc B gets an interaction with agent_metadata {source_reference: "unknown"}.
    # Assert ?has_source_reference=true returns only A.
    # Also assert ?has_source_reference=false returns only B.
```

Use the same store-setup pattern Pass 1's tests use (`record_interaction`
with an `agent_metadata` dict on the interaction).

### 6b. In new `tests/test_routes_aggregate_and_schema.py`

Required test cases:

1. **`test_aggregate_group_by_file_type_returns_counts`** — seed 3 pdf
   + 2 docx. `?group_by=file_type` returns buckets sorted by count
   desc: `[{pdf,3}, {docx,2}]`.
2. **`test_aggregate_group_by_collection_respects_collection_filter`** —
   seed docs in two collections. `?group_by=collection&collection=A`
   returns a single bucket for A.
3. **`test_aggregate_group_by_tags_splits_multi_tag_docs`** — seed
   doc with tags `[x,y]` and doc with tags `[x]`. `?group_by=tags`
   returns `[{x,2}, {y,1}]`. Assert `total_documents == 2` (distinct
   docs), NOT `3`.
4. **`test_aggregate_group_by_tags_skips_no_tag_docs`** — seed 1
   tagless doc, 1 tagged `[x]`. `?group_by=tags` returns `[{x,1}]`,
   total_buckets=1, total_documents=1.
5. **`test_aggregate_has_warnings_filter_applies`** — seed 2 docs, 1
   with a warning. `?group_by=file_type&has_warnings=true` returns
   only the warnings doc's file_type bucket.
6. **`test_aggregate_has_source_reference_filter_applies`** — mirror
   of 6a's setup. `?group_by=collection&has_source_reference=true`
   returns only A's collection bucket.
7. **`test_aggregate_missing_group_by_returns_422`** — no `group_by`
   param. FastAPI's own validation returns 422 for missing required
   query params; confirm that's what we see (not 400). Different
   layer of the stack.
8. **`test_aggregate_unknown_group_by_returns_400_with_valid_list`** —
   `?group_by=bogus` returns 400 and the body includes a
   `valid_group_by` list matching `_AGGREGATE_REGISTRY` keys.
9. **`test_aggregate_deterministic_sort_on_tie`** — seed two file
   types with equal counts. Assert buckets come back in
   alphabetical group order when counts tie.
10. **`test_schema_returns_all_registry_keys`** — hit
    `/api/documents/schema`; assert top-level keys include
    `list_endpoint`, `aggregate_endpoint`, `filters`, `includes`,
    `aggregatable_fields`, `caps`, `brute_force_fallback`, `deferred`.
11. **`test_schema_filter_keys_match_registry`** — meta drift guard:
    import `_FILTER_REGISTRY` from the routes module and assert its
    keys are exactly the keys in the response's `filters` dict.
12. **`test_schema_aggregatable_fields_match_aggregate_validator`** —
    for every field in `response["aggregatable_fields"]`, hit
    `/api/documents/aggregate?group_by=<field>` and assert **not** 400
    (i.e. the schema promises only what aggregate actually accepts).
13. **`test_list_documents_unknown_query_param_returns_400`** —
    `?xyz=1` on `/api/documents` returns 400 with a `valid_params`
    list. (This belongs here, not in `test_routes_list_documents.py`,
    because the validator is new in Pass 2.)
14. **`test_aggregate_unknown_query_param_returns_400`** — same for
    `/api/documents/aggregate`.

**Do not** add tests for the 1000-bucket cap — constructing 1001
unique file_types via seed data is wasteful. Instead add one unit-
level assertion elsewhere if you feel it's needed, or skip. The cap
is a guard; the logic is linear; `len(counter) > N → 400` is trivial.

Keep tests short — one assertion per concern. Use InMemoryDedupStore +
InMemoryVectorStore; no Postgres.

---

## Step 7 — HARD GATE: pytest

```
python -m pytest tests/ -v
```

**Expected:** `219 passed` (205 baseline after BL-19 at `2c9bace` + 1
new `has_source_reference` test in `test_routes_list_documents.py` + 13
new in `test_routes_aggregate_and_schema.py`). Count may be off by a
couple if Pass 1's test count was 199 vs. my 205 baseline — use
`python -m pytest tests/ --collect-only -q | tail -5` to confirm the
actual starting count. Note any discrepancy in `DAVE_DONE.md`.

Any existing test regression → **stop and report**. Do NOT commit
on a red gate. Do NOT delete or "fix" existing tests to reach a green
gate — if something's broken, the right move is to tell Sam.

---

## Step 8 — hand off (do NOT stage, commit, or push)

Final `git status --short`. Expected:

- ` M SPEC.md`
- ` M src/pipeline/api/routes.py`
- ` M tests/test_routes_list_documents.py`  *(the single new test)*
- `?? tests/test_routes_aggregate_and_schema.py`
- Plus existing untracked helpers / DAVE_DONE.md / phase_8 artifacts

If anything else is modified or staged, **stop and report**.

---

## Step 9 — overwrite `DAVE_DONE.md`

Report for Bob. Include:

- Files edited: `src/pipeline/api/routes.py`, `SPEC.md`,
  `tests/test_routes_list_documents.py`.
- Files created: `tests/test_routes_aggregate_and_schema.py`.
- Summary `git diff` of routes.py (confirm scope: registries,
  validator helper, `has_source_reference` helper, `has_source_reference`
  filter added to /documents, `/aggregate` route, `/schema` route).
- SPEC diff (Pass-1 disclaimer deletion + two new subsections).
- Full contents of the new test file.
- Pytest summary line.
- Scope-fence call-outs for Bob:
  - No changes to `dedup.py` (scope fence — aggregation is in-route).
  - No changes to `services.py` (presentation logic only).
  - No changes to the client library (Pass 3).
  - `has_source_reference` is implemented as a post-filter; N+1 on
    `get_interactions` is deliberate Pass-2 pragmatism, flagged for a
    future batch-fetch pass.
  - `tag` / `has_warnings` / `has_source_reference` remain post-query
    filters; SQL-pushdown explicitly deferred.
  - `store_status` absent from the schema by design (BL-19 made it
    vestigial); the `deferred` block in the schema response documents
    why.
  - `agent_metadata.*` group_by values absent by design — future pass.
- Any surprises (unexpected test failures, line-number drift, SPEC
  section location changed from what I described, etc.). Better to
  over-report than under-report here.

Bob reviews scope, stages the 4 paths, commits, pushes. Deploy-flow
STOP applies as usual.

---

## Do NOT

- Touch `dedup.py`, `services.py`, or any file under `src/pipeline/`
  other than `src/pipeline/api/routes.py`. Scope fence.
- Push the filters or the aggregate grouping into SQL. Route-level is
  the Pass-2 target. Future pass.
- Add the deferred items (`store_status`, `agent_metadata.*` group_by,
  date ranges). Flag opinions in `DAVE_DONE.md`, do not implement.
- Touch the client library. Pass 3.
- Touch the skills directory. Pass 3.
- Delete or rename any existing default-row field or any Pass-1
  filter. Strictly additive — `has_source_reference` is the only new
  /documents filter, and the two new endpoints are new surfaces.
- Add more tests than listed. One surface, one test.
- Commit, stage, amend, or push. Hand off to Bob.
