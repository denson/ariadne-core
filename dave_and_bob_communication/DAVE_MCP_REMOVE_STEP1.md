# Step 1: Create `pipeline/services.py`

**For:** Dave  
**Context:** Read `DAVE_MCP_REMOVAL_PLAN.md` for the full 5-step plan. This is step 1.

---

## What to do

Create a new file `src/pipeline/services.py` by extracting the service layer from `mcp_server.py`. This is a copy-and-adapt, not a move — `mcp_server.py` stays untouched for now.

## What goes in `services.py`

Copy these from `mcp_server.py`, keeping all their imports:

### 1. Imports needed

At the top, add the imports that the extracted code needs. Look at what `mcp_server.py` imports and bring over everything EXCEPT the MCP-specific imports (`from mcp.server import FastMCP`, `from mcp.server.transport_security import TransportSecuritySettings`). You will need at minimum:

```python
import asyncio
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
```

Plus the pipeline-internal imports:
```python
from pipeline.chunking.chunker import Chunk, ChunkingConfig, chunk_document
from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    PgDedupStore,
    SearchLogEntry,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig
from pipeline.enrichment.images import ImageEnricher
from pipeline.enrichment.vision import VisionConfig
from pipeline.extraction.markitdown import MarkItDownExtractor
from pipeline.storage.base import InMemoryVectorStore
from pipeline.storage.pgvector import PgVectorStore
```

### 2. Module docstring

```python
"""Ariadne Core service layer — shared state and document processing logic.

This module contains all the business logic for document extraction, storage,
search, and lifecycle management. The REST API routes and any future interfaces
import from here.
"""
```

### 3. Shared state (copy as-is)

```python
_extractor = MarkItDownExtractor(enable_plugins=True)
_dedup_store = InMemoryDedupStore()
_vector_store = InMemoryVectorStore()
_embedding_client = EmbeddingClient()
_image_enricher = ImageEnricher(None)
```

### 4. Configure functions (copy as-is)

- `configure_embedding(config: EmbeddingConfig) -> None`
- `configure_image_enrichment(api_key, model, base_url) -> None`
- `configure_stores(dedup_store, vector_store) -> None`

### 5. Constants (copy as-is)

- `_STANDALONE_IMAGE_EXTENSIONS`
- `SUPPORTED_EXTENSIONS`

### 6. Core functions (copy as-is)

- `_process_single_document()` — the big one, ~300 lines
- `_find_document_by_id()`
- `_get_chunks_for_document()`
- `_count_chunks_for_document()`
- `_post_filter_results()`

### Important: fix the inline `re` import

In `_process_single_document`, around the image warning block (line ~1249 in mcp_server.py), there's `import re as _re`. Since we'll have `import re` at the top of services.py, change `_re.findall` to `re.findall` and remove the inline import.

## What NOT to do

- Do NOT modify `mcp_server.py`
- Do NOT modify `routes.py` or `app.py` (that's steps 2-3)
- Do NOT add any MCP imports
- Do NOT add the `@app.tool()` decorated functions — those stay in `mcp_server.py` until it's deleted

## Verify

Run: `python -c "from pipeline.services import _process_single_document, configure_stores, SUPPORTED_EXTENSIONS"` — should import clean with no errors.

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`.
