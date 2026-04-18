# DAVE — Query API Pass 1: `/documents` filters + includes + cap raise

**Phase 8 is closed** — V2 re-ingest landed 560/574 docs in
`world-bank-ree`, ghost-write pathology is verified gone, and the
post-mortem fixes (BL-18 client ingest timeout floor + BL-21 server 500
body propagation) shipped in `571beeb` and are live on prod. You're
clear to touch `routes.py`.

Design context: `dave_and_bob_communication/SAM_QUERY_API_DESIGN.md`.
Don't read the design doc directly — this instruction is self-contained.
All 5 open design questions in that doc were resolved on 2026-04-17 by
Denson and are already baked into the Scope section below.

**Scope of Pass 1:**

- Add two new filter params (`tag`, `has_warnings`) to
  `GET /api/documents`
- Add `include=` query param with four accepted values
  (`agent_metadata`, `tags`, `last_interaction`, `markdown`)
- Raise the `limit` cap to 500 (50 when `markdown` is in include)
- Add one cheap field (`warnings_count`) to the default thin row
- Rich 400 responses on unknown filter/include keys and
  limit-over-cap
- SPEC update
- Tests for each new surface

**Explicitly DEFERRED to a later pass** — do not try to squeeze these
in:

- `store_status` filter (needs a schema decision — persist as column
  vs derive at read-time — too large for this pass)
- `has_source_reference` filter (lives in `DocumentInteraction`, not
  `StoredDocument`; interaction-table join design needed)
