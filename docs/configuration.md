# Configuration Reference

Ariadne Core uses a single config file (`ariadne.yaml`) plus environment variables. This document explains every option.

## How configuration works

Three layers, applied in order (later layers override earlier ones):

1. **Built-in defaults** — reasonable starting values baked into the code
2. **Config file** (`ariadne.yaml`) — your settings, with `${VAR}` interpolation for secrets
3. **Environment variables** — override any config value directly (e.g., `PORT`, `DATABASE_URL`, `ARIADNE_API_KEY`)

The config file lives at `config/ariadne.yaml` in the repo and is baked into the Docker image at build time.

## Environment variables

On Railway (or any hosting platform), set environment variables directly. Railway provides `DATABASE_URL` automatically via the Postgres plugin.

Required variables:

| Variable | What it is | Where to get it |
|----------|-----------|-----------------|
| `EMBEDDING_API_KEY` | API key for the embedding model | Any OpenAI-compatible provider (OpenAI, Gemini, Groq, DeepSeek, Together AI, etc.) |
| `VISION_API_KEY` | API key for the vision model (image descriptions) | Same provider key works, or use a different provider |
| `ARIADNE_API_KEY` | API key for client authentication | Pick any strong secret |

Optional overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (from Postgres plugin) | Postgres connection string |
| `PORT` | `8000` | HTTP port (Railway sets this) |
| `MCP_PORT` | (from config) | MCP port. Set equal to `PORT` for single-port mode on Railway |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model name |
| `EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | Embedding API endpoint |
| `VISION_MODEL` | `gpt-4o-mini` | Vision model name |
| `VISION_BASE_URL` | `https://api.openai.com/v1` | Vision API endpoint |

