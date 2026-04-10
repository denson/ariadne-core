# Audience: Evaluator — Understanding Fit and Tradeoffs

> **Note:** This file is a *seed angle* for the dynamic presenter, not a
> hard branch. The presenter may pull excerpts from here when a user's
> interests match this audience. It is also a fallback "standard tour" if
> the user explicitly asks for one (e.g. "give me the evaluator view"). See
> `SKILL.md` v2.0 for how the dynamic presenter works.


The person is exploring whether Ariadne Core is the right tool for their needs. They
want to understand architecture, costs, limitations, and how it compares to alternatives.
They're not ready to deploy yet — they're deciding. Respect that.

## What to emphasize

- What it does well and where it falls short (be honest about limitations)
- Cost model: hosting + API calls, nothing else
- What formats are supported and which aren't
- Architecture simplicity: one container, one database, one API key
- What it's NOT: not a document editor, not an OCR pipeline, not enterprise-scale

## Flow

### 1. What it does (the pipeline)

Walk through the seven-step pipeline at a conceptual level. They want to understand
the architecture, not deploy it.

-> **Show `img_02.png`** (The Extraction Pipeline) — walk along the conveyor belt, explain
each station briefly.

-> **`AskUserQuestion`**: *"What kinds of documents are you working with — mostly PDFs, or a mix of formats?"* Options: Mostly PDFs / Mix of formats / Not sure yet / Continue

Key points:
- Basic extraction is free via MarkItDown (MIT licensed) — but performs sub-optimally without API keys for vision-dependent content
- If you only need extraction, you can just install MarkItDown directly — Claude Code or any coding agent can set it up for you
- The only API costs are embedding (~$0.02/M tokens with OpenAI, cheaper or free with other providers) and vision (optional, ~$0.15/M tokens with OpenAI)
- Embedding is required for search to work — without it, the system only extracts
- Vision enrichment is optional — skip it if your documents don't contain images worth describing
- Dedup means you never pay twice for the same document
- Everything ends up in Postgres with pgvector — standard, queryable, backupable

### 2. Format coverage

-> **Show `img_07.png`** (Document Format Mosaic)

-> **`AskUserQuestion`**: *"Any formats in your workflow that you're worried about — scanned PDFs, legacy Office, something else?"* Options: Scanned PDFs / Legacy Office / All digital, should be fine / Continue

**Supported well:** PDF (text-layer), DOCX, PPTX, XLSX, CSV, HTML, XML, JSON, TXT,
Markdown, RTF, EPUB, EML, MSG, ZIP, Jupyter notebooks, WAV, MP3.

**Limitations (be honest):**
- Scanned PDFs with no text layer — poor results. MarkItDown can't do OCR. Managed/Team
  editions will add enhanced extraction to handle this.
- Legacy Office (.doc, .ppt) — not supported
- Complex tables with merged cells — heuristic, not ML layout detection
- BMP, TIFF, HEIC images — not supported
- Images need a vision API key for meaningful extraction

### 3. Architecture and deployment

-> **Show `img_03.png`** (Many Clients, One Service)

-> **`AskUserQuestion`**: *"What would be connecting to this — Claude Code, an agent framework like Open Brain, or something custom?"* Options: Claude Code / Agent framework / Custom system / Still deciding / Continue

Key architecture decisions to highlight:
- **Single container** — no workers, no Redis, no message queue. Processing is inline.
- **Single-port mode** — MCP and REST API share one HTTP port on Railway/Fly.io
- **API key auth** — one key controls all access. Not OAuth, not per-user auth.
- **Postgres for everything** — documents, chunks, vectors, provenance, API keys

This simplicity is intentional — it's a personal/single-user tool. It's not designed
for multi-tenant SaaS or enterprise scale.

-> **`AskUserQuestion`**: *"Is the single-container approach a fit for what you're evaluating, or are you looking for something more distributed?"* Options: Single container is fine / Need more scale / Still figuring that out / Continue

### 4. Cost breakdown

Be specific about costs:

| Component | Cost | Notes |
|-----------|------|-------|
| Hosting (Railway) | $0-5/mo | Free tier works for light use |
| Embedding API | ~$0.02/M tokens (OpenAI) | ~$0.001 per document. Cheaper/free with Groq, DeepSeek, local models |
| Vision API | ~$0.15/M tokens (OpenAI) | Only for images. Google Gemini, local models also work |
| Extraction | $0 | Free, no API calls (sub-optimal without vision API for image-heavy docs) |
| Database | Included | Railway Postgres plugin |

A personal library of hundreds of documents costs a few dollars total to process.

**Platform costs beyond API calls:** Railway and similar platforms charge for compute,
storage (Postgres disk), and data egress. For personal use this is minimal. If their
other systems (OpenClaw, Open Brain) run on the same platform, egress between services
is free or negligible — recommend co-locating for cost efficiency.

### 5. What it's NOT

Be clear about boundaries:
- **Not enterprise-scale** — designed for personal use, not thousands of users
- **Not multi-tenant** — one API key, one user. No per-user access control.
- **Not an OCR pipeline** — can't handle scanned documents well (yet)
- **Not a document editor** — it extracts and retrieves, doesn't modify
- **Not tied to any LLM vendor** — works with any OpenAI-compatible provider (OpenAI, Google Gemini, Groq, DeepSeek, Together AI, Mistral, Ollama, LM Studio, vLLM). Anthropic models work through OpenRouter or Bifrost. We plan to deploy custom open models in the future.

**Database scaling:** The Personal Edition uses Postgres with pgvector. This handles
personal libraries well — thousands of documents, hundreds of thousands of chunks. But
they'll eventually outgrow a single Postgres instance at scale. We're testing more
robust options for the managed editions — Pinecone, Snowflake, Qdrant, Weaviate Cloud.
We'll share findings for personal/professional users too. Be honest about this limit
but frame it as a known growth path, not a blocker.

-> **`AskUserQuestion`**: *"Any concerns about cost or scale for your use case, or does this pricing work?"* Options: Pricing works / Have concerns / Need to think about it / Continue

### 6. Comparison with alternatives

If they ask how it compares:

| Alternative | Difference |
|-------------|------------|
| LlamaIndex / LangChain | Ariadne Core is a deployed service, not a library. No code to write. |
| Pinecone / Weaviate Cloud | Ariadne Core handles extraction + chunking + embedding, not just vector storage |
| Azure Doc Intelligence | Ariadne Core is open source, self-hosted, and much cheaper |
| Enterprise doc platforms | Ariadne Core is simpler and cheaper (no local GPU required) but handles fewer edge cases. Managed/Team editions fill the gaps. |

### 7. If they're convinced

If they want to proceed, point them to:
- **Deploy:** The Railway deployment path (or hand off to **ariadne-core-deploy** skill)
- **Connect:** `claude mcp add` for Claude Code, REST API for agent systems
- **Learn:** The **ariadne-document-intelligence** skill for using the tools effectively

## What NOT to do

- Don't push them to deploy — they're evaluating, not committing
- Don't hide limitations — they'll find them anyway and lose trust
- Don't compare favorably to tools you don't know well
- Don't oversell the format support — be specific about what works and what doesn't
- Don't dive into deployment steps unless they ask