- Date range filters (`created_after`, `created_before`)
- `/documents/aggregate` endpoint (that's Pass 2)
- `/documents/schema` endpoint (that's Pass 2)
- Client library updates (that's Pass 3)
- Skill doc updates (that's Pass 3)

If any of these feel obvious while you're in the file, **do not do
them** — flag in `DAVE_DONE.md` for Pass 2/3 instead. Scope discipline
matters more than velocity here.

---

## Step 0 — pre-flight

```
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**
- `HEAD == origin/main == 571beeb` (the Phase 8 post-mortem fixes
  commit — `Fix client ingest timeout + propagate server 500 bodies`)
  or a descendant of it
- Nothing modified/staged
- Untracked: top-level `DAVE_DONE.md`, the 4 `phase_8_*` artifacts
  from the V2 ingest run, and the 6 helper scripts (`probe_*.py`,
  `purge_collection.py`, etc.). None of these are tracked; all are
  safe to ignore.

If `HEAD != origin/main`, or anything is modified/staged, or a
surprise tracked file has appeared, **stop and report**.

---

## Step 1 — add the filter params to `GET /api/documents`

File: `src/pipeline/api/routes.py`. The `list_documents` route is
currently at line 333–387 (check — line numbers may have drifted).

### 1a. Route signature changes

Current:

```python
@router.get("/documents")
async def list_documents(
    collection: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    api_key: APIKey | None = Depends(check_api_key),
):
```

Change to:

```python
@router.get("/documents")
async def list_documents(
    collection: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None, description="Match docs with this tag in their tag list"),
    has_warnings: Optional[bool] = Query(None, description="Filter to docs that have (or do not have) any warnings"),
    include: list[str] = Query(default_factory=list, description="Fields to include in each row. Accepted: agent_metadata, tags, last_interaction, markdown"),
    limit: int = Query(20, ge=1),  # upper bound validated below, depends on include
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    api_key: APIKey | None = Depends(check_api_key),
):
```

Notice: the `le=100` bound on `limit` is REMOVED from the validator.
We validate the upper bound in Step 1c based on the include set,
because the cap is shape-dependent (500 default, 50 with markdown).

### 1b. Validate `include` values up front

Immediately after the signature, before any other logic:

```python
_VALID_INCLUDES = {"agent_metadata", "tags", "last_interaction", "markdown"}
bad_includes = [i for i in include if i not in _VALID_INCLUDES]
if bad_includes:
    raise HTTPException(
        status_code=400,
        detail={
            "error": f"Unknown include value(s): {bad_includes}.",
            "valid_includes": sorted(_VALID_INCLUDES),
            "see": "SPEC.md § Querying documents",
        },
    )
include_set = set(include)
```

### 1c. Validate `limit` against shape-dependent cap

```python
cap = 50 if "markdown" in include_set else 500
if limit > cap:
    raise HTTPException(
        status_code=400,
        detail={
            "error": f"limit={limit} exceeds cap of {cap} for this include set.",
            "cap_applied": cap,
            "cap_rationale": (
                "50 when 'markdown' is included (full doc body per row); "
                "500 otherwise"
            ),
            "include_set": sorted(include_set),
        },
    )
```

### 1d. Apply `tag` and `has_warnings` filters

The existing code has two branches — `PgDedupStore` and in-memory
fallback. The signature of `_svc._dedup_store.list_documents` in
`dedup.py` does not currently accept `tag` or `has_warnings`, so:

**For the Pg branch:** don't modify the `list_documents` signature
in `dedup.py`. Instead, post-filter the returned `page_docs` list in
`routes.py` after the DB call. Yes, this is inefficient at large
collection sizes — we accept that for Pass 1 and flag it in
`DAVE_DONE.md` for a future "push filters into SQL" optimization
pass. Rationale: changing the `dedup.py` signature and SQL query is
cross-cutting and drifts scope; post-filter keeps this pass tight.

**For the in-memory branch:** add the filters to the existing list
comprehension chain in the same place where `collection` and
`file_type` are applied.

Concretely, after the existing filter block and before
`page_docs = docs[offset:offset + limit]` (in-memory) or after
`page_docs, total = _svc._dedup_store.list_documents(...)` (pg),
apply:

```python
# New filters — post-query for now (flag: push into SQL in a
# future pass for large-collection performance).
if tag is not None:
    page_docs = [d for d in page_docs if d.tags and tag in d.tags]
if has_warnings is not None:
    if has_warnings:
        page_docs = [d for d in page_docs if d.warnings]
    else:
        page_docs = [d for d in page_docs if not d.warnings]
```

**Important:** the `total` count returned to the caller currently
reflects the pre-filter total (from the DB COUNT). Because we're
post-filtering in-memory on a single page, `total` will be wrong
whenever `tag` or `has_warnings` is active. Set `total = len(page_docs)`
in that case and add a `total_is_exact_for_page_only` flag to the
response. Document this in SPEC and in the response itself. This
is explicitly a Pass-1 pragmatism — the future SQL-push pass will
fix `total`.

```python
total_exact = True
if tag is not None or has_warnings is not None:
    total = len(page_docs)  # pre-page-slicing count is now wrong; use page size
    total_exact = False
```

### 1e. Apply `include` to the row shape

Replace the existing per-row dict comprehension with an expanded
version that respects `include_set`. Helper approach:

```python
def _build_row(d, include_set: set[str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "document_id": d.document_id,
        "source_file": d.source_file,
        "title": d.title,
        "file_type": d.file_type,
        "collection": d.collection_id,
        "content_fingerprint": d.content_fingerprint,
        "chunk_count": _svc._count_chunks_for_document(d.document_id),
        "interaction_count": len(_svc._dedup_store.get_interactions(d.document_id)),
        "created_at": d.created_at,
        "warnings_count": len(d.warnings) if d.warnings else 0,  # NEW: cheap addition to default row
    }
    if "tags" in include_set:
        row["tags"] = list(d.tags) if d.tags else []
    if "markdown" in include_set:
        row["markdown"] = d.markdown
    if "agent_metadata" in include_set or "last_interaction" in include_set:
        interactions = _svc._dedup_store.get_interactions(d.document_id)
        latest = interactions[-1] if interactions else None
        if "agent_metadata" in include_set:
            row["agent_metadata"] = latest.agent_metadata if latest else None
        if "last_interaction" in include_set:
            row["last_interaction"] = (
                {
                    "agent_notes": latest.agent_notes,
                    "action": latest.action,
                    "created_at": latest.created_at,
                } if latest else None
            )
    return row
```

Use `_build_row` in the existing list-comprehension return:

```python
return {
    "documents": [_build_row(d, include_set) for d in page_docs],
    "total_count": total,
    "total_is_exact": total_exact,
    "limit": limit,
    "offset": offset,
}
```

**Note:** `_build_row` is defined inside the route function (as a
local closure) or as a private module-level helper in `routes.py`.
Either is fine; pick the one that reads cleanest. Do NOT move it to
`services.py` — this is presentation logic, not pipeline logic.

**Flag for DAVE_DONE.md:** the `get_interactions` call in
`_build_row` is N+1 when any include value requires interactions
(`agent_metadata` or `last_interaction`). For Pass 1 this is fine —
default callers don't include those fields. Note the cost in the
report so a future pass can batch-fetch.

---

## Step 2 — SPEC update

File: `SPEC.md`. Find the `/api/documents` GET section (currently
around line 400-430; look for `## List documents` or similar). Add
a new subsection right after its existing content:

```markdown
### Querying documents — filters, includes, and cap

**Filters** (all optional query params on `GET /api/documents`):

| Param | Type | Effect |
|---|---|---|
| `collection` | string | Exact match on collection name |
| `file_type` | string | Exact match (leading dot stripped, so `pdf` and `.pdf` both work) |
| `tag` | string | Match docs whose tag list contains this tag |
| `has_warnings` | bool | If `true`, only docs with at least one warning; if `false`, only docs with none |
| `include_deleted` | bool | Include soft-deleted docs (default `false`) |
| `limit` | int | Max rows per page (shape-dependent cap — see below) |
| `offset` | int | Pagination offset |

Unknown filter keys are silently ignored by FastAPI's routing layer
(per its standard behavior for query params not declared on the
route). Future passes add stricter validation.

**Includes** — use `include=` query param (repeatable) to thicken
the returned row. Default row is always returned; `include=` adds
fields.

| Include value | Adds |
|---|---|
| `agent_metadata` | Latest interaction's `agent_metadata` dict |
| `tags` | Full tag list |
| `last_interaction` | `{agent_notes, action, created_at}` for the most recent interaction |
| `markdown` | Full document markdown body |

Unknown include values return `400` with a list of valid values.

**Cap** — `limit` is bounded by the include set:

| Include set contains | Cap |
|---|---|
| `markdown` | 50 |
| anything else, or default | 500 |

`limit > cap` returns `400` with the applicable cap and rationale.

**Default row shape** (always returned):

```json
{
  "document_id": "...",
  "source_file": "...",
  "title": "...",
  "file_type": "...",
  "collection": "...",
  "content_fingerprint": "...",
  "chunk_count": 42,
  "interaction_count": 3,
  "created_at": "...",
  "warnings_count": 0
}
```

**`total_count` semantics:** when `tag` or `has_warnings` is active,
`total_count` reflects the current page's post-filter size, not the
whole-collection total. The response includes `"total_is_exact":
false` to signal this. Without these filters, `total_count` is the
exact collection total. Pass-1 limitation; future passes push the
filters into SQL and restore exact totals in all cases.

**Brute-force fallback** — if the question you're asking can't be
expressed with these filters, paginate `list_documents` with
`include=[...]` covering the fields you need, then filter
client-side:

```python
all_docs = []
offset = 0
while True:
    page = client.list_documents(
        collection="my-collection",
        include=["agent_metadata", "tags"],
        limit=500,
        offset=offset,
    )
    all_docs.extend(page.documents)
    if len(page.documents) < 500:
        break
    offset += 500
# now filter client-side
```
```

Verify your SPEC edit:

```
git diff -- SPEC.md
```

Should be exactly one new subsection inserted after the existing
`/api/documents` GET section, plus (if the existing section's
`limit`/`offset` documentation conflicts with the new description)
a minimal tweak to remove the old `le=100` claim. Nothing else.

---

## Step 3 — tests

File: `tests/test_routes_list_documents.py` (new — the existing
`tests/test_routes.py` is large; keep this pass's tests isolated).

Before writing, read an existing route-test file to match the
fixture pattern. Good candidates: `tests/test_routes.py`. Look for
the pattern that sets up a FastAPI `TestClient` and populates the
in-memory dedup/vector stores.

Required test cases:

1. **`test_list_documents_default_shape_has_warnings_count`** — no
   filters/includes; assert response `documents[0]` has exactly
   the default 10 fields (the 9 existing plus new `warnings_count`).
2. **`test_list_documents_tag_filter_matches_only_tagged`** —
   seed 3 docs, one with tag "keep"; `?tag=keep` returns only that
   one.
3. **`test_list_documents_has_warnings_true`** — seed 2 docs, one
   with a warning; `?has_warnings=true` returns only that one.
4. **`test_list_documents_has_warnings_false`** — same seed;
   `?has_warnings=false` returns only the clean one.
5. **`test_list_documents_include_tags_adds_field`** —
   `?include=tags` adds a `tags` field to each row; without it the
   field is absent.
6. **`test_list_documents_include_markdown_caps_limit_at_50`** —
   `?include=markdown&limit=51` returns 400; `limit=50` is fine.
7. **`test_list_documents_without_markdown_allows_limit_500`** —
   `?limit=500` returns 200; `?limit=501` returns 400.
8. **`test_list_documents_unknown_include_returns_400_with_valid_list`** —
   `?include=bogus` returns 400 and the response body contains
   `"valid_includes"` listing the four accepted values.
9. **`test_list_documents_include_agent_metadata_pulls_from_latest_interaction`** —
   seed a doc with two interactions whose metadata differs; assert
   the returned `agent_metadata` matches the second (most recent)
   interaction's.
10. **`test_list_documents_total_is_exact_flag`** — without
    `tag`/`has_warnings`, `total_is_exact` is `true`; with either,
    it's `false`.

Keep tests short — one assertion per concern. Use the InMemoryVectorStore
+ InMemoryDedupStore path; do not spin up Postgres.

---

## Step 4 — HARD GATE: pytest

```
python -m pytest tests/ -v
```

**Expected:** `199 passed` (189 from the current baseline at
`571beeb` after the Phase 8 post-mortem fixes + 10 new from this
pass — confirm baseline by counting first if you're paranoid, and
note any discrepancy in `DAVE_DONE.md`). The client-side test count
(`pytest client/tests/`) is unrelated to this pass — leave that alone.

Any existing test regression → **stop and report**. Do NOT commit
on a red gate.

---

## Step 5 — hand off (do NOT stage, commit, or push)

Final `git status --short`. Expected:

- ` M SPEC.md`
- ` M src/pipeline/api/routes.py`
- `?? tests/test_routes_list_documents.py`
- Plus existing untracked helpers (4 scripts + whatever Phase 8
  left behind)

If anything else is modified or staged, **stop and report**.

---

## Step 6 — overwrite `DAVE_DONE.md`

Report for Bob:

- Files edited: `src/pipeline/api/routes.py`, `SPEC.md`
- Files created: `tests/test_routes_list_documents.py`
- Summary git diff of routes.py (confirm the scope — filter param
  additions, include param, cap validation, row-builder helper,
  `total_is_exact` flag)
- SPEC diff (confirm one new subsection inserted after the
  existing section)
- Full contents of the new test file
- pytest summary line
- Explicit call-outs for Bob's scope tripwire:
  - The `total_is_exact` Pass-1-pragmatism is intentional, flagged
    for a future SQL-push pass
  - The N+1 `get_interactions` call in `_build_row` when
    `include=agent_metadata|last_interaction` is intentional and
    flagged for a future batch-fetch pass
  - No changes to `dedup.py` (deliberate — scope fence)
  - No changes to `services.py` (deliberate — presentation logic,
    not pipeline)
  - No changes to the client library (that's Pass 3)
- Any surprises (unexpected test failures, SPEC section location
  drifted, etc.)

Bob reviews scope, stages `routes.py` + `SPEC.md` +
`tests/test_routes_list_documents.py` + `DAVE_DONE.md`, commits,
pushes.

---

## Do NOT

- Touch `dedup.py`, `services.py`, or any file under `src/pipeline/`
  other than `src/pipeline/api/routes.py`. Scope fence.
- Add the deferred filters (`store_status`, `has_source_reference`,
  date ranges). Those are their own passes. Flag in `DAVE_DONE.md`
  if you have opinions, but do not implement.
- Add the `/documents/aggregate` or `/documents/schema` endpoints.
  Pass 2.
- Touch the client library. Pass 3.
- Touch the skills directory. Pass 3.
- Delete or rename any existing default-row field
  (`document_id`...`created_at`). Strictly additive — the new
  `warnings_count` is the only default-row change.
- Push the filter logic into the SQL in `dedup.py`. Tempting for
  performance, but scope fence — Pass 1 post-filters, future pass
  SQL-pushes.
- Add more tests than listed. One regression, one test, scoped to
  the new surface.
- Commit, stage, amend, or push. Hand off to Bob.
