# BOB_DONE — Phase 6b of 8: user-facing docs → native Gemini + caveat banner

**Status:** COMMITTED + PUSHED
**Commit SHA:** `6db1663`
**Parent:** `0b9a39e` (phase 6a)
**Range:** `0b9a39e..6db1663`
**Push target:** `origin/main`
**Instruction file:** `dave_and_bob_communication/BOB_CODE4B_DOCS.md`
**Companion:** `DAVE_CODE4B_DOCS.md` / `DAVE_DONE.md`

---

## 1. Scope confirmation

Exactly **five tracked files** were included in the commit:

1. `README.md`
2. `docs/configuration.md`
3. `docs/installation.md`
4. `docs/docint-architecture.md`
5. `scripts/setup.py`

`git show --stat 6db1663` confirms: 5 files, 74 insertions, 46 deletions.

**`client/src/ariadne_core_client/cli.py` was NOT modified** — Dave confirmed zero `DEFAULTS_TABLE` hits there; my phase-6a flag #4 pointed at `scripts/setup.py` L80, not cli.py. Gate PASS.

**Excluded from the commit** (left working-tree modified for future phases):
- `CLAUDE.md` — pre-existing workspace edit carried from earlier phases.
- `dave_and_bob_communication/BOB_REVIEW.md` — comms tracking file.
- `dave_and_bob_communication/DAVE_DONE.md` — Dave's phase-6b report.
- `_phase1_smoke.py`, `scripts/_probe_embedder.py`, `scripts/_probe_text_encoding.py`, `scripts/_probe_vision.py` — untracked probe scripts.

---

## 2. Dave's seven flagged anomalies — Bob's handling

1. **`docint-architecture.md:544` hits Grep 1 but isn't in Step 7f's explicit line list.** **Confirmed leave-alone.** Read L535-548 in context: L544 sits inside the "Image Understanding → Key points" bullet list, paired with the L545 bullet "Any OpenAI-compatible vision API works — OpenAI, Anthropic, Groq, Together, etc." This is the exact narrative-prose pattern the instruction's scope boundary reserves for banner-coverage. The banner at L3 of this file (`> **⚠️ v1 runtime is Gemini-native.** ...`) provides the honest correction. Line-number drift from instruction-authoring to now explains Step 7f's enumeration gap. **Not folded in.**
2. **Grep 2 shows 5 hits, not 4 — extra hit at `docint-architecture.md:360`.** **Confirmed expected.** The extra hit is the intentional env-override block comment (`EMBEDDING_PROVIDER=google-gemini               # v1 runtime is Gemini-native`) written per Step 7a. One banner per file ✓; the extra line-360 hit is a deliberate inline comment echo. Grep 2 gate interprets as PASS.
3. **`configuration.md` embedding YAML `dimensions: 1536` unchanged.** **Confirmed leave-alone.** Gemini `gemini-embedding-001` default dimension is also 1536 (per `EmbeddingConfig` in `src/pipeline/config.py` L51). No edit needed.
4. **Unprefixed env var names preserved in `docs/installation.md`.** **Confirmed leave-alone per Step 6b instruction.** Known backlog drift from phase 2 — carried forward in backlog item #1 below.
5. **No markdown-table alignment issues encountered.** **Confirmed.** Providers-table `(v1 default)` label suffix in README is pipe-tolerant.
6. **`docs/roadmap/*` not touched.** **Confirmed out-of-scope per Sam's instruction top boundary** — phase 6c under Sam's supervision, blocked on `docs/TOKEN_SAVINGS_FRAMING.md` guardrail. Backlog item #2.
7. **`skills/` not touched.** **Confirmed out-of-scope per scope boundary.**

All seven are leave-alone confirmations. No new escalations. Nothing folded into this commit.

---

## 3. Independent verification — Step 3 four-grep gate

### Grep 1 — stale model defaults

