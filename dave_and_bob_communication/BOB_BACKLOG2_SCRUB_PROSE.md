# BOB — Backlog 2 of 4: Scrub residual OpenAI-shim prose

Three trivial edits. Land in one commit.

1. `src/pipeline/enrichment/images.py` line 151 — `"openai:"` → `"gemini:"` in the `chain_entry["tool"]` f-string.
2. `src/pipeline/enrichment/vision.py` line 39 — docstring says "OpenAI-compatible vision API"; rewrite to reflect the native Gemini client.
3. `tests/test_enrichment.py` lines 203–206 — the assertion was pinned to the wrong label as a "reality check" during Phase 7. Flip it to match the fixed source, and drop the explanatory comment since the discrepancy is gone.

Hard gate: `python -m pytest tests/test_enrichment.py -v` passes after the edits.

---

## Step 0 — pre-flight

```
git status
git rev-parse HEAD
```

`HEAD` should be `86cebe2`. Modified/staged: nothing. Untracked: the 5 scripts. Stop and report if otherwise.

---

## Step 1 — edit `src/pipeline/enrichment/images.py` line 151

Change:

```python
            "tool": f"openai:{self._config.model}" if self._config else "none",
```

to:

```python
            "tool": f"gemini:{self._config.model}" if self._config else "none",
```

Only that one character range (`openai` → `gemini`). Nothing else in the file.

---

## Step 2 — edit `src/pipeline/enrichment/vision.py` line 39

Change the `VisionClient` class docstring from:

```python
    """Client for describing images via an OpenAI-compatible vision API."""
```

to:

```python
    """Client for describing images via Google Gemini's native generateContent endpoint."""
```

Only that docstring line. Nothing else in the file.

---

## Step 3 — edit `tests/test_enrichment.py` lines 203–206

Current block looks roughly like:

```python
        # `openai:` prefix — phase 4 only rewrote vision.py. Assert reality
        # rather than the aspirational `gemini:` label.
        assert chain["tool"] == "openai:gemini-2.0-flash"
```

Replace with:

```python
        assert chain["tool"] == "gemini:gemini-2.0-flash"
```

Drop the explanatory comment lines. The label is no longer aspirational — it matches the source after Step 1.

If the comment spans more or fewer than the two lines shown above, match the intent (remove the "openai prefix reality check" comment explaining the mismatch) and update the assertion string. Report exactly what you found and changed.

---

## Step 4 — verify diffs

```
git diff
```

Paste the full diff. Scope should be exactly:

- `src/pipeline/enrichment/images.py`: 1 line changed (`openai` → `gemini`)
- `src/pipeline/enrichment/vision.py`: 1 docstring line changed
- `tests/test_enrichment.py`: 1 assertion changed, 1–2 comment lines removed

If anything else appears in the diff, stop and report.

---

## Step 5 — HARD GATE: targeted pytest

```
python -m pytest tests/test_enrichment.py -v
```

Must pass green. If anything fails, stop and report — do not stage or commit.

Then run the full suite as a regression check:

```
python -m pytest tests/ -v
```

Expected: 174 passed. Must match the Phase 7 green baseline.

---

## Step 6 — stage, commit, push

```
git add src/pipeline/enrichment/images.py src/pipeline/enrichment/vision.py tests/test_enrichment.py
git status --short
```

Three staged files only. Then:

```
git commit -m "$(cat <<'EOF'
Scrub residual OpenAI-shim prose from enrichment modules

Three leftovers from the OpenAI-compat-shim era that the Phase 3-6
migration didn't catch:

- images.py line 151: image_enrichment chain-entry tool label was
  "openai:{model}"; flip to "gemini:{model}" to match the embedder's
  already-correct "gemini:" label at embedder.py:236,271.
- vision.py line 39: VisionClient docstring said "OpenAI-compatible
  vision API"; update to describe the native generateContent client.
- test_enrichment.py: Phase 7 test suite asserted the wrong label
  ("openai:gemini-2.0-flash") as a "reality check" pending this fix.
  Flip the assertion to match.

Full pytest suite still 174/174 green.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

---

## Report back

- Step 0 output
- Step 4 full diff
- Step 5 both pytest outputs (targeted + full)
- New commit SHA
- `origin/main` confirmation
- Final `git status --short`

## Do NOT

- Touch any file other than the three listed
- Broaden scope to rewrite other docstrings
- Skip the pytest hard gate
