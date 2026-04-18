# Backlog

Work that has been explicitly deferred — not forgotten, not out of
scope, just not now. Agents picking up this repo should read this file
before proposing new work, to avoid re-discovering items that are
already queued and to avoid stepping on items that need a planning
conversation first.

Each entry notes its blocker. An item without a blocker is ready to
schedule; an item with a blocker is waiting on that dependency.

## Tier-2 migration cleanup — blocked on provider-framing decision

### BL-5a — Tier-2 doc scrub: provider-framing rewrite

Three active docs still describe Ariadne as "any OpenAI-compatible
API" — coherent paragraphs from the pre-migration era, not simple
model-name swaps. Post-Phase-3–5 (commits through `e0ccb12`), the
runtime speaks native Gemini only, and `SPEC.md` → "Provider
constraints" documents that other providers would require forking.

- `README.md:366–387` — entire "Compatible providers" section
- `docs/docint-architecture.md` — 10 instances (lines 29, 46, 68, 70,
  289–291, 544–545, 987)
- `scripts/setup.py` — `PROVIDERS` dict + `DEFAULTS_TABLE`. Already
  carries an explicit `TODO(native-gemini migration)` at lines 40–42
  flagging this for a post-migration decision. Do not remove the
  TODO until BL-5a is addressed.

**Blocker:** product decision on the provider story. Options:
(a) native Gemini only for v1, (b) Gemini native + explicitly
forkable for others with SPEC.md as the contract, (c) restore a
provider abstraction (would re-introduce the OpenAI-compat shim
removed in Phase 3–5). The `BL-5.5` onboarding planning session is
the natural venue for this call.

---

## Onboarding / packaging — blocked on planning session

### BL-5.5 — Onboarding redesign

The current walkthrough skill assumes a user clones the repo and runs
the pipeline locally. The emerging model is different: most users
install `ariadne-core-client` and one or more skills that guide them
through setting up Railway, then talk to the deployment from Claude
Code Desktop. This changes what the walkthrough is, where it lives,
and possibly whether it belongs in the plugin at all.

Scope for the planning conversation:
- Target user path — client install + Railway-setup skills, vs
  current local-install walkthrough
- Role of `walkthrough_html/` preset + dynamic HTML pages in the new
  flow (template for Claude Code Desktop to drive onboarding)
- The `skills/ariadne-core-walkthrough/SKILL.md` (5130 bytes, plugin
  template) vs `.claude/skills/walkthrough/SKILL.md` (7726 bytes,
  runtime-customized) drift — same directory has byte-identical
  YAMLs but a substantively different SKILL.md. Needs resolution
  alongside the redesign rather than as an isolated sync pass.
- Relationship to BL-5a — "what providers do we support" and "how do
  users onboard" are arguably the same question.

**Blocker:** whiteboard-style planning session with the user. Not a
Dave/Bob delegation.

**Files in scope when BL-5.5 lands:**
- `skills/ariadne-core-walkthrough/*` (including `image_manifest.yaml`,
  `project_knowledge_graph.yaml`, `references/ConceptViz_prompts.md`,
  `SKILL.md`, `starter_deck.md`, `README.md`)
- `.claude/skills/walkthrough/*` (mirror + customized SKILL.md)
- `walkthrough_html/` (preset beats + dynamic template + PNGs + CSS)
- `docs/website-integration/README.md` (downstream use of
  `knowledge_graph_embed.html`)

Note: a few of these files contain stale `text-embedding-3-small` /
`gpt-4o-mini` references. Deliberately NOT swept in BL-5 — fold into
the redesign so we don't churn text that's about to be rewritten.

---

## Ready to schedule — no blocker

### BL-8 — `/api/health` false positive

