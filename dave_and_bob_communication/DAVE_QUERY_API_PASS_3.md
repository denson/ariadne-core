# DAVE — Query API Pass 3: client library + skill doc

**Pass 2 shipped** the server-side query surface: `tag` /
`has_warnings` / `has_source_reference` filters, `include=` projection,
paginated envelope, `/documents/aggregate`, `/documents/schema`, and
`warnings_count` on every row. **Pass 3 is the non-server catch-up:**
teach the Python client and the doc-intelligence skill to use that
surface. No server code changes at all.

The provenance plan's server + SPEC work (`source_reference`,
`source_notes`, server warning) already shipped in prior passes.
That's out of scope here too — we're only wiring Pass 2 through to
agents.

---

## Scope of Pass 3

**In scope:**

- `client/src/ariadne_core_client/models.py`: add `warnings_count`
  to `Document`; add `DocumentListPage`, `AggregateBucket`,
  `AggregateResponse`, `QuerySchema` dataclasses.
- `client/src/ariadne_core_client/client.py`:
  - `list_documents()` — add `tag`, `has_warnings`,
    `has_source_reference`, `include` params. Change return type
    from `list[Document]` to `DocumentListPage` (see breaking-change
    note below).
  - New `aggregate()` method.
  - New `schema()` method.
  - `_parse_document()` — read `warnings_count`.
- `client/tests/` — add tests for all four new behaviors.
- `skills/ariadne-document-intelligence/SKILL.md`:
  - New `## Query API` section covering discovery + filters +
    aggregation + includes + `warnings_count`.
  - Fix the existing "Search filters reference" table so readers
    don't confuse `/api/search` filters with `/api/documents`
    filters.
  - Update the "Browsing and managing documents" example to call
    out the new filters.

**Explicitly OUT of scope — do not touch:**

- Any file under `src/pipeline/` (server code is frozen for this
  pass).
- `SPEC.md` (already current — Pass 2 updated §Aggregate, §Schema,
  and the filter list, and the provenance subsection already
  landed).
- `src/pipeline/cli.py` — the CLI is a separate surface. If Dave
  notices the CLI lacks aggregate/schema, flag in `DAVE_DONE.md`,
  don't fix.
- Any migration, schema check, or DB code.
- The cannabis skill in `D:\video_projects\...` (different repo,
  not part of ariadne-core).
