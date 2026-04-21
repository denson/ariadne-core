---
name: ariadne-document-intelligence
description: "Process, search, and manage documents using Ariadne Core. Triggers: ingest this, search my documents, process this file, find that PDF."
---

# Ariadne Document Intelligence

This skill is for USING Ariadne Core, not learning about it. For general questions
about what Ariadne Core is or how it works, use the ariadne-core-walkthrough skill.

## Why this skill exists

Expensive models should spend their tokens on thinking, not parsing PDFs. A 100-page
PDF that would consume 50,000-100,000 tokens of raw content becomes 5,000 tokens of
clean, searchable Markdown through Ariadne Core. That's 10-20x more efficient
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

```python
from ariadne_core_client import AriadneClient
client = AriadneClient()
client.health()
```

If this succeeds, you're good — skip to the ingestion section below.

If it fails with a connection error, tell the user that Ariadne Core needs to be
deployed and connected. Point them to the installation docs or the
**ariadne-core-install** skill.

The client resolves the server URL and JWT automatically from:
1. Environment variables: `ARIADNE_URL`, `ARIADNE_ACCESS_TOKEN` (a JWT)
2. `.env` file in current directory or parent directories
3. `.mcp.json` file (legacy support)

Ariadne Core uses Auth0 OAuth 2.1 Bearer JWT as of the `ariadne--xft.2` merge
(commit `54165c9`). The `ariadne login` CLI that runs the PKCE flow and caches a
refresh token in the OS keyring is landing in ticket `ariadne--xft.5`. Until
then, obtain a test JWT from **Auth0 dashboard → Applications → your app → Test
tab → copy the access token**, then set `ARIADNE_ACCESS_TOKEN=<jwt>` in your
`.env`.

If no credentials are configured yet, the client CLI can create a `.env` from the
project's `.env.example` template:

```bash
ariadne setup
```

This copies `.env.example` to `.env` in the current directory. Edit it to fill in
your `ARIADNE_URL` and `ARIADNE_ACCESS_TOKEN`. The full `.env.example` also
includes server-side configuration (embedding provider, vision provider, database,
Auth0 tenant) for users running their own Ariadne Core deployment.

Clients can check which Auth0 tenant a server expects via the unauthenticated
discovery endpoint:

```bash
curl https://$ARIADNE_URL/.well-known/ariadne-config
```

Do not attempt to use the client until you've confirmed the connection works.

## Client setup

The client package wraps the REST API. Install it:

```bash
pip install ariadne-core-client
```

Set up the client with default caller metadata — these apply to every call:

