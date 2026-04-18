# Task: Fix 5 minor gaps found in bidirectional sync audit (Step 7)

**For:** Dave

---

## What to do

Five small additions to `ariadne-core/SPEC.md`. Each is 1-3 lines. No sections are being rewritten — just filling gaps.

---

## Gap 1: Suggested tags from extraction (~Pipeline order, step 3)

The pipeline can add tags during extraction (encoding warnings, language detection), but this isn't described as a general capability.

**Fix:** After Pipeline order step 3 ("Extract to Markdown"), add a sentence:

```
Extraction may add suggested tags to the document (e.g., `encoding:windows-1252`, `language:french`, `content:binary-data`). These are informational — they help agents and users filter or review documents but do not affect processing.
```

Insert this as a note after step 4 (Language validation), since that's where most suggested tags come from. Keep it as a standalone paragraph between steps 4 and 5, not as part of a numbered step.

---

## Gap 2: Empty extraction guard (~Pipeline order, after step 3)

The spec doesn't say what happens when extraction produces empty content.

**Fix:** Add one sentence at the end of Pipeline order step 3:

Change step 3 from:
```
3. **Extract to Markdown** — MarkItDown converts the document to clean Markdown. For .txt files, the charset-normalizer output from step 2 is used directly (MarkItDown is skipped to avoid re-detection errors)
```

To:
```
3. **Extract to Markdown** — MarkItDown converts the document to clean Markdown. For .txt files, the charset-normalizer output from step 2 is used directly (MarkItDown is skipped to avoid re-detection errors). If extraction produces empty content, the document is still stored but tagged `content:empty` and a warning is included in the response.
```

---

## Gap 3: Embedding extra_params (~Configuration section)

PLANNED capability for passing provider-specific options to the embedding API. Not implemented yet but should be noted.

**Fix:** In the Configuration section, add one row to the Embedding table:

| `ARIADNE_EMBEDDING_EXTRA_PARAMS` | `{}` | JSON string of provider-specific options passed to the embedding API (planned — not yet implemented) |

---

## Gap 4: Token savings metrics in convert response (~REST API, POST /api/documents)

The convert response includes token savings data but this isn't documented in the endpoint spec.

**Fix:** In the `POST /api/documents` response description, find the response line and add `token_savings` to it. The response line currently says something like:

```
**Response:** JSON with `document_id`, `collection`, ...
```

Add `token_savings` (dict with `original_size`, `markdown_size`, `reduction_ratio`) to that list. If the response is described as a paragraph, append:

```
The response also includes `token_savings` — a dict with `original_size` (bytes), `markdown_size` (bytes), and `reduction_ratio` (e.g., `15.2` means 15.2x smaller). This quantifies the extraction efficiency per document.
```

---

## Gap 5: OAuth mention (~Authentication subsection)

OAuth is partially implemented but not mentioned in the spec.

**Fix:** In the Authentication subsection (after the API key description), add one line:

```
**OAuth:** Partially implemented. OAuth token validation is supported but not yet documented or exposed in the client package. API key auth is the primary authentication method.
```

---

## Also fix (from Bob's Step 6 review note)

In the Caller metadata field table (~line 812), the `agent_type` description lists `"claude-cowork"` and `"ob1"` as examples. Update to:

```
Client type: `"claude-code"`, `"cursor"`, `"api"`, `"ci"`, etc.
```

Remove `"claude-cowork"` (dead platform target) and `"ob1"` (internal, not useful as an example).

---

## What NOT to change

Everything else. These are surgical additions — 1-3 lines each. Do not rewrite any section.

## Do not commit

Leave for Bob. Write completion report to `DAVE_DONE.md`.
