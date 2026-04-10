# Fix 004 Results: `list_documents` Missing `chunk_count` and `interaction_count`

## Root Cause

The REST `GET /api/documents` endpoint in `routes.py` (line 327-343) serialized each document entry without `chunk_count` or `interaction_count` fields. The MCP handler in `mcp_server.py` (line 394-409) already had these fields via `_count_chunks_for_document()` and `_dedup_store.get_interactions()`, but the REST route — which the STDIO proxy delegates to — omitted them.

Same pattern as Fix 003: the MCP handler had the correct logic, but the REST endpoint did not.

## What Changed

**`src/pipeline/api/routes.py`** — `list_documents` REST endpoint (line 327):
- Added `"chunk_count": _mcp._count_chunks_for_document(d.document_id)` to each document entry
- Added `"interaction_count": len(_mcp._dedup_store.get_interactions(d.document_id))` to each document entry

One file changed, one location.

## Verification Results

All 6 steps passed.

### Step 1: convert_document sample.txt
```
document_id: df97b2e3-2e53-44ab-bf6e-3bd30661b1ee
chunks_count: 2
collection: counts-test
store_status: stored
```

### Step 2: convert_document sample.html
```
document_id: c163008f-4739-46e0-b3c2-00b8557835c6
chunks_count: 1
collection: counts-test
store_status: stored
```

### Step 3: convert_document sample.txt again (dedup)
```
document_id: df97b2e3-2e53-44ab-bf6e-3bd30661b1ee
was_dedup_skip: true
interactions: 2 (original ingest + dedup skip)
```

### Step 4: list_documents with collection "counts-test"
```json
{
  "total_count": 2,
  "documents": [
    {
      "document_id": "c163008f-4739-46e0-b3c2-00b8557835c6",
      "source_file": "sample.html",
      "chunk_count": 1,
      "interaction_count": 1
    },
    {
      "document_id": "df97b2e3-2e53-44ab-bf6e-3bd30661b1ee",
      "source_file": "sample.txt",
      "chunk_count": 2,
      "interaction_count": 2
    }
  ]
}
```

### Step 5: chunk_count and interaction_count present and > 0
- sample.html: `chunk_count: 1`, `interaction_count: 1`
- sample.txt: `chunk_count: 2`, `interaction_count: 2`

### Step 6: sample.txt interaction_count >= 2
`interaction_count: 2` (original ingest + dedup skip)
