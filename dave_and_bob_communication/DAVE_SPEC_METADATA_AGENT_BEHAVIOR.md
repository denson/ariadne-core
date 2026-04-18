# Task: Update remaining sections — remove MCP references, update examples (Step 6)

**For:** Dave

---

## What to do

Update the remaining sections of `ariadne-core/SPEC.md` (everything after `## Document management` through the end of the file). The content in these sections is mostly good — the problem is MCP references that need to become REST API / client package references.

There are 6 specific changes. Do them all.

---

## Change 1: Caller metadata section (~line 805)

**Current first line:**
```
`convert_document`, `search`, and `ingest` accept these optional fields...
```

**Replace with:**
```
All document and search endpoints accept these optional fields for provenance tracking. Ingestion endpoints (`POST /api/documents`, `POST /api/ingest`) create a `document_interactions` row on every call, even dedup skips. `POST /api/search` creates a `search_log` row on every call.
```

The field table below it is fine — leave it.

---

## Change 2: Worked examples in Metadata Conventions (~lines 938–1095)

These four worked examples use MCP-style JSON payloads with `convert_document`, `uri`, etc. Rewrite them to use client package calls instead.

### Example 1 (single document, ~line 940): Replace the `convert_document` JSON block with:

```python
doc = client.ingest_file("acme-q1-2026-report.pdf",
    collection="acme-financials",
    tags=["financial", "q1-2026"],
    source="https://acme.com/investor-relations/q1-2026-report.pdf",
    agent_notes="User asked about revenue trends in Acme Q1 2026 quarterly report. Extracting for analysis.",
    agent_metadata={"intent": "research", "project": "acme-review"}
)
```

Update the surrounding text: change "The agent uploads the file, then calls `convert_document`:" to "The agent ingests the file:". Keep the rest of the narrative.

### Example 2 (batch ingest, ~line 964): Replace the `ingest` JSON block with:

```bash
ariadne ingest /data/contracts/ \
    --collection atlas-vendor-contracts \
    --tags legal,project:atlas,vendor \
    --recursive
```

Or via Python:

```python
# The CLI handles the batch; the agent sets metadata via env or config
```

Update "The agent calls `list_collections` first to see if a relevant collection exists, then calls `ingest`:" to "The agent checks existing collections, then ingests the directory:". Keep the rest.

### Example 3 (research session, ~line 990): Replace the search JSON blocks with:

**Step 1:**
```python
results = client.search("termination clause early exit penalty",
    collection="atlas-vendor-contracts",
    top_k=10,
    agent_notes="User comparing termination clauses across vendor contracts for Project Atlas.",
    agent_metadata={"intent": "research", "project": "atlas"}
)
```

**Step 3:**
```python
results = client.search("early termination penalty fee 30 days notice",
    collection="atlas-vendor-contracts",
    top_k=5,
    filters={"tags": ["vendor"]},
    agent_notes="Narrowing to specific penalty terms. 4 of 10 had relevant clauses.",
    agent_metadata={
        "intent": "research",
        "project": "atlas",
        "findings": "Termination clauses in Vendor A (S8), C (S12), D (S6.3), F (S9). Vendor B has none."
    }
)
```

Update "The agent calls `get_document`" to "The agent calls `client.get_document()`" in Step 2.

### Example 4 (multi-agent handoff, ~line 1036):

**Agent A:**
```python
doc = client.ingest_url("https://example.com/reports/safety-audit-2026.pdf",
    collection="compliance-audits",
    tags=["compliance", "safety", "2026"],
    agent_notes="Ingesting annual safety audit report. Downloaded from compliance portal.",
    agent_metadata={"intent": "archival", "status": "extracted"}
)
```

**Agent B:** Replace the `force: true` JSON block with:

```python
client.update_document(doc.document_id,
    tags=["compliance", "safety", "2026", "status:reviewed"],
    agent_metadata={
        "intent": "compliance-review",
        "status": "reviewed",
        "findings": "3 critical findings: fire suppression (S4), ventilation (S7), emergency exits (S11). All prior-year findings closed.",
        "related_documents": ["doc-uuid-prior-year-audit"]
    }
)
```

**Important:** Update the note after Agent B's block. The old note says `force: true` re-processes the entire document just to update metadata. The new version uses `update_document` which is a metadata-only update via `PATCH /api/documents/{id}` — no re-processing. Replace the old note with:

