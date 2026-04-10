# Patch 001: Search Response Fields — Full Enumeration

**Resolves:** CHECK_SKILL_VS_SPEC_RESULTS.md — Discrepancy #3 (Search response fields)

**Problem:** The `search` tool's docstring in both `mcp_server.py` and `mcp_stdio_proxy.py` says only `"JSON string with ranked chunks and source metadata"`. The OB1 skill says `"Returns ranked chunks with source file, page, section, relevance score, and full interaction history."` Neither tells callers the actual response shape. The architecture doc's prose is also incomplete — it mentions `source_file` and `document link` which don't match the code's actual field names.

The **code is correct** — the response is well-structured and complete. The **documentation is incomplete** in four places.

---

## Files to patch (4)

### 1. `src/pipeline/mcp_server.py` — lines 194–195

**Current:**
```python
    Returns:
        JSON string with ranked chunks and source metadata.
```

**Replace with:**
```python
    Returns:
        JSON with top-level keys: query, top_k, collection, results_count, results.

        Each result object contains:
        - chunk_id: Unique chunk identifier
        - document_id: Source document ID
        - collection: Collection the chunk belongs to
        - text: Chunk text content
        - section: Section heading (may be null)
        - page: Page number (may be null)
        - token_count: Token count of the chunk
        - relevance_score: Cosine similarity score (0-1, 4 decimal places)
        - embedding_model: Model used to generate the embedding
        - interactions: Array of all agent interactions with the source document,
          each containing agent_id, agent_type, model, initiated_by, agent_notes,
          agent_metadata, action, was_dedup_skip, created_at
```

### 2. `src/pipeline/mcp_stdio_proxy.py` — lines 186–187

**Current:**
```python
    Returns:
        JSON string with ranked chunks and source metadata.
```

**Replace with:** Same replacement as file 1 above (identical docstring).

### 3. `docs/docint-architecture.md` — line 463

**Current:**
```
Returns: Ranked chunks with source_file, page, section, relevance_score, document link, provenance summary, and all `document_interactions` for each matched document (so the caller sees which agents have previously touched the result).
```

**Replace with:**
```
Returns: JSON with top-level keys `query`, `top_k`, `collection`, `results_count`, and `results` array. Each result includes `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, and `interactions` (array of all `document_interactions` for the source document, so the caller sees which agents have previously touched the result).
```

**Why:** The current prose says `source_file` (not a field in the response — the code uses `document_id`), `document link` (does not exist), and `provenance summary` (does not exist as a discrete field — `interactions` serves this purpose). Align the spec prose with what the code actually returns.

### 4. OB1 skill: `skills/ariadne-document-intelligence/SKILL.md` — lines 45–47

**Current:**
```markdown
- **`search`** — Semantic search over stored documents. Returns ranked chunks with
  source file, page, section, relevance score, and full interaction history. Supports
  filters for collection, source file, file type, tags, and document ID.
```

**Replace with:**
```markdown
- **`search`** — Semantic search over stored documents. Returns JSON with `query`,
  `results_count`, and `results` array. Each result includes `chunk_id`, `document_id`,
  `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`,
  `embedding_model`, and `interactions` (full history of agent touches on the source
  document). Supports filters for collection, source file, file type, tags, and
  document ID.
```

---

## Verification

After patching, run this check:

1. **Grep consistency:** All four files should list exactly the same 10 result fields in the same order: `chunk_id`, `document_id`, `collection`, `text`, `section`, `page`, `token_count`, `relevance_score`, `embedding_model`, `interactions`.
2. **Code match:** The field list should match the keys in the dict literal at `mcp_server.py` line 241–265 exactly.
3. **No phantom fields:** Confirm that `source_file`, `document link`, and `provenance summary` no longer appear in any search response description (they were never in the code).

---

## What this patch does NOT change

- The code itself — the response structure is already correct.
- The SPEC.md file — it already has the correct field list (line 98). No change needed.
- Filter parameters — already consistent across all files.
- The `convert_document` response fields — already correct in all files.
