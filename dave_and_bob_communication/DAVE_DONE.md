# DAVE_DONE — Query API Pass 3

## SHAs pushed

- *(single commit; SHA recorded after `git push`)*

## Files touched

- `client/src/ariadne_core_client/models.py` — added `Document.warnings_count`; new `DocumentListPage`, `AggregateBucket`, `AggregateResponse`, `QuerySchema` dataclasses.
- `client/src/ariadne_core_client/client.py` — imports updated; `_endpoint` stringifies `has_warnings` + `has_source_reference`; `_parse_document` reads `warnings_count`; `list_documents` rewritten (new filters + `include=`, returns `DocumentListPage`); new `aggregate()` and `schema()` methods.
- `client/tests/test_query_api_pass3.py` — new file, 5 tests.
- `skills/ariadne-document-intelligence/SKILL.md` — new `## Query API` section; "Search filters reference" retitled to `(chunks via /api/search)` with a one-liner pointer to the Query API; "Browsing and managing documents" step 2 gets a Query API pointer.
- `dave_and_bob_communication/DAVE_DONE.md` — this file (overwrites the prior Phase 8 hand-off per spec).

## Live schema dump (Step 8 proof — client talks to Pass 2)

```
OK
filters: ['collection', 'file_type', 'has_source_reference', 'has_warnings', 'include_deleted', 'tag']
includes: ['agent_metadata', 'last_interaction', 'markdown', 'tags']
aggregatable_fields: ['collection', 'file_type', 'tags']
caps: {'list_default': 500, 'list_with_markdown': 50, 'aggregate_buckets_max': 1000}
list_endpoint: /api/documents
aggregate_endpoint: /api/documents/aggregate
deferred: ['agent_metadata_group_by', 'date_range_filters', 'store_status_filter']
```

All three expected supersets (`filters`, `includes`, `aggregatable_fields`) match. Live server URL used: `https://ariadne-core-production-579a.up.railway.app` (from `.env`; note the spec's example URL `ariadne-core-production.up.railway.app` without the `-579a` suffix 404s — only the `-579a` URL is the real deployment).

## Test output

```
client\tests\test_client_timeout.py .......                              [ 58%]
client\tests\test_query_api_pass3.py .....                               [100%]

============================= 12 passed in 0.05s ==============================
```

## Known-deferred (noticed, intentionally out of scope per spec fence)

- **CLI surface**: `src/pipeline/cli.py` has no `aggregate` / `schema` subcommands and no `--tag` / `--has-warnings` / `--has-source-reference` / `--include` flags on `list`. Per spec, flag and leave.
- **SQL push-down of the new filters** — server code frozen this pass.
- **Date-range and JSON-path filters** — listed in `schema().deferred`; future pass.
- **Cannabis skill** in the external `D:\video_projects\...` repo — different repo, not part of ariadne-core.
- **Breaking change**: `list_documents` now returns `DocumentListPage` (iterable as a list of `Document`) instead of `list[Document]`. No deprecation shim (pre-1.0, no external users), per spec.
- Stale URL in the spec Step 0 command (`ariadne-core-production.up.railway.app` → should be `ariadne-core-production-579a.up.railway.app`). Left the spec alone; noting here for the next author.

## Bob handoff — smoke checks against the live Pass 2 server

- `client.schema()` → `QuerySchema` with the six expected filters (including `has_warnings`, `has_source_reference`, `tag`), four includes, three aggregatable fields, and `caps["list_default"] == 500`.
- `client.aggregate(group_by="collection")` → `AggregateResponse` iterable over `AggregateBucket`s whose `.count`s sum to `total_documents`.
- `client.list_documents(has_warnings=True)` → `DocumentListPage`; every row's `warnings_count` should be `>= 1`, and `total_count` should be non-negative.
- `client.get_document(<any_id>)` → `Document.warnings_count` round-trips (not `None` on a Pass 2 server).
