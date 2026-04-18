# DAVE — Phase 8: World-Bank corpus re-ingest (574 files)

Re-ingest the 574 already-downloaded World Bank rare-earth-economics
text files into `world-bank-ree` on the post-migration native-Gemini
runtime. The previous bulk run (on the OpenAI-compat shim) logged 555
"successes" but those chunks were poisoned by the silent-embedding-
failure bug in `services.py` — the current contents of `world-bank-ree`
cannot be trusted.

The silent-failure hole was closed at commit `3cd00ba` (today) —
embedding `RuntimeError` now produces `store_status="error"` with
`chunks_count=0` and no vector-store write. That means this run is
the first one where `store_status="stored"` is actually trustworthy,
and a durability delta of zero is a real gate instead of a prayer.

**Scope:** exactly the 574 `sha1_*.txt` files already extracted to
local disk. Not the full 1,891-row manifest. The remainder of the
manifest is for a future work-item that uses this corpus's content to
drive additional WDS search terms before re-downloading.

**Process:** you run the data operation and write a report. No code
changes. No commits, no push. Write evidence to `DAVE_DONE.md` and stop.

---

## Inputs you already have (do NOT re-ask)

- **Corpus text files:**
  `D:/video_projects/REE_projects/world_bank/world_bank_project_reports/data/content/text/`
  - Contains 574 `sha1_<hex>.txt` files (pre-extracted from PDFs,
    probably via MarkItDown) plus `bulk_ingest_errors.log`,
    `bulk_ingest_full.log`, and a `sha1/` subdir — ignore those three
    non-corpus entries
- **Manifest:**
  `D:/video_projects/REE_projects/world_bank/world_bank_project_reports/data/content/docs.jsonl`
  - 1,891 rows; filter to `row["ok"] is True` (574 rows) — those are
    the rows matching the 574 `.txt` files on disk. The filename's
    `sha1_<hex>.txt` maps to `doc_id` = `"sha1:<hex>"` in the manifest.
  - Relevant fields per row: `doc_id`, `source`, `title`, `date`,
    `docty`, `lang`, `profile_url`, `pdfurl`, `txturl`,
    `local_text_path`, `qterm_hits`, `bytes`
- **Collection name:** `world-bank-ree` (same as before; wipe + re-ingest)
- **Target runtime:** current Railway deployment

---

## What's different from `DAVE_WORLD_BANK_RESTART.md`

That doc predates the client-package rewrite, the native-Gemini
migration, and the silent-failure fix. Do not follow it. Salient
diffs:

| Old spec says | Current reality |
|---|---|
| `client.ingest(path=..., collection=...)` | `client.ingest_file(path, collection=...)` — no `path=` kw |
| `client.search_chunks(...)` | `client.search(...)` |
| `client.delete_collection` "if it exists" | It exists. Use it directly. |
| `doc.processing_chain` | `doc.provenance["processing_chain"]` — `Document` has no top-level `processing_chain` attr |
| `doc.path` | `doc.source_file` |
| `HealthResponse(...)` | `Health(status, version, engine, embedding_enabled)` |
| Phase 1: run full 11-step `DAVE_CLIENT_SMOKE_TEST.md` | Skip. Phase 7.5 already proved the full round-trip against current Railway. Replace with a 30-second check (see Step 1). |
| `scripts/bulk_ingest.py` | **Broken** against current client — imports `ariadne_client` (wrong package, now `ariadne_core_client`), calls `upload_file` / `convert_document` (removed methods). Do NOT use. Phase 8 uses a purpose-built loop — we need per-file durability tracking and stagger/retry control. |
| Commit `0141618` as "just pushed auth fix" | `main` is at `3cd00ba`, 19+ commits past that |
| Trust `store_status == "stored"` | Now actually trustworthy (as of `3cd00ba`). `store_status="error"` is now a distinct value you can grep for in the ingest log — surface any you see. |
| Store whatever `source=` you want | Use `row["profile_url"]` from the manifest. That's the canonical World Bank curation URL, not a `D:/...` path that means nothing to a future agent. |

---

## Step 0 — pre-flight

```
git rev-parse HEAD        # expected: 3cd00ba or a descendant
git rev-parse origin/main # same
git status --short        # only the 4 helper scripts ?? — no modified/staged
```

If anything else, **stop and report**.

Confirm the Railway deployment is running the current commit. Because
of BL-9 (Railway auto-deploy has flaked before), do not trust that
`git push` reached the server. Probe:

```python
from ariadne_core_client import AriadneClient
client = AriadneClient(
    agent_type="claude-code",
    initiated_by="user:denson",
    model="claude-opus-4-7",
    timeout=60,
)
print(client.health())
```

Expected: `Health(status='healthy', ...)`. **Note:** BL-8 logs that
`embedding_enabled=True` can be a false positive (it reflects config
presence, not a real round-trip). That's why Step 1 is a real ingest.

Confirm the manifest loads:

```python
import json
from pathlib import Path

MANIFEST = Path("D:/video_projects/REE_projects/world_bank/world_bank_project_reports/data/content/docs.jsonl")
rows = [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()]
ok_rows = [r for r in rows if r.get("ok") is True]
print(f"manifest rows total: {len(rows)}  ok: {len(ok_rows)}")
# expected: total 1891, ok 574
```

If the `ok` count isn't 574, **stop and ask** — we want to know
before starting whether the corpus drifted.

Build the sha1 → row index:

```python
by_sha1 = {r["doc_id"].removeprefix("sha1:"): r for r in ok_rows}
```

---

## Step 1 — 30-second liveness check (replaces the old Phase 1 smoke)

Ingest one small file into a throwaway collection and confirm the
round-trip is real. This catches key-rotation / stale-deployment
issues before you burn an hour on 574 files.

```python
SMOKE_COLLECTION = "smoke_phase_8_preflight"  # throwaway
doc = client.ingest_file(
    "tests/fixtures/clean_english_sample.txt",
    collection=SMOKE_COLLECTION,
    tags=["phase_8_preflight"],
    source="tests/fixtures/clean_english_sample.txt",
    agent_metadata={"intent": "phase_8_preflight"},
)
print(f"document_id={doc.document_id}  chunks={doc.chunks_count}  "
      f"store_status={doc.store_status}  warnings={doc.warnings}")

# Real-round-trip embedding check: score must be plausible, not ~0.
hits = client.search("clean English sample", collection=SMOKE_COLLECTION, top_k=3)
print(f"search: {hits.results_count} hits")
for h in hits:
    print(f"  score={h.relevance_score:.4f} text={h.text[:60]!r}")
```

**Hard gate:**

- `doc.chunks_count > 0`
- `doc.store_status == "stored"` (NOT `"error"`)
- `doc.warnings` is empty or contains only the known-benign provenance hint
- `hits.results_count > 0`
- Top hit's `relevance_score > 0.3` — near-zero scores mean embeddings
  aren't reaching the API even though `store_status` says stored

If any of these fail, **stop and paste the full output**. Do not
proceed to Step 2. If `store_status="error"`, the embedding provider
is down — retry in 60s, and if still `"error"`, stop and surface it;
the fix from `3cd00ba` is working as intended and the blocker is
upstream.

Cleanup (the smoke collection is disposable):

```python
client.delete_collection(SMOKE_COLLECTION, agent_notes="phase_8_preflight cleanup")
```

---

## Step 2 — snapshot current `world-bank-ree` and wipe it

### 2a. Snapshot

```python
stats_before = client.stats()
print("stats_before:", stats_before)

existing_docs = client.list_documents(collection="world-bank-ree", limit=1000)
print(f"world-bank-ree doc count (pre-wipe): {len(existing_docs)}")

hits_before = client.search(
    "rare earth elements supply chain",
    collection="world-bank-ree",
    top_k=5,
)
print(f"search score sample (pre-wipe):")
for h in hits_before:
    print(f"  score={h.relevance_score:.4f} doc={h.document_id}")
```

Record these numbers in your report. We expect pre-wipe scores to be
near-zero or absent — that's the evidence the old run was poisoned.

### 2b. Wipe

```python
result = client.delete_collection(
    "world-bank-ree",
    agent_notes="Phase 8: wiping shim-era poisoned collection before native-Gemini re-ingest",
)
print("delete_collection:", result)
```

### 2c. Verify empty

```python
remaining = client.list_documents(collection="world-bank-ree", limit=1000)
print(f"world-bank-ree doc count (post-wipe): {len(remaining)}")
assert len(remaining) == 0, f"Expected 0, got {len(remaining)}"
```

If `len(remaining) != 0`, **stop and report**. Do not proceed to the
re-ingest with stale docs still in place.

---

## Step 3 — re-ingest all 574 files

### 3a. Enumerate the corpus

```python
from pathlib import Path

TEXT_DIR = Path("D:/video_projects/REE_projects/world_bank/world_bank_project_reports/data/content/text")
files = sorted(p for p in TEXT_DIR.glob("sha1_*.txt"))
print(f"found {len(files)} sha1_*.txt files in {TEXT_DIR}")
# expected: 574
```