- Any change to `list_collections`, `create_collection`,
  `update_document`, `delete_document`, `restore_document`,
  `get_document`, `search`, `ingest_*`. Their signatures stay
  exactly as they are. (`get_document`'s response already has
  `warnings_count` server-side — the one-line `_parse_document`
  change below handles it; don't add a parameter.)

If anything feels "obvious but out of scope" while you're in the
file, flag it in `DAVE_DONE.md` and leave it. Scope discipline
matters.

---

## Breaking change acknowledgement

`list_documents()` currently returns `list[Document]`. After this
pass it returns `DocumentListPage` (which iterates as a list of
`Document` for `for d in page: ...` ergonomics, mirroring
`SearchResponse`). Code that does `docs = client.list_documents();
docs[0]` or `len(docs)` or `for d in docs:` keeps working. Code
that does `docs + [other]` or `isinstance(docs, list)` breaks.

There are **no external users** of the client yet — this is pre-1.0.
The pagination metadata (`total_count`, `total_is_exact`) is load-
bearing for agents reasoning about corpus size, so losing it in the
client wrapper was a Pass 1 mistake. Fixing it now is the right
move.

Do **not** add a deprecation path / `list_documents_legacy()` /
`as_list=True` kwarg. Just change it. If Bob's smoke reveals some
internal call site that relied on list-ness, fix the call site.

---

## Step 0 — pre-flight

```
cd ariadne-core
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Expected:

- `HEAD == origin/main`, pointing at the most recent BL-25 / BL-26
  SHA (the migration runner refactor tip).
- Nothing modified or staged. Untracked items OK: prior
  `DAVE_DONE.md`, helper scripts.

If anything else is dirty or unpushed, **stop and report**.

Also confirm the deployed server actually has Pass 2:

```
curl -s -H "X-API-Key: $ARIADNE_API_KEY" \
  https://ariadne-core-production.up.railway.app/api/documents/schema \
  | python -m json.tool
```

You should see `list_endpoint`, `aggregate_endpoint`, `filters`,
`includes`, `aggregatable_fields`, `caps`, `brute_force_fallback`,
`deferred`. If that endpoint 404s, **stop** — the server is older
than Pass 2 and this whole spec is premature.

---

## Step 1 — Model additions

File: `client/src/ariadne_core_client/models.py`.

### 1a. `Document.warnings_count`

Add one field after `warnings` (line 56):

```python
warnings: list[str] = field(default_factory=list)
warnings_count: int | None = None
```

`None` = "server didn't send the field" (older server, pre-Pass 2);
`int` = "server sent the count". Do **not** default to `0` — we need
to distinguish "no warnings" from "unknown".

### 1b. New dataclasses

Add below the existing `Collection` dataclass (~line 131). Order
them `DocumentListPage`, then aggregate types, then `QuerySchema`:

```python
@dataclass
class DocumentListPage:
    """Paginated response from list_documents.

    Iterates as its `documents` list so `for d in page: ...` and
    `len(page)` work like the old `list[Document]` return type.
    """
    documents: list[Document] = field(default_factory=list)
    total_count: int = 0
    total_is_exact: bool = True
    limit: int = 0
    offset: int = 0

    def __iter__(self):
        return iter(self.documents)

    def __len__(self):
        return len(self.documents)

    def __getitem__(self, idx):
        return self.documents[idx]

    def __repr__(self) -> str:
        exact = "" if self.total_is_exact else "~"
        return (
            f"DocumentListPage(docs={len(self.documents)}, "
            f"total={exact}{self.total_count}, "
            f"limit={self.limit}, offset={self.offset})"
        )


@dataclass
class AggregateBucket:
    """One row of an aggregate response."""
    group: str | None
    count: int


@dataclass
class AggregateResponse:
    """Response from /api/documents/aggregate."""
    group_by: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    buckets: list[AggregateBucket] = field(default_factory=list)
    total_buckets: int = 0
    total_documents: int = 0

    def __iter__(self):
        return iter(self.buckets)

    def __len__(self):
        return len(self.buckets)

    def __repr__(self) -> str:
        return (
            f"AggregateResponse(group_by={self.group_by!r}, "
            f"buckets={self.total_buckets}, "
            f"docs={self.total_documents})"
        )


@dataclass
class QuerySchema:
    """Discovery response from /api/documents/schema.

    Fields are dicts of `{name: description}` as returned by the
    server. Treat this as documentation metadata — inspect it, don't
    mutate it.
    """
    list_endpoint: str = ""
    aggregate_endpoint: str = ""
    filters: dict[str, str] = field(default_factory=dict)
    includes: dict[str, str] = field(default_factory=dict)
    aggregatable_fields: dict[str, str] = field(default_factory=dict)
    caps: dict[str, int] = field(default_factory=dict)
    brute_force_fallback: str = ""
    deferred: dict[str, str] = field(default_factory=dict)
```

Don't forget to import `Any` at the top of `models.py` — it's
already imported (line 6), so just verify.

---

## Step 2 — Client parser update

File: `client/src/ariadne_core_client/client.py`.

In `_parse_document` (line 126), add `warnings_count` read. Keep
`warnings` read as-is. The server returns `warnings_count` on both
list rows and get-by-id, so one call site covers both:

```python
warnings=list(data.get("warnings") or []),
warnings_count=data.get("warnings_count"),
```

`data.get("warnings_count")` returns `None` if absent (older server),
`int` if present. That's exactly the semantic we want.

---

## Step 3 — `list_documents()` new signature

File: `client/src/ariadne_core_client/client.py`, lines 426-453.

Replace the full method. New version:

```python
def list_documents(
    self,
    *,
    collection: str | None = None,
    file_type: str | None = None,
    tag: str | None = None,
    has_warnings: bool | None = None,
    has_source_reference: bool | None = None,
    include: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    include_deleted: bool = False,
) -> DocumentListPage:
    """List documents on the server, with filters + projection.

    Args:
        collection: exact collection name.
        file_type: exact file type (leading dot stripped
            server-side).
        tag: docs whose tag list contains this tag. Single-value
            only — the server ANDs nothing, it just matches one.
        has_warnings: True = only docs with >=1 warning; False =
            only clean docs; None = both.
        has_source_reference: True = latest interaction's
            agent_metadata has a non-empty, non-"unknown"
            source_reference; False = inverse; None = both.
        include: list of extra row fields to request. Accepts
            any of: "agent_metadata", "tags", "last_interaction",
            "markdown". Server caps limit at 50 when "markdown"
            is in this list, 500 otherwise.
        limit: page size (default 20).
        offset: page offset (default 0).
        include_deleted: include soft-deleted docs (default False).

    Returns:
        A `DocumentListPage` with `.documents`, `.total_count`,
        `.total_is_exact`, `.limit`, `.offset`. Iterable as a list
        of `Document`.

    Raises:
        AriadneClientError: on non-dict response or server 4xx/5xx.
    """
    params: dict[str, Any] = {
        "collection": collection,
        "file_type": file_type,
        "tag": tag,
        "has_warnings": has_warnings,
        "has_source_reference": has_source_reference,
        "limit": limit,
        "offset": offset,
        "include_deleted": include_deleted,
    }
    # `include` is repeated — build query manually because
    # `_endpoint` uses `urlencode` which doesn't repeat list
    # values the way FastAPI expects without `doseq=True`.
    # We can't change `_endpoint`'s signature without breaking
    # other callers, so build here and hand the full URL over.
    base = self._endpoint("/api/documents", **params)
    if include:
        from urllib.parse import urlencode as _ue
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}{_ue([('include', v) for v in include])}"

    response = _http.json_request(
        "GET",
        base,
        headers=self._headers(),
        timeout=self.timeout,
    )
    data = response if isinstance(response, dict) else {}
    return DocumentListPage(
        documents=[
            self._parse_document(item)
            for item in data.get("documents") or []
            if isinstance(item, dict)
        ],
        total_count=int(data.get("total_count") or 0),
        total_is_exact=bool(data.get("total_is_exact", True)),
        limit=int(data.get("limit") or limit),
        offset=int(data.get("offset") or offset),
    )
