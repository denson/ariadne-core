# Ariadne Document Intelligence Skill

Teaches AI agents how to use [Ariadne Core](https://github.com/nate-b-j/ariadne-core) — an open source document extraction and retrieval pipeline that converts files into clean Markdown and searchable vector embeddings.

## What this skill does

When an agent has this skill and Ariadne Core is connected via MCP, the agent knows how to:

- Ingest documents (single files or entire directories) into organized collections
- Search previously ingested documents with semantic search and filters
- Choose appropriate collections instead of dumping everything into "default"
- Include caller metadata for provenance tracking on every call
- Handle errors gracefully (corrupt files, missing API keys, unsupported formats)
- Bridge with Open Brain when available (summary thoughts that point back to Ariadne)

Without this skill, agents tend to try reading documents directly (wasting tokens), skip metadata, ignore collections, and miss the search-first pattern for recall questions.

## Requirements

- Ariadne Core running and connected via MCP (STDIO or Streamable HTTP)
- The six MCP tools available: `convert_document`, `search`, `get_document`, `list_documents`, `list_collections`, `ingest`

## Installation

Copy the `ariadne-document-intelligence/` directory into your agent's skills folder:

| Client | Skills location |
|--------|----------------|
| Claude Desktop (Cowork) | Project-level or via plugin |
| Claude Code | `.claude/skills/` in your project |
| Cursor | `.cursor/skills/` or equivalent |

## Supported formats

Over 20 formats including PDF, DOCX, PPTX, XLSX, CSV, HTML, TXT, Markdown, JSON, XML, RTF, EPUB, EML, MSG, ZIP, Jupyter notebooks, WAV, MP3, M4A. Images (JPG, PNG, GIF) require a vision API key for content extraction.

## Version

2.0.0 — Canonical skill replacing both the old `ariadne-core-integration` (v0.1.0) and the OB1-hosted `ariadne-document-intelligence` (v1.1.0).
