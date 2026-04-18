# Review + commit: pytest native-Gemini contract + FIXES.md + phase-6a dataclass gap (phase 7 of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_CODE5_TESTS_AND_FIXES.md`, `DAVE_DONE.md`. Phases 1-6b merged (`db676b0`, `731fb49`, `e0caf2e`, `c5e923e`, `43a286f`, `0b9a39e`, `6db1663`).

Dave rewrote the pytest suite to assert the native Gemini contract, deleted `test_openai_live.py`, added a FIXES.md closure entry — **and surfaced two gaps that make this a bigger phase than originally scoped.** Read `DAVE_DONE.md` end-to-end before anything else. Six anomalies flagged; three of them (1, 4, 5) are real decisions you need to make before committing. Sam reviewed and thinks Dave's judgement calls are correct — this instruction tells you how to proceed.

Scope expanded vs. the original instruction: adds `tests/test_extraction.py`, `src/pipeline/embedding/embedder.py`, and `src/pipeline/enrichment/vision.py` to the tracked-modified list.

---

## Step 0: Fix the pip environment shadow FIRST (anomaly 5)

Before any verification, fix Denson's local Python environment. Dave discovered bare `python -m pytest tests/` resolves to an archived editable install of `ariadne-thread` at `C:\Users\denso\claude_projects\nate_skills\ariadne-thread\src`, not this repo's `src/`. Every `import OK` check in phases 3-6 ran against the archived code.

Run from `ariadne-core/`:

```bash
pip list | grep -iE "ariadne|pipeline"
```

Expect to see **both** `ariadne-core 0.1.0` and `ariadne-thread 0.1.0 (editable)`. Confirm the problem.

Fix:

```bash
pip uninstall -y ariadne-thread
pip uninstall -y ariadne-core   # removes the non-editable version too, clean slate
pip install -e src/
pip list | grep -iE "ariadne|pipeline"
```

After the fix, only `ariadne-core 0.1.0 (editable)` pointing at `...ariadne-core\src` should remain. Verify:

```bash
python -c "import pipeline; print(pipeline.__file__)"
```

Expected path contains `ariadne-core\src\pipeline\__init__.py`. If it still points at `nate_skills\ariadne-thread`, the fix didn't take — investigate before proceeding.

**This step is a local-machine fix, not a repo change.** Nothing to commit from Step 0.

---

## Step 1: Scope check + anomaly inventory

```bash
cd ariadne-core
git status
```

**Expected tracked-modified files** (seven in the commit, plus one deletion):

1. `tests/test_embedding.py` (rewritten)
2. `tests/test_enrichment.py` (rewritten)
3. `tests/test_config.py` (3 clusters)
4. `tests/test_extraction.py` (1 test relaxed — anomaly 3)
5. `FIXES.md` (section 0 prepended)
6. `src/pipeline/embedding/embedder.py` (dataclass defaults — anomaly 4)
7. `src/pipeline/enrichment/vision.py` (dataclass defaults — anomaly 4)

Plus:
- `D tests/test_openai_live.py` (staged deletion via `git rm`)
- `DAVE_DONE.md` (not in the commit)

Pre-existing leftovers (carry-over, ignore): `CLAUDE.md`, `dave_and_bob_communication/BOB_REVIEW.md`, untracked `_phase1_smoke.py`, untracked `scripts/_probe_*.py`, untracked `scripts/_generate_encoding_fixtures.py`. Leave all of them untouched.

Any additional tracked-modified file is out of scope; stop and flag.

---

## Step 2: Read the diff — seven files

```bash
git diff tests/test_embedding.py tests/test_enrichment.py tests/test_config.py \
         tests/test_extraction.py FIXES.md \
         src/pipeline/embedding/embedder.py src/pipeline/enrichment/vision.py
git diff --cached tests/test_openai_live.py   # confirms staged deletion
```

Verify against the per-file checklist in `DAVE_DONE.md` section 1. Key things to eyeball:

### `tests/test_embedding.py`
- Mock payloads use `{"embeddings": [{"values": [...]}]}` shape everywhere (native).
- `test_embed_texts_preserves_order` is gone with a comment explaining why.
- `test_api_call_format` asserts `:batchEmbedContents` suffix, `x-goog-api-key` header (case-insensitive), `"Authorization" not in req.headers`.
- `test_processing_chain_entry` uses `.startswith("gemini:")` (stricter than the instruction specified — fine, anomaly 6).

