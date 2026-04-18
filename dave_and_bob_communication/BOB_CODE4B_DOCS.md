# Review + commit: docs native-Gemini defaults + caveat banner (phase 6b of 8)

**For:** Bob
**From:** Sam
**Companion:** `DAVE_CODE4B_DOCS.md`, `NATIVE_GEMINI_OVERVIEW.md`. Phases 1-6a merged (`db676b0`, `731fb49`, `e0caf2e`, `c5e923e`, `43a286f`, `0b9a39e`).

Dave updated five user-facing docs to reconcile them with the Gemini-native runtime. Tactical string swaps plus one honest banner — no narrative rewrites. Your job: verify and push. This is the last phase before tests (phase 7); next time Denson runs an end-to-end deploy, what he reads in the docs must match what the code actually does.

`docs/roadmap/*` is **out of scope** — phase 6c is under Sam's supervision, blocked on the token-savings guardrail.

---

## Step 1: Scope check

```bash
cd ariadne-core
git status
```

**Expected tracked-modified files** (five):

1. `README.md`
2. `docs/configuration.md`
3. `docs/installation.md`
4. `docs/docint-architecture.md`
5. `scripts/setup.py`

Plus `DAVE_DONE.md` (not in the commit). `client/src/ariadne_core_client/cli.py` should **not** be modified — Dave confirmed it has no `DEFAULTS_TABLE`; Bob's phase-6a flag was about `setup.py`. Anything else tracked-modified is out of scope; stop and flag.

---

## Step 2: Read the diff

```bash
git diff README.md docs/configuration.md docs/installation.md docs/docint-architecture.md scripts/setup.py
```

Verify, file by file:

### `scripts/setup.py`

One line inside `DEFAULTS_TABLE` — the Google Vision line went from `gemini-3.1-flash-lite-preview` to `gemini-2.0-flash`. OpenAI block below unchanged. Nothing else.

### `README.md`

Four edit clusters:

1. **Railway command block** — adds two `..._BASE_URL` lines, switches model defaults to `gemini-embedding-001` / `gemini-2.0-flash`, API-key hints say "gemini-api-key" not "provider-api-key".
2. **Long banner** inserted immediately after `## Compatible providers` heading, canonical wording from instruction Step 1. Grep `"v1 runtime is Gemini-native"` should hit here.
3. **Google Gemini row** in the providers table — label is `**Google Gemini** (v1 default)`, base URL drops `/openai/`, models are `gemini-embedding-001, gemini-2.0-flash`.
4. **Cost table** — both rows swapped to Gemini models and Gemini rates (~$0.15/M embedding, ~$0.10/M vision).

Must **not** touch: L98, L152, L176 "any OpenAI-compatible provider" prose (banner covers it); full providers tables rows other than the Gemini row; L327 ASCII tree line.

### `docs/configuration.md`

Five edit clusters:

1. **Short banner** inserted under the top heading.
2. **Defaults table** four rows (L36-39 range) — both models and both base URLs swapped.
3. **Embedding YAML** — `model`, `provider` (`google-gemini`), `base_url` updated.
4. **Embedding defaults table** — four rows updated, "OpenAI, Together AI, Fireworks, Ollama, etc." parenthetical dropped from the `provider` row.
5. **Image-enrichment YAML + defaults table** — same pattern. Prompt text preserved verbatim.