```
README.md:372:| **OpenAI** | `https://api.openai.com/v1` (default) | `text-embedding-3-small`, `gpt-4o-mini` |
scripts/setup.py:49:        "default_embedding": "text-embedding-3-small",
scripts/setup.py:50:        "default_vision": "gpt-4o-mini",
scripts/setup.py:84:    Embedding: text-embedding-3-small
scripts/setup.py:85:    Vision:    gpt-4o-mini
docs/configuration.md:103:| `text-embedding-3-small` | 1536 | OpenAI | $0.02/M tokens | Best value for most use cases |
docs/installation.md:194:  -d '{"model": "text-embedding-3-small", "input": "test"}'
docs/docint-architecture.md:289:| gpt-4o-mini | ~$0.002/image | Good | ~1s | API key |
docs/docint-architecture.md:544:- **API calls.** Vision API calls (gpt-4o-mini at ~$0.002/image, or any OpenAI-compatible endpoint) are cheap and fast. A 50-page document with 10 images costs about $0.02 to enrich.
```

9 hits. Per-hit audit:
- `README.md:372` — OpenAI row of providers table (leave-alone).
- `scripts/setup.py:49-50` — `PROVIDERS["openai"]` entry (phase-6a decision).
- `scripts/setup.py:84-85` — `DEFAULTS_TABLE` OpenAI block (Step 2 explicit leave-alone).
- `docs/configuration.md:103` — embedding model-recommendation table (leave-alone).
- `docs/installation.md:194` — OpenAI curl diagnostic (leave-alone).
- `docs/docint-architecture.md:289` — vision cost-options reference table (leave-alone).
- `docs/docint-architecture.md:544` — narrative prose in "Image Understanding → Key points" bullet list (Dave anomaly #1; banner covers).

**Zero `gemini-3.1-flash-lite-preview` hits anywhere. Zero hits in Railway blocks, YAML config examples, env-override blocks, or default-value tables.** PASS.

### Grep 2 — caveat banner placement

```
docs/installation.md:1
docs/docint-architecture.md:2
docs/configuration.md:1
README.md:1
Found 5 total occurrences across 4 files.
```

1 hit per README / configuration / installation. 2 in docint-architecture: L3 banner + L360 intentional env-override inline comment (Dave anomaly #2). **Exactly one banner per file.** PASS.

### Grep 3 — residual JSON tool labels

```
(no matches)
```

Zero hits. All four `openai:gpt-4o-mini` / `openai:bge-large-en-v1.5` sites rewritten to `gemini:gemini-2.0-flash` / `gemini:gemini-embedding-001`. PASS.

### Grep 4 — residual `/v1beta/openai` shim paths

```
(no matches)
```

Zero hits across all five files. PASS.

All four gates: **PASS**.

---

## 4. Step 5 link spot-check

Banner references three code paths:

```
src/pipeline/embedding/embedder.py         exists ✓
src/pipeline/enrichment/vision.py          exists ✓
src/pipeline/extraction/text_encoding.py   exists ✓
```

All three files present (phases 3-5 landed them). Banner markdown uses inline code, not link syntax — no dead-link risk.

---

## 5. Authorship audit

- No `author`, `owner`, `creator`, `maintainer`, `by`, `copyright`, `holder`, `vendor`, `publisher` field touched in any of the five files this phase. Pure narrative + config-reference edits.
- `scripts/setup.py` L6 `Author: Denson Smith` verified intact (single-line edit at L80 only).
- No fork/template leftover names introduced.
- Commit author: `denson <densonsmith2@gmail.com>` — correct git identity.

---

## 6. Backlog items (verbatim from Sam's Step 7)

1. **Unprefixed env var names in `docs/installation.md`** (`EMBEDDING_API_KEY`, `VISION_API_KEY`, etc.). Known drift from phase 2 backlog. Kept for consistency with the file's existing pattern; should be reconciled to `ARIADNE_*` in a future docs cleanup.
2. **Phase 6c (roadmap docs) pending.** `docs/roadmap/pro-pricing.md` and `docs/roadmap/token_pricing_snapshot.md` still reference OpenAI-compat URLs and model names. Blocked on Sam reading `docs/TOKEN_SAVINGS_FRAMING.md` and clearing specific edits with Denson per the token-savings guardrail in `CLAUDE.md`.
3. **Multi-provider runtime support is gone in v1.** Banner documents this. Restoring multi-provider (via a provider abstraction in `src/pipeline/`) is a product decision for v2, not a bug fix.

No new backlog items from Dave's seven flagged anomalies — all were leave-alone confirmations.

Carried forward from phase 6a (still open):
- **`config/ariadne.yaml` env-var naming drift** (`EMBEDDING_*` vs `ARIADNE_EMBEDDING_*`). Pre-existing.
- **Multi-provider support broken in `scripts/setup.py`** interactive menu (openai/together entries no longer drivable). TODO in place; needs product call.

---

## 7. What was not committed / explicitly out of scope

- **`CLAUDE.md`** — pre-existing working-tree edit from earlier workspace work. Not touched this phase.
- **`dave_and_bob_communication/*.md`** — comms files, excluded from commits by convention.
- **`_phase1_smoke.py`, `scripts/_probe_*.py`** — untracked probe scripts from phases 1-5.
- **`client/src/ariadne_core_client/cli.py`** — no `DEFAULTS_TABLE`; correctly untouched per Sam's Step 1.
- **`docs/roadmap/*.md`** — phase 6c, under Sam's supervision (token-savings guardrail).
- **`skills/`** — backlog item 17.
- **Narrative-prose "any OpenAI-compatible" lines** (`README.md` L98/L152/L176/L327; `docs/docint-architecture.md` L24/L41/L63/L65/L539-541/L544/L983) — banner covers per Sam's instruction.
- **Reference tables** (README providers table non-Gemini rows; `configuration.md` L96-101 embedding recommendation table; `docint-architecture.md` L282-286 vision cost-options table) — reference-only, banner covers.
- **OpenAI curl diagnostic example** (`installation.md` L184-188) — OpenAI-specific by surrounding prose framing.
- **`scripts/setup.py` `PROVIDERS["openai"]` / `"together"`** — phase-6a preservation decision.
- **SPEC.md, skills, tests** — later phases.

---

## 8. Phase 6b conclusion

- Five files committed (`6db1663`), pushed to `origin/main`.
- Four Step 3 gates: ALL PASS.
- Dave's seven flagged anomalies: all confirmed leave-alone; none folded in, none escalated.
- Step 5 link spot-check: all three banner-referenced paths exist.
- Scope: strictly five target files; `cli.py` untouched; no out-of-scope tracked files included.
- No Railway action required — env vars already correct.

Standing by for phase 7 (tests).