```python
from ariadne_core_client import AriadneClient

client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

The client returns dataclasses (`Document`, `SearchResult`, `Collection`, `Stats`, `Health`),
not dicts. Errors are exceptions (`AriadneClientError`, `AriadneAuthError`,
`AriadneNotFoundError`, `AriadneServerError`), not error dicts.

## How to ingest documents

**Single file or directory?** This is the first decision. Get it wrong and you
burn LLM tokens on data movement — exactly the waste Ariadne exists to prevent.

### Three ingestion methods (preference order)

| Priority | Method | Token cost | When to use |
|----------|--------|-----------|-------------|
| 1st | `client.ingest_url(url)` | Zero — server fetches | Document at an HTTP/HTTPS URL |
| 2nd | `client.ingest_file(path)` | Zero — client uploads | Local file |
| 3rd | `client.ingest_bytes(content, filename)` | Already paid | File dropped in chat UI |

#### 1. URL — server fetches directly (best)

```python
doc = client.ingest_url("https://example.com/report.pdf",
    collection="reports",
    tags=["financial", "q1-2026"],
    agent_notes="User wants revenue trends from Q1 report"
)
```

The URL is automatically recorded as the document's `source_reference`. This is the
best path when the document is at a URL — zero bytes flow through the agent.

#### 2. Local file — client uploads

```python
doc = client.ingest_file("path/to/report.pdf",
    collection="reports",
    source="https://example.com/report.pdf",
    agent_notes="User wants revenue trends from Q1 report"
)
```

Or via CLI:

```bash
ariadne ingest report.pdf --collection reports
```

The client handles the upload + conversion in one call. The file bytes travel over
HTTP once and never enter the LLM's context. A 6 MB PDF as base64 would be ~8 MB /
~1.5-2M tokens — uploading avoids that entirely.

Note: `ingest_file()` does NOT auto-set `source_reference` from the file path — a
local path is not provenance. Pass the `source` parameter if you know where the
document came from.

#### 3. Bytes already in context — store what you have

When a user drops a file into the chat UI, you already have the content. Rather
than discarding it, store it:

```python
doc = client.ingest_bytes(file_content,
    filename="report.pdf",
    collection="reports",
    agent_notes="User dropped file in chat, storing for search"
)
```

After ingesting bytes, tell the user: "This file is now in Ariadne and searchable.
Next time, give me the file path instead of dropping it — I'll ingest it directly
without loading it into our conversation."

### Batch ingestion

For directories, use the CLI:

```bash
ariadne ingest data/reports/ --collection reports --recursive
ariadne ingest data/reports/ --collection reports --manifest manifest.jsonl
```

The `--manifest` flag attaches per-file metadata from a JSONL manifest during
ingestion. Useful for corpora with existing metadata (academic papers, regulatory
documents, etc.).

For server-side directories, use `POST /api/ingest` directly (the CLI handles this).

> **DO NOT** loop over files calling `client.ingest_file()` when the CLI handles
> batching. One CLI call replaces hundreds of individual calls. If you have more
> than 5 files, use the CLI.

### Source convenience parameter

All ingest methods accept an optional `source` string — a shortcut for
`agent_metadata["source_reference"]`:

```python
client.ingest_file("report.pdf", source="https://documents.worldbank.org/...")
client.ingest_bytes(content, filename="report.pdf", source="gdrive:1BxiMVs...")
```

### What NOT to do

- Do not base64-encode file content into API calls. The bytes would flow through
  the LLM's context window, burning tokens for transport instead of understanding.
- Do not loop over files calling the client manually when the CLI handles batching.
- Do not pass local file paths to the REST API directly — local paths are meaningless
  to the server. Use `client.ingest_file()` which handles upload automatically.
- Never display the JWT (or any auth credential) in terminal output, chat, or logs.

## When to use Ariadne instead of reading files directly

When you encounter a document — PDF, DOCX, PPTX, XLSX, or any supported format —
ingest it via the client package instead of trying to read the file directly. Three
reasons:

1. **Token efficiency.** The extracted Markdown is 8-15x smaller than raw content.
   A 40-page contract that would flood your context becomes a few thousand tokens of
   clean, structured text.

2. **Future searchability.** The document is chunked, embedded, and stored. Any future
   search by you or another agent can find it.

3. **Provenance.** Every ingestion is recorded — who asked, when, what model, why.
   Search results come with full history.

The only exception: very small plain text files (under ~10 pages) that you can handle
directly in context without extraction.

## Chunking

Chunking strategy is auto-selected by file type. You usually don't need to set it,
but you can override it with `chunking_config` if the auto selection isn't right.

**Auto-selection defaults:**

| File type | Strategy | Why |
|-----------|----------|-----|
| `.pptx` | `by_page` | Each slide is a self-contained unit |
| `.csv`, `.xlsx` | `fixed_size` | Tabular data has no heading structure |
| `.txt` with no headings | `fixed_size` with high overlap | No natural section breaks |
| Everything else | `by_title` | Most structured documents have section headings |

**Override example:**
```python
doc = client.ingest_file("report.pdf",
    collection="reports",
    chunking_config={
        "strategy": "fixed_size",
        "max_characters": 2500,
        "overlap": 400
    }
)
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

Before choosing, call `client.list_collections()` to see what already exists. If the
user's document fits an existing collection, use that one rather than creating a new
one with a slightly different name.

## Caller metadata

Every call should include caller metadata. The provenance trail is only useful if
you actually populate it.

- **`agent_type`**: Always set. `"claude-code"`, `"cursor"`, `"api"`, etc.
- **`initiated_by`**: Always set when you know the user. Format: `"user:name"`
  (e.g., `"user:denson"`).
- **`model`**: Always set. The model you're running on (e.g., `"claude-opus-4-6"`).
- **`agent_notes`**: Set on every call. Use the user's prompt or a brief description
  of why this action is being taken. This is the single most valuable provenance
  field — future agents and future searches see *why* this document was ingested,
  not just that it was.
- **`agent_id`**: Set when available. Your session ID or workflow identifier.
- **`agent_metadata`**: Set when there's structured context worth preserving
  (project ID, workflow stage, etc.).

Set defaults on the constructor and they apply to every call:

```python
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

**Example — good metadata on an ingest call:**
```python
doc = client.ingest_url("https://acme.example.com/legal/msa-2026.pdf",
    collection="acme-contracts",
    tags=["legal", "msa"],
    agent_notes="User uploaded Acme MSA and wants to find the termination clause",
    agent_metadata={
        "source_reference": "https://acme.example.com/legal/msa-2026.pdf",
        "intent": "compliance-review"
    }
)
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

A document with no recorded origin is unverifiable and uncitable. A corpus full of
unsourced documents is noise. Recording provenance at ingest time is the single
cheapest thing you can do to keep the corpus useful.

### Source-of-truth hierarchy (default)

Use the most authoritative source you have:

1. **DOI** — for research papers. Format `"doi:10.xxxx/..."`. Look in the document text and metadata.
2. **URL** — the original URL the document was downloaded from.
3. **Database / API reference** — a query, endpoint, or record ID.
4. **Local file path** — the original filesystem path.
5. **`"unknown"`** — explicit, with a `source_notes` explanation.

Project-specific skills (e.g., cannabis, legal, medical) may override this hierarchy
with stricter rules per document type. Follow the project skill's rules when one applies.

### Per-tier guidance

- **DOI** — search the first page or document metadata. Many papers have a DOI on page 1 or in the bottom-of-page footer.
- **URL** — record the **original URL the document came from**, not the server upload path. The server path is meaningless to a future agent; the source URL lets them re-fetch and verify.
- **Database / API** — record the query or endpoint that produced the document, e.g. `"pubmed:32168263"` or `"https://api.example.com/reports/2026-03"`.
- **Local file** — record the original path as context, e.g. `"file:///D:/research/2026/draft.pdf"`. If the path itself is meaningless out of context, also set `source_notes`.
- **Unknown** — explicit only. Set `"source_reference": "unknown"` AND a `source_notes` explanation. Never leave the field missing as a way to mean "I don't know".

### Explicit unknown beats missing

`"source_reference": "unknown"` with notes is fine. Missing `source_reference` is not.
The explicit value tells the next agent "this was considered" — a missing field tells
them "no one tried".

### When to ask

If provenance isn't obvious from the user's message or context, **ask before ingesting**:

> "Where did this document come from? A URL, a DOI, a database, or somewhere else?
> I want to record it so we can cite it later."

Asking once at ingest time is much cheaper than discovering six months from now that
you have a corpus of unsourced documents.

## Process: Ingesting a document

> **Single file or many files?** For bulk ingestion (more than 5 files, or a whole
> directory), skip this process and use the CLI: `ariadne ingest <path> --collection <name> --recursive`.
> For a single file, follow the steps below.

1. **Get the file URL or path** from the user's message or context.

2. **Determine provenance.** Decide what `source_reference` you'll record in
   `agent_metadata` (see Provenance section). If the user gave you a URL or DOI,
   that IS the provenance. If they handed you a local file with no context, ask
   them where it came from before ingesting — don't silently default to `"unknown"`.

3. **Choose a collection** using the decision tree above. Call `client.list_collections()`
   first to see what exists.

4. **Ingest the document** using the appropriate method:

   - URL: `client.ingest_url(url, collection=..., ...)`
   - Local file: `client.ingest_file(path, collection=..., source=..., ...)`
   - Bytes in context: `client.ingest_bytes(content, filename=..., collection=..., ...)`

   Include all caller metadata and the `source` parameter when you have provenance.

5. **Check the response.** The `Document` dataclass includes:
   - `document_id`: UUID for this document (use with `get_document` and search filters)
   - `source_file`: original filename
   - `title`: extracted or inferred document title
   - `markdown`: the full extracted Markdown text
   - `file_type`: detected file extension
   - `chunks_count`: how the document was broken up for search
   - `was_dedup_skip`: `true` means already ingested — tell the user
   - `warnings`: array of non-fatal issues. Relay these to the user.
   - `token_savings`: dict with `original_size`, `markdown_size`, `reduction_ratio`
   - `interactions`: present on dedup hits, shows who previously touched this document

6. **Handle errors:**
   - Zero-byte or corrupt file → tell the user the file appears damaged
   - Password-protected → tell the user to remove the password and retry
   - Unsupported format → tell the user which formats are supported
   - Image with no vision API → relay the warning, suggest configuring
     `ARIADNE_IMAGE_ENRICHMENT_API_KEY`
   - Embedding not configured → search won't work, tell the user an embedding API
     key is needed
   - Service unreachable → suggest checking deployment is running and URL is correct