```

**Note on booleans and `_endpoint`:** `_endpoint` already has special
cases for `include_deleted`, `include_chunks`, `include_interactions`
to stringify bools. `has_warnings` and `has_source_reference` are
**new booleans** that need the same treatment — FastAPI's `bool`
Query coerces "true"/"false", "True"/"False", "1"/"0"; Python's
default `str(True)` is `"True"` which FastAPI does accept, but be
safe and add them to the `_endpoint` stringify list so behavior is
uniform:

```python
if isinstance(params.get("has_warnings"), bool):
    params["has_warnings"] = "true" if params["has_warnings"] else "false"
if isinstance(params.get("has_source_reference"), bool):
    params["has_source_reference"] = (
        "true" if params["has_source_reference"] else "false"
    )
```

Add those two blocks to `_endpoint` alongside the existing
`include_deleted` / `include_chunks` / `include_interactions`
stringifiers (client.py line 61-66). Keep them adjacent so the
pattern is visible.

Also import `DocumentListPage` at the top:

```python
from ariadne_core_client.models import (
    AggregateBucket,
    AggregateResponse,
    Collection,
    Document,
    DocumentListPage,
    Health,
    Interaction,
    QuerySchema,
    SearchResponse,
    SearchResult,
    Stats,
)
```

(Alphabetical, keeping the existing convention.)

---

## Step 4 — New `aggregate()` method

File: `client/src/ariadne_core_client/client.py`.

Place it **after** `list_documents()` and **before** `list_collections()`
so related methods stay adjacent.

```python
def aggregate(
    self,
    group_by: str,
    *,
    collection: str | None = None,
    file_type: str | None = None,
    tag: str | None = None,
    has_warnings: bool | None = None,
    has_source_reference: bool | None = None,
    include_deleted: bool = False,
) -> AggregateResponse:
    """Group-by count over /api/documents filters.

    Args:
        group_by: one of "collection", "file_type", "tags".
            Call `self.schema()` for the current list.
        collection, file_type, tag, has_warnings,
        has_source_reference, include_deleted: same semantics as
            `list_documents`. Applied as a WHERE clause before
            grouping.

    Returns:
        An `AggregateResponse`. Iterates as a list of
        `AggregateBucket`.

    Raises:
        AriadneClientError: on non-dict response or server 4xx
            (e.g. unknown `group_by` returns a structured 400 with
            the valid list; that surfaces as an AriadneClientError
            with the error detail).
    """
    params: dict[str, Any] = {
        "group_by": group_by,
        "collection": collection,
        "file_type": file_type,
        "tag": tag,
        "has_warnings": has_warnings,
        "has_source_reference": has_source_reference,
        "include_deleted": include_deleted,
    }
    response = _http.json_request(
        "GET",
        self._endpoint("/api/documents/aggregate", **params),
        headers=self._headers(),
        timeout=self.timeout,
    )
    if not isinstance(response, dict):
        raise AriadneClientError(
            "aggregate response was not a JSON object",
            request_info=f"GET {self.url}/api/documents/aggregate",
        )
    return AggregateResponse(
        group_by=response.get("group_by", "") or "",
        filters=dict(response.get("filters") or {}),
        buckets=[
            AggregateBucket(
                group=b.get("group"),
                count=int(b.get("count") or 0),
            )
            for b in response.get("buckets") or []
            if isinstance(b, dict)
        ],
        total_buckets=int(response.get("total_buckets") or 0),
        total_documents=int(response.get("total_documents") or 0),
    )
