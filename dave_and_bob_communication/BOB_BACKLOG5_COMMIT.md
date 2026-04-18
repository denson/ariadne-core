# BOB — Backlog-5: Review + commit Dave's Tier-1 doc scrub

Read `dave_and_bob_communication/DAVE_DONE.md` first. Then verify scope,
commit, push.

---

## Step 0 — pre-flight

```
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

**Expected:**
- `HEAD` and `origin/main` both at `08bfde2`
- ` M` on 5 files:
  - `dave_and_bob_communication/DAVE_DONE.md`
  - `docs/configuration.md`
  - `docs/installation.md`
  - `migrations/001_initial.sql`
  - `skills/ariadne-core-build/SKILL.md`
- `??` on 3 new/newly-trackable files:
  - `tests/fixtures/README.md` (new, written by Dave)
  - `tests/fixtures/clean_english_sample.txt` (Phase 7.5 fixture)
  - `tests/fixtures/mojibake_sample.txt` (Phase 7.5 fixture)
- `??` on the ongoing untracked set:
  - `scripts/_generate_encoding_fixtures.py`
  - `scripts/_probe_embedder.py`
  - `scripts/_probe_text_encoding.py`
  - `scripts/_probe_vision.py`

If anything else is modified, staged, or present — **stop and report**.

---

## Step 1 — scope tripwire: verify the 4 edited files

Run `git diff -- docs/configuration.md docs/installation.md migrations/001_initial.sql skills/ariadne-core-build/SKILL.md`
and confirm the diff matches the spec in
`dave_and_bob_communication/DAVE_BACKLOG5_DOC_SCRUB.md` exactly:

### `docs/configuration.md`
- Lines 101–106: example-models table replaced. **"Cost" column dropped
  from the header.** First two rows are now `gemini-embedding-001` at
  1536 and 3072 dims (not OpenAI models). BAAI rows retained with a
  "requires forking per SPEC.md → 'Provider constraints'" note.
- Line 233: `ARIADNE_EMBEDDING_MODEL=text-embedding-3-large` →
  `ARIADNE_EMBEDDING_MODEL=gemini-embedding-001`
- Line 239: `ARIADNE_IMAGE_ENRICHMENT_MODEL=gpt-4o` →
  `ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash`

### `docs/installation.md`
- Lines 188–196: "Embedding or vision errors" curl block swapped from
  `api.openai.com/v1/embeddings` + `text-embedding-3-small` to
  `generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents`
  with `x-goog-api-key` header.
- One-line note about `AQ.*`-format keys rejecting the OpenAI-compat
  shim added.
- "See [Compatible providers]" link REMOVED.

### `migrations/001_initial.sql`
- Line 93: `(text-embedding-3-small)` → `(gemini-embedding-001)`. One
  word change. Nothing else in the file.

### `skills/ariadne-core-build/SKILL.md`
- Line 80: vision.py tree-comment `(any OpenAI-compat endpoint)` →
  `(native Gemini generateContent)`
- Lines 221–223: API-first guard-rail bullet rewritten. Must name
  `batchEmbedContents` + `generateContent`, name Google Gemini as the
  default, and add a pointer to SPEC.md → "Provider constraints" for
  other providers. Must preserve the "Local model support exists only
  as a config option — never the default" sentence.

**Stop-and-report triggers:**
- Diff touches any file not listed (especially: `README.md`,
  `docs/docint-architecture.md`, `scripts/setup.py`, anything under
  `skills/ariadne-core-walkthrough/`, anything under
  `.claude/skills/walkthrough/`, anything under `docs/roadmap/`)
- The `TODO(native-gemini migration)` at `scripts/setup.py:40–42` was
  removed
- The example-models table in configuration.md has pricing numbers in
  the Gemini rows (Dave was told to drop the Cost column specifically
  to sidestep fabricated pricing)
- The "See [Compatible providers]" link is still in installation.md

Do not paste the full diff — a diff-stat plus the specific-edit
confirmations above is enough. If any check fails, stop.

---

## Step 2 — verify `tests/fixtures/README.md` content

```
cat tests/fixtures/README.md
```

Confirm the file exists and contains (at minimum):
- A "Files" table describing both fixtures
- An "Expected pipeline behavior" table with four columns:
  `encoding_confidence`, `llm_coherent`, `coherent (final)`,
  `Suggested tags`
- A "Why these are tracked as bytes, not regenerated" section
- A "Building your own pipeline on top of ariadne-core" section

Paste the file verbatim in your report for the record. If the content
is substantively different from Step 6 of `DAVE_BACKLOG5_DOC_SCRUB.md`
(e.g., missing the Expected-behavior table), **stop and report**.

---

## Step 3 — verify the two fixture `.txt` files

```
ls -la tests/fixtures/clean_english_sample.txt tests/fixtures/mojibake_sample.txt
python -c "print(open('tests/fixtures/mojibake_sample.txt', encoding='utf-8').read()[:100])"
```

- Both files exist
- The mojibake file preview shows classic mojibake patterns (e.g.
  `â€™`, `â€œ`, `Ã©` — at least one of these)

If the mojibake file doesn't show those patterns, the fixture was
regenerated incorrectly on some machine — **stop and report**. We do
NOT want to commit a "clean" mojibake file that's actually valid UTF-8.

---

## Step 4 — optional paranoia pytest

No source code changed, so pytest is not required. If you want the
reassurance, run:

```
python -m pytest tests/ -v
```

Must still be 177/177 green. Any failure → **stop and report**, do not
commit.

---

## Step 5 — stage, commit, push

Stage all 8 paths explicitly (no `git add .` — the untracked helper
scripts must remain untracked):

```
git add \
  docs/configuration.md \
  docs/installation.md \
  migrations/001_initial.sql \
  skills/ariadne-core-build/SKILL.md \
  tests/fixtures/README.md \
  tests/fixtures/clean_english_sample.txt \
  tests/fixtures/mojibake_sample.txt \
  dave_and_bob_communication/DAVE_DONE.md
