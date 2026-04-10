# Batch Ingest: Q4 Research Papers

## Tool Calls (in order)

### 1. List existing collections

**Tool:** `list_collections`

```json
{}
```

**Purpose:** Check what collections already exist before deciding whether to create a new "q4-research" collection or use an existing one.

---

### 2. Batch ingest the directory

**Tool:** `ingest`

```json
{
  "path": "/data/incoming/q4-research",
  "collection": "q4-research",
  "recursive": false,
  "file_types": ["pdf", "docx"],
  "force": false,
  "tags": ["q4-research", "research-papers", "pricing"],
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-haiku-4-5-20251001",
  "agent_id": "wonderful-kind-meitner",
  "agent_notes": "User uploaded batch of Q4 research papers and wants to search across them for pricing models. Expects ~12 PDFs and a few DOCX files.",
  "agent_metadata": {
    "task": "batch-ingest",
    "expected_file_count": "~15",
    "use_case": "pricing-model-research"
  }
}
```

**Purpose:** Ingest all PDF and DOCX files from `/data/incoming/q4-research/` into the `q4-research` collection. The `ingest` tool will:
- Scan the directory for PDF and DOCX files
- Convert each to Markdown using MarkItDown
- Check for dedup (skip if already in system)
- Chunk by title (default for mixed documents)
- Embed using configured embedding API
- Store chunks + vectors in pgvector
- Record one interaction row per file processed, plus dedup skips

---

## User-Facing Message

```
Got it! I'm going to batch-ingest your Q4 research papers into the system.

I'm setting up a `q4-research` collection to keep your research separate from other
projects, which will make search results cleaner when you're looking for pricing
insights later.

I'm processing all PDFs and DOCX files from `/data/incoming/q4-research/`.
Depending on file size and count (~15 files), this should take a minute or two.

Once it's done, I'll tell you:
- How many files were processed
- How many chunks they became (better granularity = better search)
- Whether any were skipped (dedup)
- Any warnings (e.g., missing image processing, corrupted pages)

After that, you can ask me things like:
- "Search for pricing models in my Q4 research"
- "What did these papers say about subscription pricing?"
- "Find all mentions of tiered pricing strategies"

And I'll retrieve the exact sections that match, not just whole documents.

Ingesting now...
```

---

## Why These Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `path` | `/data/incoming/q4-research` | User specified this directory |
| `collection` | `q4-research` | User's project context (Q4 research), descriptive and clear |
| `recursive` | `false` | User said "in there" (implied single folder, not subfolders) |
| `file_types` | `["pdf", "docx"]` | User mentioned "12 PDFs and a few DOCX files" |
| `force` | `false` | First ingestion, no reason to re-process |
| `tags` | `["q4-research", "research-papers", "pricing"]` | Labels for later filtering by use case |
| `agent_type` | `"claude-code"` | Running in Claude Code environment |
| `initiated_by` | `"user:denson"` | User identified themselves as Denson |
| `model` | `"claude-haiku-4-5-20251001"` | The model powering this session |
| `agent_notes` | User request + context | Critical provenance: explains *why* these docs were ingested for future search context |
| `agent_metadata` | Structured data | Preserves intent (pricing research) and expectations (file count, use case) |

---

## What Happens Next

Assuming Ariadne Core is running and the directory exists:

1. **Discovery** — Find all `.pdf` and `.docx` files in `/data/incoming/q4-research/`
2. **Dedup check** — For each file, compute SHA-256 fingerprint of normalized text; skip any already in `q4-research` collection
3. **Extraction** — Convert each (non-dedup) file to Markdown
4. **Enrichment** — If configured with `VISION_API_KEY`, describe images in extracted content
5. **Chunking** — Break Markdown by title (strategy auto-selected for mixed doc types)
6. **Embedding** — Send chunks to embedding API (OpenAI-compatible), get vectors
7. **Storage** — Store chunks + vectors + metadata in pgvector (table: `chunks`)
8. **Interaction logging** — Create one `document_interactions` row per file (including dedup skips)
9. **Report** — Return summary: files processed, chunks created, skips, errors

---

## When You Want to Search

Once ingestion is complete, use the `search` tool with queries like:

```json
{
  "query": "pricing models",
  "collection": "q4-research",
  "top_k": 5,
  "agent_type": "claude-code",
  "initiated_by": "user:denson",
  "model": "claude-haiku-4-5-20251001",
  "agent_notes": "User searching for pricing model strategies in Q4 research papers"
}
```

The search will return ranked chunks (by relevance score) with source document, page/section, and the exact matching text. Much more efficient than reading entire PDFs.

---

## If Something Goes Wrong

- **Directory not found** → Check path, ensure files are there: `ls /data/incoming/q4-research/`
- **No files matched** → Ensure files are named `*.pdf` or `*.docx` (case-sensitive on Linux)
- **Ariadne not running** → Start the Docker Compose stack: `docker-compose up -d`
- **Vision API warnings** — Images won't be described unless `VISION_API_KEY` is set in `.env`
- **Unsupported formats** — Only PDF, DOCX supported in this call; PPTX, XLSX, etc. require separate calls

Tell me if any issues come up and I can help debug!
