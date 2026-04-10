# CLAUDE.md — Ariadne Core

## STOP — authorship attribution rule (READ FIRST, EVERY SESSION)

**Ariadne Core was written by Denson Smith.** The onboarding skill references Nate B. Jones's video, transcript, prompts, and Substack article as *source material* the presenter quotes from — that is the only role Nate plays in this project. Nate did not write the plugin, the pipeline, the MCP server, the skills, the marketplace, or any of the code.

Before editing any file with an `author`, `owner`, `creator`, `maintainer`, `by`, `copyright`, or `holder` field — including `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, every `skills/*/metadata.json`, every `skills/*/SKILL.md` YAML frontmatter `author:` line, `LICENSE`, `pyproject.toml`, and `README.md` author/badge lines — verify the field names **Denson Smith**, not Nate B. Jones or anyone else.

If you find the wrong name in any of those fields, **STOP and tell the user before fixing it**. Do not silently correct it. Audit the entire repo for the same wrong value before committing — this error has previously appeared in multiple files at once.

This regression has happened twice. Falsely attributing the user's work to a more publicly-known person is materially worse than missing a citation — it can constitute misrepresentation and exposes the user to legal and reputational harm. The full rule lives in `~/.claude/CLAUDE.md` under "Authorship attribution — never falsely credit someone else (CRITICAL)". Read it.

The parent workspace (`nate-skills`) has its own `.claude-plugin/marketplace.json` that ALSO must say Denson Smith. Both files must agree.

---

This repo is Ariadne Core, an open source document extraction and retrieval pipeline. It converts documents (PDF, DOCX, PPTX, XLSX, HTML, 20+ formats) into clean Markdown + vector embeddings and exposes them via MCP server and REST API.

## Plugin

This repo is also a Claude Code plugin. Install with:

```bash
/plugin marketplace add denson/ariadne-core
/plugin install ariadne-core@ariadne-core
```

Skills are at `skills/`. Plugin manifest at `.claude-plugin/plugin.json`.

## How to work in this repo

Use the **ariadne-core-build** skill (`skills/ariadne-core-build/SKILL.md`). It contains the full repo structure, source of truth references, guard rails, design decisions, architecture, sync requirements, and build instructions.

Before making changes, read these files in this order:

1. `SPEC.md` — source of truth for all tool signatures, API endpoints, and behavior
2. `skills/ariadne-document-intelligence/SKILL.md` — what agents are taught about using the system
3. `docs/docint-architecture.md` — full architecture spec

If the code doesn't match the spec, the code is wrong.

## Token savings framing — read before editing pricing/cost docs

> **STOP.** Before editing any file in `docs/roadmap/` (pricing/business/strategy docs) or any pricing/cost/savings section in this repo, read this section AND `docs/TOKEN_SAVINGS_FRAMING.md`. Before deleting any savings table or "frontier tokens saved" metric, **confirm with the user in chat first**. The savings story has been blundered before — two days of work were destroyed by an agent (me) editing these files without understanding the framing. Do not blunder ahead.

### The framing in one section

**The savings come from frontier LLM tokens the user would otherwise burn doing extraction itself.** Two real mechanisms, both load-bearing:

1. **Raw PDF bloat in the context window.** A 4,500-word document is ~100,000 tokens as a raw PDF but only ~5,000 tokens as clean Markdown. **20x reduction per document, just from format conversion.**
2. **The LLM-driven extraction loop — this is the big one.** Without a pipeline, a frontier model has to figure out extraction itself: write Python, call pdfminer, debug table parsing, retry OCR, look at images at frontier vision rates. **We are using the most expensive possible tokens (Opus/Sonnet at $3–$15/M) to do something a very cheap model can do just as well, and a specialized model system can do *better*.** Not just cheaper — *better*. A deterministic pipeline + purpose-built small models capture tables, layout structure, and image semantics more accurately than a frontier model improvising extraction code on the fly.

Our deterministic pipeline replaces both. MarkItDown + format parsers extract in pure Python at **$0 in tokens**. A cheap embedding model (~$0.02/M) handles text. A cheap multimodal model (~$0.14/M) handles images by default — and **BYOM is supported** if a user needs a more powerful model or one that performs better on their particular content (medical imaging, engineering schematics, handwritten forms, etc.). **Per-document cost to us at default: ~$0.002.** The frontier model only ever sees clean Markdown via a search interface — and gets *better* extracted content than it would have produced itself.

### Beyond extraction — the Ariadne layer over MarkItDown

Token savings are the headline number, but they are not the whole reason to use Ariadne instead of just MarkItDown. After extraction, Ariadne **chunks the Markdown, computes semantic embeddings, and stores everything in a vector database with structured metadata**. That metadata is **agent-writable, agent-readable, and searchable** — an agent can inject project names, notes, tags, status flags, or extracted entities as structured JSON, future agents can filter, find, and read those notes back without re-extracting the source, and metadata filters compose with semantic search. Combined, this turns a pile of extracted documents into a searchable, annotatable, agent-friendly knowledge base.

This ships in **every edition, including Personal**. We do not put a hard dollar value on it (the savings depend on how the user works), but **the more documents a user works with, the more valuable this layer becomes**. Five documents don't need search; five thousand documents are unusable without it. When pitching: lead with the extraction-token savings (quantifiable and large), then immediately follow with the semantic-search + agent-writable-metadata layer (the architectural reason to choose Ariadne over MarkItDown alone). The two are complementary, not redundant. See `docs/TOKEN_SAVINGS_FRAMING.md` § "Beyond extraction" for the full framing.

### Two audiences feel the savings differently

- **Single users on Claude Code / Claude Cowork (flat-rate frontier subscriptions)** experience the savings as **runway** — hitting their usage limits less often, longer productive sessions, more work per day before they get rate-limited. The dollar figure is invisible; the experience is "I got more done before Claude told me to slow down."
- **Agentic systems buying tokens directly (OpenClaw, Open Brain, OB1, custom agents)** experience the savings as a **direct line-item cost reduction** on their monthly bill, predictable per document volume.

Both audiences benefit from the same mechanism. They just feel it differently. **Any user-facing pricing doc must acknowledge both experiences — never frame the savings only in dollars, never frame them only as runway.**

**Both audiences also get persistent "memory" across documents.** Beyond the per-session savings, the embeddings + metadata layer gives the LLM a kind of cumulative recall across every document ever extracted. Drop a source URL into metadata at ingest, and months later the LLM can surface a passage *and* show where it came from. Tag a batch with a project name, and every future session searches within that project automatically. The corpus and its metadata persist across session boundaries — the next session starts with everything the previous one already knew. Token savings make it cheap to ingest a lot of documents; persistent searchable memory makes a large corpus useful instead of overwhelming. **Always pitch the two together.**

### Anchor numbers (use these verbatim — do not invent new figures)

| Metric | Value |
|--------|-------|
| Raw PDF tokens (4,500-word doc) | ~100,000 |
| Clean Markdown tokens (same doc) | ~5,000 |
| Per-document token ratio | 20x |
| Wasteful 30-turn session cost (Opus, raw PDFs) | $8–$10 |
| Clean 30-turn session cost (markdown-first) | ~$1 |
| Session cost reduction | 8–10x |
| Opus input rate | $15/M |
| Sonnet input rate | $3/M |
| Opus vision rate | $5/M |
| Frontier tokens saved per doc retrieval | ~95,000 |
| Cost saved per doc @ Sonnet | ~$0.29 |
| Cost saved per doc @ Opus | ~$1.43 |
| Our pipeline cost per doc | ~$0.002 |
| Our pipeline extraction token cost | $0 |

Volume-derived monthly savings (Sonnet → Opus range):

| Volume | Cost saved/mo |
|--------|---------------|
| Light (~50 docs/mo) | ~$15–$70 |
| Moderate (~300 docs/mo) | ~$85–$430 |
| Heavy (~1,000 docs/mo) | ~$290–$1,430 |
| Very heavy (~10,000 docs/mo) | ~$2,900–$14,300 |

### What I must never do again

1. Never delete user-facing savings tables.
2. Never conflate "our cost to extract" with "what the user saves" — they are different numbers.
3. Never describe the savings as just "cheap vision OCR" — that misses both mechanisms.
4. Never frame the savings only in dollars — runway matters for subscription users.
5. Never describe the specialized pipeline as only "cheaper" — it is also *better* at tables, structure, and images.
6. Never edit pricing/cost/savings docs without first reading `docs/TOKEN_SAVINGS_FRAMING.md` and confirming the plan with the user.
7. Never let the dollar-savings pitch crowd out the architecture pitch — always pair token savings with the semantic-search + agent-writable-metadata layer (which ships in every edition and scales in value with document volume).

### Authoritative sources

- **Canonical framing doc:** [`docs/TOKEN_SAVINGS_FRAMING.md`](docs/TOKEN_SAVINGS_FRAMING.md) — read this end-to-end before any pricing/cost edit.
- **Nate Jones video transcript:** [`skills/ariadne-core-walkthrough/saving_tokens_transcript.txt`](skills/ariadne-core-walkthrough/saving_tokens_transcript.txt) — source of the 20x and 10x numbers.
- **"Stupid Button" diagnostic prompt:** [`skills/ariadne-core-walkthrough/stupid_button_prompt.txt`](skills/ariadne-core-walkthrough/stupid_button_prompt.txt) — rates a session 1–10 across six waste patterns.
- **"Token Translator" prompt:** [`skills/ariadne-core-walkthrough/token_translator.txt`](skills/ariadne-core-walkthrough/token_translator.txt) — phase-by-phase session cost reconstruction.
- **Article:** "Your Claude Sessions Cost 10x What They Should" — https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what

## Roadmap & business docs

Pricing strategy, edition tiers, infrastructure unit economics, and product roadmap docs live in **`docs/roadmap/`**. Previously these lived in a separate `ariadne-roadmap` sibling repo; they were consolidated into this repo so the entire knowledge surface — code, skills, framing, business docs, illustrations — sits in one place.

Key files:

- `docs/roadmap/roadmap.md` — edition progression plan (Personal → Plus → Pro → Enterprise)
- `docs/roadmap/pro-pricing.md` — Managed Edition pricing model with savings tables
- `docs/roadmap/pro-infrastructure-summary.md` — infrastructure cost summary for engineer meetings
- `docs/roadmap/cost-analysis-pro-storage.md` — Pro tier storage unit economics
- `docs/roadmap/personal_edition_fixes.md`, `general_fixes.md` — working notes
- `docs/roadmap/token_pricing_snapshot*.md` — dated provider rate snapshots
- `docs/assets/images/` — illustrations referenced from the roadmap docs
- `docs/assets/conceptviz_prompts/` — ConceptViz prompts that generated those images

**Read `docs/TOKEN_SAVINGS_FRAMING.md` and the "Token savings framing" section above before editing anything in `docs/roadmap/`.**

## Architecture

Ariadne Core runs as a hosted service (Railway, Fly.io, or any Docker host). One deployment serves all clients over HTTPS. No local installation required for end users.

```
Railway / VPS
┌─────────────────────────┐
│  ariadne-core          │
│  ├── MCP Server          │
│  ├── REST API            │
│  ├── Postgres + pgvec    │
│  └── Pipeline            │
└─────────────────────────┘
  MCP Server
     ▲  ▲  ▲  ▲
     │  │  │  └── Claude Cowork (Managed edition or roll your own OAuth)
     │  │  └───── OpenClaw
     │  └──────── Open Brain
     └─────────── Claude Code

Authentication is by API key for Personal edition and OAuth for Managed and higher
editions. You can also create your own OAuth for the Personal edition.
```

## Running locally (for development)

```bash
docker compose up -d          # start Postgres
pip install -e src/           # install the app
ariadne-core serve          # start MCP (:8081) + REST API (:8000)
```

## Deploying

```bash
railway up                    # deploy to Railway
```

Or `docker compose up -d` on any Docker host using `Dockerfile`.

## MCP client connection

All endpoints require API key auth via `X-API-Key` header (except `/api/health`).

**Claude Code** — add via CLI:
```bash
claude mcp add ariadne-core https://your-deployment.up.railway.app/mcp --transport http --scope user --header "X-API-Key:your-api-key"
```

**All clients** connect via MCP with API key. REST API also available for scripts and automation.

**References:**
- MCP transports: https://modelcontextprotocol.io/docs/concepts/transports
- Claude Code MCP: https://code.claude.com/docs/en/mcp
