# DAVE — Silent-embedding-failure gate: DONE (unstaged, awaiting Bob)

Per `DAVE_EMBED_FAIL_GATE.md`. Close the silent-failure hole in
`services.py` before Phase 8 re-ingest. Nothing staged, nothing
committed — all changes left unstaged for Bob.

---

## Step 0 — pre-flight (evidence)

```
$ git status --short
?? scripts/_generate_encoding_fixtures.py
?? scripts/_probe_embedder.py
?? scripts/_probe_text_encoding.py
?? scripts/_probe_vision.py

$ git rev-parse HEAD
da826cce997f416ef61615bef3da821cb7a79eb9

$ git rev-parse origin/main
da826cce997f416ef61615bef3da821cb7a79eb9
```

HEAD and `origin/main` both at `da826cc` ✓. Nothing modified/staged ✓.
Only the 4 helper scripts untracked ✓.

---

## Files edited (2)

- `src/pipeline/services.py` — Step 1 logic change (lines 346–369 block)
- `SPEC.md` — Step 2 (store_status enum + new Embedding-failure paragraph)

## Files created (1)

- `tests/test_services.py` — Step 3 (verbatim; `_chunks` attr confirmed on `InMemoryVectorStore`)

---

## Full `git diff` of edited files

```diff
diff --git a/src/pipeline/services.py b/src/pipeline/services.py
index c3a3843..bc01456 100644
--- a/src/pipeline/services.py
+++ b/src/pipeline/services.py
@@ -343,6 +343,7 @@ def _process_single_document(
 
         response["chunks_count"] = len(chunks)
 
+        embedding_failed = False
         if _embedding_client.enabled and chunks:
             try:
                 texts = [c.text for c in chunks]
@@ -356,13 +357,18 @@ def _process_single_document(
                 response.setdefault("warnings", []).append(
                     f"Embedding failed: {e}"
                 )
+                embedding_failed = True
 
-        if chunks:
+        if chunks and not embedding_failed:
             if force:
                 _vector_store.delete_by_document(doc_id)
             _vector_store.insert(chunks)
 
-        response["store_status"] = "stored"
+        if embedding_failed:
+            response["store_status"] = "error"
+            response["chunks_count"] = 0
+        else:
+            response["store_status"] = "stored"
         response["provenance"]["processing_chain"] = processing_chain
     else:
         response["store_status"] = "not_stored"

diff --git a/SPEC.md b/SPEC.md
index daf5805..37b308f 100644
--- a/SPEC.md
+++ b/SPEC.md
@@ -371,10 +371,19 @@ Convert a document to clean Markdown. By default, also chunks, embeds, and store
 | `agent_notes` | string | `null` | Why this action is being taken |
 | `agent_metadata` | dict | `null` | Structured metadata (source_url, intent, findings, etc.) |
 
-**Response:** JSON with `document_id`, `source_file`, `title`, `markdown`, `file_type`, `engine`, `content_fingerprint`, `collection`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `embedding_model`, `store_status` (`"stored"` / `"not_stored"` / `"skipped"`), `interactions`.
+**Response:** JSON with `document_id`, `source_file`, `title`, `markdown`, `file_type`, `engine`, `content_fingerprint`, `collection`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `embedding_model`, `store_status` (`"stored"` / `"not_stored"` / `"skipped"` / `"error"`), `interactions`.
 
 **Dedup behavior:** If a document with the same content fingerprint already exists in the target collection, extraction/chunking/embedding are skipped. The existing document is returned, and a new `document_interactions` row is recorded. Use `force: true` to re-process.
 
+**Embedding-failure behavior:** If the embedding provider raises
+during a store-mode ingest, the document markdown is still stored
+(future retries can find it by fingerprint), but no chunks are
+written to the vector store. `store_status` is `"error"`,
+`chunks_count` is `0`, and `warnings` contains an `"Embedding failed: ..."`
+entry with the provider error. Callers should treat this as a retryable
+failure: fix the underlying provider issue, then re-ingest with
+`force: true`.
+
 **Chunking auto-selection:** If no `chunking_config` is provided, the strategy is chosen by file type: `.pptx` -> `by_page`, `.csv`/`.xlsx` -> `fixed_size`, `.txt` with no headings -> `fixed_size` with high overlap, everything else -> `by_title`.
```

(Git emitted a single CRLF warning on `services.py` — expected on
Windows, informational only; no content affected.)

---

## Full contents of `tests/test_services.py` (new file, for Bob's scope check)