Phase 7.5 showed `client.health()` returning `embedding=True` while
the embedding endpoint was actually 400ing (wrong model name pinned
on Railway's env vars). Health claimed healthy; pipeline was broken.

Fix candidates:
- Add a live round-trip probe (embed a 1-token sample) to health
- Or degrade the flag name to `embedding=configured` so it reflects
  what's actually being checked (presence of config, not liveness)
- Option 1 costs one API call per health check; option 2 costs
  nothing and is arguably more honest

Must-not-break: the existing no-auth contract on `/api/health` (per
`SPEC.md`).

### BL-10 — `ariadne-core serve` console-script install failure

Observed during Phase 7 prep: `pip install -e src/` fails to write
the `ariadne-core serve` console entry point. Workaround used
throughout Phase 7.5: run via `python -m pipeline.api.server` or
equivalent. Fix the packaging so the console script actually
installs.

### BL-12 — Spurious `VISION_API_KEY` warning on standalone image ingest

Phase 7.5 anomaly 4: ingesting a standalone image file with a valid
vision config still emits a "VISION_API_KEY not set" warning, even
though the vision call succeeded (produced a 1270-char Gemini
description). Warning logic is wrong somewhere.

### BL-13 — `image_enrichment.images_processed` counter semantics

Phase 7.5 anomaly 2: on a standalone image document,
`vision_extraction` runs and produces output, but
`image_enrichment.images_processed` stays at 0. The counter appears
to track only images *embedded inside* a non-image document.

Fix options:
- Rename to `embedded_images_processed` so zero isn't alarming on
  standalone images
- Increment from `vision_extraction` when the document IS an image
- Leave as-is and document the semantics clearly

### BL-14 — `scripts/_generate_encoding_fixtures.py` crashes on Windows cp1252

The generator's final preview `print()` crashes on a Windows `cp1252`
console because the mojibake string contains characters the console
can't encode. The file writes complete before the crash — operator
impact is a scary-looking traceback on success. Trivial fix: wrap
the preview in `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`
or skip the preview on Windows.

### BL-15 — `DAVE_PHASE_7_5_SMOKE_TEST.md` method-name drift

The Phase 7.5 smoke spec references client method names that don't
match the actual `ariadne-core-client` API:
- `client.ingest` → actually `client.ingest_file`
- `client.search_chunks` → actually `client.search`
- `doc.processing_chain` attribute access on the client's `Document`
  model → not present; must read from the response dict or a
  different field

Update the spec so future smoke runs don't trip on name mismatches.
(Dave worked around these live each time — the workarounds should be
the spec.)

### BL-21 — Query API filters + include=agent_metadata are post-query / N+1

`tag`, `has_warnings`, and `has_source_reference` are applied as
route-level Python post-filters over the already-paginated page.
Consequence: `total_count` is wrong whenever any of them is active
(we return `len(page_docs)` and set `total_is_exact=false`). Separately,
`include=agent_metadata` and `include=last_interaction` trigger an
N+1 on `get_interactions` — one query per row returned. Both
deliberately accepted for Pass 1/2 pragmatism; both want a single
"push filters into SQL + batch-fetch interactions" pass.

Fix direction: extend `PgDedupStore.list_documents` signature to
accept the new filters and build a SQL WHERE clause; add a
`get_latest_interactions_batch(doc_ids)` method returning a dict
keyed by document_id. Both are moderate SQL work, no schema change.

Blocker: none — ready to schedule. Good candidate for "Pass 2.5" or
a dedicated server-performance pass after Pass 3 lands.

### BL-22 — `has_warnings` filter is a no-op against Postgres — RESOLVED

Resolved in this commit. Migration 005 adds a `warnings TEXT[] NOT
NULL DEFAULT '{}'` column; `PgDedupStore.store_document` persists
the list on INSERT (and on the ON CONFLICT resurrection path); every
SELECT that builds a `StoredDocument` reads the column; and
`_row_to_stored_document` maps it onto the dataclass field. The
Pass-1 `has_warnings` filter now queries persisted data. Historical
rows (pre-005) appear warning-free — no backfill. New ingests
persist warnings correctly.

### BL-23 — `agent_metadata.*` as `group_by` / `has_*` filters

The schema's `deferred` block names this explicitly. Useful queries
("how many docs per source_reference prefix?") need grouping by a
JSON path inside the latest interaction's `agent_metadata`. Pass 2
only aggregates over columns (`collection`, `file_type`, `tags`).

Fix direction: lateral-join the latest interaction per doc at the SQL
level (already partly needed for BL-21's batch-fetch), then
`jsonb_path_query_first` for the path. Start with two concrete
group_by values (`agent_metadata.source_reference`,
`agent_metadata.docty`) rather than a general JSON-path interface.

Blocker: probably waits for BL-21's SQL refactor to avoid double-
writing the latest-interaction subquery.

### BL-24 — Ensure JSON responses emit `Content-Type: application/json; charset=utf-8`

Ensure JSON responses emit Content-Type: application/json; charset=utf-8.
Root cause: Windows clients (PowerShell Invoke-WebRequest etc.) default to
cp1252 when charset is missing. Server bytes were always correct UTF-8 —
see dave_and_bob_communication/BL24_SCHEMA_MOJIBAKE_ROOT_CAUSE.md.

405/404 responses from Starlette's routing layer still lack charset;
ASCII-only bodies so no mojibake risk. Address if/when error bodies gain
non-ASCII content.

### BL-25 — `docker-compose` `initdb.d` mount masks migration-runner gaps

`docker-compose.yml` mounts `./migrations:/docker-entrypoint-initdb.d:ro`,
so on a fresh `pgdata` volume Postgres applies every SQL file in
`migrations/` at container init — *before* `_apply_migrations()` in
`src/pipeline/stores.py` runs. That silently masks missing runner
blocks locally: BL-22 shipped migration 005 but forgot to add the
corresponding `_apply_migrations` block, and every local test (+ the
fresh-Pg `down -v && up` cycle) still passed because the column had
already been created by `initdb.d`. Production — Railway's managed
Postgres, no `initdb.d` — 500'd on `d.warnings` missing until the
runner block was added.

Fix directions: (a) drop the `initdb.d` mount so local + prod both
rely solely on the Python runner (requires `001_initial.sql` to be
guaranteed present before first connect); (b) add a CI smoke that
brings up a vanilla pg16 image (no `initdb.d`) and runs the runner
end-to-end; (c) add a runner-completeness check that diffs
`migrations/NNN_*.sql` filenames against the hard-coded blocks in
`_apply_migrations` and fails startup if they drift.

Blocker: none — ready to schedule. (c) is probably the cheapest,
highest-leverage option.

---

## Operator / infrastructure — user-driven

### BL-9 — Railway auto-deploy diagnostic

During Phase 7.5, Railway did not auto-deploy seven successive
Phase 7 commits; the smoke only caught up after a manual redeploy.
Root cause unknown. Investigation is a Railway-dashboard task, not
an agent task.

---

## Guardrailed — requires explicit sign-off to edit

### BL-11 — Roadmap docs scrub under token-savings framing

Several `docs/roadmap/*` files reference OpenAI pricing as comparison
anchors — `docs/roadmap/pro-pricing.md`,
`docs/roadmap/pro-infrastructure-summary.md`,
`docs/roadmap/token_pricing_snapshot.md`,
`docs/roadmap/token_pricing_snapshot_update.md`.

Per `CLAUDE.md` → "Token savings guardrail", these docs must be
read end-to-end via `docs/TOKEN_SAVINGS_FRAMING.md` before any edit,
and any deletion of a savings table or metric requires explicit
user sign-off. The OpenAI references are deliberate comparison
anchors; they may or may not need to change when the provider story
is resolved in BL-5a/5.5. Do not touch without a planning pass.

---

## Phase 8 post-mortem — deferred items

### BL-17 — NUL-byte `psycopg.DataError` on MarkItDown output — RESOLVED

Resolved in this commit. `MarkItDownExtractor.extract()` now strips
`\x00` bytes from `markdown` and `title` at the extraction output
convergence point and emits a warning with the stripped count. All
downstream layers (chunking, dedup, storage) therefore never see
NULs. Re-ingest of the 11 known-NUL-byte Phase 8 sha1s is expected
to succeed after deploy.

### BL-19 — `store_status="error"` writes a metadata-only documents row — RESOLVED

Resolved in `5b91150`. `_process_single_document` now attempts
embed BEFORE any documents-row write. On embed failure the function
returns an error dict (HTTP 422 at the route) and no documents row,
chunks, vectors, or interaction are written. Ingest is transactional:
either everything lands or nothing does. Closes the BL-20 stats-
count drift as a side effect (no orphan rows to count).

Note: this is a client-visible change — embed-fail responses are now
HTTP 422 instead of HTTP 200 with `store_status="error"`. Existing
callers that wrap ingest calls in try/except continue to work; any
caller relying on the 200 shape needs to move handling into the
except branch.

### BL-20 — `/api/stats` counts orphan rows as documents — RESOLVED

Resolved by BL-19 in `5b91150`. Orphan rows no longer exist, so
stats and list_documents naturally return correct counts. No
standalone fix was needed.

---

## Explicitly NOT backlog — leave as-is

The following files contain stale refs but are historical artifacts
per the Backlog-4 precedent. Do not sweep them:

- `tests/COMPLY_*.md`, `tests/FIX_*.md`, `tests/VALIDATE_SKILL.md`,
  `tests/CHECK_SKILL_VS_SPEC_RESULTS.md` — test-investigation
  artifacts, frozen snapshots
- `docs/ariadne-document-intelligence-workspace/iteration-1/*` — eval
  snapshots, frozen
- `docs/patches/*` — historical patch records, frozen
- `FIXES.md`, `HTTP_proxy_fix.md` — historical investigation notes,
  frozen
- `walkthrough_html/*.html` — contain no stale refs; their onboarding
  role is handled under BL-5.5

---

## How to use this file

- Before proposing new work, grep this file. If your proposal matches
  a BL-* entry, continue that entry rather than starting a new one.
- When a BL-* item lands, delete its entry from this file in the same
  commit. This file shrinks over time.
- If you're adding a new deferred item, place it under the right
  section and assign the next BL-* number. The number is permanent;
  don't reuse retired numbers.