Must **not** touch: the embedding-model reference table at L96-101 (OpenAI / BAAI rows stay — they're roll-your-own candidates, banner covers it).

### `docs/installation.md`

Two edit clusters:

1. **Short banner** inserted under the first heading.
2. **Railway command block** — models swapped, two `_BASE_URL` lines added. **Legacy unprefixed var names kept** (`EMBEDDING_API_KEY` not `ARIADNE_EMBEDDING_API_KEY`) — that's correct per Dave's instruction (known backlog drift, out of scope here).

Must **not** touch: the OpenAI curl diagnostic example at L184-188.

### `docs/docint-architecture.md`

Five edit clusters:

1. **Short banner** inserted near the top.
2. **Env override block** (~L353-357) — `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `EMBEDDING_PROVIDER`, `EMBEDDING_BASE_URL` all updated. Note `EMBEDDING_DIMENSIONS` went from `1024` to `1536` because the default model changed (BAAI/bge-large-en-v1.5 → gemini-embedding-001).
3. **YAML config example** (~L567-579) — both `embedding:` and `image_enrichment:` sections swapped.
4. **Optional-overrides hint block** (~L637-642) — two lines updated, `bge-m3` line removed.
5. **Four JSON `"tool"` labels** — `openai:gpt-4o-mini` → `gemini:gemini-2.0-flash` (×2) and `openai:bge-large-en-v1.5` → `gemini:gemini-embedding-001` (×2). Lines ~238, ~245, ~850, ~851.

Must **not** touch: L24, L41, L63, L65, L539-541, L983 prose about "any OpenAI-compatible endpoint" (banner covers it). Vision cost-options table at L282-286 (reference, banner covers).

---

## Step 3: Grep sanity

```bash
cd ariadne-core
grep -n "text-embedding-3-small\|gpt-4o-mini\|gemini-3.1-flash-lite-preview" \
  README.md docs/configuration.md docs/installation.md docs/docint-architecture.md scripts/setup.py
grep -c "v1 runtime is Gemini-native" \
  README.md docs/configuration.md docs/installation.md docs/docint-architecture.md
grep -n "openai:gpt-4o-mini\|openai:bge-large-en-v1.5" docs/docint-architecture.md
grep -n "/v1beta/openai" \
  README.md docs/configuration.md docs/installation.md docs/docint-architecture.md scripts/setup.py
```

- **First grep** (stale model defaults): every hit must be in an allowed "leave alone" location. Expect roughly:
  - `setup.py` — OpenAI block of `DEFAULTS_TABLE` (both `text-embedding-3-small` and `gpt-4o-mini`) plus the `PROVIDERS["openai"]["default_embedding"]` / `default_vision` dict entries (kept per phase 6a).
  - `README.md` — OpenAI row of providers table (`text-embedding-3-small, gpt-4o-mini`).
  - `docs/configuration.md` — embedding-model reference table (`text-embedding-3-small`, `text-embedding-3-large`).
  - `docs/installation.md` — curl diagnostic example.
  - `docs/docint-architecture.md` — vision-options table (`gpt-4o-mini`, `gpt-4o`).
  - **Zero hits** of `gemini-3.1-flash-lite-preview` anywhere.
  - **Zero hits** inside Railway blocks, YAML config examples, env-override blocks, or default-value tables.

  If any hit looks like it's inside a live config example or defaults table, read context and verify. Dave's report lists 9 hits; tolerate around that number but audit each one.

- **Second grep** (banner placement): exactly `1` per file, four files. Output like `README.md:1`, `docs/configuration.md:1`, etc.
- **Third grep** (JSON tool labels): **zero hits**. If either `openai:gpt-4o-mini` or `openai:bge-large-en-v1.5` shows up, Dave missed one of the four label sites.
- **Fourth grep** (residual `/v1beta/openai` paths): **zero hits across all five files.**

---

## Step 4: Read Dave's seven flagged anomalies

Open `DAVE_DONE.md` and read every flagged item. Dave specifically called out `docs/docint-architecture.md:544` as a narrative-prose "leave-alone" call that deserves Bob attention. Go read line 544 in context (a few lines above and below). Two outcomes:

- **If the line is pitch-style prose about multi-provider** — consistent with the other "leave alone" positions from the instruction. The banner at the top of the file is the honest correction. Leave it, include in report as confirmed.
- **If the line is something structurally different** — a config example, a tool label, a defaults claim — that Dave genuinely shouldn't have left: stop, flag, decide whether to fold into this commit or kick to a follow-up.

Same treatment for the other six anomalies. Most will be prose leave-alone calls consistent with the banner approach. Don't expand scope beyond what the instruction authorized unless something Dave flagged looks like an actual miss.

---

## Step 5: Link spot-check

Render the caveat banner mentally — it references three code paths:

- `src/pipeline/embedding/embedder.py`
- `src/pipeline/enrichment/vision.py`
- `src/pipeline/extraction/text_encoding.py`

Confirm all three files exist at those paths (they do; phases 3-5 all landed there). Banner markdown doesn't use link syntax, just inline code, so a dead-link fix isn't needed — but make sure the paths are typo-free.

---

## Step 6: Commit + push

Suggested subject: `Reconcile docs with Gemini-native runtime + roll-your-own caveat`

Body: updates README, docs/configuration.md, docs/installation.md, docs/docint-architecture.md, and `scripts/setup.py` `DEFAULTS_TABLE` to advertise the native Gemini base URL (`https://generativelanguage.googleapis.com/v1beta`) and default models (`gemini-embedding-001` / `gemini-2.0-flash`). Adds a prominent "v1 runtime is Gemini-native" caveat banner at the top of each doc file explaining that other provider URLs listed are reference-only — users who want to swap providers must fork and modify the clients in `src/pipeline/`. Updates Railway command blocks, YAML examples, defaults tables, env-override blocks, the Cost table, and JSON `tool` labels (`openai:*` → `gemini:*`). Leaves existing provider-table rows, cost-reference tables, and "any OpenAI-compatible" narrative prose intact — the banner provides the honest correction without ripping out the structure for a future multi-provider v2. References SPEC.md `### Provider constraints`. Phase 6b of the native-Gemini migration.

Push to default branch.

---

## Step 7: Backlog items

Copy verbatim into `BOB_DONE.md`:

1. **Unprefixed env var names in `docs/installation.md`** (`EMBEDDING_API_KEY`, `VISION_API_KEY`, etc.). Known drift from phase 2 backlog. Kept for consistency with the file's existing pattern; should be reconciled to `ARIADNE_*` in a future docs cleanup.
2. **Phase 6c (roadmap docs) pending.** `docs/roadmap/pro-pricing.md` and `docs/roadmap/token_pricing_snapshot.md` still reference OpenAI-compat URLs and model names. Blocked on Sam reading `docs/TOKEN_SAVINGS_FRAMING.md` and clearing specific edits with Denson per the token-savings guardrail in `CLAUDE.md`.
3. **Multi-provider runtime support is gone in v1.** Banner documents this. Restoring multi-provider (via a provider abstraction in `src/pipeline/`) is a product decision for v2, not a bug fix.

Plus any genuinely new backlog items from Dave's seven flagged anomalies (most should be leave-alone confirmations, not new items).

Do **not** fix any of these in this commit.

---

## Step 8: Report

Write completion to `BOB_DONE.md`: commit SHA, push target, one-line confirmation of exactly five files in the commit, your handling of each of Dave's seven flagged anomalies (one line each — "confirmed leave-alone" or "escalated to X"), the three backlog items verbatim, and the output of all four greps from Step 3 as independent verification.

No Railway action required — env vars already correct.