If the count isn't 574 ± a handful, **stop and ask** before starting.

Every filename must join to the manifest. Fail loudly if any orphan:

```python
orphans = [p for p in files if p.stem.removeprefix("sha1_") not in by_sha1]
if orphans:
    print(f"ORPHAN FILES (not in manifest ok rows): {len(orphans)}")
    for p in orphans[:10]:
        print(f"  {p.name}")
    raise SystemExit("Stopping — orphan files mean the manifest disagrees with disk.")
```

### 3b. Ingest loop

Purpose-built. Not the CLI, not `scripts/bulk_ingest.py` (broken).

Per-file metadata is built from the manifest row so every document
has real provenance — canonical World Bank URL, original title, date,
document type — rather than a local `D:/...` path that means nothing
six months from now.

```python
import json
import time
from pathlib import Path

COLLECTION = "world-bank-ree"
STAGGER_MS = 150
LOG_PATH = Path("phase_8_ingest_log.json")

log = []  # one dict per file: path, ok, document_id, chunks, store_status, warnings, error
for idx, fp in enumerate(files, 1):
    sha1 = fp.stem.removeprefix("sha1_")
    row = by_sha1[sha1]  # guaranteed to exist after the orphan check above

    metadata = {
        "corpus": "world-bank-ree",
        "phase": "phase_8_reingest",
        "source_reference": row["profile_url"],  # canonical WB curation URL
        "doc_id_manifest": row["doc_id"],        # e.g. "sha1:abc123..."
        "title": row.get("title"),
        "publication_date": row.get("date"),
        "document_type": row.get("docty"),
        "language": row.get("lang"),
        "qterm_hits": row.get("qterm_hits"),
        "pdf_url": row.get("pdfurl"),
        "txt_url": row.get("txturl"),
        "original_local_path": row.get("local_text_path"),
        "original_byte_size": row.get("bytes"),
    }
    # drop Nones so the agent_metadata stays tidy
    metadata = {k: v for k, v in metadata.items() if v is not None}

    try:
        doc = client.ingest_file(
            str(fp),
            collection=COLLECTION,
            tags=["corpus:world-bank-ree", "type:report", "topic:ree"],
            source=row["profile_url"],  # canonical WB URL, not D:/...
            agent_metadata=metadata,
            agent_notes=f"Phase 8 re-ingest: {row.get('title', sha1)[:80]}",
        )
        log.append({
            "path": str(fp),
            "sha1": sha1,
            "ok": True,
            "document_id": doc.document_id,
            "chunks": doc.chunks_count,
            "store_status": doc.store_status,
            "warnings": list(doc.warnings),
        })
        tag = "ok" if doc.store_status == "stored" else f"!{doc.store_status}"
        print(f"[{idx}/{len(files)}] {tag} {fp.name}  chunks={doc.chunks_count} "
              f"warnings={len(doc.warnings)}")
    except Exception as e:
        log.append({"path": str(fp), "sha1": sha1, "ok": False, "error": str(e)})
        print(f"[{idx}/{len(files)}] FAIL {fp.name}: {e}")

    # checkpoint every 25 files so a mid-run crash doesn't lose the log
    if idx % 25 == 0:
        LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")

    time.sleep(STAGGER_MS / 1000)

LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")
```

Counts to record:

- `total` — `len(files)`
- `ok` — `sum(1 for r in log if r.get("ok"))`
- `stored` — `sum(1 for r in log if r.get("store_status") == "stored")`
- `errored` — `sum(1 for r in log if r.get("store_status") == "error")`
- `fail` (client-side exception, never reached server cleanly) —
  `sum(1 for r in log if not r.get("ok"))`
- `with_warnings` — `sum(1 for r in log if r.get("ok") and r.get("warnings"))`

Tail the HTTP-status distribution of `fail` entries (group by 4xx vs
5xx vs timeout). 5xx clusters around a contiguous range of indices
is a sign of a Railway hiccup — note it. 4xx on the client side is
our bug.

Run this in the background via Monitor so you can do other checks
while it runs. Expect ~1–2 hours at 150ms stagger + per-file latency.

---

## Step 4 — durability check (the real gate)

Server-side state is the proof — not the ingest log's `store_status`,
though as of `3cd00ba` the log is now consistent with reality too.

```python
stats_after = client.stats()
print("stats_after:", stats_after)
print(f"world-bank-ree count in stats: {stats_after.collections.get('world-bank-ree')}")

durable = client.list_documents(collection="world-bank-ree", limit=1000)
print(f"durable doc count: {len(durable)}")
```

