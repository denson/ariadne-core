# ariadne-core-client

Python client for the [Ariadne Core](../README.md) document extraction and retrieval API.

Stdlib-only: no `requests`, no `httpx`, no `click`. Ships an `AriadneClient` class and an `ariadne` CLI.

**Author:** Denson Smith

## Installation

From a clone of this repo:

```bash
pip install -e client/
```

Or from a published wheel:

```bash
pip install ariadne-core-client
```

Requires Python 3.10+.

## Credentials

`AriadneClient()` resolves `url` and `api_key` in this order and stops at the first hit:

1. Explicit `AriadneClient(url=..., api_key=...)` arguments
2. `ARIADNE_URL` / `ARIADNE_API_KEY` environment variables
3. A `.env` file, walking up from the current directory
4. A `.mcp.json` file, walking up from the current directory (for an `ariadne` MCP server entry)

## Quick start

```python
from ariadne_core_client import AriadneClient

client = AriadneClient()  # picks up credentials from env / .env / .mcp.json

print(client.health())

doc = client.ingest_file("report.pdf", collection="research", tags=["q1", "draft"])
print(doc.document_id, doc.chunks_count)

results = client.search("quarterly revenue", collection="research", top_k=5)
for hit in results.results:
    print(f"{hit.relevance_score:.3f}  {hit.chunk_text[:120]}")
```

## Python API

| Method | Purpose |
| ------ | ------- |
| `health()` | Server health check |
| `ingest_url(url, *, collection, tags, source, ...)` | Ingest a document from a URL |
| `ingest_file(path, *, collection, tags, source, ...)` | Ingest a local file |
| `ingest_bytes(content, filename, *, collection, tags, ...)` | Ingest raw bytes |
| `search(query, *, collection, top_k, filters, ...)` | Semantic search |
| `get_document(document_id, *, include_chunks, include_interactions)` | Fetch a single document |
| `list_documents(*, collection, file_type, limit, offset, include_deleted)` | List documents |
| `list_collections()` | List collections |
| `create_collection(name, *, description)` | Create a collection |
| `update_document(document_id, *, tags, collection, agent_metadata, ...)` | Patch a document |
| `delete_document(document_id, *, agent_notes)` | Soft-delete a document |
| `restore_document(document_id, *, agent_notes)` | Restore a deleted document |
| `delete_collection(name, *, agent_notes)` | Soft-delete a collection |
| `restore_collection(name, *, agent_notes)` | Restore a deleted collection |
| `stats()` | Server-wide stats |

Errors raise `AriadneClientError` (or its subclasses `AriadneAuthError`, `AriadneNotFoundError`, `AriadneServerError`).

## CLI

```bash
ariadne health
ariadne stats
ariadne list-collections
ariadne list-documents --collection research --limit 50
ariadne search "quarterly revenue" --collection research --top-k 5
ariadne ingest https://example.com/report.pdf --collection research --tags q1,draft
ariadne ingest ./report.pdf --collection research
ariadne ingest ./docs --recursive --collection research
```

Every subcommand accepts `--json` to emit raw JSON on stdout (useful for piping to `jq`). Batch directory ingests print per-file progress to stderr so stdout stays parseable.

Exit codes: `0` on success, `1` on client/transport errors, `2` on usage errors, `130` on Ctrl-C.

## License

Apache-2.0
