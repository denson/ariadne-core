# Test fixtures

Byte-level fixtures for the extraction + encoding-validator pipeline.

## Files

| File | What it is |
|------|-----------|
| `clean_english_sample.txt` | UTF-8 English text. Known-good input. |
| `mojibake_sample.txt` | The same text deliberately corrupted: UTF-8 bytes decoded as cp1252 (produces sequences like `â€™s CEO`, `â€œ...â€`). Known-garbled input. |

## Expected pipeline behavior

A correct ariadne-core pipeline produces these `encoding_detection`
chain entries:

| Fixture | `encoding_confidence` | `llm_coherent` | `coherent` (final) | Suggested tags |
|---------|----------------------|----------------|--------------------|----------------|
| clean   | > 0.5                | true           | true               | `language:en` only |
| mojibake | ≈ 0.0               | true (LLM reads through mojibake) | **false** (byte gate overrides) | `language:en`, `encoding:suspect`, `status:needs-review` |

If both fixtures produce `coherent=true`, the byte-confidence gate at
`src/pipeline/extraction/markitdown.py` is bypassed or broken. If the
mojibake fixture produces `coherent=true` and no `encoding:suspect`
tag, the validator is trusting the LLM's raw vote — that's the exact
bug Phase 7.5 was built to catch (see commit `5d239cd` + `08bfde2`).

## Why these are tracked as bytes, not regenerated

Mojibake is hard to reproduce byte-for-byte across machines — terminal
encoding, editor autocorrect, and Python's default encoding can all
silently normalize the bytes back to valid UTF-8. Tracking the exact
bytes makes the live-smoke tests deterministic across environments.

## Regenerating (only if you really need to)

```bash
python scripts/_generate_encoding_fixtures.py
```

Note: the generator's final preview `print()` crashes on Windows
`cp1252` consoles. The files are written correctly before the crash.

## Use in testing

**Unit tests** (`tests/test_extraction.py`) stub `detect_and_decode` and
`validate_language` via `monkeypatch` — they don't read these files.
Keep that way for hermeticity.

**Live smoke** (`dave_and_bob_communication/DAVE_PHASE_7_5_SMOKE_TEST.md`)
ingests these fixtures against a real deployment to verify:

- The embedder actually reaches the configured provider (not a mock)
- The language validator's byte-confidence gate fires on real mojibake
- The suggested-tag block picks up the gate signal

## Building your own pipeline on top of ariadne-core

If you fork ariadne-core to run a different extraction or validation
path, drop these fixtures into your own test suite. They're a cheap
way to prove two things:

1. Your encoding-detection path actually runs — if both fixtures return
   `coherent=true`, your gate is probably bypassed.
2. Your language validator doesn't false-positive on clean text.