7. **Tell the user what happened.** Which collection, how many chunks, whether it was
   a dedup skip. Keep it brief: "Processed acme-msa-2026.pdf into the acme-review
   collection (47 chunks). It's now searchable."

## Process: Searching documents

1. **Determine the search query.** Use the user's question directly, or extract the
   search intent from a broader request. "What did the Acme contract say about
   termination?" → query: `"termination clause"`.

2. **Scope the search** when context makes it obvious:
   - User mentions a collection → set `collection`
   - User mentions a specific file → use `filters={"source_file": "filename"}`
   - User mentions a file type → use `filters={"file_type": "pdf"}`
   - User mentions tags → use `filters={"tags": ["tag1", "tag2"]}`
   - User mentions a specific document ID → use `filters={"document_id": "uuid"}`
   - Combine filters when multiple constraints apply — they AND together

3. **Call search:**

   ```python
   results = client.search("termination clause",
       collection="acme-contracts",
       top_k=10,
       agent_notes="User wants to compare termination clauses across contracts"
   )
   ```

4. **Use interaction history to prioritize results.** Each search result includes an
   `interactions` array showing every agent that has touched that document — who
   ingested it, when, what model, and most importantly the `agent_notes` explaining
   *why*. Use this to decide which results matter most:
   - A document whose `agent_notes` say "User wants to find the termination clause"
     is more relevant to a termination question than one with higher vector similarity
     but unrelated provenance
   - A document ingested by `initiated_by: "user:denson"` is the user's own document
   - Multiple interactions from different agents signal an important document
   - The `agent_type` and `model` tell you how the document was processed and by whom

5. **Present results clearly.** For each relevant result:
   - The source document name and relevant section/page
   - The matching text
   - How it relates to the user's question
   - Don't just dump raw chunks — synthesize an answer from the results

6. **Follow up if needed.** If the user wants more detail on a specific document,
   call `client.get_document(document_id)`.

## Process: Browsing and managing documents

1. Call `client.list_collections()` to see what's available.
2. Call `client.list_documents(collection=...)` filtered by
   collection if the user asks. For richer queries (by tag,
   warnings status, or provenance) see the Query API section.
3. Present results as a navigable list — document name, collection, file type,
   when it was ingested.
4. If the user wants to see a specific document, call `client.get_document(document_id)`.

### Updating metadata after review

Use `client.update_document()` to annotate documents without re-processing:

```python
client.update_document(document_id,
    tags=["legal", "msa", "status:reviewed"],
    agent_metadata={
        "status": "reviewed",
        "findings": "3 key clauses: termination (S8), IP (S12), non-compete (S15)"
    }
)
```

This is a metadata-only update via `PATCH` — no re-extraction, re-chunking, or
re-embedding. Use it after reviewing a document to record what you found.

### Soft-delete and restore

Documents support soft-delete with a 48-hour recovery window:

```python
client.delete_document(document_id)     # soft-delete
client.restore_document(document_id)    # undo within 48h
client.delete_collection("old-project") # soft-delete all docs in collection
client.restore_collection("old-project") # restore collection within 48h
```

After 48 hours, deleted documents are permanently purged.

## Query API

For any question that involves counting, filtering, or grouping
documents in the corpus, use the Query API — not search. Search is
for content retrieval; the Query API is for corpus introspection.

### Start with `schema()`

When you're unsure what's available, call `client.schema()` first.
It returns the live registry of filters, includes, aggregatable
fields, and caps for this server — so you never have to guess.

```python
sch = client.schema()
print(sch.filters)              # {filter_name: description}
print(sch.aggregatable_fields)  # valid group_by values
print(sch.caps)                 # limits per request
```

### Filtering with `list_documents()`

`list_documents()` returns a `DocumentListPage` — iterable like a
list, plus pagination metadata on `total_count`, `total_is_exact`,
`limit`, `offset`.

Supported filters (combinable; all AND together):

| Param | Type | Behavior |
|---|---|---|
| `collection` | str | Exact collection match. |
| `file_type` | str | Exact file type (`.pdf` and `pdf` both accepted). |
| `tag` | str | Docs whose tag list contains this tag. |
| `has_warnings` | bool | `True` = only docs with >=1 warning; `False` = only clean docs. |
| `has_source_reference` | bool | `True` = `source_reference` (latest-wins from `agent_metadata`) is a non-empty string that isn't literally `"unknown"`. Indexed column, O(log n). |
| `include_deleted` | bool | Default False. |

