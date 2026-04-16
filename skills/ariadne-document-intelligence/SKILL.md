---
name: ariadne-document-intelligence
description: "Process, search, and manage documents using Ariadne Core tools. Triggers: ingest this, search my documents, process this file, find that PDF."
---

# Ariadne Document Intelligence

This skill is for USING the tools, not learning about them. For general questions
about what Ariadne Core is or how it works, use the ariadne-core-walkthrough skill.

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

You have the following MCP tools when Ariadne Core is connected:

- **`convert_document`** — Convert a single document to Markdown. Chunks, embeds, and
  stores it by default. Use for any individual file the user uploads or references.
  Accepts optional `chunking_config` to override the auto-selected chunking strategy.
  Accepts HTTP/HTTPS URLs or server-side paths from the upload endpoint. For local
  files, upload via REST `POST /api/upload` first and pass the returned server-side
  path here.

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

## How to ingest documents

**Single file or directory?** This is the first decision. Get it wrong and you
burn LLM tokens on data movement — exactly the waste Ariadne exists to prevent.

### Path A — Single file (upload + convert_document)

The most common case. User drops a file, pastes a URL, says "ingest this."

**Step 1 — Upload the file via REST:**

```bash
curl -s -X POST "$ARIADNE_URL/api/upload" \
  -H "X-API-Key:$ARIADNE_API_KEY" \
  -F "file=@path/to/document.pdf"
```

Response: `{"path": "/tmp/uploads/abc123/document.pdf"}`

**Step 2 — Call `convert_document` with the server-side path:**

```
uri: "/tmp/uploads/abc123/document.pdf"
collection: "my-collection"
store: true
tags: ["source:upload"]
agent_notes: "User wants to review the Q4 financials"
```

Done. The file bytes go over HTTP once and never touch the LLM context.

**If the file is at an HTTP/HTTPS URL**, skip the upload — pass the URL directly:

```
uri: "https://example.com/reports/q4-2025.pdf"
```

**Never base64-encode file content into an MCP tool argument.** A 6 MB PDF
becomes ~8 MB of base64 — roughly 1.5–2 M tokens of tool-call payload before
the server has done any work. Always use the REST upload for local files.

**Credential handling:** never display the API key from `.mcp.json` in terminal
output, chat, or logs. Never include it in curl commands shown to the user. Read
credentials programmatically so they are never echoed.

### Path B — Directory / many files (bulk_ingest.py)

User says "ingest this folder," "process all these files," or you're looking at
more than 5 files. Use `bulk_ingest.py` — it talks to the REST API directly, so
zero file bytes pass through the LLM context.

**Dry run first:**

```bash
python ariadne-core/scripts/bulk_ingest.py data/reports/ \
  --collection wb_reports --dry-run
```

**Then ingest:**

```bash
python ariadne-core/scripts/bulk_ingest.py data/reports/ \
  --collection wb_reports \
  --tags type:report,topic:policy
```

Useful flags: `--recursive`, `--skip-existing`, `--max-files N`,
`--extensions pdf,docx`, `--agent-notes "..."`.

The script reads the server URL and API key from `.mcp.json` + `.env` — no
credentials on the command line.

**Pre-flight check:** The script lives in the `ariadne-core` git repo, which
should be a subdirectory of the project workspace. Before running it:

```bash
# Clone if missing:
git clone https://github.com/denson/ariadne-core.git

# Or refresh if present:
cd ariadne-core && git pull && cd ..

# Verify:
ls ariadne-core/scripts/bulk_ingest.py
```

If the file is missing after a successful `git pull`, stop and tell the
user — something is wrong with their clone.

> **DO NOT** loop over files calling `convert_document` via MCP. That defeats
> Ariadne's core value proposition. One Bash call to `bulk_ingest.py` replaces
> hundreds of MCP round-trips. If you have more than 5 files, use Path B.

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

## Ingesting local files

Ariadne Core runs as a remote service, so you cannot pass local file paths
directly to `convert_document`. Use Path A (upload + convert_document) or
Path B (bulk_ingest.py) from the routing section above. Both paths send file
bytes over HTTP to the server — they never pass through the LLM context.

For bulk ingestion, use `bulk_ingest.py` (Path B above). For single files,
use the upload + convert_document pattern (Path A above).

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
agent_metadata: {
  "source_reference": "https://acme.example.com/legal/msa-2026.pdf",
  "intent": "compliance-review"
}
```

**Example — bad metadata (don't do this):**
```
agent_type: null
initiated_by: null
agent_notes: null
```

### Metadata conventions

Follow the conventions in SPEC.md "Metadata Conventions" for how to populate
`collection`, `tags`, `agent_notes`, and `agent_metadata`. Key points:

- **`collection`**: name it after the project, topic, or task — not `"default"`
- **`tags`**: lowercase, hyphenated, use namespace prefixes (`"project:atlas"`,
  `"status:reviewed"`, `"source:email"`)
- **`agent_notes`**: write notes that help a future agent decide whether to re-read
  the document. Bad: `"processed this file"`. Good: `"Extracted for Q1 pricing review.
  Found 3 tables on revenue projections."`
