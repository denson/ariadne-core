# Native-Gemini migration — overview

**Context:** The OpenAI-compatible shim at `https://generativelanguage.googleapis.com/v1beta/openai/*` is not usable with the new `AQ.*`-format Gemini API keys (April 2026). Empirically verified — every header combination fails on the shim, every native endpoint succeeds with `x-goog-api-key`. Full probe results in `C:\Users\denso\claude_projects\ariadne-core-workspace\test_auth_variants.py`.

Ariadne's bundled embedding and image-enrichment paths must migrate off the shim to native Gemini endpoints for v1. Other OpenAI-compatible providers (OpenAI proper, Together, Groq) may be wired back in later by a configuring agent — that is explicitly out of scope here.

The earlier "fix" in commit `0141618` (swap `Authorization: Bearer` → `x-goog-api-key` on the shim) is wrong and must be replaced. The comment block it added is wrong too — it claims `x-goog-api-key` works on the shim, which it doesn't.

Order is **spec → skills → code → verification**. Code phase is split by file because each native migration touches request shape, response parser, and comment block — we want atomic Bob reviews and independent local probes.

---

## Phased instructions

Each instruction is one Dave task, one Bob review. Do not advance until the previous phase is merged on `main`.

### Spec

1. **`DAVE_SPEC_NATIVE_GEMINI.md`** — update `SPEC.md` `### Embedding` and `### Image enrichment` subsections with native endpoint contracts, base URL values, and a "Provider constraints" note. SPEC is the source of truth; skills + code derive from it.

### Skills

2. **`DAVE_SKILLS_NATIVE_GEMINI.md`** — update `skills/ariadne-core-deploy/SKILL.md` + mirror at `.claude/skills/ariadne-core-deploy/SKILL.md` with new base URLs and provider notes. Keep the two byte-identical.

### Code

3. **`DAVE_CODE1_EMBEDDER.md`** — rewrite `src/pipeline/embedding/embedder.py` for native `POST {base}/models/{model}:batchEmbedContents`. New payload shape (`{"requests": [...]}`), new response parser (`{"embeddings": [{"values": [...]}]}`). Replace the wrong comment block from 0141618. Local probe before push.

4. **`DAVE_CODE2_VISION.md`** — rewrite `src/pipeline/enrichment/vision.py` for native `POST {base}/models/{model}:generateContent` with `inlineData` image parts. New response parser (`candidates[0].content.parts`). Replace wrong comment block. Local probe.

5. **`DAVE_CODE3_TEXT_ENCODING.md`** — rewrite `src/pipeline/extraction/text_encoding.py` for native `generateContent` (text only, simpler than vision). Replace wrong comment block.

6. **`DAVE_CODE4_CONFIG_DOCS_ENV.md`** — strip `/openai` suffix from defaults and prose across:
   - `src/pipeline/config.py`
   - `.env.example`
   - `client/src/ariadne_core_client/cli.py` (the `_ENV_TEMPLATE` constant)
   - `scripts/setup.py`
   - `config/ariadne.yaml`
   - `README.md`
   - `docs/configuration.md`
   - `docs/installation.md`
   - `docs/docint-architecture.md`
   - `docs/roadmap/pro-pricing.md`

7. **`DAVE_CODE5_TESTS_AND_FIXES.md`** — update `tests/test_openai_live.py`, `tests/test_config.py` to mock native endpoint shapes. Add FIXES.md entry summarizing the migration.

### Verification

8. **`DAVE_WORLD_BANK_RESTART.md`** (already written) — three-phase smoke test → clean `world-bank-ree` → re-ingest 574 files. Hard gate on each phase.

---

## Railway env (Denson, manual)

Already done. Both `ARIADNE_EMBEDDING_BASE_URL` and `ARIADNE_IMAGE_ENRICHMENT_BASE_URL` are now `https://generativelanguage.googleapis.com/v1beta` (no `/openai`).

Once the code lands, Railway will redeploy and pick up the working paths with no further env action.

---

## Deferred (see workspace `BACKLOG.md`)

- **Walkthrough skills** (item 17) — still describe provider as OpenAI-compatible. Marketing copy, not runtime, defer until the migration ships.
- **Silent-failure bug** in `services.py` (item 18) — orthogonal to auth fix, separate cleanup after migration.