```

---

## Step 5 — New `schema()` method

File: `client/src/ariadne_core_client/client.py`.

Place after `aggregate()`, before `list_collections()`.

```python
def schema(self) -> QuerySchema:
    """Fetch the query-surface discovery document.

    Call this first from an agent to learn what filters, includes,
    and aggregatable fields are available on this server.

    Returns:
        A `QuerySchema` with per-server filter / include /
        aggregatable-field registries and caps.
    """
    response = _http.json_request(
        "GET",
        self._endpoint("/api/documents/schema"),
        headers=self._headers(),
        timeout=self.timeout,
    )
    if not isinstance(response, dict):
        raise AriadneClientError(
            "schema response was not a JSON object",
            request_info=f"GET {self.url}/api/documents/schema",
        )
    return QuerySchema(
        list_endpoint=response.get("list_endpoint", "") or "",
        aggregate_endpoint=(
            response.get("aggregate_endpoint", "") or ""
        ),
        filters=dict(response.get("filters") or {}),
        includes=dict(response.get("includes") or {}),
        aggregatable_fields=dict(
            response.get("aggregatable_fields") or {}
        ),
        caps=dict(response.get("caps") or {}),
        brute_force_fallback=(
            response.get("brute_force_fallback", "") or ""
        ),
        deferred=dict(response.get("deferred") or {}),
    )
```

---

## Step 6 — Tests

File: `client/tests/test_query_api_pass3.py` (new file).

Use whatever test harness the other client tests use — look at
`client/tests/test_client.py` or similar for the pattern (there's
usually a fake-transport or a `responses`/`httpx`-mock setup). Do
not invent a new harness.

Required tests:

1. **`test_list_documents_new_filters`** — call
   `list_documents(tag="x", has_warnings=True,
   has_source_reference=False, include=["tags", "agent_metadata"])`
   and assert the recorded URL contains all five params, including
   two `include=` occurrences. Confirm booleans serialize as
   `true`/`false` (not `True`/`False`).

2. **`test_list_documents_returns_page`** — given a fake server
   response with `documents`, `total_count: 42`,
   `total_is_exact: false`, `limit: 20`, `offset: 0`: returned
   object is a `DocumentListPage`, `len(page) == len(documents)`,
   `page.total_count == 42`, `page.total_is_exact is False`, and
   `for d in page: assert isinstance(d, Document)` works.

3. **`test_document_warnings_count_parsed`** — server returns
   `{"warnings": ["w1"], "warnings_count": 1, ...}`: parsed
   `Document.warnings == ["w1"]`, `Document.warnings_count == 1`.
   Also test the absent-field case: server returns no
   `warnings_count` key → `Document.warnings_count is None`.

4. **`test_aggregate_basic`** — fake server response:
   ```json
   {"group_by": "collection",
    "filters": {"has_warnings": true},
    "buckets": [{"group": "a", "count": 3}, {"group": "b", "count": 1}],
    "total_buckets": 2,
    "total_documents": 4}
   ```
   Call `client.aggregate("collection", has_warnings=True)`. Assert
   the URL has `group_by=collection` and `has_warnings=true`, return
   is an `AggregateResponse`, `len(resp) == 2`, first bucket is
   `AggregateBucket(group="a", count=3)`.

5. **`test_schema_basic`** — fake server response matching the
   `/api/documents/schema` shape (all eight top-level keys). Call
   `client.schema()`, assert return is a `QuerySchema`, all four
   registry fields are dicts, `caps["list_default"] == 500`.

Run tests:

```
cd ariadne-core
pytest client/tests/test_query_api_pass3.py -v
pytest client/tests/ -v    # full client suite, must still pass
```

If any existing test broke from the `list_documents` breaking change
(likely a test that does `isinstance(result, list)` or relies on
concatenation), fix the test — the new return type is the new
contract.

---

## Step 7 — Skill doc updates

File: `skills/ariadne-document-intelligence/SKILL.md`.

### 7a. New `## Query API` section

