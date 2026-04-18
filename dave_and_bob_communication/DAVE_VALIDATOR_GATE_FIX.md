# DAVE — Fix language validator's byte-vs-LLM signal gate

Phase 7.5 caught a real bug: the language validator's final `coherent`
field is the LLM's vote alone, ignoring charset-normalizer's byte-level
confidence. Frontier LLMs can "read through" mojibake — they parse
`â€™s CEO` as `'s CEO` and vote `coherent=true, language=en, confidence=high`
— while the byte detector correctly reports `encoding_confidence=0.0`.

The fix: AND-gate the two signals. If either says garbled, the text is
garbled. Preserve the LLM's raw opinion in a separate field so the bug
signal is still visible in the chain.

---

## Scope

One source edit, one test addition, unit-test hard gate, commit, push.

No change to `src/pipeline/extraction/text_encoding.py` itself — the
functions `detect_and_decode` and `validate_language` stay pure
(each returns its own signal). The gate goes at the call site in
`markitdown.py` where both signals are already in scope.

---

## Step 0 — pre-flight

```
git status
git rev-parse HEAD
git rev-parse origin/main
```

Both at `98964dc`. Working tree clean except 5 untracked helper scripts.

---

## Step 1 — edit `src/pipeline/extraction/markitdown.py`

Find the block that appends the `encoding_detection` entry to
`processing_chain`. It currently reads roughly:

```python
            processing_chain.append({
                "step": "encoding_detection",
                "detected_encoding": detected_encoding,
                "encoding_confidence": enc_confidence,
                "language": lang_result.language,
                "language_script": lang_result.script,
                "language_confidence": lang_result.confidence,
                "coherent": lang_result.coherent,
                "llm_model": lang_result.model,
                "ts": datetime.now(timezone.utc).isoformat(),
                "ms": validation_ms,
            })
```

Replace the whole append call with:

```python
            # Combine byte-level encoding confidence with the LLM's coherence
            # vote. Frontier LLMs can read English through mojibake (they
            # parse 'â€™' as a curly apostrophe), so the LLM will vote
            # coherent=true on a file that charset-normalizer correctly
            # scored 0.0. If either signal says garbled, the text is
            # garbled. Threshold is deliberately generous (0.5): legitimate
            # rare encodings can score lower than 1.0 but should still be
            # above 0.5 on any real text.
            ENCODING_CONFIDENCE_THRESHOLD = 0.5
            bytes_ok = enc_confidence >= ENCODING_CONFIDENCE_THRESHOLD
            final_coherent = lang_result.coherent and bytes_ok

            processing_chain.append({
                "step": "encoding_detection",
                "detected_encoding": detected_encoding,
                "encoding_confidence": enc_confidence,
                "language": lang_result.language,
                "language_script": lang_result.script,
                "language_confidence": lang_result.confidence,
                "coherent": final_coherent,
                "llm_coherent": lang_result.coherent,
                "llm_model": lang_result.model,
                "ts": datetime.now(timezone.utc).isoformat(),
                "ms": validation_ms,
            })
```

Then, a few lines below, the warnings block currently fires on
`lang_result.coherent`:

```python
            if not lang_result.coherent:
                warnings.append("Encoding validation: text may be garbled")
```

Change to fire on `final_coherent` so the warning reflects the combined
decision:

```python
            if not final_coherent:
                warnings.append("Encoding validation: text may be garbled")
```

Keep everything else in that block unchanged.

---

## Step 2 — add a unit test to `tests/test_extraction.py`

Add a test that simulates the exact failure Phase 7.5 caught: a file
where `detect_and_decode` returns low byte-confidence but `validate_language`
returns `coherent=True` (LLM fooled). The `encoding_detection` chain entry
must have `coherent=False` and `llm_coherent=True`.

Stub `detect_and_decode` and `validate_language` with `monkeypatch` so the
test is hermetic (no LLM call). Use a `.txt` path.

Rough shape:

```python
def test_encoding_detection_gate_overrides_llm_on_low_byte_confidence(
    tmp_path, monkeypatch
):
    """Mojibake: byte detector says low confidence; LLM is fooled and votes
    coherent=true. Final coherent must be False."""
    from pipeline.extraction import markitdown as md_mod
    from pipeline.extraction.text_encoding import LanguageValidation

    fake_txt = tmp_path / "mojibake.txt"
    fake_txt.write_text("pretend this is mojibake", encoding="utf-8")

    def fake_detect(path):
        return ("pretend decoded text", "windows-1252", 0.0)

    def fake_validate(text, config):
        return LanguageValidation(
            coherent=True,
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

    enc_step = next(
        (s for s in result.processing_chain if s["step"] == "encoding_detection"),
        None,
    )
    assert enc_step is not None, "encoding_detection step missing from chain"
    assert enc_step["coherent"] is False, (
        f"Expected coherent=False when byte confidence is 0.0 "
        f"(mojibake gate), got {enc_step}"
    )
    assert enc_step["llm_coherent"] is True, (
        "LLM's raw opinion should still be preserved in llm_coherent"
    )
    assert enc_step["encoding_confidence"] == 0.0
```

**Verify the extractor class name and entry-point method** before writing
the test — if the class isn't `MarkItDownExtractor` or the method isn't
`extract`, adjust. Other tests in `test_extraction.py` show the correct
shape.

Also add a complementary test for the happy path: byte confidence high
AND LLM says coherent → final coherent=True. Same pattern, different
stub values (`enc_confidence=0.9`, `lang_result.coherent=True`).

---

## Step 3 — HARD GATE: bare pytest

```
python -m pytest tests/ -v
```

Must be 176/176 (174 pre-existing + 2 new). If any test fails, **stop and
report** — do not commit.

---

## Step 4 — stage, commit, push

```
git add src/pipeline/extraction/markitdown.py tests/test_extraction.py
git status --short
```

Expected: two staged files, nothing else.

```
git commit -m "$(cat <<'EOF'
Gate coherent flag on byte-level encoding confidence

Phase 7.5 live smoke caught a validator bug: mojibake text (UTF-8
bytes decoded as cp1252 -- e.g. "â€™" for curly apostrophe) was
flagged coherent=true by the Gemini language validator despite
charset-normalizer reporting encoding_confidence=0.0. Frontier LLMs
read through the encoding noise and parse the text as English, so
the LLM vote alone is insufficient to detect mojibake.

Fix: AND-gate the LLM's coherent vote with a byte-level confidence
threshold (0.5). If either signal says garbled, the final coherent
flag is False. Preserve the LLM's raw opinion as llm_coherent in
the processing_chain entry for debugging.

Verified by new unit tests:
  test_encoding_detection_gate_overrides_llm_on_low_byte_confidence
  test_encoding_detection_happy_path_both_signals_agree

Full pytest suite 176/176 green.

Phase 8 (world-bank re-ingest) remains blocked until Phase 7.5 is
re-run against the live Railway deployment and confirms the fix.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main
git log -1 --oneline
git rev-parse origin/main
```

---

## Step 5 — write DAVE_DONE.md

Overwrite `dave_and_bob_communication/DAVE_DONE.md` with a short report:

- What changed (source edit, two new tests)
- Commit SHA
- pytest count before/after
- Note that this commit does NOT re-run Phase 7.5 live — Sam will redeploy
  Railway and re-trigger smoke

---

## Do NOT

- Touch `src/pipeline/extraction/text_encoding.py` — the gate goes at the
  call site, not inside the validator
- Change the threshold without flagging — 0.5 is deliberate, if you think
  it should be different, stop and report before committing
- Run Phase 7.5 live — that's Sam's re-trigger after redeploy
- Rewrite the warning or the rest of the `encoding_detection` handling
  beyond what's prescribed

Bob will review after, then Sam will trigger Railway redeploy and Dave's
Phase 7.5 re-run.
