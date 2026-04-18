# BOB — Phase 7 diagnostic (DO NOT COMMIT)

Pause `BOB_CODE5_TESTS_AND_FIXES.md` at Step 0. Do **not** commit anything. Sam
needs a clean read of on-disk state before deciding how to proceed with Phase 7.

Please do the following and report back. Report every section — do not
summarize or skip.

---

## 1. Fix the pip environment shadow (required before anything else is trustworthy)

```
pip uninstall -y ariadne-thread
pip uninstall -y ariadne-core
pip install -e src/
python -c "import pipeline, sys; print(pipeline.__file__); print(sys.executable)"
```

Report both paths. The `pipeline.__file__` must point inside
`ariadne-core\src\pipeline\__init__.py`. If it does not, **stop and tell Sam
what it points at instead**.

## 2. Show Dave's uncommitted changes in full

```
git status
git diff --stat
git diff
```

Paste all three. Do **not** truncate the diff — Sam needs to see every line
Dave touched.

## 3. Run pytest bare and paste the full output

No `PYTHONPATH=src`, no `--ignore`, no other flags:

```
python -m pytest tests/ -v
```

Do not delete any test files yet. If it fails on the four orphan test files
(`test_api.py`, `test_ingest.py`, `test_mcp.py`, `test_search_filters.py`),
that is expected — Sam wants to see exactly how it fails.

## 4. Report current state of three specific locations

- `src/pipeline/enrichment/images.py` line 151 — paste the full line. Sam wants
  to know if the `openai:` vs `gemini:` tool label was touched.
- `src/pipeline/embedding/embedder.py` lines 30–40 — paste the `EmbeddingConfig`
  dataclass defaults.
- `src/pipeline/enrichment/vision.py` lines 30–40 — paste the `VisionConfig`
  dataclass defaults.

## 5. Do NOT

- Commit
- Push
- Delete any files
- Edit any files (beyond the pip uninstall/reinstall in Step 1)
- Run `git add`

---

Report back with all five sections in a single response. Sam will decide next
steps after reading.