```
Note: `update_document` (PATCH) updates metadata without re-processing content — no re-extraction, re-chunking, or re-embedding. This is the efficient way to annotate after review.
```

---

## Change 3: Dedup section (~line 1106)

**Current:**
```
The `force` flag on `convert_document` and `ingest` overrides this...
```

**Replace with:**
```
The `force` flag on `POST /api/documents` and `POST /api/ingest` overrides this when you know a document has changed.
```

---

## Change 4: Provenance section — action table (~line 1119)

Replace the action table:

| Action | Source | Meaning |
|--------|--------|---------|
| `"convert"` | `POST /api/documents` | Agent deliberately processed a single document via URL or server-side path |
| `"ingest"` | `POST /api/ingest` | Document was swept up in a batch directory ingestion |
| `"search"` | `POST /api/search` (in `search_log`) | Query recorded in the search log |

---

## Change 5: Collections section (~line 1154)

This section is now redundant with the Document management > Collections subsection added in Step 5. **Delete the entire `## Collections` section** (lines ~1154–1158 plus the `---` before it). The content is already covered in Document management.

---

## Change 6: Expected agent behavior (~line 1179)

Rewrite this entire section. The current version references `convert_document` MCP tool throughout. Replace with:

```markdown
## Expected agent behavior

These patterns should be taught via the skill file and reinforced via Claude Code project instructions.

### When to use Ariadne instead of reading files directly

When the agent encounters a document (PDF, DOCX, PPTX, XLSX, or any supported format), it should ingest it via the client package instead of trying to read the file directly. The extracted Markdown is cleaner, more token-efficient (often 8-15x smaller than raw content), and gets stored for future search. The only exception is very small text files (under ~10 pages of plain text) where the agent can handle them in context without extraction.

### How to choose an ingestion method

1. **Document at a URL** → `client.ingest_url(url)` — server fetches directly, zero tokens
2. **Local file** → `client.ingest_file(path)` — client uploads, zero tokens
3. **Content already in context** (user dropped file in chat) → `client.ingest_bytes(content, filename)` — stores what the agent already has

Never pass raw file bytes through the LLM's context when you can avoid it. A 6 MB PDF as base64 is ~1.5-2M tokens of transport payload.

### How to choose a collection

The agent should never dump everything into `"default"`. Collection choice follows this logic:

1. If the user specifies a collection name, use it.
2. If the agent is working in a project context (a repo, a research topic, a client engagement), use the project name. Examples: `"ariadne-core"`, `"q4-research"`, `"acme-contract-review"`.
3. If the user is doing a one-off task with no clear project, use a descriptive name. Examples: `"receipts"`, `"reference-docs"`, `"meeting-notes"`.
4. If none apply, use `"default"` — but this should be rare.

The agent should tell the user which collection it chose and why, so the user can correct it or reuse it later.

### How to use caller metadata

Every call should include caller metadata. This is not optional in practice — the provenance trail is only useful if agents actually populate it.

- `agent_type`: always set. `"claude-code"`, `"cursor"`, `"api"`, etc.
- `initiated_by`: always set when user identity is known. Format: `"user:name"`.
- `model`: always set. The model the agent is running on.
- `agent_notes`: set on every call. The user's prompt or a brief description of why this action is being taken. This is the most valuable provenance field.
- `agent_id`: set when available. The session ID or workflow identifier.
- `agent_metadata`: set when there's structured context worth preserving.

When using the client package, set defaults on the constructor and they apply to every call:

```python
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-6"
)
```

### When to search before answering

If the user asks a question that could be answered by documents they've previously ingested ("what did the report say about...", "find that contract clause about..."), the agent should call `client.search()` before attempting to answer. Don't guess from memory — search first, then synthesize from results.

Use the `collection` parameter or `filters` to narrow search when the context makes it obvious.

### When to use batch vs. single ingestion

- Single file → `client.ingest_url()` or `client.ingest_file()`
- Directory of files → `ariadne ingest` CLI command (handles batching, progress, error recovery)
- The agent should tell the user how many files were found and give a time estimate before starting a large batch
```

---

## What NOT to change

- Sections 1-3 (approved)
- REST API section (approved)
- Client package section (committed)
- Configuration section (committed)
- Pipeline order section (committed)
- Ingestion section (committed)
- Search section (committed)
- Document management section (committed)
- Search Log section (fine as-is)

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.