Compare:

- `len(durable)` vs `stored` count from Step 3 → **must match**.
  If `durable < stored`, something worse than the old silent-failure
  bug is happening — record and stop.
- `stats_after.collections["world-bank-ree"]` vs `len(durable)` →
  should match. If not, that's a stats-vs-list-documents drift worth
  a backlog note.
- `errored` count from Step 3 → should be 0 under healthy operation.
  Each `errored` row means the provider raised during that file's
  embedding call. Re-ingest those with `force=True` after the run
  completes; list them in the report.

### Search quality spot-check

Run three canonical queries against the re-ingested collection:

```python
queries = [
    "rare earth elements supply chain",
    "mining environmental impact assessment",
    "lanthanum cerium neodymium",
]
for q in queries:
    r = client.search(q, collection="world-bank-ree", top_k=5)
    print(f"\nquery: {q!r}  hits={r.results_count}")
    for h in r:
        print(f"  score={h.relevance_score:.4f}  doc={h.document_id}  "
              f"text={h.text[:80]!r}")
```

**Expected:**

- Each query returns `top_k` hits (or close to it)
- Top scores are **noticeably > 0** — if all scores cluster near zero,
  embeddings are bad even on the native runtime. Paste the full output
  and **stop**.
- Scores are not uniform across unrelated queries (a uniform score
  distribution means the vector store is returning random rows)

---

## Step 5 — hand off

Write the report to `DAVE_DONE.md`. Required sections:

- **Step 0** — HEAD, health, deployment-freshness note, manifest-row
  counts (total 1891 / ok 574)
- **Step 1** — preflight round-trip result (document_id, chunks,
  warnings, search top hit score). Cleanup result.
- **Step 2** — pre-wipe count + search-score sample, delete_collection
  result, post-wipe count
- **Step 3** — file count, total/ok/stored/errored/fail/with_warnings,
  failure HTTP breakdown, wall-clock elapsed, path to
  `phase_8_ingest_log.json`, any orphan check output
- **Step 4** — durability delta (`len(durable) - stored`), stats
  agreement, three search-query outputs with top-5 scores each, list of
  any `errored` sha1s with their provider error messages
- **Anomalies** — anything unexpected. Especially:
  - Any `fail` that isn't a 5xx (client-side errors are our bug)
  - Any `errored` rows (the new `store_status="error"` path —
    expected to be 0; non-zero = provider intermittent)
  - Any search score < 0.1 on a query that should have strong matches
  - Any document whose ingest response has `warnings` containing
    "Embedding failed" — with `3cd00ba` landed, those should be rare
    and will correlate 1:1 with `store_status="error"`

Do NOT commit. Do NOT push. Sam reviews the report and decides whether
to fire a Bob cleanup/commit pass (e.g., if we learned something worth
recording in `docs/BACKLOG.md` or CLAUDE.md).

---

## Hard gate for Phase 8 completion

All must hold:

1. Step 1 preflight passes (real round-trip score > 0.3)
2. Step 2 wipe confirms 0 remaining
3. Step 3 ingest completes without an unrecoverable error
4. Step 4: `durable == stored` (no silent-failure delta)
5. Step 4: `errored == 0`, or if non-zero, each one has a provider
   error message that explains it and a plan for retry
6. Step 4: all three spot-check queries return hits with plausible
   scores

If 4 fails, we have real evidence that even the post-`3cd00ba` fix
isn't enough — e.g., embeddings succeed but the vector-store write
drops chunks somewhere else. Stop and report without declaring Phase 8
complete.

---

## Future work (NOT Phase 8)

After Phase 8 lands clean, a separate task uses this corpus's content
to generate additional WDS search terms and download the remainder of
the 1,891-row manifest. Do not attempt it in this pass.

---

## Do NOT

- Use `scripts/bulk_ingest.py` — it's broken against the current
  client (flag in backlog if we want to formally retire it)
- Use `client.ingest` — doesn't exist; it's `ingest_file` / `ingest_url`
  / `ingest_bytes`
- Use `client.search_chunks` — it's `search`
- Ingest files that aren't in the 574-row `ok` set from the manifest
  — the rest of the 1,891 rows are a separate future task
- Use `source=str(fp)` (local `D:/...` path) — that's a regression
  from what this task specifically fixed. Use `row["profile_url"]`
- Re-run the full 11-step `DAVE_CLIENT_SMOKE_TEST.md` — Phase 7.5
  already covered it; duplicating it burns an hour for no new signal
- Modify any source file — this is a data op, not a code change
- Commit, push, or stage anything
