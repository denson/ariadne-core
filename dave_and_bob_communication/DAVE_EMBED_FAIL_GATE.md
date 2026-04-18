# DAVE — Silent-embedding-failure gate (pre-Phase-8)

Close the silent-failure hole in `services.py` before Phase 8. Today an
embedding `RuntimeError` is swallowed into a warning string but
`store_status="stored"` is set anyway and the chunks are inserted without
embeddings. Downstream: `list_documents` counts the doc, but vector
search returns zero hits for anything in it. Exactly the "555 successes,
most poisoned" pattern from the pre-migration run — we want it gone
before re-ingesting 574 World Bank files.

Scope: one logic tweak in `src/pipeline/services.py`, one SPEC line
update, one new test. Dave writes, does NOT commit. Bob commits.

---

## Step 0 — pre-flight

```
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Expected:
- `HEAD` and `origin/main` both at `da826cc`
- Nothing modified or staged
- Untracked: only the 4 helper scripts (same set you've seen all week)

Anything else → **stop and report**.

---

## Step 1 — edit `src/pipeline/services.py`

Current block, lines 346–369 (read the file first to confirm line numbers
haven't drifted):

```python
        if _embedding_client.enabled and chunks:
            try:
                texts = [c.text for c in chunks]
                embed_result = _embedding_client.embed_texts(texts)
                for chunk, embedding in zip(chunks, embed_result.embeddings):
                    chunk.embedding = embedding
                    chunk.embedding_model = _embedding_client.model
                processing_chain.append(embed_result.processing_chain_entry)
                response["embedding_model"] = _embedding_client.model
            except RuntimeError as e:
                response.setdefault("warnings", []).append(
                    f"Embedding failed: {e}"
                )

        if chunks:
            if force:
                _vector_store.delete_by_document(doc_id)
            _vector_store.insert(chunks)

        response["store_status"] = "stored"
        response["provenance"]["processing_chain"] = processing_chain
    else:
        response["store_status"] = "not_stored"
        response["chunks_count"] = 0
```

Change to:

```python
        embedding_failed = False
        if _embedding_client.enabled and chunks:
            try:
                texts = [c.text for c in chunks]
                embed_result = _embedding_client.embed_texts(texts)
                for chunk, embedding in zip(chunks, embed_result.embeddings):
                    chunk.embedding = embedding
                    chunk.embedding_model = _embedding_client.model
                processing_chain.append(embed_result.processing_chain_entry)
                response["embedding_model"] = _embedding_client.model
            except RuntimeError as e:
                response.setdefault("warnings", []).append(
                    f"Embedding failed: {e}"
                )
                embedding_failed = True

        if chunks and not embedding_failed:
            if force:
                _vector_store.delete_by_document(doc_id)
            _vector_store.insert(chunks)

        if embedding_failed:
            response["store_status"] = "error"
            response["chunks_count"] = 0
        else:
            response["store_status"] = "stored"
        response["provenance"]["processing_chain"] = processing_chain
    else:
        response["store_status"] = "not_stored"
        response["chunks_count"] = 0