Insert a new top-level section **after `## Process: Browsing and
managing documents`** (ends around line 489) and **before `## When
to search before answering`** (line 491).

Content:

```markdown
## Query API

For any question that involves counting, filtering, or grouping
documents in the corpus, use the Query API — not search. Search is
for content retrieval; the Query API is for corpus introspection.

### Start with `schema()`

When you're unsure what's available, call `client.schema()` first.
It returns the live registry of filters, includes, aggregatable
fields, and caps for this server — so you never have to guess.

```python
sch = client.schema()
print(sch.filters)              # {filter_name: description}
print(sch.aggregatable_fields)  # valid group_by values
print(sch.caps)                 # limits per request
```

### Filtering with `list_documents()`

`list_documents()` returns a `DocumentListPage` — iterable like a
list, plus pagination metadata on `total_count`, `total_is_exact`,
`limit`, `offset`.

Supported filters (combinable; all AND together):

| Param | Type | Behavior |
|---|---|---|
| `collection` | str | Exact collection match. |
| `file_type` | str | Exact file type (`.pdf` and `pdf` both accepted). |
| `tag` | str | Docs whose tag list contains this tag. |
| `has_warnings` | bool | `True` = only docs with >=1 warning; `False` = only clean docs. |
| `has_source_reference` | bool | `True` = latest interaction's `agent_metadata.source_reference` is a non-empty string that isn't literally `"unknown"`. |
| `include_deleted` | bool | Default False. |

Every row now carries `warnings_count` (int). Use it to spot
documents that need cleanup without paying to materialize the
`warnings` array on every row.

### Adding extra row fields with `include=`

By default `list_documents()` returns a lean row. Request extra
fields with `include=[...]`:

| `include` value | Adds |
|---|---|
| `"tags"` | Full tag list. |
| `"agent_metadata"` | Latest interaction's agent_metadata dict. |
| `"last_interaction"` | `{agent_notes, action, created_at}` of the latest interaction. |
| `"markdown"` | Full markdown body. Caps `limit` at 50. |

Example — find all papers that lack a DOI in their provenance:

```python
page = client.list_documents(
    tag="docty:paper",
    has_source_reference=False,
    include=["last_interaction", "agent_metadata"],
    limit=50,
)
for doc in page:
    print(doc.source_file, doc.warnings_count)
print(f"Total: {page.total_count} (exact={page.total_is_exact})")
```

### Counting with `aggregate()`

`aggregate()` groups by one field and counts, reusing all the same
filters as a WHERE clause. Much cheaper than paging the full list
client-side.

```python
# How many docs per collection?
resp = client.aggregate(group_by="collection")
for b in resp:
    print(b.group, b.count)

# How many warnings-laden PDFs per collection?
resp = client.aggregate(
    group_by="collection",
    file_type="pdf",
    has_warnings=True,
)
```

Valid `group_by` values: `collection`, `file_type`, `tags`. (Call
`schema()` to confirm — the server is the source of truth.) Grouping
by `tags` counts each distinct tag separately: a document with two
tags contributes +1 to each bucket.

### When filters don't fit

If your question can't be expressed with the filters above (e.g. a
date range, or a nested `agent_metadata` path), the Query API
deliberately doesn't hide the fallback: paginate `list_documents()`
with the `include=[...]` you need, filter client-side. `schema()`
returns a `brute_force_fallback` hint describing this. Date range
and JSON-path filters are listed under `schema().deferred` — not
planned for this release.
```

### 7b. Fix the existing "Search filters reference"