`EMBEDDING_API_KEY` and `VISION_API_KEY` can use the same key if you use the same provider for both. They work with any OpenAI-compatible provider — see [Compatible providers](../README.md#compatible-providers).

## Config file reference

Below is the full `ariadne.yaml` with every option explained.

### database

Connection to the Postgres database (with pgvector extension).

```yaml
database:
  url: ${DATABASE_URL:-postgresql://app:${DB_PASSWORD}@localhost:5432/pipeline}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `url` | string | (see above) | Postgres connection string. On Railway, `DATABASE_URL` is set automatically. For local dev, uses `DB_PASSWORD` with localhost. |

### vector_store

Which vector database backend to use.

```yaml
vector_store:
  backend: pgvector
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backend` | string | `pgvector` | Vector store backend. Options: `pgvector` (recommended), `qdrant`, `weaviate`, `milvus`. Phase 1 only implements pgvector. |

### embedding

Configuration for the embedding API that converts text chunks into vectors for search.

```yaml
embedding:
  model: text-embedding-3-small
  dimensions: 1536
  provider: openai-compatible
  base_url: https://api.openai.com/v1
  api_key: ${EMBEDDING_API_KEY}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | string | `text-embedding-3-small` | Embedding model name. Must match what the API expects. |
| `dimensions` | int | `1536` | Vector dimensions. Must match the model's output. The Postgres vector column is sized to this value. |
| `provider` | string | `openai-compatible` | API provider type. Any OpenAI-compatible endpoint works (OpenAI, Together AI, Fireworks, Ollama, etc.). |
| `base_url` | string | `https://api.openai.com/v1` | API base URL. Change for non-OpenAI providers. |
| `api_key` | string | (none) | API key. Use `${EMBEDDING_API_KEY}` to pull from environment. If empty, embedding is disabled (documents are extracted but not embedded or searchable). |

Common embedding models:

| Model | Dimensions | Provider | Cost | Notes |
|-------|-----------|----------|------|-------|
| `text-embedding-3-small` | 1536 | OpenAI | $0.02/M tokens | Best value for most use cases |
| `text-embedding-3-large` | 3072 | OpenAI | $0.13/M tokens | Slightly better quality |
| `BAAI/bge-large-en-v1.5` | 1024 | Together AI, Fireworks | Varies | Strong open-source retrieval model |
| `BAAI/bge-m3` | 1024 | Together AI, Fireworks | Varies | Multilingual (if your docs aren't all English) |

When changing models, you must also update `dimensions` to match, and re-embed existing documents (existing vectors from a different model are incompatible).

### image_enrichment

Configuration for the vision API that describes images found in documents.

```yaml
image_enrichment:
  enabled: true
  provider: openai-compatible
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  api_key: ${VISION_API_KEY}
  prompt: "Describe this image in detail. Include any text, data, charts, diagrams, or visual elements."
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` | Set to `false` to skip image enrichment entirely. |
| `provider` | string | `openai-compatible` | API provider type. |
| `base_url` | string | `https://api.openai.com/v1` | API base URL. |
| `model` | string | `gpt-4o-mini` | Vision model. `gpt-4o-mini` is cheapest and sufficient for document images. `gpt-4o` for higher quality. |
| `api_key` | string | (none) | API key. Can use the same key as embedding if using the same provider. If empty, image enrichment is disabled. |
| `prompt` | string | (see above) | The prompt sent to the vision model with each image. Customize for domain-specific needs. |

### markitdown

Configuration for the MarkItDown extraction engine.

```yaml
markitdown:
  enable_plugins: true
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enable_plugins` | bool | `true` | Enable MarkItDown plugins (e.g., `markitdown-ocr` for image extraction). Plugins are loaded via Python entry points. |

### chunking

How extracted documents are split into chunks for embedding and search.

```yaml
chunking:
  default_strategy: by_title
  max_characters: 1500
  new_after_n_chars: 1000
  overlap: 200
  combine_under_n_chars: 200
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_strategy` | string | `by_title` | Default chunking strategy. Auto-selected by file type when not specified per document. Options: `by_title`, `by_page`, `fixed_size`. |
| `max_characters` | int | `1500` | Hard maximum characters per chunk (~375 tokens). |
| `new_after_n_chars` | int | `1000` | Soft limit: prefer to start a new chunk after this many characters, if a section break is available. |
| `overlap` | int | `200` | Characters of overlap between consecutive chunks. Preserves context across chunk boundaries. |
| `combine_under_n_chars` | int | `200` | Merge sections smaller than this into the preceding chunk. Prevents tiny chunks. |

Chunking strategy auto-selection by file type:

| File type | Strategy | Why |
|-----------|----------|-----|
| `.pptx` | `by_page` | Each slide is self-contained |
| `.csv`, `.xlsx` | `fixed_size` | Tabular data has no heading structure |
| `.txt`, `.log` without headings | `fixed_size` (high overlap) | No natural section breaks |
| Everything else | `by_title` | Split at Markdown headings |

The calling agent can override with a `chunking_config` parameter on `convert_document` or `ingest`.

### api

Server settings.

```yaml
api:
  host: 0.0.0.0
  port: 8000
  mcp_port: 8000
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `host` | string | `0.0.0.0` | Bind address. `0.0.0.0` listens on all interfaces. |
| `port` | int | `8000` | REST API port. Overridden by `PORT` env var on Railway. |
| `mcp_port` | int | `8000` | MCP port. When equal to `port`, runs in single-port mode (MCP mounted inside FastAPI). |

Authentication is controlled by the `ARIADNE_API_KEY` environment variable. When set, all endpoints except `/api/health` require a valid `X-API-Key` header.

### paths

File paths for document processing.

```yaml
paths:
  incoming: ./data/incoming
  processed: ./data/processed
  temp: ./data/temp
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `incoming` | string | `./data/incoming` | Where incoming documents are placed for processing. |
| `processed` | string | `./data/processed` | Where processed Markdown files are written. |
| `temp` | string | `./data/temp` | Temporary files during processing. Cleaned up automatically. |

### logging

```yaml
logging:
  level: info
  format: json
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `level` | string | `info` | Log level: `debug`, `info`, `warning`, `error`. |
| `format` | string | `json` | Log format: `json` (structured, good for production) or `text` (readable, good for development). |

## Environment variable overrides

Any config value can be overridden with an environment variable using the pattern `ARIADNE_SECTION_KEY`. Examples:

```bash
# Override the embedding model
ARIADNE_EMBEDDING_MODEL=text-embedding-3-large

# Override the embedding dimensions
ARIADNE_EMBEDDING_DIMENSIONS=3072

# Override the image enrichment model
ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o

# Override the log level
ARIADNE_LOGGING_LEVEL=debug

# Override the chunking strategy
ARIADNE_CHUNKING_DEFAULT_STRATEGY=fixed_size
```

## Example: minimal config for Railway

Set these environment variables on Railway and the defaults handle everything else:

```
EMBEDDING_API_KEY=your-provider-api-key
VISION_API_KEY=your-provider-api-key
ARIADNE_API_KEY=your-secret-key
```

Railway provides `DATABASE_URL`, `PORT` automatically.

## Example: multilingual document library

For a document library with non-English content, override the embedding model:

```bash
railway variables set ARIADNE_EMBEDDING_MODEL=BAAI/bge-m3
railway variables set ARIADNE_EMBEDDING_DIMENSIONS=1024
railway variables set EMBEDDING_BASE_URL=https://api.together.xyz/v1
```

Make sure to re-embed any existing documents after switching models — vectors from different models are incompatible.
