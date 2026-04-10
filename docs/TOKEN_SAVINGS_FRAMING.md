# Token Savings Framing — Canonical Reference

> **This document is the single source of truth for how Ariadne Core saves users frontier-LLM tokens.** Every other doc that talks about pricing, costs, margins, or token savings should link back here and use the anchor numbers below verbatim.

## How to use this doc

**Read this file end-to-end before editing any file that mentions costs, pricing, token savings, margins, frontier models, or "what users get for their money."** This includes:

- Anything in `docs/roadmap/` (`pro-pricing.md`, `pro-infrastructure-summary.md`, `roadmap.md`, `personal_edition_fixes.md`, `cost-analysis-pro-storage.md`, `general_fixes.md`, `token_pricing_snapshot.md`, `token_pricing_snapshot_update.md`)
- Pricing or value-prop sections in `README.md`, `CLAUDE.md`, or `SPEC.md`
- ConceptViz prompts that visualize savings or costs (`docs/assets/conceptviz_prompts/roadmap_prompts.md`, `docs/assets/conceptviz_prompts/infra_prompts.md`)
- Any new doc you're tempted to write that says "you save $X by using Ariadne Core"

**Before deleting any savings table, savings metric, or "frontier tokens saved" row: confirm with the user in chat first.** The savings story has been blundered before — two days of work were destroyed when an agent edited these files without understanding the framing. Do not repeat that mistake.

**When you commit changes that touch these topics, cite this file in the commit message** (e.g., "per `docs/TOKEN_SAVINGS_FRAMING.md`") so future audits can trace the framing back here.

---

## The canonical framing

**The savings come from frontier LLM tokens the user would otherwise burn doing extraction itself.** Two real mechanisms, both load-bearing:

### Mechanism 1 — Raw PDF bloat in the context window

A 4,500-word document is **~100,000 tokens as a raw PDF** (because of embedded fonts, layout metadata, binary structure) but only **~5,000 tokens as clean Markdown**. That's a **20x reduction per document, just from format conversion**, before any retrieval is involved.

When a frontier model has to read a raw PDF — drag it into the context window, look at it with vision tokens, parse the layout — every one of those 100K tokens hits at the frontier rate. Multiply across a multi-document research session and you get exactly the kind of session-cost blowup Nate Jones describes.

### Mechanism 2 — The LLM-driven extraction loop *(this is the big one)*

Without a pipeline, a frontier model that needs to read a document has to **figure out how to extract it itself**. That means:

- Writing Python in the conversation (extraction code, error handling)
- Calling pdfminer / PyMuPDF / OCR libraries
- Debugging table parsing when columns get misaligned
- Retrying when OCR fails on scanned pages
- Looking at images with frontier vision rates (~$5/M for an Opus-class vision model)
- Navigating inconsistent layouts across multi-page forms
- Writing "fix-up" code when the first pass produces garbage

**We are literally using the most expensive possible tokens (~$3–$15/M for frontier-tier reasoning models, Sonnet-class through Opus-class) to do something a very cheap model can do just as well, and a specialized model system can do *better*.** Not just cheaper — *better*. A deterministic pipeline + purpose-built small models capture tables, layout structure, and image semantics more accurately than a frontier model improvising extraction code on the fly. We're burning frontier tokens on a task where frontier models are not even the best tool.

### What our pipeline does instead

Ariadne Core replaces **both** mechanisms:

- **Extraction:** MarkItDown + format-specific parsers extract documents in pure Python at **$0 in tokens**. No frontier model writes code. No frontier model retries OCR. Pure deterministic pre-written code.
- **Embedding:** A small embedding model (~$0.02/M class) chunks and embeds the text.
- **Image description:** A small multimodal model (~$0.14/M class — Gemma 4, Gemini Flash, and similar are current examples) describes images by default. For tables and document structure, this specialized pipeline is often *higher quality* than a frontier model's ad-hoc parsing. **BYOM (bring your own model)** is supported — if a user needs a more powerful image model, a domain-specific multimodal model that performs well on their particular content (medical imaging, engineering schematics, handwritten forms, etc.), or a model they're already paying for, they can plug it in. The default is the cheap path; the door is open to whatever fits the use case.
- **Per-document cost to us — derivation:** for a typical 4,500-word document with ~3 images:
  - Text: 5,000 tokens × ~$0.02/M = **~$0.0001**
  - Images: 3 images × ~5,000 vision tokens each × ~$0.14/M = **~$0.0021**
  - **Total: ~$0.002 per document.** This is small, changes fast, and changes in our favor as small-model rates fall. The math scales linearly if your documents have more images or more text — plug in your own numbers and the conclusion still holds: this is rounding error compared to the savings.