The existing table at line 506 describes `/api/search` filters but
the heading doesn't say so. Readers will think those are
`/api/documents` filters. Fix by retitling and scoping:

Replace `## Search filters reference` (line 506) with:

```markdown
## Search filters reference (chunks via `/api/search`)

These filters apply to `client.search(...)` — chunk-level retrieval.
For document-level filtering see the Query API section above.
```

Keep the existing table and "Unknown filter keys are silently
ignored" line as-is.

### 7c. Update the "Browsing and managing documents" example

In the numbered list at line 453, step 2 says
`client.list_documents(collection=...)`. Expand step 2 to mention
the new filters so agents see them where they need them:

```markdown
2. Call `client.list_documents(collection=...)` filtered by
   collection if the user asks. For richer queries (by tag,
   warnings status, or provenance) see the Query API section.
```

Don't restate the whole Query API cheat sheet here — one pointer is
enough.

---

## Step 8 — Sync check

The client package and the skill doc must agree with `SPEC.md` and
with the live server. Quick sanity pass:

- Every filter the new skill section documents must be a key in
  `client.schema().filters` on the deployed server.
- Every include value must be a key in `client.schema().includes`.
- Every `group_by` value must be in `schema().aggregatable_fields`.

Do a live check against Railway:

```python
from ariadne_core_client import AriadneClient
c = AriadneClient()
sch = c.schema()
assert set(sch.filters.keys()) >= {
    "collection", "file_type", "tag",
    "has_warnings", "has_source_reference",
    "include_deleted",
}
assert set(sch.includes.keys()) >= {
    "agent_metadata", "tags", "last_interaction", "markdown",
}
assert set(sch.aggregatable_fields.keys()) >= {
    "collection", "file_type", "tags",
}
print("OK")
```

If any of those assertions fail, **stop and report** — the server
is out of sync with what Pass 2 should have shipped.

---

## Step 9 — DAVE_DONE.md

Create `dave_and_bob_communication/DAVE_DONE.md` overwriting any
prior content. Structure:

1. **SHAs pushed.** New commit SHA(s). One line per commit.
2. **Files touched.** Bullet list.
3. **Live schema dump.** Paste the output of the Step 8 live check
   (first-call proof Pass 3 talks to Pass 2 correctly).
4. **Test output.** `pytest client/tests/ -v` tail — at minimum the
   final summary line.
5. **Known-deferred.** Anything you noticed but intentionally
   didn't do (CLI aggregate/schema flags, SQL push-down of the new
   filters, date-range filters, cannabis skill in the other repo).
6. **Bob handoff.** One sentence per check you want Bob to run
   (smoke: `schema()`, `aggregate(group_by="collection")`, a
   `list_documents(has_warnings=True)` call, and `warnings_count`
   round-trip via `get_document`).

---

## Step 10 — Commit + push

Single commit. Suggested message:

```
Query API Pass 3: client + skill catch-up

Teach the Python client and doc-intelligence skill to use the
Pass 2 server surface:
- list_documents() accepts tag, has_warnings,
  has_source_reference, include=. Returns DocumentListPage with
  pagination metadata (breaking: previously list[Document]).
- New aggregate() method for group-by counts.
- New schema() method for live discovery.
- Document.warnings_count added; parsed from both list rows and
  get-by-id.
- Skill doc gains a Query API section; search-filter table
  re-scoped to /api/search to prevent confusion.

No server, SPEC.md, or CLI changes.
```

Push:

```
git push origin main
```

STOP after push. Do not redeploy Railway — nothing in this pass
requires a server redeploy. Bob will smoke against the already-
deployed Pass 2 server.

---

## Summary of scope fence

- ✅ `client/src/ariadne_core_client/models.py`
- ✅ `client/src/ariadne_core_client/client.py`
- ✅ `client/tests/test_query_api_pass3.py` (new)
- ✅ `skills/ariadne-document-intelligence/SKILL.md`
- ✅ `dave_and_bob_communication/DAVE_DONE.md`
- ❌ anything under `src/pipeline/`
- ❌ `SPEC.md`
- ❌ `src/pipeline/cli.py`
- ❌ migrations, schema, database code
- ❌ cannabis skill in the external repo

If the scope fence above doesn't cover a file you want to change,
**flag it in `DAVE_DONE.md` and leave it.** Scope discipline
matters.