### `tests/test_enrichment.py`
- `test_describe_image_from_url` uses `mock_urlopen.side_effect = [fetch_resp, api_resp]` — the two-call pattern.
- `test_url_fetch_error_raises_runtime_error` is new, asserts `"Failed to fetch image URL"`.
- `test_processing_chain_entry` asserts `"openai:gemini-2.0-flash"` — that's reality because of anomaly 2 (enricher still uses the wrong prefix). Read the comment Dave left above the assertion; it must make anomaly 2 visible to future readers.

### `tests/test_config.py`
- `test_defaults_without_file` asserts Gemini models.
- `TestInterpolateVars.test_nested_in_url` (lines 63-66) unchanged — that's correct per instruction Step 4d.

### `tests/test_extraction.py` (anomaly 3, scope extension)
- Exactly one test changed: `test_processing_chain_recorded`. `== 1` → `>= 1` with a short comment explaining the phase-5 `encoding_detection` step. No other edits.

### `FIXES.md`
- New section 0 at the top. References all 7 commits (`db676b0`, `731fb49`, `e0caf2e`, `c5e923e`, `43a286f`, `0b9a39e`, `6db1663`). The 7th commit in the section is *this* phase — SHA not known yet, so Dave wrote the commit summary without a SHA; you'll amend after pushing or leave as-is with a hand-wavy "(this commit)" reference. **Sam's preference:** leave the commit-without-SHA line intact, don't amend — SHAs for prior commits are stable, and hunting your own SHA post-push is error-prone.
- Includes anomaly 2 (enricher label) as a "Known carry-forward items" bullet.
- Contains the `PYTHONPATH=src` caveat for the test command. Read it; you may want to update this if Step 0's pip fix removes the need for `PYTHONPATH=src`.