- **What the frontier model sees:** clean Markdown via a search interface. It never has to look at the raw document, never has to write extraction code, never has to debug OCR. It gets *better* extracted content than it would have produced itself, at a tiny fraction of the token cost.

---

## Beyond extraction: the Ariadne layer over MarkItDown

Token savings on extraction is the headline number, but it is **not** the whole reason to use Ariadne Core instead of just running MarkItDown locally. Extraction is the first step; what Ariadne does *after* extraction is where the persistent, compounding value lives — and it ships in **every edition, including Personal**.

### Semantic embeddings + structured metadata

Once a document is extracted to Markdown, Ariadne:

1. **Chunks the text** into retrieval-sized pieces.
2. **Computes semantic embeddings** for every chunk with a cheap, purpose-built embedding model.
3. **Stores them in a vector database** alongside structured metadata.

This means an LLM (or an agent acting on the user's behalf) can do **semantic search** across a corpus — find the right paragraphs by meaning, not by keyword — and pull back exactly the context that's relevant to the question being asked. No more dragging whole documents into the context window hoping the answer is in there.

The combination of *deterministic extraction* + *semantic retrieval* is what makes Ariadne a "pipeline" rather than a one-shot extractor like MarkItDown alone. MarkItDown gets you Markdown. Ariadne gets you Markdown that's *findable* by meaning, indefinitely, across thousands of documents.

### Metadata is a first-class, agent-writable *and* agent-readable surface

Every document and every chunk carries **structured metadata** — and that metadata is not a static blob set at ingestion time. **Agents and LLMs can both write to it and read and search across it.**

- An agent ingesting a batch of documents related to one project can inject the project name into the metadata as structured JSON, so future searches can be scoped to that project.
- An agent reviewing a contract can attach notes, tags, status flags, or extracted entities to the document so the next agent (or the same agent in a future session) can find them instantly.
- A multi-agent workflow can use metadata as a scratchpad — "I have already reviewed this; here's my conclusion; here's what to look at next" — without needing to re-read the source.
- Filters on metadata (collection, source_file, file_type, tags, document_id) compose with semantic search, so an agent can ask "find chunks about pricing structure, but only in documents tagged `quarterly-report` from this project."
- An agent can **read** metadata back at any time — pull the notes the previous agent left, see which documents have already been processed, retrieve the tags or status flags attached to a chunk — without paying to re-extract or re-summarize the source. Metadata is queryable, filterable, and returned alongside every search result.

This is what turns a pile of extracted Markdown into a **searchable, annotatable, agent-friendly knowledge base**. It is the part of Ariadne that the user does not buy with money — it is the part the user buys with the *right architecture choice*.

### Why this matters for the savings story

We are **not** putting a hard dollar value on the metadata + semantic search layer the way we do for raw extraction tokens. The savings here are real but harder to quantify in advance because they depend on how the user works:

- **Personal users** get this in the free Personal edition — same pipeline, same metadata, same retrieval. The reason to choose Ariadne over MarkItDown alone is the embeddings + metadata, not the extraction (MarkItDown does the extraction either way; Ariadne uses MarkItDown internally).
- **The more documents a user works with, the more valuable this layer becomes.** Five documents and you don't need search. Five hundred documents and you cannot live without it. Five thousand documents and an agent without retrieval is just a tab-soup nightmare.
- **The compounding effect:** every document an agent processes can leave notes in metadata for future agents, so the system gets smarter over time without re-paying extraction or re-burning context.

When pitching, lead with the extraction-token savings (because they are quantifiable and large), then **immediately follow** with "and you also get semantic search + agent-writable metadata over everything you ingest, in every edition, which scales in value the more you use it." Do not let the savings pitch crowd out the architecture pitch — they are complementary.

---

## Two audiences feel the savings differently

This is critical for the framing. Not every user sees a dollar sign on a bill. There are two distinct audiences and the savings story must speak to both — never frame it only in dollars, and never frame it only as runway.

### Audience 1 — Single users on Claude Code / Claude Cowork (flat-rate frontier subscriptions)

These users are not buying tokens by the million. They're on a subscription with **usage limits**. For them, the savings show up as:

- **Hitting their limits less often.** A raw PDF in a conversation eats context window and burns through rate limits fast.
- **Longer productive sessions** before they get rate-limited or cut off.
- **More work per day** before hitting the daily/weekly cap.
- **More work per dollar of subscription**, even though the dollar-per-document number is invisible to them.

The pitch to this audience is about **runway**, not billing. "I got more done before Claude told me to slow down."

### Audience 2 — Agentic systems buying tokens directly (OpenClaw, Open Brain, OB1, custom agents)

These users (or the systems acting on their behalf) pay per-token to a frontier provider. For them, the savings are:

- **A direct line-item cost reduction** on their monthly bill.
- **Quantifiable in dollars** for a given volume of documents processed.
- **Predictable** — they can model "X documents per month → Y dollars saved at Sonnet rates."

The pitch to this audience is about **dollars**. The frontier-tokens-saved tables in `pro-pricing.md` speak directly to them.

**Both audiences benefit from exactly the same mechanism. They just feel it differently. Any doc that talks about savings must acknowledge both experiences.**

### What both audiences also get: persistent "memory" across documents

Beyond the per-session savings, **both audiences get a real benefit that has nothing to do with usage limits or token bills: their LLM gains a kind of persistent "memory" across every document they have ever extracted, plus all the metadata attached to each one.**

This is a direct consequence of the embeddings + metadata layer described above, but it deserves its own beat in the pitch because it is what users *feel* day to day, regardless of which audience they are in. And it is something users can leverage with very little ceremony:

- **Source-of-truth tracking.** When ingesting a PDF downloaded from a URL, drop the original source URL into metadata. Months later, when the LLM surfaces a passage from that document in a search result, it knows exactly where the passage came from and can show the user the link — no re-googling, no "I'm not sure where I read this," no broken provenance chain.
- **Project context that survives session boundaries.** Tag a batch of documents with the project name once, and every future agent session that searches within that project gets the right scope automatically. The "memory" lives in metadata, not in the conversation.
- **Cumulative knowledge, not per-session knowledge.** Every document a user processes adds to a corpus the LLM can search semantically forever after. A single Claude Code session ends; the corpus and its metadata persist. The next session starts with everything the previous one already knew.
- **Cross-document recall.** Ask "what did I learn about pricing structure across all the contracts I reviewed last quarter?" and the LLM can find the relevant chunks across hundreds of documents — with source citations intact via metadata — without any of those documents being in the current context window.

For the **Claude Code / Cowork** audience, this is the difference between "Claude that helps me with whatever I just pasted in" and "Claude that knows my whole document history and can find anything in it." For the **agentic system** audience, this is the difference between paying the same extraction cost on every run and **paying it once and reusing the result indefinitely**, with metadata-driven recall as a free side effect.

**Always pitch this alongside the savings.** Token savings are the headline; persistent searchable memory is the lived experience. They reinforce each other — the savings make it cheap to ingest a lot of documents, and the memory makes a large ingested corpus useful instead of overwhelming.

---

## Nate Jones's punchline (the 10x)

From "Your Claude Sessions Cost 10x What They Should" (https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what):

A wasteful 30-turn session — raw PDFs in context, Opus for everything, conversation sprawl, context resubmission — runs **$8–$10**.

The same work done cleanly — markdown-first, fresh conversations every 10–15 turns, model-appropriate routing — runs **~$1**.

**That's the 10x.** Same outcome, 1/10 the spend.

Nate identifies six waste patterns:

1. Raw document ingestion (the 20x penalty above)
2. Conversation sprawl (multiplicative cost as turn count grows)
3. Model misuse (Opus for formatting / proofreading instead of reasoning)
4. Web search waste (10K–50K extra tokens per native search)
5. Context resubmission (full history every turn)
6. No markdown conversion before ingestion

Ariadne Core directly attacks #1 and #6, and the deterministic pipeline avoids the #2/#3/#5 escalation that happens when a frontier model is improvising extraction in a long conversation.

---

## Caveats before you read the anchor table

Three things the table below does *not* try to do. Stating them explicitly so a meeting reviewer has the answers up front.

### 1. The savings tables count Mechanism 1 only

The "frontier tokens saved per doc retrieval" anchor (~95,000) and the volume-derived monthly savings tables both come from **Mechanism 1 alone** — the raw-PDF-to-Markdown 20x reduction, multiplied by document count. **They do not include Mechanism 2** (the frontier-tokens-burned-on-extraction-loop savings), even though Mechanism 2 is described as "the big one" above.

We exclude Mechanism 2 from the dollar figures on purpose: it's per-session, not per-document, and varies wildly by workflow. Some agents and tools today already capture *some* of Mechanism 2 by routing extraction to subroutines or built-in PDF parsers. Frontier models will get better at extraction over time. But a deterministic pipeline + purpose-built small models will remain more efficient than a frontier model improvising extraction code, unless those frontier models effectively copy our approach.

**The anchor table is therefore a floor, not a ceiling.** Real savings are larger than the numbers below.

### 2. No sensitivity / range analysis — the savings dwarf the variance

A reviewer might ask: what if the user's documents are 9,000 words instead of 4,500? What if there are zero images, or ten? What if they're on Haiku instead of Opus? Different inputs, different numbers.

We are deliberately not building a sensitivity table around these point estimates. **The savings are large enough at every reasonable parameter combination that the variance does not change the conclusion.** A heavy user saves somewhere between hundreds and thousands of dollars per month at frontier rates. The error bars on that are wide, but the *sign* of the answer is not in question. Once Pro is up and we have real users running real workloads, we'll publish empirics across actual document distributions. Until then, the back-of-napkin numbers are honest about being back-of-napkin and the magnitude defends itself.

### 3. Back-of-the-napkin caveat for sessions-per-document

Mechanism 1 is per-retrieval and Mechanism 2 is per-session, but the volume tables are sized per-document for a *typical* user — one whose agent opens a document, asks a handful of questions, and moves on. We don't try to model the bridge from documents to sessions because it varies wildly by workflow. **If your agent re-opens the same document across many sessions, your real savings are larger than the table shows; if it ingests once and never revisits, smaller. You know which you are.** Run Nate Jones's `token_translator` prompt on a real session of yours if you want a number tied to your own workflow rather than ours.

---

## Anchor numbers — single source of truth

**Every doc that cites savings must use these numbers. No invented figures. If you need a number that isn't here, ask the user before making one up.**

> Vendor rates below are approximate frontier-tier and small-model numbers as of 2026-04. They are not snapshotted with citations because they change on quarterly cycles in **only one direction** in this market: down. Vendors compete by dropping rates as inference hardware improves and new entrants commoditize each tier. The worst case for our savings story is that our pipeline cost shrinks while frontier rates stay the same — i.e., the savings get *bigger* over time, never smaller. The per-document derivations scale linearly if you plug in different numbers.

| Metric | Value | Source |
|--------|-------|--------|
| Raw PDF tokens (4,500-word doc) | ~100,000 | Nate transcript |
| Clean Markdown tokens (same doc) | ~5,000 | Nate transcript |
| Per-document token ratio | 20x | Nate transcript |
| Wasteful 30-turn session cost (Opus, raw PDFs) | $8–$10 | Nate transcript |
| Clean 30-turn session cost (markdown-first) | ~$1 | Nate transcript |
| Session cost reduction | 8–10x | Nate article title |
| Opus-class input rate | ~$15/M | frontier reasoning, premium tier (2026-04) |
| Sonnet-class input rate | ~$3/M | frontier reasoning, mid tier (2026-04) |
| Opus-class vision rate | ~$5/M | frontier vision, premium tier (2026-04) |
| Frontier tokens saved per doc retrieval | ~95,000 | 100K − 5K |
| Cost saved per doc @ Sonnet | ~$0.29 | 95K × $3/M |
| Cost saved per doc @ Opus | ~$1.43 | 95K × $15/M |
| Our pipeline cost per doc | ~$0.002 | embedding + vision |
| Our pipeline extraction token cost | $0 | pure Python |

### Volume-based savings (derived from anchors)

For the user-example tables in `pro-pricing.md` and `pro-infrastructure-summary.md`. Range = Sonnet to Opus.

| Volume | Frontier tokens saved/mo | Cost saved/mo (Sonnet→Opus) |
|--------|--------------------------|------------------------------|
| Light (~50 docs/mo) | ~4.75M | **~$15–$70/mo** |
| Moderate (~300 docs/mo) | ~28.5M | **~$85–$430/mo** |
| Heavy (~1,000 docs/mo) | ~95M | **~$290–$1,430/mo** |
| Very heavy (~10,000 docs/mo) | ~950M | **~$2,900–$14,300/mo** |

These are the savings the Managed-tier $20/mo management fee buys you, *on top of* the deterministic pipeline being more accurate than ad-hoc frontier extraction. **Mechanism 1 only — see "Caveats before you read the anchor table" above.** Real savings including Mechanism 2 are larger.

---

## What I must never do again

This list exists because an agent (me) made every one of these mistakes in the session of 2026-04-09 and destroyed two days of work doing it.

1. **Never delete user-facing savings tables.** If a savings table looks wrong, ask the user. Don't delete it.
2. **Never conflate "our cost to extract" with "what the user saves."** Our cost is ~$0.002/doc. The user's savings are $0.29–$1.43/doc. These are different numbers measuring different things.
3. **Never describe the savings as "cheap vision OCR."** That misses the raw-PDF bloat (Mechanism 1) AND the bigger point about frontier tokens burned on extraction (Mechanism 2). Vision is just one piece.
4. **Never frame the savings only in dollars.** Single users on Claude Code / Claude Cowork experience the savings as *runway* — not hitting limits, not as a dollar bill drop. Both framings must appear in any user-facing doc.
5. **Never describe the specialized pipeline as only "cheaper."** In many cases it is also *better* at tables, structure, and images than a frontier model doing ad-hoc extraction. "Better, not just cheaper" is part of the pitch.
6. **Never edit anything about pricing, costs, margins, or savings without first reading this doc and confirming with the user.** Plan first. Get approval. Then execute.
7. **Never let the dollar-savings pitch crowd out the architecture pitch.** Token savings are the headline number, but the semantic search + agent-writable metadata layer is the *architectural* reason to use Ariadne over MarkItDown alone. It ships in every edition (including Personal), and its value scales with document volume. Lead with the savings, immediately follow with the architecture. They are complementary, not redundant — never present one without the other in a user-facing pricing or value-prop doc.

---

## Reference materials

The original sources for the framing above. Read these if you want to go deeper or verify a number.

- [`docs/skills/ariadne-core-walkthrough/saving_tokens_transcript.txt`](skills/ariadne-core-walkthrough/saving_tokens_transcript.txt) — Nate Jones video transcript. Source of the 100K→5K and $8–$10 → ~$1 numbers, plus the six waste patterns.
- [`docs/skills/ariadne-core-walkthrough/stupid_button_prompt.txt`](skills/ariadne-core-walkthrough/stupid_button_prompt.txt) — "Stupid Button" diagnostic prompt. Rates a user's token burn 1–10 across the six waste patterns.
- [`docs/skills/ariadne-core-walkthrough/token_translator.txt`](skills/ariadne-core-walkthrough/token_translator.txt) — "Token Translator" prompt. Reconstructs the hidden token math of a session phase-by-phase.
- **Article:** "Your Claude Sessions Cost 10x What They Should" — https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what
- **PromptKit:** https://promptkit.natebjones.com/20260330_161_promptkit_1