Every row now carries `warnings_count` (int). Use it to spot
documents that need cleanup without paying to materialize the
`warnings` array on every row.

### Adding extra row fields with `include=`

By default `list_documents()` returns a lean row. Request extra
fields with `include=[...]`:

| `include` value | Adds |
|---|---|
| `"tags"` | Full tag list. |
| `"agent_metadata"` | Latest interaction's agent_metadata dict. |
| `"last_interaction"` | `{agent_notes, action, created_at}` of the latest interaction. |
| `"markdown"` | Full markdown body. Caps `limit` at 50. |

Example — find all papers that lack a DOI in their provenance:

```python
page = client.list_documents(
    tag="docty:paper",
    has_source_reference=False,
    include=["last_interaction", "agent_metadata"],
    limit=50,
)
for doc in page:
    print(doc.source_file, doc.warnings_count)
print(f"Total: {page.total_count} (exact={page.total_is_exact})")
```

### Counting with `aggregate()`

`aggregate()` groups by one field and counts, reusing all the same
filters as a WHERE clause. Much cheaper than paging the full list
client-side.

```python
# How many docs per collection?
resp = client.aggregate(group_by="collection")
for b in resp:
    print(b.group, b.count)

# How many warnings-laden PDFs per collection?
resp = client.aggregate(
    group_by="collection",
    file_type="pdf",
    has_warnings=True,
)
```

Valid `group_by` values: `collection`, `file_type`, `tags`. (Call
`schema()` to confirm — the server is the source of truth.) Grouping
by `tags` counts each distinct tag separately: a document with two
tags contributes +1 to each bucket.

### When filters don't fit

If your question can't be expressed with the filters above (e.g. a
date range, or a nested `agent_metadata` path), the Query API
deliberately doesn't hide the fallback: paginate `list_documents()`
with the `include=[...]` you need, filter client-side. `schema()`
returns a `brute_force_fallback` hint describing this. Date range
and JSON-path filters are listed under `schema().deferred` — not
planned for this release.

## When to search before answering

If the user asks a question that could be answered by documents they've previously
ingested, search first. Don't guess from memory.

Triggers for "search first":
- "What did [document] say about..."
- "Find that [thing] in my documents"
- "What do we know about X"
- "Search my docs for..."
- Any question where the answer is likely in a document the user previously uploaded

Use `client.list_collections()` first if you're not sure what's been ingested. If
there's nothing in the store, tell the user rather than guessing.

## Search filters reference (chunks via `/api/search`)

These filters apply to `client.search(...)` — chunk-level retrieval.
For document-level filtering see the Query API section above.

| Filter key | Type | Behavior |
|------------|------|----------|
| `collection` | string | Match chunks in this collection |
| `document_id` | string | Match chunks from a specific document |
| `source_file` | string | Substring match (case-insensitive) against filename |
| `file_type` | string | Exact match against extension (`.pdf` and `pdf` both accepted) |
| `tags` | list[str] | Match documents with any of the specified tags (OR logic) |

Unknown filter keys are silently ignored.

## Supported formats

Over 20 formats: PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV, HTML, TXT, Markdown, JSON,
XML, RTF, EPUB, EML, MSG, ZIP (recursive), Jupyter notebooks, RST, ORG, WAV, MP3, M4A.

Images (JPG, JPEG, PNG, GIF, WEBP) require a vision API key
(`ARIADNE_IMAGE_ENRICHMENT_API_KEY`) for content extraction. Without it, images are
accepted but produce empty output with a warning.

Not supported: scanned PDFs (no text layer), legacy .doc/.ppt, complex layouts with
merged cells, BMP/TIFF/HEIC.

## Notes

- Dedup is automatic. You don't need to check if a document was already ingested —
  just ingest it and the system handles it. Use `force=True` only when the user says
  the document content has changed.

- Tags are useful for filtering search results later. If the user mentions categories,
  topics, or labels, apply them as tags during ingestion.

- Search results include interaction history — which agents have previously touched
  each document. This context is useful when answering questions about document
  provenance or workflow history.

- Token efficiency matters. Always ingest through Ariadne before passing document
  content to an LLM. A 100-page PDF that would cost 50K-100K raw tokens is extracted
  to 5K-8K tokens of clean Markdown.

- All processing is synchronous. Ingest and search calls return the full result when
  they complete. There is no async job_id or polling pattern.
