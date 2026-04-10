---
name: ariadne-document-intelligence
description: |
  Use Ariadne Core tools to process, search, and manage documents. Triggers when the
  user wants to DO something with documents: upload, ingest, search, extract, or query.
  Examples: "ingest this", "store this document", "process this file", "search my
  documents", "find that PDF", "what does [document] say about [topic]", "ingest this
  folder". Do NOT trigger on general questions about what Ariadne Core is or how it
  works — those go to the onboarding skill instead. This skill is for USING the tools,
  not learning about them.
version: 4.0.0
---

# Ariadne Document Intelligence

## Why this skill exists

Expensive models should spend their tokens on thinking, not parsing PDFs. A 100-page
PDF that would consume 50,000-100,000 tokens of raw content becomes 500 tokens of
relevant, retrieved context through Ariadne Core. That's 100-200x more efficient
use of the model's attention.

In practice, this means users hit their usage limits less often. A raw PDF in a
conversation eats context window and burns through rate limits fast. The same document
extracted and retrieved via search uses a fraction of the tokens — longer productive
sessions, fewer interruptions, more work done before hitting any wall.

Ariadne Core handles the extraction, chunking, embedding, and search so you can
focus on answering the user's actual question. This skill teaches you when and how
to use it.

## Before using this skill — check connection

Before doing anything else, verify that Ariadne Core is connected.
Try calling `list_collections`. If it succeeds, you're good — skip to the tools
section below.

If it fails with a connection error, or the Ariadne Core tools aren't available,
tell the user that Ariadne Core needs to be deployed and connected. Point them
to the installation docs or the **ariadne-core-install** skill.

Do not attempt to use `convert_document`, `search`, `ingest`, or any other Ariadne
tool until you've confirmed the connection works.

## Tools available

You have six MCP tools when Ariadne Core is connected:

- **`convert_document`** — Convert a single document to Markdown. Chunks, embeds, and
  stores it by default. Use for any individual file the user uploads or references.
  Accepts optional `chunking_config` to override the auto-selected chunking strategy.
  Accepts HTTP/HTTPS URLs or server-side paths from the upload endpoint.

- **`search`** — Semantic search over stored documents. Returns JSON with `query`,
  `results_count`, and `results` array. Each result includes `chunk_id`, `document_id`,
  `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`,
  `embedding_model`, and `interactions` (full history of agent touches on the source
  document). Supports filters for collection, source file, file type, tags, and
  document ID.

- **`get_document`** — Get the full Markdown content and all chunks for a document by
  ID. Use after search when the user wants the complete document, not just matching
  chunks. Pass `include_chunks: false` or `include_interactions: false` to trim the
  response when you only need part of it.

- **`list_documents`** — Browse stored documents by collection or file type. Returns
  metadata only. Supports `limit` (default 20, max 100) and `offset` for pagination.
  Use when the user wants to see what's in the store.

- **`list_collections`** — See all collections with document counts. Use before choosing
  a collection for ingestion, or when the user asks what's available.

- **`ingest`** — Batch-ingest files from a server-side directory. Use when files have
  been uploaded to the server and need bulk processing.

## When to use `convert_document` instead of reading files directly

When you encounter a document — PDF, DOCX, PPTX, XLSX, or any supported format —
use `convert_document` rather than trying to read it directly. There are three reasons:

1. **Token efficiency.** The extracted Markdown is 8-15x smaller than raw content.
   A 40-page contract that would flood your context becomes a few thousand tokens of
   clean, structured text.

2. **Future searchability.** With `store: true` (the default), the document is chunked,
   embedded, and stored. Any future search by you or another agent can find it.

3. **Provenance.** Every ingestion is recorded — who asked, when, what model, why.
   This means search results come with full history.

The only exception: very small plain text files (under ~10 pages) that you can handle
directly in context without extraction.

## How to handle local files

Ariadne Core runs as a remote service, so you cannot pass local file paths directly.
When the user references a local file:

