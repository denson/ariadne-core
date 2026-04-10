# General Fixes and Enhancements

**Date:** 2026-04-07
**Status:** Open

---

## Open source philosophy: encourage community workarounds

Convey this sentiment across all docs (README, CLAUDE.md, onboarding skill, install skill, SPEC):

We expect the community will quickly come up with workarounds for various limitations of the Personal edition. Want to set up OAuth yourself? Great, do it. Want to connect to Pinecone instead of Postgres? Go for it. Want to add SSO, swap in a different vector store, build your own extraction pipeline on top? We're happy you're doing that.

What we're doing for Managed, Team, and Enterprise customers is setting up and managing those same kinds of things with an emphasis on reliability and security. If you can do it without us, go for it.

### Where to surface this

- **README.md** — in the Editions section. Frame paid tiers as "we handle this for you reliably and securely" not "you can't do this without paying us"
- **CLAUDE.md** — already has "You can also create your own OAuth for the Personal edition." Expand this sentiment to other capabilities.
- **Onboarding skill** — when explaining tiers: Personal is solo and self-hosted, Managed is solo with managed hosting (BYO models or buy from us), Team is a group sharing a common database with a team agent handling bulk ingestion. The difference between tiers is capabilities and who shares the data — not artificial feature gates. Managed is a managed service — users don't see or run the code.
- **SPEC.md** — note that the architecture is designed to be extensible. The `VectorStore` protocol, `APIKeyStore` protocol, and extraction router are extension points the community can use.

### Tone

Not "you're on your own" — more like "we built it to be extensible, we love seeing what people do with it, and when you want someone to handle it professionally, that's what the paid tiers are for."

---

## Token savings dashboard — core retention strategy

This is the single most important retention mechanism across all paid tiers. We need to show every user — at every time scale — how many **frontier model tokens** Ariadne Core has saved them and what that translates to in real money.

The people we're selling to have likely seen Nate B. Jones's video on token waste. They already know that raw PDFs cost 100K+ tokens when 5K of Markdown would do. They know the 8-10x cost reduction is real. They know Jensen Huang's $250K/year/engineer figure. What we need to do is prove it's happening for them, specifically, with their data, on an ongoing basis.

### What to build

A usage report at every time scale — daily, weekly, monthly, yearly, and lifetime — that shows:

1. **Documents processed** — count and total size of raw documents extracted
2. **Frontier tokens saved** — estimated tokens that would have been consumed if the raw documents had been sent directly to the model, minus the tokens actually consumed via search retrieval (chunks returned). This is the big number — the 20-100x savings on expensive model tokens.
3. **Cost savings by model** — translate frontier token savings into dollar amounts for the models the user might be using:
   - Claude Opus 4.6 ($5/M input)
   - Claude Sonnet 4.6 ($3/M input)
   - Claude Haiku 4.5 ($1/M input)
   - GPT-5 ($1.25/M input)
   - GPT-5 Mini ($0.25/M input)
   - Gemini 3.1 Pro ($2/M input)
   - Gemini 2.5 Flash ($0.30/M input)
   - Open models via Together AI / Groq (Llama 3.3 70B ~$0.88/M, 8B ~$0.10/M)
   - Next-gen models (update pricing as Mythos etc. drop — the savings will be even more dramatic)
4. **Efficiency ratio** — tokens retrieved via search vs tokens that would have been consumed by raw document context (e.g., "you used 500 tokens of search results instead of 100,000 tokens of raw PDF — 200x more efficient")
5. **Cumulative lifetime savings** — running total since the user started. This number only grows and becomes the most compelling retention metric over time.

### Time scales matter

| Time scale | What the user sees | Retention effect |
|-----------|-------------------|-----------------|
| Daily | "Today you saved 2.4M frontier tokens (~$12 at Opus rates)" | Immediate feedback loop |
| Weekly | "This week: 12M tokens saved, $60 at Opus rates" | Habit reinforcement |
| Monthly | "This month: 48M tokens saved, $240 at Opus rates" | Justifies the Managed tier bill |
| Yearly | "This year: 580M tokens saved, $2,900 at Opus rates" | Makes renewal a no-brainer |
| Lifetime | "Since you started: 1.2B tokens saved, $6,000 at Opus rates" | Makes switching unthinkable |

### Where to surface this

- **REST API endpoint** — `/api/stats/savings` with date range parameters (day/week/month/year/lifetime)
- **MCP tool** — a `usage_stats` or `savings_report` tool so the agent can report savings to the user conversationally
- **Search results** — optionally include a "tokens saved" note in search responses (e.g., "this search returned 3 chunks (1,200 tokens) from a document that would have cost 85,000 tokens to send raw")
- **Monthly email/notification** — proactive reminder of value delivered (for Managed/Team/Enterprise)

### Data we already have

The `document_interactions` and `search_log` tables already track every operation with timestamps. Documents store their raw size and chunk count. We have most of the data — we just need to compute and present the savings.

### The system gets more efficient over time

The built-in search and retrieval functionality should improve continuously. As new memory and retrieval technologies become available — or as we develop them — we integrate them to return better results with fewer tokens. Better search precision means smaller, more targeted result sets, which means even more frontier tokens saved per query.

This creates a compounding value effect: the longer someone uses Ariadne Core, the more efficient it gets at serving them, the more tokens it saves, the harder it becomes to justify leaving.

### Cross-tier development flywheel

Improvements flow in all directions across tiers:

- **Community (Personal)** builds workarounds, extensions, new vector store backends, custom extraction scripts
- **Managed** validates which community innovations are worth managing and securing
- **Team** surfaces coordination patterns (dedup-as-coordination, team agent strategies) that benefit everyone
- **Enterprise** develops custom extraction and graph representations that can be generalized back down

Any development in any tier can be shared by all. The open source base means community innovations flow up; our managed infrastructure means reliability innovations flow down. This cross-fertilization accelerates the improvement rate across the board.

### What users actually feel

Most users won't look at a savings dashboard. They'll experience the value as: hitting their usage limits less often. A raw PDF in a conversation eats context window and burns through rate limits fast. The same document extracted and retrieved via search uses a fraction of the tokens — longer productive sessions, fewer "you've reached your limit" interruptions, more work per dollar of frontier subscription.

The dashboard quantifies what they already feel. It turns "this tool makes my work smoother" into "this tool saved me $240 this month."

### Why this matters for pricing

The business case for every tier depends on users understanding the value. A user who sees "Ariadne Core saved you $240 this month across 3,200 document retrievals" is a user who renews their Managed subscription without thinking twice. A user who sees an opaque monthly charge with no visible value is a churn risk.

Our pricing captures a tiny fraction of the value we create. The token savings dashboard makes that ratio visible — and makes the subscription feel like the best deal they have.

### The economics

Even as we become more efficient at extraction (which is the whole point), that efficiency creates more demand for storage and retrieval — users process more documents because it's cheap to do so. The business opportunity is that the money saved on extraction is much greater in most expected scenarios than any additional storage costs. And the storage/search/retrieval need exists regardless — even without efficient extraction, users still need to store, search, and retrieve information. We just make the extraction step stop being the expensive part.
