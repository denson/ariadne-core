# Ariadne Core Single Document Ingest - Evaluation 1

## Task
Process `/data/incoming/acme-msa-2026.pdf` for a vendor agreement review.

## MCP Tool Calls (in order)

### Call 1: Convert Document
**Purpose:** Extract the PDF to clean Markdown format.

```json
{
  "tool": "convert_document",
  "parameters": {
    "uri": "file:///data/incoming/acme-msa-2026.pdf",
    "store": false,
    "agent_id": "denson-vendor-review",
    "agent_type": "claude-code",
    "model": "claude-haiku-4-5-20251001",
    "initiated_by": "user:denson",
    "agent_notes": "Vendor agreement review - processing Acme Corp MSA for comparison with existing contracts"
  }
}
```

**Expected Response:** Document metadata and extracted Markdown content. Includes:
- `document_id`: UUID of the converted document
- `content`: Cleaned Markdown representation of the PDF
- `metadata`: Document title, page count, extraction duration, fingerprint (SHA-256 of normalized content)
- `processing_chain`: Record of extraction tool (MarkItDown) and parameters

---

### Call 2: Ingest Document
**Purpose:** Process the converted Markdown through the full pipeline: dedup check → chunking → embedding → vector storage.

```json
{
  "tool": "ingest",
  "parameters": {
    "uri": "file:///data/incoming/acme-msa-2026.pdf",
    "collection": "vendor-agreements",
    "force": false,
    "chunking_config": {
      "strategy": "by_title",
      "max_characters": 1000,
      "overlap_percent": 10
    },
    "agent_id": "denson-vendor-review",
    "agent_type": "claude-code",
    "model": "claude-haiku-4-5-20251001",
    "initiated_by": "user:denson",
    "agent_notes": "Vendor agreement review - processing Acme Corp MSA for comparison with existing contracts"
  }
}
```

**Expected Response:**
- `document_id`: UUID (same as from convert_document)
- `chunks_created`: Number of semantic chunks extracted (determined by by_title strategy)
- `vectors_created`: Count of embeddings stored in pgvector
- `processing_chain`: Appended records for chunking strategy, embedding model, timestamps
- `document_interactions`: Row created recording this ingest action, agent metadata, timestamp

**Key behaviors:**
- Fingerprint is checked against existing documents in `vendor-agreements` collection
- If found (dedup hit): Processing skips to step 7 (interaction recording only), returns existing document_id
- If not found: Full pipeline executes: chunk by semantic sections (by_title strategy) → embed each chunk using configured embedding API → store in pgvector with embedding_model column populated
- All metadata (agent_id, initiated_by, agent_notes) is recorded in document_interactions table

---

## User-Facing Message

---

Great! I've initiated processing of the Acme Corp MSA. Here's what I'm doing:

1. **Extract**: Converting the PDF to clean Markdown using MarkItDown, preserving document structure.

2. **Dedup Check**: Looking for this exact document in your vendor-agreements collection. If it's already there, we skip expensive processing and just record that you've touched it.

3. **Process**: Breaking the contract into semantic chunks (sections, clauses) and embedding them using your configured embedding API.

4. **Store & Index**: Saving the chunks to pgvector so you can search them later by meaning—not just keywords.

The document will be stored in your **vendor-agreements** collection under document ID `[document_id]`. Once processing completes, you'll be able to search across all your vendor agreements using queries like:

- "What are the payment terms?"
- "What's the termination clause?"
- "Compare this to our other MSAs"

The system also logs that you (Denson) touched this document on [timestamp], so if another team member searches and finds it, they'll know you've already reviewed it.

Ready whenever you want to search!

---

## Key Design Decisions Reflected

1. **Agent Tenancy**: Caller metadata (agent_id, agent_type, model, initiated_by, agent_notes) is captured for every interaction, not just the document.

2. **Collection Scoping**: Documents are organized by collection (`vendor-agreements`), allowing the same document to exist in multiple logical namespaces and dedup to be scoped per collection.

3. **Dedup with Interaction Recording**: Even if this exact PDF was processed before, an interaction row is created, so the audit trail shows Denson reviewed it on this date.

4. **Chunking Strategy Auto-Selection**: The `by_title` strategy is optimal for legal documents with clear section headers (typical of MSAs). Caller can override via `chunking_config`.

5. **Two-Step Process**: `convert_document` (extraction only) is separate from `ingest` (full pipeline). This allows the user to inspect extracted Markdown before committing to embedding/storage if desired.

6. **No Force Flag Here**: Since this is the first ingest, `force: false` is appropriate. If Denson later wants to re-embed after changing embedding models, they'd call `ingest` again with `force: true`.
