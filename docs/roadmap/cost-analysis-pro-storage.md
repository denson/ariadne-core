# Storage and Cost Analysis: Personal and Managed Editions

**Date:** 2026-04-07
**Status:** Discussion draft

---

## What Drives Cost

It's not who you are or what tools you use. It's how many documents you need to process.

A solo operator with a billion-dollar business running OpenClaw might process 5 documents a month — or 5,000. A 50-person engineering team might need to ingest an entire regulatory corpus on day one and then trickle updates. A researcher might bulk-import 10,000 papers and then mostly search. Whether a human or an agentic system is doing the work is irrelevant to the cost — what matters is the volume of documents going through the pipeline.

The tier structure (Personal → Managed → Team → Enterprise) is about **capabilities**, not usage volume:
- Personal: self-hosted, API key auth, MarkItDown extraction
- Managed: OAuth, better extraction (OCR, vision via a small multimodal model API), managed hosting
- Team: shared database, team agent, coordinated ingestion, access control
- Enterprise: custom data layer, custom extraction, graph representations, governance

Any tier can have light or heavy document volume. The cost analysis below applies to all tiers — it's about sizing infrastructure for a given workload, not about which tier someone is on.

### The business case

Both humans and agentic systems already find, store, and process text from many sources. Ariadne Core makes extraction dramatically more efficient. As extraction gets cheaper, users process more — creating demand for storage and retrieval. **The frontier-LLM tokens saved on extraction (typically ~$15–$1,430/mo depending on volume, Mechanism 1 floor) are dramatically larger than any additional storage costs incurred** — see `pro-pricing.md` for the per-volume tables and [`ariadne-core/docs/TOKEN_SAVINGS_FRAMING.md`](https://github.com/denson/ariadne-core/blob/master/docs/TOKEN_SAVINGS_FRAMING.md) for the canonical framing, anchor numbers, and caveats (the savings count raw-PDF-to-Markdown reduction only — real savings including the extraction-loop mechanism are larger). And the storage/search/retrieval need exists regardless — even without efficient extraction, you still need to store and search information. We just make the extraction step stop being the expensive part.

---

## Usage Profiles (applies to any tier)

These profiles are about document volume, not about which tier or what tool is doing the work.

### Light (~20-60 documents/month)
- Occasional document processing — a few docs per session, a few sessions per week
- Example: a consultant who processes client deliverables as they arrive
- **Monthly:** ~200-1,200 chunks

### Moderate (~100-500 documents/month)
- Regular daily use, processing reports/papers/specs as part of workflow
- Example: an engineer keeping up with specs and datasheets
- **Monthly:** ~1,000-10,000 chunks

### Heavy (~500-2,000 documents/month)
- Bulk imports, folder ingestion, research-intensive work
- Example: a researcher importing a corpus of papers, or onboarding a new project's documentation
- **Monthly:** ~5,000-40,000 chunks

### Very heavy (~5,000-30,000+ documents/month)
- Continuous ingestion — monitoring sources, crawling databases, regulatory filings
- Example: a compliance operation tracking regulatory changes across jurisdictions
- **Monthly:** ~50,000-600,000 chunks

### After 12 months of accumulation

| Profile | Documents | Chunks | Markdown text | Embedding index (1536-dim) |
|---------|-----------|--------|---------------|---------------------------|
| Light | 240-720 | 2.4K-14K | ~12-36 MB | ~20-115 MB |
| Moderate | 1,200-6,000 | 12K-120K | ~60-300 MB | ~100 MB-1 GB |
| Heavy | 6,000-24,000 | 60K-480K | ~300 MB-1.2 GB | ~480 MB-3.8 GB |
| Very heavy | 60K-360K | 600K-7.2M | ~3-18 GB | ~5-58 GB |

### How the numbers work
- Average document: ~50 KB markdown output
- Average chunks per document: 5-20 (depends on length and chunking strategy)
- Each vector: 1536 floats x 4 bytes = 6,144 bytes per vector
- HNSW index overhead: ~8 GB per 1M vectors (includes neighbor lists)
- Total storage per chunk: ~6 KB vector + ~1 KB metadata + chunk text

---

## pgvector Scaling Reality

pgvector on a single Postgres instance handles:

| Scale | Performance | Notes |
|-------|------------|-------|
| < 1M vectors | Excellent | Sub-50ms search latency |
| 1-5M vectors | Good | May need tuning, adequate for single user |
| 5-10M vectors | Adequate | Performance degrades, need optimization |
| 10M+ vectors | Poor | 15x slower than dedicated vector DBs, consider alternatives |

**Key constraint:** The HNSW index must fit in RAM. At 8 GB per 1M vectors, a very heavy workload after 12 months (up to 7.2M chunks) needs up to 58 GB of RAM just for the index.

**Light through heavy workloads:** pgvector on a single Postgres instance works comfortably for years. Even a heavy workload after 12 months is under 4 GB of index. A small Railway or Fly.io instance handles this fine.

**Very heavy workloads:** Will approach pgvector limits within 1-2 years. These workloads need a plan for migrating to a dedicated vector database (Pinecone, Weaviate) or Snowflake Cortex — which is a capabilities decision (Team or Enterprise tier), not a volume penalty.

---

## Infrastructure Costs by Workload

### Self-hosted (Personal tier — user pays provider directly)

| Profile | Postgres plan needed | Estimated monthly cost | Notes |
|---------|---------------------|----------------------|-------|
| Light | Railway free tier / Starter | $0-5/mo | Free tier works for months |
| Moderate | Railway Starter / Pro | $5-10/mo | Outgrows free tier within weeks of daily use |
| Heavy | Railway Pro | $10-20/mo | Needs more storage, still well within single-instance Postgres |
| Very heavy | Railway Pro / dedicated | $50-100+/mo | Large Postgres instance, significant storage |

Plus API costs for embedding/vision (user's own keys):
- Embedding: ~$0.02/M class (~$0.0001 per document for text)
- Vision: ~$0.14/M class (only for image-heavy docs; ~$0.002 per document at ~3 images each)

### Managed hosting (Managed tier and above — we pay, we charge)

| Component | Light | Moderate | Heavy | Very heavy |
|-----------|-------|----------|-------|------------|
| Postgres (storage) | ~$5/mo | ~$5-10/mo | ~$10-20/mo | ~$50-100/mo |
| Postgres (RAM for index) | ~$5/mo | ~$5/mo | ~$5-10/mo | ~$30-60/mo |
| App container | ~$5/mo | ~$5/mo | ~$5/mo | ~$10/mo |
| Egress | ~$1/mo | ~$1-2/mo | ~$2-5/mo | ~$10-20/mo |
| **Total infra/mo** | **~$16/mo** | **~$16-22/mo** | **~$22-40/mo** | **~$100-190/mo** |

### Shared costs (amortized across managed users)

| Component | Monthly cost | Notes |
|-----------|-------------|-------|
| API tokens (small multimodal model class — Gemma 4 via Google/Together AI is a current example) | Variable — ~$0.07–$0.14/M class | Zero idle cost. We pay only for actual processing. |
| Management/monitoring | Fixed | Our operational overhead |

No GPU infrastructure to manage. Token costs are nearly zero (~$0.001–0.003 per document) because the deterministic pipeline does extraction in pure code. Token costs are absorbed by the management fee at typical usage. Users can also BYO their own model API keys — zero token cost to us.

### The growing cost problem (managed hosting)

Storage costs are monotonic — they only go up as documents accumulate. A managed user with a heavy workload who joins in January:

| Month | Cumulative docs | Storage cost/mo | Embedding index |
|-------|----------------|-----------------|-----------------|
| 1 | 2,000 | ~$5 | ~160 MB |
| 6 | 12,000 | ~$10 | ~960 MB |
| 12 | 24,000 | ~$18 | ~1.9 GB |
| 24 | 48,000 | ~$30 | ~3.8 GB |

For heavy workloads, a flat $20/mo management fee + Railway costs stays profitable for over a year. For very heavy workloads ($50-100+/mo infra), a flat fee doesn't work — storage-aware pricing is needed.

---

## Two Managed Models

### Managed A: Managed Personal (dedicated Postgres on Railway)

- Each user gets their own Postgres instance and app container on Railway
- We handle setup, deployment, updates, backups
- Storage/egress costs are real and per-user

**Pricing options:**
- **Flat fee + storage overage:** $20/mo management fee + Railway costs, includes 5 GB storage, $0.25/GB/mo after that. User understands the model.
- **Tiered:** Managed ($20/mo management fee + Railway costs, 10 GB), Managed+ ($40/mo, 50 GB), Managed Max ($80/mo, 200 GB)
- **Pure markup:** We pass through Railway costs + management fee. Transparent but unpredictable for user.

**Pros:** Simple to build (concierge on top of Personal), user gets dedicated resources, no noisy neighbor issues, scales predictably per user.

**Cons:** Higher per-user cost at low scale, no shared infrastructure savings, each user needs their own instance management.

### Managed B: Multi-tenant (shared infrastructure)

- Shared Snowflake, or Neo4j + Pinecone/Weaviate in multi-tenant mode
- Data isolated at the application/schema level
- We run shared infrastructure

**Pricing options:**
- Same tier/overage models as Managed A but potentially lower price points due to shared infra
- Better margins at scale (100+ users sharing infrastructure)

**Pros:** Better unit economics at scale, shared infrastructure costs amortized, can offer lower price points.

**Cons:** More complex to build, noisy neighbor risk, multi-tenant security concerns, need to build isolation guarantees.

---

## Risk Factors

### Storage growth is the primary risk for managed hosting
For very heavy workloads, a flat fee without storage awareness will lose money. For light through heavy workloads, a flat fee can work for a long time. The risk scales with document volume, not with tier or whether a human or agent is doing the work.

### Egress is secondary but real
Every search returns chunks over the wire. An agent doing 100 searches/day at 5 chunks each = 500 chunk retrievals/day. At ~2 KB per chunk response, that's ~1 MB/day — negligible. But agents that retrieve full documents (get_document) at 50 KB each, 50 times/day = 2.5 MB/day. Still manageable, but worth monitoring.

### Ingestion bursts
An agent that ingests 1,000 documents in a burst generates significant API token volume. Since we buy from managed providers, bursts don't impact other users (no shared GPU contention). Large bursts push users past the $5 included allowance into pass-through pricing — which is breakeven for us now and profitable at scale with volume discounts. BYO users don't affect our costs at all.

### The "I never delete anything" problem
Users (and especially agents) have no incentive to delete old documents. Storage grows forever. Options:
- Offer archival tier (cold storage, slower retrieval, cheaper)
- Charge for active storage, free for archived
- Set default retention policies (configurable, not forced)
- Let the user's agent manage retention as part of its workflow

---

## Recommendation

Start with **Managed A (Managed Personal)** because:
1. It's simple — we're selling a managed service, not building multi-tenant infrastructure
2. Storage costs map directly to each user, no cross-subsidization risk
3. We learn real usage patterns before committing to shared infrastructure
4. Pricing with included storage + overage is honest and understood

Move to **Managed B (multi-tenant)** when:
1. We have 50+ Managed users and the per-user management overhead justifies shared infra
2. We've validated real-world usage patterns and can size shared resources confidently
3. The Team tier needs multi-tenant anyway, so the investment serves both

**Suggested starting price point for Managed A:**
- $20/mo management fee + Railway costs, includes 10 GB storage, managed hosting, embedding/vision tokens passed through at cost (nearly zero in practice). Or BYO model API keys. $0.25/GB/mo overage.
- $3/GB/mo overage
- A moderate user hits overage around month 8-10. That's fair — they've accumulated significant value by then.

These numbers need validation against actual Railway pricing and real user patterns.
