# Ariadne Core — Open Source Document Extraction & Retrieval Pipeline

> **⚠️ v1 runtime is Gemini-native.** Only Google Gemini is wired
> up out of the box. To use a different provider, fork the repo
> and modify the clients in `src/pipeline/`. See `SPEC.md` →
> "Provider constraints."

## Architecture Specification v0.3

**Project:** Open source document extraction and retrieval pipeline, deployable as a hosted service (Railway, Fly.io, or any Docker host). Designed for Claude Code, Open Brain, OpenClaw, or any MCP/REST API client.

**License:** Apache 2.0 (compatible with MarkItDown's MIT).

**Scope of this document:** The buildable architecture for Phase 1 MVP (document extraction + vector retrieval using MarkItDown). Phase 2 adds Unstructured integration for scanned/complex documents and a Web UI. Phase 3 (hypergraph reasoning) is referenced as a future extension but not specified here.

---

## What This Is

This is the open source, personal/SMB alternative to what enterprise vendors (Unstructured Platform + Pinecone, Azure Document Intelligence, etc.) sell to Fortune 500 companies. Same core capability — extract documents, store them in a vector database, retrieve what's relevant — but designed to run on your own hardware, for your own documents, at near-zero marginal cost.

The core philosophy: **expensive models like Claude Opus should spend their tokens on thinking, not on parsing PDFs.** This pipeline does the extraction work with cheap, fast methods — deterministic code, cheap API calls for embedding and image description — so that by the time an expensive model sees the content, it's clean Markdown and precisely scoped retrieval results.

### The Cost Stack

| Layer | What does the work | Cost | When it runs |
|-------|-------------------|------|-------------|
| **Free deterministic** | MarkItDown (pdfminer, pdfplumber, mammoth, python-pptx, csv parsers) | $0 | Every document |
| **Cheap API calls** | Embedding API, vision API for image descriptions (any OpenAI-compatible endpoint) | ~$0.001–0.01/doc | Every chunk (embedding), images needing description |
| **Expensive model (Opus, etc.)** | Reasoning, analysis, synthesis | Per-token | Never touches raw documents — only sees clean Markdown + retrieved chunks |

The core extraction pipeline runs with zero API calls — MarkItDown converts documents to Markdown using purely deterministic code. The only API calls are for embedding chunks and optionally describing images, both of which are cheap (~$0.001–0.01 per document).

The expensive model only enters the picture when a human or agent asks a question — and when it does, it gets 500 tokens of relevant context instead of 100,000 tokens of raw PDF binary.

### Target Users

- **Personal use:** Individual running Claude Code who processes documents regularly. Deploy on Railway's free tier — no local setup required.
- **Agentic systems:** Open Brain, OpenClaw, or any system that needs document memory. Connect via MCP with API key auth.

For enterprise scale (thousands of users, millions of documents, managed SLA), Unstructured's Platform + Pinecone/Weaviate Cloud is the right answer. This project is not competing at that tier — it's serving everyone below it who currently has nothing.

### What It Does

1. **Extracts** documents (20+ formats) into clean, token-efficient Markdown using MarkItDown
2. **Enriches** extracted content with image descriptions via vision API (any OpenAI-compatible endpoint)
3. **Chunks** documents into semantically coherent segments with metadata (section, page, source)
4. **Embeds** chunks using a configurable embedding API
5. **Stores** embeddings in a vector database for semantic retrieval
6. **Serves** extraction and retrieval via MCP tools and REST API

It is designed to work as:

- An MCP server that Claude Code or any MCP client can call during a conversation
- A REST API that batch pipelines and custom agents can hit
- A standalone service that any agentic system can integrate as its document memory layer

It is **not** tied to Open Brain (OB1), though an OB1 skill will teach agents how to connect the two systems.

---

## Design Principles

1. **Cheap extraction, expensive reasoning.** The pipeline maximizes what can be done with free, deterministic code. Embedding and image description are cheap API calls. The expensive model (Claude Opus, GPT-4, etc.) only sees clean output, never raw documents.

2. **Standalone first.** Runs without Open Brain, without Claude, without any specific LLM vendor. Exposes standard interfaces (MCP, REST) that anything can call.

3. **Simple stack, no local GPU required.** Phase 1 uses MarkItDown for extraction. No PyTorch, no CUDA in the container. Model inference (embedding, vision) is handled via API calls to any OpenAI-compatible provider, or with an open model on a local GPU. Phase 2 adds Unstructured for scanned/complex documents when needed (commercial deployments).

4. **Enrich what code can't handle.** After extraction, images embedded in documents are sent to a vision API for description. Any OpenAI-compatible endpoint works — swap by changing a URL and model name.

5. **Vector store is pluggable.** Default is pgvector (same Postgres that stores job metadata). Abstraction layer supports Qdrant, Weaviate, or Milvus as config changes, not rewrites.

6. **Designed for extension.** The architecture supports adding Unstructured as a second extraction engine (Phase 2), a Web UI (Phase 2), and hypergraph reasoning (Phase 3) without re-architecting. The processed document store, chunking metadata, and vector embeddings are structured so future services can consume them without re-processing source documents.

---

## System Overview

```
Railway / Fly.io / VPS
┌─────────────────────────────────────────────────────────────────┐
│                     ariadne-core container                     │
│                                                                 │
│  ┌──────────────┐   ┌──────────────────────────────────────┐   │
│  │  MCP Server   │   │  FastAPI Application                 │   │
│  │              │   │                                      │   │
│  │  Tools:       │   │  POST /api/upload                   │   │
│  │  convert      │   │  POST /api/documents                │   │
│  │  search       │   │  POST /api/search                   │   │
│  │  get_document │   │  GET  /api/documents/{id}           │   │
│  │  list         │   │  GET  /api/stats                    │   │
│  │  ingest       │   │  GET  /api/health                   │   │
│  │              │   │                                      │   │
│  │  Transport:   │   │  Auth: X-API-Key header             │   │
│  │  Streamable   │   │  (ARIADNE_API_KEY env var)          │   │
│  │  HTTP         │   │                                      │   │
│  └──────┬───────┘   └──────────┬───────────────────────────┘   │
│         │                      │                               │
│         └──────────┬───────────┘                               │
│                    │                                           │
│  ┌─────────────────▼───────────────────────────────────────┐   │
│  │                    MarkItDown                             │   │
│  │                                                         │   │
│  │  <100ms/doc, 20+ formats                                │   │
│  │  Plugin system (entry-point based)                      │   │
│  │  markitdown-ocr plugin for image extraction from docs   │   │
│  └─────────────────┬───────────────────────────────────────┘   │
│                    │                                           │
│  ┌─────────────────▼───────────────────────────────────────┐   │
│  │              Post-Processing Pipeline                    │   │
│  │                                                         │   │
│  │  1. Content fingerprint (SHA-256) — skip if collision   │   │
│  │  2. Image enrichment (vision API describes images)      │   │
│  │  3. Chunk (by_title, configurable)                      │   │
│  │  4. Embed (configurable API)                            │   │
│  │  5. Store in vector DB                                  │   │
│  │  6. Write processed files to ./data/processed/          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────┐  ┌──────────────────┐                        │
│  │  PostgreSQL  │  │  Local Storage   │                        │
│  │  + pgvector  │  │                  │                        │
│  │             │  │  ./data/incoming/ │                        │
│  │  Documents   │  │  ./data/processed/│                       │
│  │  Chunks      │  │  ./data/temp/    │                        │
│  │  Embeddings  │  │                  │                        │
│  │  Jobs        │  │                  │                        │
│  │  Metadata    │  │                  │                        │
│  └─────────────┘  └──────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
  MCP Server
     ▲  ▲  ▲  ▲
     │  │  │  └── Claude Cowork (Managed edition or roll your own OAuth)
     │  │  └───── OpenClaw
     │  └──────── Open Brain
     └─────────── Claude Code

Authentication is by API key for Personal edition and OAuth for Managed and higher
editions. You can also create your own OAuth for the Personal edition.
```

---

## Extraction Engine

Phase 1 uses MarkItDown exclusively. All documents go through the same path — no routing decision needed.

### Supported Formats

| Format | Extensions | Notes |
|--------|-----------|-------|
| PDF (text-layer) | .pdf | pdfminer + pdfplumber. Works for all modern, digitally-created PDFs. |
| Word (modern) | .docx | mammoth (DOCX → HTML → Markdown) |
| PowerPoint | .pptx | python-pptx. Chart data extracted as Markdown tables. |
| Excel | .xlsx, .xls | pandas + openpyxl |
| HTML | .html, .htm | BeautifulSoup + custom markdownify |
| CSV | .csv | stdlib csv module |
| EPUB | .epub | |
| Images | .jpg, .png | LLM vision via markitdown-ocr plugin (sends to vision API) |
| Audio | .wav, .mp3, .m4a | Google Speech Recognition API |
| Jupyter | .ipynb | |
| ZIP | .zip | Recursive extraction |
| XML/RSS/Atom | .xml | |
| Outlook | .msg | |
| YouTube | URLs | Transcript extraction |
| Wikipedia | URLs | |

### Limitations (Phase 1)

These document types are **not well-handled** by MarkItDown alone and are deferred to Phase 2 (Unstructured integration):

- **Scanned PDFs** — no text layer means no extraction. The `markitdown-ocr` plugin can send pages to a vision API as images, but this is expensive and slow compared to proper OCR + layout detection.
- **Legacy Office** (.doc, .ppt) — not supported by MarkItDown.
- **Complex layouts** — tables with merged cells, multi-column layouts, forms. MarkItDown uses heuristics, not ML layout detection.
- **BMP, TIFF, HEIC images** — not supported.

The install skill should warn users about these limitations and explain that Phase 2 will add support via Unstructured.

### Edge Cases

- **Zero-byte or corrupt files**: reject at intake with structured error
- **Very large files (>100MB)**: route to dedicated queue with extended timeout
- **Password-protected documents**: fail gracefully with clear error message

---

## Processing Pipeline

### Extraction Phase

MarkItDown produces native Markdown strings directly — no normalization step needed.

### Output Format

Every processed document produces two artifacts:

**Markdown file** (`{document_id}.md`):
```markdown
<!-- ariadne:document_id: 550e8400-e29b-41d4-a716-446655440000 -->
<!-- ariadne:source: quarterly-report-q4-2025.pdf -->
<!-- ariadne:pages: 47 -->
<!-- ariadne:engine: markitdown -->
<!-- ariadne:processed: 2026-04-03T14:22:00Z -->
<!-- ariadne:tokens_estimate: 5230 -->
<!-- ariadne:content_fingerprint: sha256:abc123... -->
<!-- ariadne:agent_id: cowork-session-abc123 -->
<!-- ariadne:collection: q4-research -->

# Q4 2025 Quarterly Report

## Executive Summary
Revenue grew 12% year-over-year to $4.2B...
```

**Metadata JSON** (`{document_id}.json`):
```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_file": "quarterly-report-q4-2025.pdf",
  "content_fingerprint": "sha256:abc123...",
  "file_type": "pdf",
  "pages": 47,
  "engine": "markitdown",
  "processing_time_ms": 1240,
  "output_tokens_estimate": 5230,
  "token_savings_ratio": 18.7,
  "provenance": {
    "agent_id": "cowork-session-abc123",
    "agent_type": "claude-cowork",
    "model": "claude-sonnet-4-6",
    "collection": "q4-research",
    "initiated_by": "user:denson",
    "processing_chain": [
      {
        "step": "extraction",
        "tool": "markitdown",
        "timestamp": "2026-04-03T14:22:00Z",
        "duration_ms": 1240
      },
      {
        "step": "image_enrichment",
        "tool": "gemini:gemini-2.0-flash",
        "timestamp": "2026-04-03T14:22:01Z",
        "images_processed": 3,
        "duration_ms": 2800
      },
      {
        "step": "embedding",
        "tool": "gemini:gemini-embedding-001",
        "timestamp": "2026-04-03T14:22:04Z",
        "chunks_embedded": 14,
        "duration_ms": 1100
      }
    ]
  },
  "chunks": [
    {
      "chunk_id": "...-chunk-001",
      "text": "Revenue grew 12%...",
      "section": "Executive Summary",
      "page": 1,
      "token_count": 340
    }
  ],
  "errors": [],
  "warnings": []
}
```

The `provenance` block is the key addition. Every document records *who* asked for it (agent identity), *what model* was involved, *which collection* it belongs to, and the full *processing chain* — each step with its tool, timestamp, and duration. Downstream consumers (OB1, other agents, analysis pipelines) can trace any artifact back to its source and understand exactly how it was derived.

### Image Enrichment

After extraction but before chunking, the pipeline enriches image content. MarkItDown's `markitdown-ocr` plugin can extract images from PDFs, DOCX, and PPTX and send them to a vision API, but this happens during extraction only if the plugin is enabled and an LLM client is configured. The post-processing pipeline provides a second pass to catch any images that weren't described during extraction.

```
For each image reference in the Markdown output:
  1. Check if image already has a text description (skip if yes)
  2. Extract the image data (base64)
  3. Send to vision API with extraction prompt
  4. Attach description to the Markdown output at the image's location
```

**Vision API options:**

| Option | Cost | Quality | Latency | Requirements |
|--------|------|---------|---------|-------------|
| gpt-4o-mini | ~$0.002/image | Good | ~1s | API key |
| gpt-4o | ~$0.01/image | Best | ~2s | API key |
| Any OpenAI-compatible API | Varies | Varies | Varies | Endpoint + key |

If no vision API is configured, images are preserved as-is in the Markdown (with any alt text MarkItDown extracted) but without semantic descriptions.

**Output format in Markdown:**
```markdown
![Image: Page 5, Figure 2](image_ref)

> **Image description:** Bar chart showing quarterly revenue from Q1 2024 to Q4 2025.
> Revenue increased from $3.1B to $4.2B over the period, with the strongest growth
> in Q3 2025 (+8% QoQ). The chart includes a dotted trend line projecting $4.5B for Q1 2026.
```

### Chunking

Documents are chunked after Markdown conversion and image enrichment. Default strategy uses section boundaries with these parameters:

```python
CHUNK_DEFAULTS = {
    "strategy": "by_title",
    "max_characters": 1500,       # ~375 tokens
    "new_after_n_chars": 1000,    # soft limit, prefer section breaks
    "overlap": 200,               # continuity between chunks
    "combine_under_n_chars": 200, # merge tiny sections
}
```

Each chunk inherits metadata: document ID, page number(s), section heading, element types. This metadata powers filtered retrieval.

**Chunking strategy is auto-selected by file type, then overridable per document or per collection.** The pipeline inspects the file type (and optionally the extracted Markdown structure) to pick a sensible default. The caller can always override via `chunking_config`.

Default strategy selection:

| File Type / Structure | Auto-Selected Strategy | Why |
|----------------------|----------------------|-----|
| `.pptx` | `by_page` | Each slide is a self-contained unit |
| `.csv`, `.xlsx` | `fixed_size` (row-aware) | Tabular data has no heading structure |
| `.txt`, `.md` with headings | `by_title` | Heading boundaries align with topic shifts |
| `.txt`, `.log` with no headings | `fixed_size` with high overlap (400 chars) | No natural section breaks; overlap preserves context |
| `.pdf`, `.docx` (default) | `by_title` | Most structured documents have section headings |

Tuning guidance by use case:

| Use Case | Adjustment | Why |
|----------|-----------|-----|
| Scientific papers | `by_title` with larger chunks (2500 chars) | Dense technical content needs more context per chunk |
| Legal contracts | `by_title` with section numbering preserved | Clause references matter for retrieval |
| Transcripts | `fixed_size` with high overlap (400 chars) | Conversational flow doesn't respect section breaks |

**Guidance for the calling LLM:** The MCP tools accept an optional `chunking_config` parameter to override the auto-selected strategy. A well-prompted agent can inspect the first page of extracted Markdown to confirm the auto-selection was appropriate, or the user can set a collection-level default that applies to all documents ingested into that collection.

### Embedding

**The embedding model is explicitly configurable.** There is no hard default — the system ships with a recommended starting point, but the model must be chosen based on the document corpus, language requirements, and hardware constraints.

Recommended starting point: `BAAI/bge-large-en-v1.5` (1024 dimensions, ~1.3GB) for English-language corpora.

| Model | Dimensions | Size | MTEB Score | Language | Notes |
|-------|-----------|------|-----------|----------|-------|
| bge-large-en-v1.5 | 1024 | 1.3GB | 63.55 | English | Recommended starting point for English |
| nomic-embed-text-v1.5 | 768 | 550MB | 62.28 | English | Smaller, faster, lower-cost alternative |
| e5-large-v2 | 1024 | 1.3GB | 62.20 | English | Microsoft, similar quality tier |
| bge-m3 | 1024 | 2.2GB | 61.80 | 100+ languages | Best choice for multilingual corpora |
| multilingual-e5-large | 1024 | 2.2GB | 60.55 | 100+ languages | Alternative multilingual option |

**Configuration:**
```
EMBEDDING_MODEL=gemini-embedding-001           # Model name
EMBEDDING_DIMENSIONS=1536                      # Must match chosen model
EMBEDDING_PROVIDER=google-gemini               # v1 runtime is Gemini-native
EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
EMBEDDING_API_KEY=${EMBEDDING_API_KEY}
```

**Why this matters for multi-language support:** If your documents include non-English content, you *must* switch to a multilingual embedding model (bge-m3, multilingual-e5-large, etc.). English-only models will produce poor retrieval quality for other languages.

> **Note:** When changing the embedding model, existing vectors must be re-embedded. The system tracks which model produced each embedding and will warn if a search query uses a different model than the stored vectors.

### Deduplication

**Hard requirement:** Every incoming document is hashed before any expensive processing begins. If the fingerprint already exists in the target collection, the pipeline skips extraction, chunking, and embedding — but still records the interaction. This is the first step in the post-processing pipeline, not the last.

Fingerprinting uses SHA-256 on normalized extracted text (lowercase, trimmed, collapsed whitespace). The hash is checked against the `(collection_id, content_fingerprint)` unique index on `documents`. On collision:

1. Skip all expensive processing (extraction, enrichment, chunking, embedding)
2. Insert a row in `document_interactions` recording who asked, when, and why — this is never skipped
3. Return the existing document record to the caller

This means the `documents` table is the single source of truth for content, while `document_interactions` captures every agent call regardless of whether the content was already known. When vector search returns a result, the API includes all interactions for that document — giving you the full picture of which agents, workflows, and users have touched it.

A `force` flag on the ingest/convert tools allows re-processing when the caller knows content has changed despite the same fingerprint (e.g., the source file was updated in place).

Dedup is scoped per collection — the same document can exist in multiple collections without conflict. This follows the pattern proven at 75K+ scale in OB1's import pipelines.

---

## Vector Store

### Default: pgvector

Same Postgres instance that stores job metadata, document records, and audit logs. Adding vector search eliminates a separate service from the stack.

SQL filtering alongside vector search is the key advantage: "find chunks similar to X where source_file = 'policy.pdf' AND date > '2025-01-01'" in a single query.

Scale ceiling: ~5M vectors with HNSW, covering 500K–1M documents.

### Abstraction Layer

```python
class VectorStore(Protocol):
    async def insert(self, chunks: list[Chunk]) -> None: ...
    async def search(
        self, query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None
    ) -> list[SearchResult]: ...
    async def delete(self, chunk_ids: list[str]) -> None: ...
    async def count(self, filters: dict | None = None) -> int: ...
```

Implementations: `PgVectorStore` (default), `QdrantStore`, `WeaviateStore`, `MilvusStore`.

Switching backends: `VECTOR_STORE_BACKEND=pgvector|qdrant|weaviate|milvus` in environment config.

### When to Switch

| Backend | When | Why |
|---------|------|-----|
| pgvector | Default, <5M chunks | No extra service, SQL filtering, standard Postgres ops |
| Qdrant | >5M chunks or dataset exceeds RAM | Memory-mapped vectors, integrated filtered HNSW |
| Weaviate | Hybrid search required (semantic + keyword) | Native BM25 + vector fusion in one query |
| Milvus | >50M chunks, Kubernetes available | Distributed scale-out |

---

## MCP Server

The primary interface for interactive LLM use. Extends MarkItDown's existing MCP server architecture.

### Transport

- **Streamable HTTP** — all clients connect over HTTPS. The MCP endpoint is at `/mcp`.

### Caller Metadata

Every tool accepts optional caller metadata. This is how provenance tracking works — the calling agent identifies itself, and the pipeline records that identity in `document_interactions`. This row is always created, even when the document is a dedup skip, so the provenance trail captures every agent that has touched a document.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| agent_id | string | no | Caller's identity (e.g., "code-project-abc", "ob1-agent-daily", "api-key:research-bot") |
| agent_type | string | no | Client type: "claude-code", "ob1", "openclaw", "cursor", "api", "cli", etc. |
| model | string | no | The LLM model the caller is running (e.g., "claude-sonnet-4-6"). Useful for tracing which model initiated the processing. |
| collection | string | no | Logical grouping for the documents (e.g., "q4-research", "onboarding-docs", "daily-capture"). Acts as a namespace for search and organization. |
| initiated_by | string | no | Human or system identity (e.g., "user:denson", "cron:nightly-ingest") |

If not provided, the server infers what it can from the connection context (API key name, MCP client headers) and defaults the rest. The `collection` parameter is particularly important — it's how different agents and workflows keep their documents organized without stepping on each other.

### Tools

**`convert_document`**
Convert a document to clean Markdown optimized for LLM consumption.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| uri | string | yes | file://, http://, https://, or data: URI |
| store | boolean | no | If true (default), also chunk, embed, and store in vector DB |
| collection | string | no | Collection to store in (default: "default") |
| tags | array | no | Tags to apply to the document |
| force | boolean | no | If true, re-process even if fingerprint matches an existing document (default: false) |

Returns: Markdown string + metadata (engine, pages, processing_time, token_savings_ratio, provenance)

For large documents (estimated >30s processing): returns immediately with a job_id. Client polls via `get_document(job_id)`.

**`search`**
Semantic search over the document knowledge store.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | yes | Natural language query |
| top_k | integer | no | Number of results (default 5, max 20) |
| collection | string | no | Limit search to a collection (default: search all) |
| filters | object | no | source_file, date_range, file_type, tags, agent_id, agent_type |

Returns: JSON with top-level keys `query`, `top_k`, `collection`, `results_count`, and `results` array. Each result includes `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, and `interactions` (array of all `document_interactions` for the source document, so the caller sees which agents have previously touched the result).

**`get_document`**
Retrieve the full processed Markdown for a specific document.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| document_id | string | yes* | Internal document ID |
| source_file | string | yes* | Original filename (alternative to document_id) |

*One of document_id or source_file required.

**`list_documents`**
List all documents in the knowledge store.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| page | integer | no | Page number (default 1) |
| per_page | integer | no | Results per page (default 50) |
| collection | string | no | Filter to a collection |
| filters | object | no | file_type, date_range, tags, agent_id, agent_type |

**`ingest`**
Trigger batch ingestion of a directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | yes | Directory path to ingest |
| recursive | boolean | no | Process subdirectories (default true) |
| file_types | array | no | Filter to specific extensions |
| collection | string | no | Collection to store in (default: "default") |
| output_dir | string | no | If set, also write .md + .json files to this directory (the "directory of markdown" use case) |
| force | boolean | no | If true, re-process documents even if fingerprints match (default: false) |

Returns: job_id, files_found, estimated_time.

---

## REST API

Same functionality as MCP tools, for batch pipelines and custom integrations.

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/documents | Submit single document |
| POST | /api/documents/batch | Submit batch job |
| GET | /api/documents/{id} | Get processed result (includes full provenance) |
| GET | /api/jobs/{id} | Batch job status + progress |
| POST | /api/search | Semantic search (filterable by collection, agent, date) |
| POST | /api/ingest | Trigger directory ingestion |
| GET | /api/collections | List collections |
| POST | /api/collections | Create a collection |
| GET | /api/stats | Queue depth, throughput, storage per collection |
| GET | /api/health | Health check (no auth) |

Auth: API key in `X-API-Key` header. Keys stored hashed in Postgres. The key's `name` field is used as the `agent_id` in provenance tracking.

All POST endpoints accept the caller metadata fields (`agent_id`, `agent_type`, `model`, `collection`, `initiated_by`) in the request body. If not provided, they're inferred from the API key and connection context.

---

## Image Understanding

Image understanding is handled by the image enrichment step in the post-processing pipeline (see "Image Enrichment" under Processing Pipeline above).

Two mechanisms work together: MarkItDown's `markitdown-ocr` plugin can describe images during extraction (if enabled), and the post-processing pipeline catches any remaining images afterward. Both use the same vision API configuration.

Key points:

- **API calls.** Vision API calls (gpt-4o-mini at ~$0.002/image, or any OpenAI-compatible endpoint) are cheap and fast. A 50-page document with 10 images costs about $0.02 to enrich.
- **Not locked to any vendor.** Any OpenAI-compatible vision API works — OpenAI, Anthropic, Groq, Together, etc. Swap by changing a URL and model name.
- **Optional.** Without a vision API configured, the pipeline still works — images are preserved in the Markdown but without semantic descriptions.

**Future: MCP Sampling.** When MCP clients support the `sampling/createMessage` protocol feature, the image enrichment step could delegate vision calls to the client's model instead of needing its own. Not a priority until Claude Code implements it.

---

## Configuration

The container reads a single YAML config file mounted at `/config/ariadne.yaml`. This is the primary way users configure the system — API keys, model choices, paths, and all behavioral settings live here. Environment variables can override any config value (for CI/CD, secrets injection, etc.), but the config file is the source of truth for human-readable setup.

### Config File

```yaml
# /config/ariadne.yaml — mount this into the container

# --- Database ---
database:
  url: ${DATABASE_URL:-postgresql://app:${DB_PASSWORD}@localhost:5432/pipeline}

# --- Vector Store ---
vector_store:
  backend: pgvector       # pgvector | qdrant | weaviate | milvus
  # qdrant_url: http://qdrant:6333  # only if backend: qdrant

# --- Embedding ---
embedding:
  model: gemini-embedding-001
  dimensions: 1536
  provider: google-gemini
  base_url: https://generativelanguage.googleapis.com/v1beta
  api_key: ${EMBEDDING_API_KEY}

# --- Image Enrichment (Vision) ---
image_enrichment:
  enabled: true
  provider: google-gemini
  base_url: https://generativelanguage.googleapis.com/v1beta
  model: gemini-2.0-flash
  api_key: ${VISION_API_KEY}
  prompt: "Describe this image in detail. Include any text, data, charts, diagrams, or visual elements. Be specific about numbers, labels, and relationships shown."

# --- MarkItDown ---
markitdown:
  enable_plugins: true      # enables markitdown-ocr plugin for image extraction
  # llm_client configured automatically from image_enrichment settings above

# --- Chunking ---
chunking:
  default_strategy: by_title
  max_characters: 1500
  new_after_n_chars: 1000
  overlap: 200
  combine_under_n_chars: 200

# --- API Server ---
api:
  host: 0.0.0.0
  port: 8000
  mcp_port: 8000            # same as port for single-port mode on Railway
  # Auth controlled by ARIADNE_API_KEY env var

# --- Paths ---
paths:
  incoming: ./data/incoming
  processed: ./data/processed
  temp: ./data/temp

# --- Logging ---
logging:
  level: info               # debug | info | warning | error
  format: json              # json | text
```

### Config Resolution Order

Values are resolved in this order (later wins):

1. Built-in defaults
2. `/config/ariadne.yaml` (the config file)
3. Environment variables (mapped as `ARIADNE_SECTION_KEY`, e.g., `ARIADNE_EMBEDDING_MODEL`)

This means secrets like API keys can live in the config file for local use, or be injected via environment variables in production (Docker secrets, Kubernetes secrets, etc.) without touching the config file.

### `${VAR}` Interpolation

The config file supports `${VAR}` syntax for referencing environment variables. This is the recommended pattern for secrets: keep the config file in version control with `${VISION_API_KEY}` placeholders, and supply the actual values via `.env` or a secrets manager.

### Environment Variables (Railway / Production)

On Railway, set these environment variables. `DATABASE_URL` is provided automatically by the Postgres plugin.

```bash
# Required
EMBEDDING_API_KEY=sk-...
VISION_API_KEY=sk-...
ARIADNE_API_KEY=your-secret-key    # clients authenticate with this

# Optional overrides
# EMBEDDING_MODEL=gemini-embedding-001
# VISION_MODEL=gemini-2.0-flash
```

For local development, copy `.env.example` to `.env` and set `DB_PASSWORD` for the local Postgres container.

---

## Deployment

Ariadne Core deploys as a single Docker container. Postgres is provisioned separately (as a Railway plugin, Fly.io Postgres, or standalone). No local GPU required — model inference is via API calls, or with an open model on a local GPU.

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*
COPY src/pyproject.toml src/
COPY src/pipeline/ src/pipeline/
RUN pip install --no-cache-dir ./src/
COPY config/ config/
COPY migrations/ migrations/
ENV PORT=8000
EXPOSE 8000
CMD ["ariadne-core", "serve"]
```

The image is lightweight — MarkItDown + its dependencies, FastAPI, and the processing pipeline. No PyTorch, no CUDA, no multi-GB model weights. Embedding and image description are API calls to whatever endpoint the user configures.

### Single-port mode

On Railway (and similar platforms that expose one port), set `MCP_PORT` equal to `PORT`. The MCP Starlette app is mounted inside FastAPI at the root, and both share the same HTTP port. The MCP endpoint is at `/mcp`, REST API at `/api/*`.

### Authentication

When `ARIADNE_API_KEY` is set, all endpoints except `/api/health` require a valid `X-API-Key` header. The key is hashed and stored on startup. `MCPAuthMiddleware` gates `/mcp` requests; FastAPI dependency injection gates `/api/*` requests.

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2+ cores | 4+ cores |
| RAM | 4GB | 8GB |
| Storage | 20GB SSD | 50GB SSD |
| GPU | None | None |
| OS | Any (Docker) | Any (Docker) |

---

## Database Schema

### Design: Agent-Based Tenancy

The traditional multi-tenant model uses `tenant_id` to mean "organization." That works for SaaS but doesn't fit a system where the important question is "which agent or workflow produced this, and for what purpose?"

Ariadne Core uses two dimensions for partitioning:

- **`collection`** — a logical namespace for documents. "q4-research", "onboarding-docs", "daily-capture", "project-alpha". Collections are how different workflows and purposes stay organized. An OB1 agent's daily capture goes into one collection. A Claude Code project researching a topic goes into another. Search can span collections or be scoped to one.
- **`agent_id`** (on `document_interactions`) — the identity of whatever touched the document. A Claude Code session, an OB1 agent, a cron job, an API key. Every agent call creates an interaction row, even if the document was already processed (dedup skip). This is for provenance, not access control — you can always see everything, but you can ask "what did agent X do?"

For organizational multi-tenancy (the Fortune 50 case), add `org_id` via row-level security on top of this. The schema is ready for it but doesn't enforce it in Phase 1.

### Core Tables

```sql
-- Collections: logical namespaces for documents
CREATE TABLE collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,           -- "q4-research", "daily-capture", etc.
    description TEXT,
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',  -- for future multi-org
    created_by TEXT,                     -- agent_id that created the collection
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Seed the default collection
INSERT INTO collections (name, description) VALUES ('default', 'Default collection');

-- Documents table: one row per unique document per collection (content is king)
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID REFERENCES collections(id) DEFAULT (
        SELECT id FROM collections WHERE name = 'default'
    ),
    source_file TEXT NOT NULL,
    content_fingerprint TEXT,            -- SHA-256 of normalized text; the dedup key
    file_type TEXT NOT NULL,
    pages INTEGER,
    engine TEXT NOT NULL DEFAULT 'markitdown',
    processing_time_ms INTEGER,
    output_tokens_estimate INTEGER,
    token_savings_ratio REAL,
    markdown_path TEXT,
    tags TEXT[] DEFAULT '{}',
    processing_chain JSONB DEFAULT '[]', -- ordered list of processing steps with timestamps
    -- Metadata
    metadata JSONB DEFAULT '{}',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Document interactions: one row per agent call, even on dedup collision
-- This is the provenance record — who touched this document, when, and why
CREATE TABLE document_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES collections(id),  -- denormalized for fast queries
    agent_id TEXT,                       -- "cowork-session-abc", "ob1-agent-daily", etc.
    agent_type TEXT,                     -- "claude-cowork", "claude-code", "ob1", "api", "cli"
    model TEXT,                          -- "claude-sonnet-4-6", null for CLI/cron
    initiated_by TEXT,                   -- "user:denson", "cron:nightly-ingest"
    action TEXT NOT NULL DEFAULT 'ingest', -- "ingest", "re-ingest", "search", "retrieve"
    was_dedup_skip BOOLEAN DEFAULT false, -- true if content was already processed
    metadata JSONB DEFAULT '{}',         -- caller-supplied context (project, purpose, etc.)
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Chunks table with vector embeddings
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES collections(id),  -- denormalized for fast filtered search
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    section TEXT,
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER,
    embedding_model TEXT,                -- tracks which model produced this embedding
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- HNSW index for vector search
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Fast lookups by collection (most common search pattern)
CREATE INDEX idx_chunks_collection ON chunks (collection_id);
CREATE INDEX idx_documents_collection ON documents (collection_id);

-- Interaction queries: "what did agent X do?" / "who has touched this document?"
CREATE INDEX idx_interactions_document ON document_interactions (document_id);
CREATE INDEX idx_interactions_agent ON document_interactions (agent_id);
CREATE INDEX idx_interactions_agent_type ON document_interactions (agent_type);
CREATE INDEX idx_interactions_collection ON document_interactions (collection_id);

-- Content fingerprint dedup (scoped to collection — same doc can exist in multiple collections)
CREATE UNIQUE INDEX idx_documents_fingerprint
    ON documents (collection_id, content_fingerprint)
    WHERE content_fingerprint IS NOT NULL;

-- Jobs table
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,                  -- 'single', 'batch', 'ingest'
    status TEXT NOT NULL DEFAULT 'queued',
    collection_id UUID REFERENCES collections(id),
    agent_id TEXT,
    agent_type TEXT,
    initiated_by TEXT,
    total_files INTEGER DEFAULT 0,
    completed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- API keys
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,                  -- used as agent_id when calling via API
    default_collection TEXT,             -- optional default collection for this key
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    rate_limit_per_minute INTEGER DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
```

### How Collections Work

Collections are cheap to create and serve as the primary organizing principle:

- A Claude Code project researching competitors creates collection "q4-competitive-analysis" and ingests documents into it
- An OB1 agent running nightly capture uses collection "ob1-daily"
- A CLI batch import of your Downloads folder goes into collection "personal-archive"
- Search defaults to all collections but can be scoped: "search collection:q4-competitive-analysis for pricing strategies"

The same document can exist in multiple collections (the fingerprint dedup is scoped per collection). This is intentional — a quarterly report might be relevant to both "q4-research" and "board-prep" without duplicating storage (chunks reference the same document row).

When a document is ingested by a second agent and the fingerprint matches, the system creates a new `document_interactions` row (with `was_dedup_skip = true`) but reuses the existing document and chunks. This means the provenance trail grows with every agent that touches the document, while the expensive extraction/embedding work happens only once.

### Provenance: Two Layers

Provenance is split across two tables, each answering a different question:

**`documents.processing_chain`** answers "how was this content processed?" — an append-only JSONB list of technical steps:

```json
[
  {"step": "extraction", "tool": "markitdown", "ts": "2026-04-03T14:22:00Z", "ms": 1240},
  {"step": "image_enrichment", "tool": "gemini:gemini-2.0-flash", "ts": "2026-04-03T14:22:01Z", "ms": 2800, "images": 3},
  {"step": "embedding", "tool": "gemini:gemini-embedding-001", "ts": "2026-04-03T14:22:04Z", "ms": 1100, "chunks": 14}
]
```

**`document_interactions`** answers "who has touched this document?" — one row per agent call:

```
document_id | agent_id              | agent_type     | action  | was_dedup_skip | created_at
------------|-----------------------|----------------|---------|----------------|--------------------
abc-123     | cowork-session-7f2    | claude-cowork  | ingest  | false          | 2026-04-03T14:22:00Z
abc-123     | ob1-agent-nightly     | ob1            | ingest  | true           | 2026-04-04T02:00:00Z
abc-123     | code-project-ariadne  | claude-code    | retrieve| false          | 2026-04-04T09:15:00Z
```

When vector search returns a chunk, the API response includes the document record plus all its interactions. This lets any consumer answer "who else has used this document?" without a second query.

If a downstream agent (OB1, a summarizer, a classifier) adds derived data, it appends to `processing_chain` via the REST API and also creates an interaction row. The chain is append-only — you can always trace forward from source file to any derived artifact.

### Scaling Path

For a single user, this schema handles hundreds of thousands of documents comfortably in Postgres. For organizational scale:

- Add `org_id`-based row-level security (RLS) for true multi-tenancy
- Partition `chunks` by `collection_id` if any single collection exceeds millions of chunks
- Switch to Qdrant or Milvus for vector search if pgvector HNSW becomes the bottleneck (see Vector Store section)

---

## Performance Expectations

Estimates based on comparative analysis. Actual numbers require benchmarking.

### Processing Throughput

| Document Type | Est. Time | Notes |
|---------------|-----------|-------|
| Text PDF (10 pages) | <1s | pdfminer + pdfplumber, no API needed |
| Text PDF (100 pages) | 2-5s | Linear with page count |
| DOCX (20 pages) | <1s | mammoth conversion |
| PPTX (30 slides) | 1-3s | Chart extraction included |
| XLSX (10 sheets) | <1s | pandas + openpyxl |
| HTML page | <1s | BeautifulSoup |
| Image (JPG/PNG) with vision API | 1-2s | Depends on API latency |

Plus ~0.5-1s per chunk for embedding API calls (parallelizable).

### Token Savings

| Format | Raw Tokens (est.) | Processed Tokens | Savings |
|--------|-------------------|-----------------|---------|
| PDF (text, 10 pages) | 50,000–100,000 | 5,000–8,000 | 8–15x |
| DOCX (20 pages) | 30,000–60,000 | 8,000–12,000 | 4–6x |
| PPTX (30 slides) | 40,000–80,000 | 6,000–10,000 | 5–10x |

### Vector Search Latency

| Corpus Size (chunks) | pgvector HNSW | Qdrant |
|---------------------|---------------|--------|
| 10,000 | <10ms | <5ms |
| 100,000 | <20ms | <10ms |
| 1,000,000 | <50ms | <20ms |

Plus embedding API latency for the query (~0.1-0.5s).

---

## Extension Points

### Unstructured Integration (Phase 2)

Phase 2 adds Unstructured as a second extraction engine behind a smart router. This enables: scanned PDF processing (OCR + ML layout detection), legacy Office format support (.doc, .ppt), complex table structure detection, and form extraction. The router probes PDF text layers to decide which engine handles each document — MarkItDown for clean digital docs, Unstructured for everything else.

Phase 2 also adds a GPU worker service, Ollama for optional local models, and the two-compose-file deployment model (CPU vs GPU). This complexity is appropriate for commercial SMB deployments where we install and configure the system. The architecture is designed so Unstructured plugs in alongside MarkItDown without changing the post-processing pipeline, vector store, MCP tools, or REST API.

### Web UI (Phase 2)

A browser-based interface for document upload, search, and management. React + Tailwind, served from the same Docker stack.

### Hypergraph Reasoning (Phase 3)

The processed document store is structured to support future graph construction:

- Every chunk carries section, page, and element-type metadata enabling relationship extraction
- The metadata JSON includes structural element information (titles, tables, lists) that graph construction can consume without re-parsing
- Embedding vectors are reusable for semantic node deduplication during graph merging

Phase 3 is a separate deployment that reads from the same data store. See the PRefLexOR and Graph-PReFLexOR papers in `/references/` for the theoretical foundation.

### OB1 Integration

Open Brain connects to Ariadne Core via MCP, the same way all other clients do. OB1 agents use `agent_type: "ob1"` for provenance tracking. REST API is also available for scripts and automation.

The pipeline itself has no OB1 dependency. OB1 agents call the same MCP tools as any other client.

### Custom Converters

MarkItDown's plugin system (entry-point based) allows custom converters:

1. Write a Python class implementing `DocumentConverter` (accepts/convert methods)
2. Register via `pyproject.toml` entry point: `markitdown.plugin`
3. Plugin loads automatically when `enable_plugins=True`

This is the extension mechanism for domain-specific document formats.

---

## Project Structure

```
ariadne-core/
├── README.md
├── LICENSE
├── Dockerfile                  # Production container
├── docker-compose.yml          # Postgres for local dev
├── .env.example
├── config/
│   └── ariadne.yaml            # Main config file
├── src/
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── __main__.py        # CLI entrypoint (serve command)
│   │   ├── pipeline.py        # Extract → enrich → chunk → embed → store
│   │   ├── mcp_server.py      # MCP tool definitions
│   │   ├── config.py          # Config file + env var loader
│   │   ├── api/
│   │   │   ├── app.py         # FastAPI application + MCP auth middleware
│   │   │   ├── routes.py      # REST endpoints (including /api/upload)
│   │   │   └── auth.py        # API key store and verification
│   │   ├── extraction/
│   │   │   └── markitdown.py  # MarkItDown wrapper
│   │   ├── enrichment/
│   │   │   ├── images.py      # Image enrichment post-processing
│   │   │   └── vision.py      # Vision API client (any OpenAI-compat)
│   │   ├── chunking/
│   │   │   └── chunker.py     # Chunking strategies
│   │   ├── embedding/
│   │   │   └── embedder.py    # Embedding API client
│   │   └── storage/
│   │       ├── base.py        # VectorStore protocol
│   │       ├── pgvector.py
│   │       ├── qdrant.py
│   │       └── weaviate.py
│   └── pyproject.toml
├── migrations/
│   └── 001_initial.sql        # Database schema (auto-applied on startup)
├── tests/
├── benchmarks/
└── docs/
```

---

## Build Sequence

Priority-ordered steps to reach a deployable MVP:

| Step | What | Est. Effort | Dependencies |
|------|------|------------|--------------|
| 1 | MarkItDown wrapper + MCP server (convert_document only) | 3 days | MarkItDown |
| 2 | Image enrichment via vision API | 2 days | Step 1 |
| 3 | Chunking + embedding API + pgvector storage + search | 3 days | Step 2 |
| 4 | FastAPI application + REST endpoints + Postgres schema | 1 week | Step 3 |
| 5 | Config file loader + .env support | 2 days | Step 4 |
| 6 | Docker Compose + Dockerfile | 2 days | Steps 1-5 |
| 7 | Benchmarking against 30+ real documents | 3 days | Step 6 |
| 8 | OB1 skill (SKILL.md + README + metadata.json) | 2 days | Step 6 |

**Estimated time to deployable MVP: 3-4 weeks.**

---

## Open Questions

*Resolved decisions are noted inline. Remaining open items need answers before or during implementation.*

### Resolved

- **Project name:** Ariadne Core. PyPI package: `ariadne-core`. Docker image: `ariadne-core`. CLI command: `ariadne`.
- **License:** Apache 2.0.
- **Phase 1 extraction engine:** MarkItDown only. No Unstructured. No local GPU required — API keys or an open model on a local GPU needed for full performance. Keeps the stack simple and the Docker image small. Handles all clean digital documents well.
- **Unstructured:** Deferred to Phase 2 (commercial). Added behind a smart router for scanned PDFs, legacy Office, complex layouts. Installed by us for SMB customers.
- **Embedding model:** Explicitly configurable, not hardcoded. Recommended starting point is bge-large-en-v1.5 for English. Multilingual corpora require bge-m3 or similar. See Embedding section.
- **Chunking strategy:** Auto-selected by file type (`.pptx` → `by_page`, `.csv`/`.xlsx` → `fixed_size`, everything else → `by_title`), overridable per document or per collection. See Chunking section.
- **Web UI:** Phase 2.
- **Graph data format:** Phase 3.

### Still Open

1. **Embedding re-indexing workflow.** When a user changes their embedding model, all existing vectors become incompatible. Need a migration tool or CLI command that re-embeds the corpus incrementally without downtime.

2. **Scanned PDF fallback in Phase 1.** MarkItDown's `markitdown-ocr` plugin can send full PDF pages to a vision API as images, which works but is expensive and slow. Should Phase 1 offer this as an explicit opt-in for users who occasionally hit a scanned document, with clear cost warnings?

4. **MCP Sampling.** When MCP clients support `sampling/createMessage`, the image enrichment step could delegate to the client's model. Not a priority until Claude Code implements it.

5. **Benchmark dataset.** Need a representative set of 30+ real documents (text PDFs, DOCX, PPTX, XLSX, HTML, mixed content) for build step 7.
