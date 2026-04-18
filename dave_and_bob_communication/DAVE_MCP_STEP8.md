# Step 8: Bug fix — standalone image ingestion

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 8 of 8. Steps 1-7 must be committed first.

## The bug

Standalone image files (PNG, JPG) produce empty markdown because MarkItDown can't extract text from images. The image enrichment step never fires because it looks for image references (`![alt](path)`) in the extracted markdown — but there's no markdown to search.

## What to do

**File:** `ariadne-core/src/pipeline/mcp_server.py` — in `_process_single_document`

After the empty extraction check from Step 6, add a standalone image handling path:

1. Define the set of image extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.svg`

2. After MarkItDown extraction, check: is the file an image format AND is the markdown empty/whitespace?

3. If yes AND `_image_enricher.enabled`:
   - Call the vision model directly on the image file to get a description
   - Use that description as the markdown content
   - Add a processing chain entry for the vision step
   - Continue with normal fingerprinting, chunking, and embedding

4. If yes AND `_image_enricher` is NOT enabled:
   - Return the empty extraction error from Step 6 (vision key required)

The vision model call should use the same `_image_enricher` that already exists — look at how `ImageEnricher.enrich()` works and either call its underlying vision client directly, or add a method like `describe_image(file_path)` that takes a standalone image path.

## Important

- The markdown produced should clearly indicate it's a vision-generated description, not extracted text. Something like: `# Image: {filename}\n\n{vision_description}`
- The processing chain should show `"step": "vision_extraction"` (different from `"image_enrichment"` which is for images embedded in documents)
- `file_type` in the stored document should be the image extension (png, jpg, etc.)

## Do not commit

Report what you changed. Leave for Bob.