1. **If the file is at a URL** — pass the URL directly to `convert_document`.
2. **If you have file access** (e.g., in Claude Code) — upload it via
   `POST /api/upload` first, then pass the returned server-side path to
   `convert_document`.
3. **If neither works** — tell the user the file needs to be accessible via URL or
   uploaded to the server.

## When to use `ingest` vs `convert_document`

- Single file → `convert_document`
- Multiple files already on the server → `ingest`
- Tell the user how many files were found and give a time estimate before starting
  a large batch

## Chunking

Chunking strategy is auto-selected by file type. You usually don't need to set it,
but you can override it with `chunking_config` on `convert_document` if the auto
selection isn't right.

**Auto-selection defaults:**

| File type | Strategy | Why |
|-----------|----------|-----|
| `.pptx` | `by_page` | Each slide is a self-contained unit |
| `.csv`, `.xlsx` | `fixed_size` | Tabular data has no heading structure |
| `.txt` with no headings | `fixed_size` with high overlap | No natural section breaks |
| Everything else | `by_title` | Most structured documents have section headings |

**Override example** — if you know a document needs different chunking:
```
chunking_config: {
  "strategy": "fixed_size",
  "max_characters": 2500,
  "overlap": 400
}
```

Keys: `strategy` (`"by_title"`, `"by_page"`, `"fixed_size"`), `max_characters`, `overlap`.

## Choosing a collection

Collections are logical namespaces that keep search results relevant. A messy
"everything in default" collection degrades search quality because unrelated documents
compete for relevance. Use this decision tree:

1. **User specified one?** Use it.
2. **Working in a project context?** Use the project name: `"ariadne-core"`,
   `"q4-research"`, `"acme-contract-review"`.
3. **One-off task?** Use a descriptive name based on document type or purpose:
   `"receipts"`, `"reference-docs"`, `"meeting-notes"`.
4. **Nothing fits?** Use `"default"` — but this should be rare.

Always tell the user which collection you chose and why. They may want to correct it
or remember it for later.

Before choosing, call `list_collections` to see what already exists. If the user's
document fits an existing collection, use that one rather than creating a new one with
a slightly different name.

## Caller metadata

Every call to `convert_document`, `search`, and `ingest` should include caller
metadata. The provenance trail is only useful if you actually populate it.

- **`agent_type`**: Always set. Use `"claude-cowork"` in Cowork, `"claude-code"` in
  Claude Code, `"cursor"` in Cursor, etc.
- **`initiated_by`**: Always set when you know the user. Format: `"user:name"`
  (e.g., `"user:denson"`).
- **`model`**: Always set. The model you're running on (e.g., `"claude-sonnet-4-6"`).
- **`agent_notes`**: Set on every call. Use the user's prompt or a brief description
  of why this action is being taken. This is the single most valuable provenance
  field — future agents and future searches see *why* this document was ingested,
  not just that it was.
- **`agent_id`**: Set when available. Your session ID or workflow identifier.
- **`agent_metadata`**: Set when there's structured context worth preserving
  (project ID, workflow stage, etc.).

**Example — good metadata:**
```
agent_type: "claude-cowork"
initiated_by: "user:denson"
model: "claude-sonnet-4-6"
agent_notes: "User uploaded Acme MSA and wants to find the termination clause"
```

