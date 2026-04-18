# Step 6: Bug fix — empty fingerprint dedup

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 6 of 8. Steps 1-5 must be committed first.

## The bug

When MarkItDown extracts an image file (PNG, JPG), it produces empty markdown. This empty string gets a valid SHA-256 fingerprint (`e3b0c44...`) and gets stored. All subsequent empty extractions dedup against it, so the second image silently returns the first image's document ID.

## What to do

**File:** `ariadne-core/src/pipeline/mcp_server.py` — in `_process_single_document`

After extraction and before computing the fingerprint, check if the markdown is empty:

```python
if not result.markdown or not result.markdown.strip():
    return {
        "error": True,
        "message": f"Extraction produced empty output for {result.source_file}. "
                   "Image files require vision API configuration. "
                   "Check ARIADNE_IMAGE_ENRICHMENT_API_KEY.",
        "document_id": result.document_id,
        "source_file": result.source_file,
    }
```

Place this AFTER the existing extraction error check (`if result.errors:`) and BEFORE `fingerprint = compute_fingerprint(result.markdown)`.

## Do not commit

Report what you changed. Leave for Bob.
