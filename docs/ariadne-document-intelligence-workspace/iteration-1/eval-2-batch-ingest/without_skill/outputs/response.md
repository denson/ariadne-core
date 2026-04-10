# Batch Document Ingestion: Tool Calls and Response

## User Request
"I uploaded a bunch of research papers to /data/incoming/q4-research/ — there's like 12 PDFs and a few DOCX files in there. Can you get them all into the system? I'll want to search across them later for stuff about pricing models."

---

## MCP Tool Calls (Exact Parameter Specification)

### Single Tool Call: `ingest`

```json
{
  "tool": "ingest",
  "parameters": {
    "path": "/data/incoming/q4-research/",
    "recursive": true,
    "file_types": ["pdf", "docx"],
    "collection": "q4-research",
    "force": false
  },
  "caller_metadata": {
    "agent_id": "user:denson",
    "agent_type": "claude-code",
    "initiated_by": "user:denson",
    "agent_notes": "Batch ingest of Q4 research papers for pricing model analysis"
  }
}
```

**Notes on Parameter Selection:**

- `path: "/data/incoming/q4-research/"` — Directory specified by user
- `recursive: true` — Standard batch behavior; processes any subdirectories that may exist
- `file_types: ["pdf", "docx"]` — User mentioned "12 PDFs and a few DOCX files"
- `collection: "q4-research"` — Logical collection name for the research papers; enables later filtering when searching for pricing model content
- `force: false` — Standard dedup behavior; avoids re-processing if documents were already ingested
- **Caller metadata** — Captures that Denson initiated this batch ingest; `agent_notes` records intent for future context

---

## Expected Return Value

The `ingest` tool returns:

```json
{
  "job_id": "ingest-20260405-abc123def456",
  "files_found": 15,
  "estimated_time_seconds": 45,
  "message": "Batch ingestion queued. Check job status via get_document(job_id)."
}
```

---

## User-Facing Response

"Got it, I'm starting the batch ingest of your Q4 research papers. I found 15 documents total (PDFs and DOCX files) in `/data/incoming/q4-research/`.

Here's what's happening:

1. **Ingestion queued** — Job ID: `ingest-20260405-abc123def456`
2. **Processing order** — Documents are being extracted with MarkItDown, enriched, chunked by title/page structure, embedded, and stored in pgvector
3. **Collection** — Everything is going into the `q4-research` collection so you can search them together later
4. **Deduplication** — If any of these were already in the system, I'll skip re-processing and just create a new provenance record
5. **Estimated time** — Should finish in about 45 seconds

Once complete, you can search across all of them with queries like:

```
search("pricing model strategies in Q4 research", collection="q4-research")
```

The search will return relevant chunks with page numbers, document links, and a full provenance trail showing which agent touched each result. I'll check the job status and give you a summary once it's done."

---

## Processing Pipeline (What Happens Inside)

For each of the 15 documents:

1. **Content Fingerprint** — SHA-256 hash of normalized extracted text
2. **Dedup Check** — Query `documents` table for matching `(collection_id, content_fingerprint)` tuple
   - **If match found** — Skip expensive processing, create `document_interactions` row with `was_dedup_skip = true`, return existing document
   - **If no match** — Continue to step 3
3. **Image Enrichment** — Vision API describes any embedded images (optional; configurable)
4. **Chunking** — Auto-selected by file type:
   - `.pdf` → `by_title` (split on heading hierarchies)
   - `.docx` → `by_title` (Word styles become heading markers)
5. **Embedding** — Send chunks to configured embedding API (e.g., OpenAI, local model)
6. **Vector Storage** — Insert chunks into pgvector with `embedding_model` tracked
7. **Record Interaction** — Write to `document_interactions` table with agent_id, initiated_by, action='ingest'
8. **Processed Files** — Optionally write `.md` + `.json` to output directory

---

## Follow-Up Commands (Available After Ingest)

Once the job completes, you can:

**Check job status:**
```json
{
  "tool": "get_document",
  "parameters": {
    "document_id": "ingest-20260405-abc123def456"
  }
}
```

**Search for pricing models:**
```json
{
  "tool": "search",
  "parameters": {
    "query": "pricing models revenue tiers subscription",
    "collection": "q4-research",
    "top_k": 10
  }
}
```

**List all ingested documents:**
```json
{
  "tool": "list_documents",
  "parameters": {
    "collection": "q4-research",
    "per_page": 50
  }
}
```

**Get full text of a specific document:**
```json
{
  "tool": "get_document",
  "parameters": {
    "source_file": "filename.pdf"
  }
}
```

---

## Provenance Trail

Every document will have a `document_interactions` record:

- **agent_id:** `user:denson`
- **agent_type:** `claude-code`
- **initiated_by:** `user:denson`
- **action:** `ingest`
- **was_dedup_skip:** `true` or `false` (depending on whether it was already in the system)
- **timestamp:** ISO 8601 (when the interaction occurred)
- **agent_notes:** "Batch ingest of Q4 research papers for pricing model analysis"

If you ingest the same batch again, it will add new interaction records without re-processing, preserving the dedup efficiency.