**Example — bad metadata (don't do this):**
```
agent_type: null
initiated_by: null
agent_notes: null
```

## Process: Ingesting a document

1. **Get the file URL** from the user's message or context.

   What you can pass as `uri`:
   - HTTP/HTTPS URLs: `https://example.com/document.pdf`
   - Server-side paths from the upload endpoint

   If the user references a local file and you have file access (e.g., in Claude
   Code), upload it via `POST /api/upload` first, then use the returned path.

2. **Choose a collection** using the decision tree above. Call `list_collections`
   first to see what exists.

3. **Call `convert_document`** with:
   - `uri`: the URL or server-side path
   - `store`: `true` (default)
   - `collection`: your chosen collection name
   - `tags`: any relevant tags the user mentioned or that describe the document
   - `chunking_config`: only if the user requests a specific chunking strategy or if
     the auto-selection isn't appropriate (see chunking section below)
   - All caller metadata fields populated

4. **Check the response.** The response includes:
   - `document_id`: UUID for this document (use with `get_document` and search filters)
   - `source_file`: original filename
   - `title`: extracted or inferred document title
   - `markdown`: the full extracted Markdown text
   - `file_type`: detected file extension
   - `engine`: extraction engine used (e.g., `"markitdown"`)
   - `content_fingerprint`: SHA-256 hash used for dedup
   - `chunks_count`: how the document was broken up for search
   - `was_dedup_skip`: `true` means this document was already ingested — tell the user:
     "This document was already in the [collection] collection." No extra work needed.
   - `provenance`: processing chain with timestamps
   - `warnings`: array of non-fatal issues (e.g., image files needing a vision API key).
     Relay these to the user.
   - `processing_time_ms`: how long extraction took
   - `output_tokens_estimate`: approximate token count of the extracted Markdown
   - `token_savings_ratio`: ratio of input size to output tokens — useful for showing
     the user how much context was saved
   - `embedding_model`: which model was used for chunk embeddings
   - `store_status`: `"stored"`, `"not_stored"`, or `"skipped"`
   - `interactions`: present on dedup hits, shows who previously touched this document

5. **Handle errors:**
   - Zero-byte or corrupt file → tell the user the file appears damaged
   - Password-protected → tell the user to remove the password and retry
   - Unsupported format → tell the user which formats are supported
   - Image with no vision API → relay the warning, suggest configuring `VISION_API_KEY`
   - Embedding not configured → search won't work, tell the user an embedding API key
     is needed
   - Service unreachable → suggest checking that the Ariadne Core deployment is
     running and the URL is correct

6. **Tell the user what happened.** Which collection, how many chunks, whether it was
   a dedup skip. Keep it brief: "Processed acme-msa-2026.pdf into the acme-review
   collection (47 chunks). It's now searchable."

## Process: Batch ingesting

1. **Upload files** to the server via `POST /api/upload` if they are local.

2. **Choose a collection** — same decision tree as single documents.

3. **Call `ingest`** with:
   - `path`: the server-side directory path
   - `collection`: your chosen collection
   - `recursive`: `true` unless the user said otherwise
   - `file_types`: filter if the user asked for specific types (e.g., `["pdf", "docx"]`)
   - `force`: `false` unless the user says documents have changed
   - `tags`: any tags to apply to all documents
   - All caller metadata fields

4. **Report the summary** when done: files found, files processed, files skipped
   (dedup), and any errors. Files are processed concurrently (up to 4 at a time),
   but for large batches it may still take minutes, so set expectations with the
   user beforehand.

## Process: Searching documents

1. **Determine the search query.** Use the user's question directly, or extract the
   search intent from a broader request. "What did the Acme contract say about
   termination?" → query: `"termination clause"`.

2. **Scope the search** when context makes it obvious:
   - User mentions a collection → set `collection`
   - User mentions a specific file → use `filters: {"source_file": "filename"}`
   - User mentions a file type → use `filters: {"file_type": "pdf"}`
   - User mentions tags → use `filters: {"tags": ["tag1", "tag2"]}`
   - User mentions a specific document ID → use `filters: {"document_id": "uuid"}`
   - Combine filters when multiple constraints apply — they AND together

3. **Call `search`** with:
   - `query`: the natural language search query
   - `collection`: if scoped
   - `top_k`: default 5, increase if the user wants comprehensive results (max 20)
   - `filters`: as determined above
   - Caller metadata fields

4. **Use interaction history to prioritize results.** Each search result includes an
   `interactions` array showing every agent that has touched that document — who
   ingested it, when, what model, and most importantly the `agent_notes` explaining
   *why*. Use this to decide which results matter most:
   - A document whose `agent_notes` say "User wants to find the termination clause"
     is more relevant to a termination question than one with higher vector similarity
     but unrelated provenance
   - A document ingested by `initiated_by: "user:denson"` is the user's own document,
     not something a batch job pulled in
   - Multiple interactions from different agents signal a document that keeps coming
     up — it's probably important
   - The `agent_type` and `model` tell you how the document was processed and by whom

5. **Present results clearly.** For each relevant result:
   - The source document name and relevant section/page
   - The matching text
   - How it relates to the user's question
   - Don't just dump raw chunks — synthesize an answer from the results

6. **Follow up if needed.** If the user wants more detail on a specific document,
   call `get_document` with the document ID from the search results.

## Process: Browsing the store

1. Call `list_collections` to see what's available.
2. Call `list_documents` filtered by collection or file type if the user asks.
3. Present results as a navigable list — document name, collection, file type,
   when it was ingested.
4. If the user wants to see a specific document, call `get_document`.

## When to search before answering

If the user asks a question that could be answered by documents they've previously
ingested, search first. Don't guess from memory.

Triggers for "search first":
- "What did [document] say about..."
- "Find that [thing] in my documents"
- "What do we know about X"
- "Search my docs for..."
- Any question where the answer is likely in a document the user previously uploaded

Use `list_collections` first if you're not sure what's been ingested. If there's
nothing in the store, tell the user rather than guessing.

## Search filters reference

The `filters` parameter on `search` accepts these keys:

| Filter key | Type | Behavior |
|------------|------|----------|
| `collection` | string | Match chunks in this collection. Same as the top-level `collection` parameter — either works |
| `document_id` | string | Match chunks from a specific document |
| `source_file` | string | Substring match (case-insensitive) against the source document's filename |
| `file_type` | string | Exact match against file extension without leading dot (e.g., `"pdf"`, `"docx"`) |
| `tags` | list[str] | Match documents that have any of the specified tags (OR logic) |

Unknown filter keys are silently ignored.

## Open Brain bridge (when OB1 is available)

If Open Brain is connected, capture a summary thought after ingesting a document.
This makes the document discoverable through normal brain search alongside regular
thoughts.

**The thought should contain:**
- **content**: 2-4 sentence summary of the document
- **metadata**:
  - `source`: `"ariadne-core"`
  - `ariadne_document_id`: the document ID from Ariadne
  - `ariadne_collection`: the collection name
  - `source_file`: the original filename
  - `file_type`: extension without the dot (e.g., `"pdf"`)
  - `user_prompt`: the user's original request — this gives future agents context
    about why the document was stored

The thought is a pointer and summary, not a copy. Ariadne handles the heavy content;
Open Brain handles the memory graph.

**Search works both ways:**
- **Broad recall** → search Open Brain for thoughts + document summaries together
  ("what do I know about pricing")
- **Precise retrieval** → search Ariadne directly for chunk-level matches
  ("find the exact clause about termination in the contract")

## Supported formats

Over 20 formats: PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV, HTML, TXT, Markdown, JSON,
XML, RTF, EPUB, EML, MSG, ZIP (recursive), Jupyter notebooks, RST, ORG, WAV, MP3, M4A.

Images (JPG, JPEG, PNG, GIF) require a vision API key for content extraction. Without it,
images are accepted but produce empty output with a warning explaining that a vision
API key is needed.

Not supported: scanned PDFs (no text layer), legacy .doc/.ppt, complex layouts with
merged cells, BMP/TIFF/HEIC.

## Notes

- Dedup is automatic. You don't need to check if a document was already ingested —
  just call `convert_document` and the system handles it. Use `force: true` only when
  the user says the document content has changed.

- Tags are useful for filtering search results later. If the user mentions categories,
  topics, or labels, apply them as tags during ingestion.

- Search results include interaction history — which agents have previously touched
  each document. This context is useful when answering questions about document
  provenance or workflow history.

- Token efficiency matters. Always ingest through Ariadne before passing document
  content to an LLM. A 100-page PDF that would cost 50K-100K raw tokens is extracted
  to 5K-8K tokens of clean Markdown.

- All processing is synchronous. `convert_document` and `ingest` return the full
  result when they complete. There is no async job_id or polling pattern.