git status --short
```

Expected after staging:
- `M  docs/configuration.md`
- `M  docs/installation.md`
- `M  migrations/001_initial.sql`
- `M  skills/ariadne-core-build/SKILL.md`
- `M  dave_and_bob_communication/DAVE_DONE.md`
- `A  tests/fixtures/README.md`
- `A  tests/fixtures/clean_english_sample.txt`
- `A  tests/fixtures/mojibake_sample.txt`
- `??` on the 4 helper scripts (unchanged)

The `DAVE_DONE.md` stage will emit the usual cosmetic "directory
ignored" warning — the negation rule from `86cebe2` still carries it
through. Confirm it's staged via `git status --short`. Do not use
`git add -f`.

Then commit:

```
git commit -m "$(cat <<'EOF'
Scrub OpenAI-shim-era model refs from active docs + track smoke fixtures

Tier-1 mechanical scrub. After the native-Gemini migration (Phase 3-5,
commits through e0ccb12), several active docs still carried OpenAI-shim
example values that would steer future agents at the wrong provider:

- docs/configuration.md: example-models table showed OpenAI rows as the
  only specific recommendations; env-override examples named
  text-embedding-3-large and gpt-4o. Replaced with Gemini defaults
  matching the runtime. Dropped the Cost column from the example table
  -- pricing drifts and we had no sustainable way to keep it current in
  two places.
- docs/installation.md: "Embedding or vision errors" troubleshooting
  block used OpenAI's /v1/embeddings as the direct-test example.
  Swapped to the native Gemini batchEmbedContents endpoint with
  x-goog-api-key. Added a one-line note that AQ.*-format keys
  (April 2026+) reject the OpenAI-compat shim.
- migrations/001_initial.sql: advisory comment naming
  text-embedding-3-small as the default updated to gemini-embedding-001.
- skills/ariadne-core-build/SKILL.md: file-tree comment for vision.py
  and the API-first guard-rail bullet both named "any OpenAI-compatible
  endpoint". Updated to name native Gemini generateContent /
  batchEmbedContents with a fork-for-others pointer to SPEC.md.

Deliberately out of scope (tracked as Backlog-5a):
- README.md "Compatible providers" section
- docs/docint-architecture.md (10 instances)
- scripts/setup.py PROVIDERS dict + DEFAULTS_TABLE (carries an explicit
  TODO flagging this for a post-migration decision)

Also tracks two Phase 7.5 test fixtures that were previously untracked
(tests/fixtures/clean_english_sample.txt and mojibake_sample.txt) plus
a new tests/fixtures/README.md with LLM-facing instructions on how
future pipeline-builders should use them for validator-gate testing.
Mojibake is hard to reproduce byte-for-byte across machines -- tracking
the bytes directly makes live smoke deterministic.

Records Dave's Backlog-5 handoff report in DAVE_DONE.md per the
convention established by 86cebe2, e632181, 08bfde2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main
git log -1 --oneline
git rev-parse origin/main
git status --short
```

Final `git status --short` should show:
- No modified, no staged
- `??` only for the 4 untracked helper scripts
- The 2 fixture `.txt` files and `tests/fixtures/README.md` should NOT
  appear (they just got tracked)

---

## Report back

- Step 0 output
- Step 1 diff-stat + scope-check confirmation (which checks passed; don't
  paste the full diff of all 4 files — diff-stat + "all edits match
  spec" is fine)
- Step 2 full `tests/fixtures/README.md` contents (for the record)
- Step 3 mojibake preview output
- Step 4 pytest result if you ran it, otherwise "skipped"
- Stage-list `git status --short`
- New commit SHA
- `origin/main` confirmation
- Final `git status --short`

---

## Do NOT

- Touch any file outside the 8 paths listed
- Unstage any helper script that was supposed to be staged
- Stage any helper script that was supposed to stay untracked
- Use `git add -f` or `git add .`
- Remove the `TODO(native-gemini migration)` from `scripts/setup.py`
- Run `git commit --amend`
- Skip the scope tripwire (Step 1) even if the diff "looks fine"
