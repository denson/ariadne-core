# DAVE — Anomaly 1 tag-gate fix: DONE (unstaged, awaiting Bob)

Per `DAVE_ANOMALY1_TAG_GATE.md`. One-line source fix + one new unit test.
Working tree left unstaged for Bob to commit.

## Pre-flight (Step 0)

- `HEAD` = `e632181c1aaa29803873bcb0d3b6078010302347`
- `origin/main` = `e632181c1aaa29803873bcb0d3b6078010302347`
- Nothing modified/staged on entry. Untracked set matched spec (4 `scripts/_probe*.py` + `scripts/_generate_encoding_fixtures.py` + 2 fixtures).

## What changed

### Source (one-line fix)

`src/pipeline/extraction/markitdown.py` line 208: `lang_result.coherent` → `final_coherent` inside the suggested-tag block, so `encoding:suspect` and `status:needs-review` tags now fire when either the byte detector OR the LLM flags garbled (matching the `final_coherent` gate definition already in use one block above).

### Test (one new test)

`tests/test_extraction.py`: appended module-level function

- **`test_encoding_gate_drives_suspect_tags_on_mojibake`** — stubs `detect_and_decode` to return `("pretend decoded text", "windows-1252", 0.0)` and `validate_language` to return `coherent=True, confidence=high` (the mojibake-fooled-LLM scenario). Asserts `result.suggested_tags` includes both `encoding:suspect` and `status:needs-review`. Did NOT add a complementary happy-path negative assertion — `test_encoding_detection_happy_path_both_signals_agree` already covers the clean-text case, which implicitly exercises the same code path via `final_coherent=True`.

## Full git diff

```diff
diff --git a/src/pipeline/extraction/markitdown.py b/src/pipeline/extraction/markitdown.py
index 01f25a6..b4518c1 100644
--- a/src/pipeline/extraction/markitdown.py
+++ b/src/pipeline/extraction/markitdown.py
@@ -205,7 +205,7 @@ class MarkItDownExtractor:
                 suggested_tags.append(f"language:{lang_result.language}")
             if lang_result.confidence == "low":
                 suggested_tags.append("encoding:low-confidence")
-            if not lang_result.coherent:
+            if not final_coherent:
                 suggested_tags.append("encoding:suspect")
                 suggested_tags.append("status:needs-review")

diff --git a/tests/test_extraction.py b/tests/test_extraction.py
index 64a2fbb..7f3fd46 100644
--- a/tests/test_extraction.py
+++ b/tests/test_extraction.py
@@ -174,3 +174,43 @@ def test_encoding_detection_happy_path_both_signals_agree(tmp_path, monkeypatch)
     assert not any(
         "text may be garbled" in w for w in result.warnings
     ), "No garbled-text warning on happy path"
+
+
+def test_encoding_gate_drives_suspect_tags_on_mojibake(tmp_path, monkeypatch):
+    """Mojibake: byte detector says low confidence; LLM is fooled and votes
+    coherent=true. Suggested tags must include encoding:suspect and
+    status:needs-review so agents can filter the doc out of search."""
+    from pipeline.extraction import markitdown as md_mod
+    from pipeline.extraction.text_encoding import LanguageValidation
+
+    fake_txt = tmp_path / "mojibake.txt"
+    fake_txt.write_text("pretend this is mojibake", encoding="utf-8")
+
+    def fake_detect(path):
+        return ("pretend decoded text", "windows-1252", 0.0)
+
+    def fake_validate(text, config):
+        return LanguageValidation(
+            coherent=True,
+            language="en",
+            script="Latin",
+            confidence="high",
+            notes="",
+            model="gemini-2.0-flash",
+            skipped=False,
+        )
+
+    monkeypatch.setattr(md_mod, "detect_and_decode", fake_detect)
+    monkeypatch.setattr(md_mod, "validate_language", fake_validate)
+
+    extractor = md_mod.MarkItDownExtractor(enable_plugins=False)
+    result = extractor.extract(str(fake_txt))
+
+    assert "encoding:suspect" in result.suggested_tags, (
+        f"Expected encoding:suspect tag when byte confidence is 0.0 "
+        f"(mojibake gate), got {result.suggested_tags}"
+    )
+    assert "status:needs-review" in result.suggested_tags, (
+        f"Expected status:needs-review tag when byte confidence is 0.0, "
+        f"got {result.suggested_tags}"
+    )
```

## Hard gate

```
python -m pytest tests/ -v
...
tests/test_extraction.py::test_encoding_detection_gate_overrides_llm_on_low_byte_confidence PASSED
tests/test_extraction.py::test_encoding_detection_happy_path_both_signals_agree PASSED
tests/test_extraction.py::test_encoding_gate_drives_suspect_tags_on_mojibake PASSED
...
============================= 177 passed in 7.35s =============================
```

Count delta: **176 → 177** (one new test, no happy-path add).

## Working tree (for Bob)

```
 M src/pipeline/extraction/markitdown.py
 M tests/test_extraction.py
?? scripts/_generate_encoding_fixtures.py
?? scripts/_probe_embedder.py
?? scripts/_probe_text_encoding.py
?? scripts/_probe_vision.py
?? tests/fixtures/clean_english_sample.txt
?? tests/fixtures/mojibake_sample.txt
```

Exactly the two modified files from the spec + the untracked set from Step 0. Nothing staged, nothing committed, nothing pushed — hand-off intact per "do NOT stage/commit/push" instruction.

## Notes

- No live Phase 7.5 re-run. The existing `smoke_phase_7_5_20260417_post_fix` collection on Railway already contains the evidence the gate itself works; this fix corrects a downstream tag-emission regression observed from that same run. Re-smoke before Phase 8 is Sam's call.
- No scope drift: anomalies 2/3/4 from the Phase 7.5 report remain deferred. Warning block (line 198) and `encoding:low-confidence` tag were not touched.

Bob: review, stage the two files, commit, push.
