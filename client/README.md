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

## Authentication

The client speaks **OAuth 2.1 Bearer JWT** only. The legacy `X-API-Key` path was removed in Pass 2 of the `ariadne--xft` epic; the matching client-side constructor args (`url=`, `api_key=`) were removed in Pass 3 (xft.5.5).

**First-time setup** — sign in to your Ariadne server with PKCE via the CLI:

```bash
ariadne login --host https://your-deployment.example
```

This opens a browser to Auth0, captures the callback on a local loopback port, and stores the refresh + access + id tokens in your OS keyring (macOS Keychain / Windows Credential Manager / Linux Secret Service). The host you logged into is also persisted to `~/.config/ariadne/default`, so subsequent calls can omit `--host`.

**`AriadneClient()` resolves the server host in this order:**

1. Explicit `AriadneClient(host="https://...")` argument
2. `ARIADNE_HOST` environment variable
3. `~/.config/ariadne/default` (written by `ariadne login`)

**`AriadneClient()` resolves the access token in this order (per call):**

1. `ARIADNE_ACCESS_TOKEN` env var — always wins, bypasses the keyring entirely (useful for CI and for recovering from a broken keyring)
2. The cached access token from the keyring, if it still has > 60 s remaining
3. A fresh access token minted from the cached refresh token via Auth0's `/oauth/token`

If none of these succeed, the client raises `AriadneAuthError` **without issuing any HTTP request**. There is no unauthenticated fallback, no silent downgrade.

## Quick start

```python
from ariadne_core_client import AriadneClient

# After `ariadne login --host https://your-deployment.example`:
client = AriadneClient()

print(client.health())

doc = client.ingest_file("report.pdf", collection="research", tags=["q1", "draft"])
print(doc.document_id, doc.chunks_count)

results = client.search("quarterly revenue", collection="research", top_k=5)
for hit in results.results:
    print(f"{hit.relevance_score:.3f}  {hit.text[:120]}")
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
# One-time per host: sign in and store tokens in the OS keyring.
ariadne login --host https://your-deployment.example

# Inspect the currently stored token.
ariadne whoami
ariadne whoami --json

# Forget the currently stored tokens (refresh + access + expiry + id_token).
ariadne logout

# Data-plane subcommands (inherit the host from ~/.config/ariadne/default
# written by `ariadne login`; override per-call with --host).
ariadne health
ariadne stats
ariadne list-collections
ariadne list-documents --collection research --limit 50
ariadne search "quarterly revenue" --collection research --top-k 5
ariadne ingest https://example.com/report.pdf --collection research --tags q1,draft
ariadne ingest ./report.pdf --collection research
ariadne ingest ./docs --recursive --collection research
```

Every non-auth subcommand accepts `--host <url>` to override the stored default, and `--json` to emit raw JSON on stdout (useful for piping to `jq`). Batch directory ingests print per-file progress to stderr so stdout stays parseable.

Exit codes: `0` on success, `1` on client/transport errors, `2` on `whoami` when the stored token is already expired (scripting signal, not an error), `130` on Ctrl-C.

## License

Apache-2.0