### `src/pipeline/embedding/embedder.py` (anomaly 4)
- Two dataclass default changes at lines 32-36 (Dave's line refs): `model` → `gemini-embedding-001`, `provider` → `google-gemini`, `base_url` → `https://generativelanguage.googleapis.com/v1beta`. No other edits to the module. Verify: the HTTP logic, endpoint construction, header handling, response parsing, retry behavior, and error wording must be untouched.

### `src/pipeline/enrichment/vision.py` (anomaly 4)
- Two dataclass default changes at lines 32-35: `base_url` → Gemini native, `model` → `gemini-2.0-flash`. `prompt` and `api_key` unchanged. Nothing else in the module touched.

---

## Step 3: Hard gate — pytest must pass green

After Step 0's pip fix, the bare command should work. Run both forms — they should produce identical results:

```bash
cd ariadne-core
python -m pytest tests/ -v \
  --ignore=tests/test_api.py \
  --ignore=tests/test_ingest.py \
  --ignore=tests/test_mcp.py \
  --ignore=tests/test_search_filters.py
```

```bash
# Sanity check — same command without PYTHONPATH, should match
python -m pytest tests/test_embedding.py tests/test_enrichment.py tests/test_config.py tests/test_extraction.py -v
```

**Expected:**
- First form: `174 passed` (or whatever exact number Dave saw — match it).
- Second form: focused subset passes green.
- Zero skips of substance. One pre-existing `pytest-asyncio` deprecation warning is tolerable.

**Hard gate:** both commands green. If either goes red, stop and investigate. Do not commit a red suite.

If the suite passes only with `PYTHONPATH=src` and not bare, Step 0's pip fix didn't fully take — re-read anomaly 5 and try again.

---

## Step 4: Deal with anomaly 1 — the four orphan test files

Dave's `--ignore=` workaround gets the phase-7 hard gate to pass, but those four files are broken-on-main right now. They import `pipeline.mcp_server` which hasn't existed since commit `e0ccb12`. Nobody can run `pytest tests/` without `--ignore` flags.

**Sam's call: delete them in this same commit.**

Rationale: (a) they test a module that doesn't exist; (b) rewriting them against `pipeline/services.py` would be a substantial new piece of work — a phase of its own; (c) keeping them around forces every future contributor to remember the `--ignore` incantation; (d) they were shipped broken and the editable-install shadow (anomaly 5) has been masking that for an unknown period. Cleanest and honest.

```bash
cd ariadne-core
git rm tests/test_api.py tests/test_ingest.py tests/test_mcp.py tests/test_search_filters.py
```

After deletion:

```bash
python -m pytest tests/ -v
```

Should pass green **without** `--ignore` flags. That's the real hard gate now.

Add one line to `FIXES.md` (in the section-0 "Known carry-forward items" list or a new "Also cleaned up in this commit" sentence): note that the four mcp_server-dependent test files were deleted.

The eight tracked-modified files plus four deletions give a single coherent commit.

---

## Step 5: Grep sanity

```bash
cd ariadne-core
grep -n "openai:\|openai\.com\|/embeddings\|/chat/completions\|text-embedding-3-small\|gpt-4o-mini" tests/
grep -n "mcp_server" tests/
```

- **First grep:** four allowed hits — `test_config.py:63/66` (interpolation test string) and `test_enrichment.py:203/206` (the enricher-label reality assertion with its explanatory comment). Zero hits elsewhere.
- **Second grep:** zero hits after Step 4's deletion. If there are hits, you missed a file.

---

## Step 6: Commit + push

Suggested subject: `Update pytest suite for native Gemini contract + fix phase-6a dataclass gap`

Body: rewrites the embedding and enrichment test mocks to the native Gemini HTTP contract (`:batchEmbedContents`, `:generateContent`, `inlineData` image parts, `x-goog-api-key` header) and response shapes (`embeddings[].values`, `candidates[0].content.parts[].text`). Updates default-value assertions in `test_config.py` to the new Gemini runtime defaults. Deletes the obsolete `tests/test_openai_live.py` (superseded by `scripts/_probe_embedder.py`). Adds a new `test_url_fetch_error_raises_runtime_error` covering the server-side URL-fetch failure mode introduced in phase 4. Also fixes a phase-6a scope gap: the per-module `EmbeddingConfig` and `VisionConfig` dataclass defaults at `embedder.py` and `vision.py` were missed in commit `0b9a39e` (which updated only the duplicate in `config.py`) — this commit aligns them. Relaxes `test_processing_chain_recorded` for the `encoding_detection` step added in phase 5. Deletes four orphan test files (`test_api.py`, `test_ingest.py`, `test_mcp.py`, `test_search_filters.py`) that imported the removed `pipeline.mcp_server` module. Appends FIXES.md section 0 documenting the full 7-phase migration. References SPEC.md `### Provider constraints`. Phase 7 of the native-Gemini migration.

Push to default branch.

---

## Step 7: Backlog items

Copy verbatim into `BOB_DONE.md`:

1. **Enricher tool-label still emits `openai:{model}`** — `src/pipeline/enrichment/images.py:151` hardcodes `f"openai:{self._config.model}"`. One-line fix (`openai` → `gemini`) to land in its own commit for clean provenance. Flagged by Dave as anomaly 2; referenced in `FIXES.md` section 0 "Known carry-forward items."

2. **Pip environment hygiene** — Denson had an editable install of the archived `ariadne-thread` package shadowing the current repo's `pipeline` module. Fixed in Step 0 on Bob's local machine. Contributors cloning fresh won't hit this, but the `ariadne-core-build` skill or an onboarding doc should mention `pip install -e src/` as a required setup step and flag that older Ariadne forks must be uninstalled first.

3. **Phase 6c (roadmap docs) still pending.** Blocked on Sam reading `docs/TOKEN_SAVINGS_FRAMING.md` and clearing specific edits with Denson per the token-savings guardrail.

4. **Phase 7.5 (live smoke test) to be authored next.** Covers end-to-end Railway deployment health + single-document ingest + language-validator hot path before Phase 8's 574-file world-bank re-ingest.

Do **not** fix any of these in this commit.

---

## Step 8: Report

Write completion to `BOB_DONE.md`: commit SHA, push target, confirmation that:

- Step 0's pip fix took and bare `python -m pytest tests/` now runs against this repo's `src/`.
- Final tracked-modified list (seven files) + four deletions + one pre-staged deletion (`test_openai_live.py`).
- `pytest tests/ -v` passes green **without** `--ignore` flags after Step 4.
- Your Step 3 pytest output (pass count and timing).
- Your Step 5 grep output.
- The four backlog items verbatim.

No Railway action required this phase.
