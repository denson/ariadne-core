# Fix 003 Results: `get_document` Not Returning Chunks

## Root Cause

The MCP `get_document` tool (via STDIO proxy) calls the REST `GET /api/documents/{document_id}` endpoint. The REST route in `routes.py` (line 249-288) never fetched or included chunks in its response — it returned interactions but completely omitted chunk retrieval.

The MCP server's own `get_document` handler in `mcp_server.py` (lines 315-328) had the correct chunk logic, but it was never reached because the STDIO proxy delegates to the REST API.

## What Changed

**`src/pipeline/api/routes.py`** — `get_document` REST endpoint (line 259):
- Added `doc_chunks = _mcp._get_chunks_for_document(doc.document_id)` to fetch chunks
- Added `chunks` array to the response with `chunk_id`, `text`, `section`, `page`, `token_count`, `embedding_model` per chunk
- Added `chunk_count` field with the length of the chunks array

One file changed, one location.

## Verification Results

All 6 steps passed.

### Step 1: convert_document
```
document_id: 677808d6-3362-4474-97de-8d4bfb9843a3
chunks_count: 2
collection: chunks-test-v2
store_status: stored
```

### Step 2: chunks_count from convert response
```
chunks_count: 2
```

### Step 3: get_document with include_chunks: true
Response now includes a `chunks` array.

### Step 4: chunks array present
```json
"chunks": [
  {
    "chunk_id": "463da65c-1dcd-5dd4-8f23-0bb7d960a632",
    "text": "Ariadne Core Test Document...",
    "section": null,
    "page": null,
    "token_count": 64,
    "embedding_model": "text-embedding-3-small"
  },
  {
    "chunk_id": "b957c5a3-4321-5a37-aaaa-1b492640249b",
    "text": "## Section Two...",
    "section": "Section Two",
    "page": null,
    "token_count": 38,
    "embedding_model": "text-embedding-3-small"
  }
]
```

### Step 5: chunks array length matches chunks_count
`chunk_count: 2` matches `chunks_count: 2` from convert response.

### Step 6: chunk fields
Each chunk has: `chunk_id`, `text`, `section`, `page`, `token_count`, `embedding_model`.
