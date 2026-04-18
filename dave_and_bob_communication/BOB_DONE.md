# BOB_DONE — Query API Pass 3 review + smoke

**Status:** REVIEWED + SMOKED (PASS)
**Reviewed commit:** `01489e1` — *Query API Pass 3: client + skill catch-up* (on `main`)
**Parent:** `c5903a3` (BL-25 migration runner rewrite)
**Live server:** `https://ariadne-core-production-579a.up.railway.app` (post-redeploy 2026-04-18)
**Scope per spec:** client + skill + one new test file. **No server / SPEC.md / CLI changes.**

---

## Review gate — Dave's diff vs. spec fences

| Check | Result |
|---|---|
| Only `client/src/ariadne_core_client/{client,models}.py`, `client/tests/test_query_api_pass3.py`, `skills/ariadne-document-intelligence/SKILL.md`, `dave_and_bob_communication/DAVE_*.md` touched | ✅ (+826-line hand-off doc, spec'd) |
| Server code (`src/pipeline/api/**`, `dedup.py`, `services.py`) untouched | ✅ |
| `SPEC.md`, `migrations/`, `tests/` (server) untouched | ✅ |
| `Document.warnings_count: int \| None` added alongside existing `warnings: list[str]` | ✅ `models.py:57` |
| New dataclasses `DocumentListPage`, `AggregateBucket`, `AggregateResponse`, `QuerySchema` | ✅ `models.py:136-211` |
| `list_documents()` returns `DocumentListPage` (breaking from `list[Document]`), iterable/len/getitem work | ✅ `models.py:148-155`, `client.py:502-512` |
| Bool params (`has_warnings`, `has_source_reference`, `include_chunks`, `include_interactions`, `include_deleted`) serialize as lowercase `"true"/"false"`, never Python's `"True"/"False"` | ✅ `client.py:65-76`; test asserts `"True"`/`"False"` absent from URL (`test_query_api_pass3.py:47-48`) |
| `include=[...]` emits one `include=` param per value (server does `getlist`) | ✅ `client.py:490-493` via `urlencode([("include", v), ...])` |
| `_parse_document` reads `warnings_count` (passes through `None` when server omits key) | ✅ `client.py:157` + test pins the `None`-passthrough case (`test_query_api_pass3.py:106-109`) |
| `aggregate()` hits `/api/documents/aggregate`, returns `AggregateResponse` with populated `filters`/`buckets`/`total_*` | ✅ `client.py:514-578` |
| `schema()` hits `/api/documents/schema`, returns `QuerySchema` with all six fields | ✅ `client.py:580-616` |
| Skill doc — new `## Query API` section with `schema()` → filter table → `include=` table → `aggregate()` → brute-force-fallback note; warnings-count called out as a cheap per-row field | ✅ `SKILL.md:493-593` |
| Skill doc — search-filter table retitled `Search filters reference (chunks via /api/search)` and scoped to chunk-level retrieval with a pointer up to the Query API | ✅ `SKILL.md:609-622` |
| Skill doc — "Browsing and managing documents" step 2 pointed at Query API for richer queries | ✅ `SKILL.md:456-458` |
| Tests: 5 new, all in `client/tests/test_query_api_pass3.py` | ✅ |

**Local test run:** `cd client && python -m pytest -q` → **12 passed** (7 prior timeout tests + 5 new Pass 3 tests), 0 failures.

---

## Live smoke against Railway (four checks per Dave's hand-off §"Bob handoff")

All four checks green against the post-redeploy live server. No redeploy needed for Pass 3 itself — I re-ran after Denson's redeploy to confirm nothing moved.

### 1. `client.schema()` → `QuerySchema`

```
list_endpoint:        /api/documents
aggregate_endpoint:   /api/documents/aggregate
filters:              ['collection', 'file_type', 'has_source_reference',
                       'has_warnings', 'include_deleted', 'tag']
includes:             ['agent_metadata', 'last_interaction', 'markdown', 'tags']
aggregatable_fields:  ['collection', 'file_type', 'tags']
caps:                 {'list_default': 500, 'list_with_markdown': 50,
                       'aggregate_buckets_max': 1000}
deferred:             ['agent_metadata_group_by', 'date_range_filters',
                       'store_status_filter']
```

- All six expected filters present (incl. `has_warnings`, `has_source_reference`, `tag`). ✅
- Four includes, three aggregatable fields, `caps["list_default"] == 500`. ✅
- Dataclass populated — no `None` on any field. ✅

### 2. `client.aggregate(group_by="collection")` → `AggregateResponse`

```
total_buckets:    12
total_documents:  586
sum(b.count):     586           # matches total_documents ✅
filters echoed:   {}            # correct — no filters passed
top buckets:      [('world-bank-ree', 571), ('smoke_phase_7_5_20260417_post_fix', 3),
                   ('smoke_phase_7_5_20260417d', 3), ('bl22-smoke-1776502083', 1),
                   ('ghostprobe_20260417_144921', 1)]
```

- Buckets iterable via `for b in resp`, sorted count DESC / group ASC as Pass 2 spec'd. ✅
- `sum(bucket.count) == total_documents` — distinct-doc counting holds for non-tag group_by. ✅

### 3. `client.list_documents(has_warnings=True)` → `DocumentListPage`

```
len(page):        1
total_count:      1
total_is_exact:   False
limit:            5
offset:           0
rows:
  fac256f9... src='bl22_nul_smoke.txt' warnings_count=2
```

- Only the BL-22 pin surfaces — expected; it's the one doc with warnings on this corpus. ✅
- Every returned row has `warnings_count >= 1`. ✅
- Returned object is a `DocumentListPage`, iterable, with pagination metadata populated. ✅

### 4. `client.get_document(<id>)` — `warnings_count` round-trip

```
id:                fac256f9-ea81-4ee9-98dc-b15e75208381
source_file:       bl22_nul_smoke.txt
warnings_count:    2
len(warnings):     2
warnings_count is not None?       True   ✅
warnings_count == len(warnings)?  True   ✅
warnings sample: ['Source contained 3 NUL (0x00) byte(s); stripped before storage. …',
                  'Encoding validation: text may be garbled']
```

BL-22 pin still intact. `warnings_count` field lands on `Document` and matches the full list length. ✅

---

## Observations / flags for the next author

1. **`total_is_exact: False` on a 1-row result** — `list_documents(has_warnings=True)` returns `total_count: 1` with `total_is_exact: False`. That's a server-side heuristic (probably "skip exact COUNT when the WHERE is cheap enough to not care"), not a Pass 3 client issue. Flagged only because the client now surfaces the `total_is_exact` field and a consumer might be surprised that "small exact result" comes back as approximate. No action needed in Pass 3; worth revisiting if the server ever exposes a `count_mode` hint.
2. **Dave's own flag carried forward**: CLI (`src/pipeline/cli.py`) has no `aggregate` / `schema` subcommands and no `--tag` / `--has-warnings` / `--has-source-reference` / `--include` flags on `list`. Listed in Dave's "Known-deferred"; leaving it alone per Pass 3 fence.
3. **Stale example URL in the original spec Step 0** — the spec still lists `ariadne-core-production.up.railway.app` (no `-579a`), which 404s. Dave noted it; noting again here for whoever writes the next Pass spec.
4. **Breaking change is pre-1.0 and deliberate** — `list_documents()` no longer returns `list[Document]`. `DocumentListPage` is iterable + `len()` + subscriptable so naive for-loops and `len(page)` keep working; any caller that did `list(page)` + set/dict operations will need a one-liner fix. No shim, per spec.
5. **`DAVE_DONE.md` changed shape**: Dave overwrote the prior Phase 8 hand-off per spec. If anyone was referencing the old content, it's in the earlier commit `01489e1^`. This `BOB_DONE.md` likewise overwrites my prior Pass 2 BOB_DONE.

---

## Net

Pass 3 is clean: client matches the Pass 2 surface, tests green locally, all four live checks PASS against the post-redeploy server, and the skill doc now tells agents to start with `schema()` before guessing. No server redeploy was needed for Pass 3 itself. — Bob