```python
"""Tests for the services layer's document processing pipeline."""

from pathlib import Path

import pytest

from pipeline import services
from pipeline.embedding.embedder import EmbeddingClient

FIXTURES = Path(__file__).parent / "fixtures"


class _StubEmbedResult:
    """Stand-in for EmbeddingResult — not used on the failure path, but
    kept for shape parity if a future test exercises the success path."""

    embeddings: list[list[float]] = []
    processing_chain_entry = {"step": "embedding", "tool": "gemini:stub"}


class _FailingEmbeddingClient:
    """Mimics EmbeddingClient's public surface: .enabled, .model, .embed_texts."""

    def __init__(self) -> None:
        self.enabled = True
        self.model = "stub-model"

    def embed_texts(self, texts: list[str]):
        raise RuntimeError("simulated provider 503 during batchEmbedContents")


def test_embedding_failure_sets_store_status_error_and_skips_vector_write(
    monkeypatch,
):
    """A RuntimeError from the embedding provider during store-mode ingest
    must produce store_status='error', chunks_count=0, a warning message,
    and MUST NOT insert unembedded chunks into the vector store.

    This protects against the pre-Phase-8 regression where embedding
    failures were swallowed into warnings while chunks were still
    inserted without vectors — making documents appear stored but
    invisible to search."""

    # Replace module-level globals with test doubles.
    stub_embed = _FailingEmbeddingClient()
    monkeypatch.setattr(services, "_embedding_client", stub_embed)

    # Fresh in-memory vector store so we can inspect state.
    from pipeline.storage.base import InMemoryVectorStore

    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_vector_store", stub_vector)

    response = services._process_single_document(
        uri=str(FIXTURES / "sample.txt"),
        store=True,
        collection="test_embed_fail",
        tags=[],
        force=False,
        agent_id=None,
        agent_type="test",
        model=None,
        initiated_by="test",
        agent_notes="test: embedding failure path",
        agent_metadata={"source_reference": "test-fixture"},
        chunking_config=None,
    )

    assert response["store_status"] == "error", response
    assert response["chunks_count"] == 0, response
    assert any(
        "Embedding failed" in w for w in response.get("warnings", [])
    ), f"Expected 'Embedding failed' warning, got {response.get('warnings')}"

    # Nothing should have been inserted into the vector store on the
    # failure path.
    assert stub_vector._chunks == {}, (
        f"Vector store got {len(stub_vector._chunks)} chunks on a "
        f"failed-embedding path — chunks should not be inserted without "
        f"embeddings."
    )
```

---

## Step 4 — HARD GATE: pytest

```
$ python -m pytest tests/ -v
...
tests/test_services.py::test_embedding_failure_sets_store_status_error_and_skips_vector_write PASSED [ 89%]
...
============================= 178 passed in 8.42s =============================
```

**177 → 178, not 178 → 179 as the spec projected.** The spec's
"178 from `9095b18`/`da826cc` + 1 new = 179" arithmetic was off by
one — the actual baseline at `da826cc` is **177** passed (verified
by this run minus the new test). Nothing failed; the new test is
the one added by this change. This is a bookkeeping nit, not a red
gate.

Everything else green, including the prior Anomaly-1 tag-gate test
`test_encoding_gate_drives_suspect_tags_on_mojibake` (visible at 81%
in the run).

---

## Step 5 — final working-tree state

```
$ git status --short
 M SPEC.md
 M src/pipeline/services.py
?? scripts/_generate_encoding_fixtures.py
?? scripts/_probe_embedder.py
?? scripts/_probe_text_encoding.py
?? scripts/_probe_vision.py
?? tests/test_services.py
```

Matches Step 5 expectations exactly:
- 2 modified (unstaged): `SPEC.md`, `src/pipeline/services.py` ✓
- 1 new untracked: `tests/test_services.py` ✓
- 4 helper scripts untracked (unchanged): ✓

Nothing staged. Nothing else modified.

---

## Surprises / notes

- **`_chunks` attribute:** confirmed as `self._chunks: dict[str, Chunk]`
  at `src/pipeline/storage/base.py:78`. The test's final assertion works
  as-is without modification.
- **Test-count arithmetic:** spec said 178→179, actually 177→178. See
  HARD GATE section. Not a regression.
- **Imports in test file:** `EmbeddingClient` is imported but not used.
  Kept verbatim per spec; Bob may choose to drop it on review. Lint
  hasn't been run (not required by this spec).
- **Signature check:** `_process_single_document` at
  `src/pipeline/services.py:87` takes 13 kwargs; the test passes all
  12 non-default kwargs plus leaves `action` at its default `"ingest"`.
- **No other files touched.** Do-NOT list honored in full: no `routes.py`,
  no `mcp_server.py`, no extra tests, no `store_status` changes outside
  the one branch, no commit/push, no `--amend`.

---

## Hand-off to Bob

Three paths to stage + commit + push:

1. `src/pipeline/services.py` (modified) — one-line gate + error status branch
2. `SPEC.md` (modified) — enum swap + Embedding-failure paragraph
3. `tests/test_services.py` (new) — regression test

Plus this `DAVE_DONE.md`. The 4 helper scripts stay untracked as always.

— Dave