- **`agent_metadata`**: use the recommended keys (`project`, `source_url`, `intent`,
  `findings`, `status`, `related_documents`) so metadata from different agents is
  interoperable
- Omit keys you don't have values for — don't pass `null`

## Provenance

**Every document MUST have `source_reference` in `agent_metadata`. This is not optional.**

A document with no recorded origin is unverifiable and uncitable. A corpus full of unsourced documents is noise. Recording provenance at ingest time is the single cheapest thing you can do to keep the corpus useful.

### Source-of-truth hierarchy (default)

Use the most authoritative source you have:

1. **DOI** — for research papers. Format `"doi:10.xxxx/..."`. Look in the document text and metadata.
2. **URL** — the original URL the document was downloaded from.
3. **Database / API reference** — a query, endpoint, or record ID.
4. **Local file path** — the original filesystem path.
5. **`"unknown"`** — explicit, with a `source_notes` explanation.

Project-specific skills (e.g., cannabis, legal, medical) may override this hierarchy with stricter rules per document type. Follow the project skill's rules when one applies.

### Per-tier guidance

- **DOI** — search the first page or document metadata. Many papers have a DOI on page 1 or in the bottom-of-page footer.
- **URL** — record the **original URL the document came from**, not the `/api/upload` server path. The server path is meaningless to a future agent; the source URL lets them re-fetch and verify.
- **Database / API** — record the query or endpoint that produced the document, e.g. `"pubmed:32168263"` or `"https://api.example.com/reports/2026-03"`.
- **Local file** — record the original path as context, e.g. `"file:///D:/research/2026/draft.pdf"`. If the path itself is meaningless out of context, also set `source_notes`.
- **Unknown** — explicit only. Set `"source_reference": "unknown"` AND a `source_notes` explanation. Never leave the field missing as a way to mean "I don't know".

### Explicit unknown beats missing

`"source_reference": "unknown"` with notes is fine. Missing `source_reference` is not. The explicit value tells the next agent "this was considered" — a missing field tells them "no one tried".

### When to ask

If provenance isn't obvious from the user's message or context, **ask before ingesting**. A reasonable question:

> "Where did this document come from? A URL, a DOI, a database, or somewhere else? I want to record it so we can cite it later."

Asking once at ingest time is much cheaper than discovering six months from now that you have a corpus of unsourced documents.

## Process: Ingesting a document

> **Is this a single file or many files?** For bulk ingestion (more than 5
> files, or a whole directory), skip this process entirely and use
> `scripts/bulk_ingest.py` via Bash instead — see Path B in the "How to
> ingest documents" section above. For a single file, follow Path A
> (upload + convert_document) and then the steps below.

1. **Get the file URL** from the user's message or context.

   What you can pass as `uri`:
   - HTTP/HTTPS URLs: `https://example.com/document.pdf`
   - Server-side paths from the upload endpoint

   If the user references a local file and you have file access (e.g., in Claude
   Code), upload it via `POST /api/upload` first, then use the returned path.

2. **Determine provenance.** Decide what `source_reference` you'll record in
   `agent_metadata` (see the Provenance section above). If the user gave you a URL
   or DOI, that IS the provenance. If they handed you a local file with no context,
   ask them where it came from before ingesting — don't silently default to
   `"unknown"`.

3. **Choose a collection** using the decision tree above. Call `list_collections`
   first to see what exists.

4. **Call `convert_document`** with:
   - `uri`: the URL or server-side path
   - `store`: `true` (default)
   - `collection`: your chosen collection name
   - `tags`: any relevant tags the user mentioned or that describe the document
   - `chunking_config`: only if the user requests a specific chunking strategy or if
     the auto-selection isn't appropriate (see chunking section below)
   - All caller metadata fields populated, including `agent_metadata.source_reference`

5. **Check the response.** The response includes:
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

6. **Handle errors:**
   - Zero-byte or corrupt file → tell the user the file appears damaged
   - Password-protected → tell the user to remove the password and retry
   - Unsupported format → tell the user which formats are supported
   - Image with no vision API → relay the warning, suggest configuring `VISION_API_KEY`
   - Embedding not configured → search won't work, tell the user an embedding API key
     is needed
   - Service unreachable → suggest checking that the Ariadne Core deployment is
     running and the URL is correct

7. **Tell the user what happened.** Which collection, how many chunks, whether it was
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
| `file_type` | string | Exact match against file extension (e.g., `".pdf"`, `".docx"`). Both `.pdf` and `pdf` are accepted |
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
