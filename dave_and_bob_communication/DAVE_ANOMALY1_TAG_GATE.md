# DAVE — Anomaly 1: Wire the tag block through `final_coherent`

Phase 7.5 post-fix smoke caught a partial-fix: the validator-gate commit
(`5d239cd`) updated the warning block to `final_coherent` but left the
suggested-tag block a few lines below reading the raw `lang_result.coherent`.
Observed consequence in the live run: the mojibake doc had
`coherent=false` in the chain entry and the garbled-text warning fired,
but its tags were `["language:en"]` only — no `encoding:suspect`, no
`status:needs-review`. Agents filtering by those tags can't find it.

One-line source change. One new unit test. Hard gate: full pytest green.

Phase 8 (world-bank re-ingest, 574 files) is held behind this so the
corpus lands with correct tags the first time.

**Process:** you write the code + tests and run the hard gate. You do
NOT stage, commit, or push. Leave the diff unstaged in the working
tree and hand off to Bob via `DAVE_DONE.md`. Bob reviews and commits.

---

## Scope

- `src/pipeline/extraction/markitdown.py` — line 208, change
  `lang_result.coherent` to `final_coherent`
- `tests/test_extraction.py` — one new test asserting the mojibake
  (low byte-confidence, LLM fooled) case gets both `encoding:suspect`
  and `status:needs-review` in its suggested_tags
- No other edits. Do not broaden scope.

---

## Step 0 — pre-flight

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**
- `HEAD` and `origin/main` both at `e632181` (Backlog-6+7 commit)
- Modified/staged: nothing
- Untracked: 4 `scripts/_probe*.py` + `scripts/_generate_encoding_fixtures.py`
  + `tests/fixtures/clean_english_sample.txt` + `tests/fixtures/mojibake_sample.txt`
  + any `DAVE_*.md` / `BOB_*.md` diagnostic files

If anything else is modified or staged, **stop and report**.

---

## Step 1 — edit `src/pipeline/extraction/markitdown.py` line 208

Current block (lines 205–210):

```python
            suggested_tags.append(f"language:{lang_result.language}")
            if lang_result.confidence == "low":
                suggested_tags.append("encoding:low-confidence")
            if not lang_result.coherent:
                suggested_tags.append("encoding:suspect")
                suggested_tags.append("status:needs-review")
```

Change line 208 from `if not lang_result.coherent:` to
`if not final_coherent:`. Nothing else in the file.

Verify:

```
git diff -- src/pipeline/extraction/markitdown.py
```

Diff should be exactly one line removed and one line added, identical
except `lang_result.coherent` → `final_coherent`. Stop if scope drifts.

**Intent check:** `final_coherent` is defined a few lines above (line 175)
as `lang_result.coherent and bytes_ok`, so a doc that either the LLM
flagged garbled OR the byte detector flagged garbled now gets the
`encoding:suspect` + `status:needs-review` tags. The clean-text happy
path (both signals agree coherent=true) still gets no suspect tag.

---

## Step 2 — add a unit test to `tests/test_extraction.py`

Mirror the shape of the two gate tests from `DAVE_VALIDATOR_GATE_FIX.md`
(the `test_encoding_detection_gate_overrides_llm_on_low_byte_confidence`
pattern). Stub `detect_and_decode` and `validate_language` with
`monkeypatch` — no live LLM.

Rough shape:

```python
def test_encoding_gate_drives_suspect_tags_on_mojibake(
    tmp_path, monkeypatch
):
    """Mojibake: byte detector says low confidence; LLM is fooled and
    votes coherent=true. Suggested tags must include encoding:suspect
    and status:needs-review so agents can filter the doc out of search."""
    from pipeline.extraction import markitdown as md_mod
    from pipeline.extraction.text_encoding import LanguageValidation

    fake_txt = tmp_path / "mojibake.txt"
    fake_txt.write_text("pretend this is mojibake", encoding="utf-8")

    def fake_detect(path):
        return ("pretend decoded text", "windows-1252", 0.0)

    def fake_validate(text, config):
        return LanguageValidation(
            coherent=True,  # LLM fooled
            language="en",
            script="Latin",
            confidence="high",
            notes="",
            model="gemini-2.0-flash",
            skipped=False,
        )

    monkeypatch.setattr(md_mod, "detect_and_decode", fake_detect)
    monkeypatch.setattr(md_mod, "validate_language", fake_validate)

    extractor = md_mod.MarkItDownExtractor()
    result = extractor.extract(str(fake_txt))

    assert "encoding:suspect" in result.suggested_tags, (
        f"Expected encoding:suspect tag when byte confidence is 0.0 "
        f"(mojibake gate), got {result.suggested_tags}"
    )
    assert "status:needs-review" in result.suggested_tags, (
        f"Expected status:needs-review tag when byte confidence is 0.0, "
        f"got {result.suggested_tags}"
    )
```

**Verify the attribute name** before running — if `suggested_tags` lives
at a different path on the `ExtractionResult` dataclass, adjust. The
existing tests in `test_extraction.py` show the correct shape.

Optionally add a complementary happy-path negative assertion: clean
text (byte confidence 0.9, LLM coherent=true) must NOT add the suspect
tags. The existing validator-gate happy-path test may already cover
this — check before duplicating.

---

## Step 3 — HARD GATE: bare pytest

```
python -m pytest tests/ -v
```

Must be 177/177 (176 from `5d239cd` + 1 new). If any test fails,
**stop and report** — do not commit.

If you added the complementary happy-path assertion and it's a new test
(not a modification of an existing one), expect 178/178 — report the
delta.

---

## Step 4 — hand off (do NOT stage, commit, or push)

Leave the two modified files unstaged in the working tree. Bob commits.

Run a final `git status --short` and confirm:
- ` M src/pipeline/extraction/markitdown.py`
- ` M tests/test_extraction.py`
- Plus the same untracked set as Step 0 (no new untracked files unless
  pytest produced cache/artifacts, which is fine)

If anything else is modified, **stop and report**.

---

## Step 5 — overwrite `dave_and_bob_communication/DAVE_DONE.md`

Short report for Bob:

- What changed (one-line source edit at `markitdown.py:208`, one new
  test in `tests/test_extraction.py` — name it)
- Paste the full `git diff` (should be small — the one-line src change
  plus the new test function)
- pytest count before/after (176 → 177 expected; 178 if you added the
  happy-path negative assertion as a new test)
- Note: this does NOT re-run Phase 7.5 live. The validator-gate smoke
  collection `smoke_phase_7_5_20260417_post_fix` already proved the
  gate itself works; the tag regression was read off that same run.
  Re-smoke is optional before Phase 8; Sam's call.

Bob will review, stage, commit, and push.

---

## Do NOT

- Touch the warning block (line 198) — it already reads `final_coherent`
  correctly as of `5d239cd`
- Change the `encoding:low-confidence` tag above — that one's keyed on
  `lang_result.confidence == "low"` which is the right signal for its
  purpose (LLM confidence, not coherence)
- Re-run live smoke — collection `smoke_phase_7_5_20260417_post_fix` on
  Railway already contains the evidence. Re-smoke is Sam's trigger
- Broaden to anomaly 2/3/4 from Dave's Phase 7.5 report — those stay
  deferred

Bob will review after, then Sam calls whether to re-smoke or go
straight to Phase 8.
