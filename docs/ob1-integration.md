# Open Brain (OB1) Integration Guide

Ariadne Core works alongside Open Brain as a document extraction and retrieval layer. OB1 agents use Ariadne Core's MCP tools to ingest documents, then query the resulting vector store for context during capture sessions.

**Ariadne Core has no OB1 dependency.** This guide covers how to connect the two systems, not how to modify either one.

## Architecture

```
OB1 Agent  ──MCP──>  Ariadne Core  ──>  pgvector
   │                                          │
   └──────── reads search results ────────────┘
```

OB1 agents call Ariadne Core's `convert_document` and `search` MCP tools. Documents are extracted, chunked, embedded, and stored in pgvector. OB1 queries the same vector store for context during daily capture and research workflows.

## Setup

Ariadne Core runs as a hosted service. OB1 agents connect to it over the network via MCP — they don't need direct database access. REST API is also available for scripts and automation. See [installation.md](installation.md) to get the stack running.

## Connecting OB1 Agents to Ariadne Core

### MCP Configuration (Recommended)

Add Ariadne Core as an MCP server in your OB1 agent configuration. For local use:

```json
{
  "mcpServers": {
    "ariadne-core": {
      "command": "docker",
      "args": ["exec", "-i", "ariadne-core-api-1", "python", "-m", "pipeline", "mcp"]
    }
  }
}
```

For remote deployments, use Streamable HTTP transport:

```json
{
  "mcpServers": {
    "ariadne-core": {
      "url": "https://your-server.example.com/mcp",
      "headers": {
        "X-API-Key": "your-api-key"
      }
    }
  }
}
```

### REST API

OB1 agents can also use the REST API directly:

```bash
# Ingest a document
curl -X POST http://localhost:8000/api/documents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ARIADNE_API_KEY" \
  -d '{
    "uri": "/path/to/document.pdf",
    "collection": "ob1-daily",
    "agent_id": "ob1-agent-daily",
    "agent_type": "ob1"
  }'

# Search for context
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ARIADNE_API_KEY" \
  -d '{
    "query": "quarterly revenue trends",
    "collection": "ob1-daily",
    "top_k": 5
  }'
```

## Collection Strategy

Use collections to separate different OB1 workflows:

| Collection | Purpose | Agent |
|-----------|---------|-------|
| `ob1-daily` | Daily capture documents | `ob1-agent-daily` |
| `ob1-research` | Research deep-dives | `ob1-agent-research` |
| `ob1-archive` | Long-term reference | `ob1-agent-archive` |

Dedup is scoped per collection — the same document can exist in `ob1-daily` and `ob1-research` without conflict. Search can span all collections or be scoped to one.

## Provenance Tracking

Every document interaction is recorded with agent metadata. When OB1 agents ingest documents, the `document_interactions` table tracks:

- **agent_id**: `"ob1-agent-daily"`, `"ob1-agent-research"`, etc.
- **agent_type**: `"ob1"`
- **model**: The LLM model the OB1 agent is running
- **initiated_by**: The human or system that triggered the capture

Search results include all interactions, so OB1 can see which agents have previously processed a document and how.

## Token Efficiency

Ariadne Core's extraction pipeline produces clean Markdown optimized for LLM consumption. A 100-page PDF that would cost 50,000-100,000 raw tokens is reduced to 5,000-8,000 tokens — an 8-15x savings. OB1 agents benefit directly: less context window consumed per document means more documents per session.

Key practices to adopt in OB1 workflows:

1. **Ingest via Ariadne Core first.** Don't pass raw files to LLMs. Extract to Markdown, then use the Markdown.
2. **Use search for context.** Instead of loading entire documents, search for relevant chunks and pass those to the LLM.
3. **Let dedup work.** When an OB1 agent encounters a document that's already been processed, the dedup gate skips expensive re-extraction but still records the interaction for provenance.

## Example: Daily Capture Workflow

```python
# OB1 agent pseudo-code for daily document capture

# 1. Discover new documents
new_files = scan_incoming_directory("/data/incoming")

# 2. Ingest each through Ariadne Core
for file_path in new_files:
    result = mcp.call("ariadne-core", "convert_document", {
        "uri": file_path,
        "collection": "ob1-daily",
        "agent_id": "ob1-agent-daily",
        "agent_type": "ob1",
        "model": "claude-sonnet-4-6",
        "initiated_by": "system:cron",
    })

    if result.get("was_dedup_skip"):
        log.info(f"Already processed: {file_path}")
    else:
        log.info(f"Ingested: {result['document_id']}, {result['chunks_count']} chunks")

# 3. Search for today's context
context = mcp.call("ariadne-core", "search", {
    "query": "action items from today's documents",
    "collection": "ob1-daily",
    "top_k": 10,
})
```
