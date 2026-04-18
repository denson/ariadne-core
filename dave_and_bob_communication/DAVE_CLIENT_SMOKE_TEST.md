# Smoke test: Client package → Railway round-trip

**For:** Dave  
**Context:** The client package is built (steps 1-5). Railway should be back up. Run a round-trip test to verify the client talks to the live server end-to-end.

---

## Prerequisites

Make sure the client is installed:

```bash
pip install -e client/
```

Credentials should resolve automatically from `.env` or environment variables (`ARIADNE_URL`, `ARIADNE_API_KEY`). If not, check what `credentials.py` finds:

```python
from ariadne_core_client.credentials import resolve_credentials
url, key = resolve_credentials()
print(f"URL: {url}")
print(f"Key: {'***' + key[-4:] if key else 'None'}")
```

If no credentials resolve, stop and report — the test can't run.

---

## Test sequence

Run these as a Python script or in sequence. Print results at each step. If any step fails, report the error and stop — don't continue past a failure.

### 1. Health check

```python
from ariadne_core_client import AriadneClient

client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-7"
)

health = client.health()
print(f"1. Health: {health}")
assert health.status == "healthy", f"Expected healthy, got {health.status}"
```

### 2. List collections (baseline)

```python
collections = client.list_collections()
print(f"2. Collections: {len(collections)} found")
for c in collections:
    print(f"   - {c.name} ({c.document_count} docs)")
```

### 3. Ingest a test document via URL

Use a small, publicly available text file. The SPEC.md raw URL from the repo works:

```python
doc = client.ingest_url(
    "https://raw.githubusercontent.com/denson/ariadne-core/main/SPEC.md",
    collection="smoke-test",
    tags=["test", "smoke-test"],
    agent_notes="Round-trip smoke test of client package against Railway deployment",
    agent_metadata={"intent": "testing", "status": "smoke-test"}
)
print(f"3. Ingest URL: {doc.document_id}")
print(f"   file={doc.source_file}, chunks={doc.chunks_count}, dedup={doc.was_dedup_skip}")
print(f"   store_status={doc.store_status}")
assert doc.document_id, "No document_id returned"
```

Save `doc.document_id` for subsequent steps.

### 4. Search for the ingested document

```python
results = client.search(
    "client package installation",
    collection="smoke-test",
    top_k=3,
    agent_notes="Smoke test search"
)
print(f"4. Search: {results.results_count} results for 'client package installation'")
for r in results:
    print(f"   score={r.relevance_score:.4f} section={r.section} text={r.text[:80]}...")
assert results.results_count > 0, "Expected at least 1 search result"
```

### 5. Get the full document

```python
full_doc = client.get_document(doc.document_id)
print(f"5. Get document: {full_doc.source_file}")
print(f"   markdown length={len(full_doc.markdown or '')} chars")
print(f"   interactions={len(full_doc.interactions)}")
assert full_doc.markdown, "No markdown content returned"
```

### 6. Update document metadata

```python
update_result = client.update_document(
    doc.document_id,
    tags=["test", "smoke-test", "status:verified"],
    agent_notes="Smoke test: marking as verified"
)
print(f"6. Update: fields changed = {update_result.get('updated_fields')}")
assert "tags" in update_result.get("updated_fields", []), "Expected tags in updated_fields"
```

### 7. List documents in smoke-test collection

```python
docs = client.list_documents(collection="smoke-test")
print(f"7. List documents: {len(docs)} in smoke-test collection")
for d in docs:
    print(f"   - {d.source_file} (id={d.document_id[:8]}...)")
```

### 8. Stats

```python
stats = client.stats()
print(f"8. Stats: {stats}")
```

### 9. Delete the test document (cleanup)

```python
del_result = client.delete_document(
    doc.document_id,
    agent_notes="Smoke test cleanup"
)
print(f"9. Delete: status={del_result.get('status')}")
assert del_result.get("status") == "scheduled_for_deletion", f"Unexpected status: {del_result}"
```

### 10. Verify deletion (search should return 0)

```python
results_after = client.search(
    "client package installation",
    collection="smoke-test",
    top_k=3,
    agent_notes="Smoke test: verifying deletion"
)
print(f"10. Post-delete search: {results_after.results_count} results (expected 0)")
```

Note: if there were pre-existing documents in smoke-test from a prior run, this might return >0. That's fine — the important thing is the round-trip worked.

### 11. CLI smoke test

Also test the CLI briefly:

```bash
ariadne health
ariadne list-collections
ariadne stats
```

All three should print human-readable output and exit 0.

---

## Report

Write results to `DAVE_DONE.md`. For each step, report PASS or FAIL with the output. If any step fails, include the full error/traceback. Note any surprising behavior (e.g., field name mismatches between what the server returns and what the client expects).

**Do not commit anything** — this is a read-only test. No files should be created or modified (except DAVE_DONE.md).
