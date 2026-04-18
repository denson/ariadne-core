# BOB — Commit silent-embedding-failure gate

Dave landed the fix per `DAVE_EMBED_FAIL_GATE.md`. Three source paths
plus `DAVE_DONE.md` to stage, commit, and push. No source edits,
no extra files.

**Why this matters:** pre-Phase-8 insurance. On a `RuntimeError` from
the embedding provider, `services.py` used to swallow it into a
warning string and still set `store_status="stored"`, inserting
chunks without embeddings — the "555 successes, most poisoned"
pattern from the pre-migration run. With 574 World Bank files about
to ingest, this hole had to close first.

---

## Step 0 — pre-flight

```
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**
- `HEAD` and `origin/main` both at `da826cc`
- Unstaged modified: ` M SPEC.md`, ` M src/pipeline/services.py`
- Untracked: `?? tests/test_services.py` plus the ongoing 4 helper scripts
  - `scripts/_generate_encoding_fixtures.py`
  - `scripts/_probe_embedder.py`
  - `scripts/_probe_text_encoding.py`
  - `scripts/_probe_vision.py`
- Nothing staged

If anything else is present (extra modified/untracked files, anything
staged, different HEAD), **stop and report**. Do not "fix" drift
yourself.

---

## Step 1 — scope tripwire

You are allowed to stage exactly these paths (and nothing else):

1. `src/pipeline/services.py`
2. `SPEC.md`
3. `tests/test_services.py`
4. `dave_and_bob_communication/DAVE_DONE.md`

Before staging, eyeball the diff:

```
git diff -- src/pipeline/services.py SPEC.md
git diff --no-index /dev/null tests/test_services.py | head -100
```

Scope expectations:

- **`src/pipeline/services.py`** — one added `embedding_failed = False`
  flag, one `embedding_failed = True` in the `except RuntimeError`
  branch, `if chunks and not embedding_failed:` gate on the
  `_vector_store.insert` block, and a new `if embedding_failed: ...
  else: ...` that writes `store_status="error"` / `chunks_count=0` on
  failure or `"stored"` on success. Nothing else.

- **`SPEC.md`** — the `store_status` parenthetical on line 374 expands
  from `"stored"` / `"not_stored"` / `"skipped"` to include
  `/ "error"`, and a new `**Embedding-failure behavior:**` paragraph
  is added after the existing `**Dedup behavior:**` paragraph,
  before `**Chunking auto-selection:**`. Nothing else.

- **`tests/test_services.py`** — new file, ~60 lines, one test
  `test_embedding_failure_sets_store_status_error_and_skips_vector_write`
  using monkeypatch against `services._embedding_client` and
  `services._vector_store`.

If any diff shows a change outside that set — an unrelated line tweak,
a lint-style rewrite, an import reorder in a different file, a touched
test outside `tests/test_services.py` — **stop and report**. Do not
stage. The whole point of the tripwire is that scope drift gets
caught here, not after the commit.

**Known benign noise:**
- Git may emit a CRLF warning on `services.py` when staging on Windows
  (informational; no content affected). Dave saw one during his run.
- Staging `DAVE_DONE.md` may emit a cosmetic
  `dave_and_bob_communication/ ignored` warning and exit 1 despite
  succeeding — `dave_and_bob_communication/` is gitignored with
  explicit negation for `DAVE_DONE.md` (commit `86cebe2`). Trust
  `git status --short` over the exit code. Never `git add -f`.

---

## Step 2 — stage

```
git add src/pipeline/services.py SPEC.md tests/test_services.py dave_and_bob_communication/DAVE_DONE.md
git status --short
```

Expected output after staging:

```
M  SPEC.md
M  src/pipeline/services.py
A  dave_and_bob_communication/DAVE_DONE.md
A  tests/test_services.py
?? scripts/_generate_encoding_fixtures.py
?? scripts/_probe_embedder.py
?? scripts/_probe_text_encoding.py
?? scripts/_probe_vision.py
```

4 staged, 4 untracked (helpers). If the count differs, **stop and
report**.

---

## Step 3 — HARD GATE: pytest

Run the full test suite one more time from the staged state. This
catches the case where Dave's local run was green but something on
`main` drifted between his pre-flight and yours (unlikely at this
`HEAD`, but cheap insurance):

```
python -m pytest tests/ -v
```

**Expected:** `178 passed`. (Note: `DAVE_EMBED_FAIL_GATE.md` projected
179; Dave flagged the off-by-one — baseline was 177, not 178.
Either number being exceeded would be fine; anything below 178 or any
failure is a red gate.)

If red → **stop and report** with the full failure section. Do not
commit on a red gate.

---

## Step 4 — commit

```
git commit -m "$(cat <<'EOF'
Close silent-embedding-failure gate in services.py

Pre-Phase-8 insurance. On a RuntimeError from the embedding provider
during a store-mode ingest, services.py previously swallowed the error
into a warning string but still set store_status="stored" and inserted
the chunks into the vector store without embeddings. Result: documents
appeared stored, list_documents counted them, but vector search
returned zero hits -- the "555 successes, most poisoned" pattern from
the pre-migration run.

The fix:

- src/pipeline/services.py: on embedding RuntimeError, skip the
  vector-store insert, set store_status="error", set chunks_count=0.
  The document markdown itself is still stored in the dedup store
  (that write happened earlier at line 267 when extraction succeeded),
  so a future retry with force=true can find it by fingerprint after
  the provider issue is fixed.
- SPEC.md: add "error" to the store_status enum; document the
  embedding-failure contract in a new paragraph alongside Dedup
  behavior.
- tests/test_services.py: new file. One regression test using
  monkeypatch to replace services._embedding_client with a stub
  that raises RuntimeError from embed_texts, and services._vector_store
  with a fresh InMemoryVectorStore. Asserts store_status="error",
  chunks_count=0, warning present, and nothing inserted into the
  vector store.

Test count 177 -> 178 passed. No existing tests regressed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git log -1 --oneline
```

Expected: one new commit on top of `da826cc`.

---

## Step 5 — push

```
git push origin main
git rev-parse origin/main
git status --short
```

Final `git status --short`: only the 4 helper scripts as `??`.
`origin/main` should match `HEAD`.

---

## Report back

- Step 0 output
- Step 1 scope-tripwire verdict (clean or drift)
- Stage-list `git status --short`
- pytest summary line (e.g. `178 passed in 8.42s`)
- New commit SHA + one-line message
- `origin/main` confirmation
- Final `git status --short`

---

## Do NOT

- Stage any helper script
- Edit any of the four staged files — if anything looks wrong, stop
  and report rather than "fixing" it. Scope drift caught here is the
  whole point.
- Amend or rebase. New commit only.
- Push with `--force` or `--no-verify`.
- Add a trailer, label, or body text not in the commit message above.
