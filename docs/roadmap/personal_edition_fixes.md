# Personal Edition Fixes

**Date:** 2026-04-07
**Status:** Open

---

## Add hosting cost guidance to documentation

Personal edition users self-host on Railway, Fly.io, or similar. They pay the provider directly. Our docs currently don't tell them what to expect in terms of ongoing costs as their document library grows. Whether a human or an agentic system is doing the processing doesn't matter — what matters is how many documents they need to process for their work.

### What needs to be added

The following documents need cost/storage guidance for self-hosting users:

- **SPEC.md** — Add a section on storage growth expectations and resource requirements. Include the relationship between document count, chunk count, embedding index size, and RAM requirements. Users need to know that pgvector's HNSW index must fit in RAM and what that means for their hosting plan as documents accumulate.

- **README.md** — The existing "Cost" section covers API costs (embedding, vision) and platform costs but doesn't address storage growth over time. Add guidance on what a typical agentic workload looks like (agents ingesting autonomously, not humans uploading manually) and how that affects their Postgres instance sizing and costs over months.

- **Onboarding skill** (`skills/ariadne-core-walkthrough/SKILL.md`) — When walking users through deployment options, surface the cost trajectory. Don't just say "free tier works" — explain that the free tier works to start but an active agent will outgrow it and what the step-up looks like.

- **Install skill** (`skills/ariadne-core-install/SKILL.md`) — During deployment, help users choose an appropriately sized Postgres instance based on their expected usage. Ask about their use case (monitoring a few sources vs. deep research) and recommend accordingly.

- **Deploy skill** (`skills/ariadne-core-deploy/SKILL.md`) — Platform-specific sizing guidance. What Railway plan for what usage profile. When to upgrade.

### Key points to convey

Costs depend on how many documents the user processes, not on what tool or agent is doing the work. Most Personal users will have light to heavy workloads where costs stay modest.

1. Storage grows as documents accumulate — costs scale with document volume
2. pgvector on a single Postgres instance handles up to ~5M vectors comfortably — most users won't approach this for years
3. Railway free tier gets you started; expect to move to a paid plan (~$5-10/mo) within weeks of regular daily use
4. Heavy users (bulk folder imports, research-intensive) should expect $10-20/mo in hosting costs
5. Very heavy workloads (30,000+ docs/month) will need larger instances — see cost analysis for sizing
6. API costs for embedding/vision are negligible — less than $0.01 per document
7. If a user outgrows pgvector, that's a signal they may benefit from Managed or Team capabilities (managed hosting, dedicated vector DBs) — not a failure of the Personal tier

### Actual Railway costs (April 2026)

Use these real numbers, not guesses:

| Resource | Railway cost | Notes |
|----------|-------------|-------|
| Disk storage | ~$0.17/GB/mo | Minimal for small-medium workloads |
| Egress | $0.05/GB | Negligible for search results (<30MB/mo even for heavy users) |
| Compute | Usage-based | ~$5/mo for a small container |
| Postgres | Usage-based | ~$5-10/mo depending on RAM for HNSW index |

### The value proposition for Personal users

Personal users get the same frontier token savings as Managed users — the pipeline is identical. Two real mechanisms drive the savings, and both apply from day one:

1. **Raw PDF bloat collapses by ~20x.** A 4,500-word document is ~100,000 tokens as a raw PDF but only ~5,000 tokens as clean Markdown. Every retrieval saves **~95,000 frontier tokens** that would otherwise hit at frontier-tier reasoning rates (~$3–$15/M, Sonnet-class through Opus-class).
2. **The LLM-driven extraction loop disappears.** Without this pipeline, your agent burns frontier tokens writing pdfminer code, debugging table parsing, retrying OCR, and looking at images at frontier vision rates (~$5/M for an Opus-class vision model). With it, that work happens in pre-written Python at $0 in tokens — and the deterministic pipeline is often *better* at tables and structure than a frontier model improvising extraction on the fly. We are using the most expensive possible tokens to do work a cheap specialized pipeline does *better*, not just cheaper.

**Beyond extraction.** Even on Personal, every document is chunked, embedded, and stored with **agent-writable, agent-readable, searchable structured metadata**. Agents can inject project names, notes, tags, and entities as JSON; future agents can filter, find, and read those notes back without re-extracting the source. The more documents a Personal user works with, the more valuable this layer becomes. Five documents don't need search; five thousand are unusable without it.

**Two audiences, two ways the savings feel:**

- **Single users on Claude Code / Claude Cowork (flat-rate subscriptions)** experience the savings as **runway** — hitting usage limits less often, longer productive sessions, more work per day before they hit any wall. They won't track token economics; they'll just notice the wall arrives much later.
- **Personal users running agentic systems that buy tokens directly** experience the savings as a **direct line-item cost reduction** — typically ~$15–$1,430/mo not burned on extraction depending on volume (see `pro-pricing.md` for the full table).

> **Floor, not ceiling.** Those per-volume dollar figures count Mechanism 1 only (the 20x raw-PDF-to-Markdown reduction × document count). They do **not** include Mechanism 2 (frontier tokens burned on the extraction loop), which is per-session and varies by workflow. Real savings are larger. The numbers are back-of-the-napkin for a typical user — if your agent re-opens the same documents across many sessions, your savings are larger; if it ingests once and never revisits, smaller. Full caveats: [`TOKEN_SAVINGS_FRAMING.md`](https://github.com/denson/ariadne-core/blob/master/docs/TOKEN_SAVINGS_FRAMING.md).

**The core pitch for any document with images:** You're paying frontier-tier rates (~$5/M for an Opus-class vision model) for the model to *look at* your images before it even starts thinking. With Ariadne Core, a small multimodal model handles the visual processing at pennies per million tokens — and **BYOM is supported** if you need a more powerful image model or a domain-specific one (medical imaging, engineering schematics, handwritten forms, etc.). The frontier model only ever sees clean extracted Markdown via a search interface.

Personal users already BYO everything — their own embedding models, their own vision models, their own API keys. They choose their own price/performance tradeoff. Managed just adds managed hosting and the option to buy tokens from us.

### Reference

- `roadmap/cost-analysis-pro-storage.md` — full cost analysis with usage profiles and scaling numbers
- `roadmap/pro-pricing.md` — two-mechanism framing and per-volume frontier savings tables
- [`ariadne-core/docs/TOKEN_SAVINGS_FRAMING.md`](https://github.com/denson/ariadne-core/blob/master/docs/TOKEN_SAVINGS_FRAMING.md) — canonical reference, anchor numbers, never-do-this-again rules
- Nate Jones, ["Your Claude Sessions Cost 10x What They Should"](https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what) — source for the 20x and 10x figures