```

Net behavioral change on an embedding `RuntimeError`:

- Chunks are NOT inserted into the vector store (previously: inserted
  without embeddings — unsearchable poison rows).
- `store_status` is `"error"` instead of `"stored"`.
- `chunks_count` reports 0 (matches what actually got stored).
- `warnings` still gets the `"Embedding failed: ..."` entry it always
  did.
- The document row itself is still in the dedup store — that write
  happened at line 267 before embedding runs. That's deliberate: the
  markdown extraction succeeded; future agents can see there's an
  errored doc and re-try with `force=true` after fixing the API issue.

Verify diff:

```
git diff -- src/pipeline/services.py
```

Should be exactly the block above. If anything else was touched, **stop
and report**.

---

## Step 2 — update `SPEC.md` line 374

Current:

```
**Response:** JSON with `document_id`, `source_file`, `title`, `markdown`, `file_type`, `engine`, `content_fingerprint`, `collection`, `chunks_count`, `was_dedup_skip`, `provenance`, `warnings`, `processing_time_ms`, `output_tokens_estimate`, `token_savings_ratio`, `embedding_model`, `store_status` (`"stored"` / `"not_stored"` / `"skipped"`), `interactions`.
```

Change the `store_status` parenthetical to:

```
`store_status` (`"stored"` / `"not_stored"` / `"skipped"` / `"error"`)
```

Then add a new paragraph **immediately after** the existing "Dedup behavior:"
paragraph (currently line 376), before the "Chunking auto-selection:"
paragraph. Exact text:

```
**Embedding-failure behavior:** If the embedding provider raises
during a store-mode ingest, the document markdown is still stored
(future retries can find it by fingerprint), but no chunks are
written to the vector store. `store_status` is `"error"`,
`chunks_count` is `0`, and `warnings` contains an `"Embedding failed: ..."`
entry with the provider error. Callers should treat this as a retryable
failure: fix the underlying provider issue, then re-ingest with
`force: true`.
```

Verify diff:

```
git diff -- SPEC.md
```

Should be exactly the parenthetical swap on the one line plus the new
paragraph. Nothing else.

---

## Step 3 — add a unit test

Create `tests/test_services.py` (new file). This is the first file to
exercise `_process_single_document` directly, so it's short and focused.

Exact content:

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

Verify diff:

```
git status --short
```

Should show `??  tests/test_services.py` (new untracked file) plus the
two ` M` edits from Steps 1–2 and the ongoing 4 helper scripts.

**Attribute-shape check before running:** `InMemoryVectorStore._chunks`
is a private dict. The test reaches into it — that's fine for a unit
test, but confirm the attribute is actually `_chunks` (not `chunks` or
something else) by reading `src/pipeline/storage/base.py` first. If the
attribute name differs, adjust the final assertion.

---

## Step 4 — HARD GATE: pytest

```
python -m pytest tests/ -v
```

Expected: **179 passed** (178 from `9095b18`/`da826cc` + 1 new). If any
test fails — especially an existing test that was green before — **stop
and report** with the full traceback. Do NOT commit on a red gate.

If the new test is the only failure: re-read Step 1 and confirm the
logic change is exact. A common mistake is keeping the `response["store_status"] = "stored"`
line unconditional instead of gating it on `not embedding_failed`.

---

## Step 5 — hand off (do NOT stage, commit, or push)

Run a final `git status --short`. Expected:

- ` M src/pipeline/services.py`
- ` M SPEC.md`
- `?? tests/test_services.py`
- Plus the ongoing 4 helper scripts as `??`

If anything else is modified or staged, **stop and report**.

---

## Step 6 — overwrite `dave_and_bob_communication/DAVE_DONE.md`

Report for Bob:

- Files edited: `src/pipeline/services.py`, `SPEC.md`
- Files created: `tests/test_services.py`
- Full `git diff` of the two edited files (should be small — the logic
  diff plus the SPEC one-line swap + new paragraph)
- Full contents of `tests/test_services.py` (for Bob's scope check)
- pytest count: 178 → 179 (or a note if it landed at 178 because a
  happy-path test was merged into an existing file — unlikely)
- Note any surprise (e.g., `_chunks` attribute naming, unexpected
  processing-chain-entry requirement, etc.)

Bob reviews scope, stages all 3 paths + `DAVE_DONE.md`, commits, pushes.

---

## Do NOT

- Change any `store_status` value outside of the one `"stored"` → error
  branch added above
- Edit `routes.py`, `mcp_server.py` (already deleted), or any other file
- Add more tests than the one described — this is one regression, one
  test. If you see something else worth testing, flag it in
  `DAVE_DONE.md` for backlog.
- Raise instead of setting `store_status="error"` — the client contract
  is "respond 2xx with a structured error signal", not 5xx
- Skip the SPEC update — the value enumeration is part of the public
  API contract
- Run `git commit --amend` or any commit at all
