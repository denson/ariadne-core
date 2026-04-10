# ConceptViz Prompts for Edition Progression Roadmap

---

**img_01 — The Five Tiers**

Five comparison cards arranged left to right like a pricing page, growing slightly taller as they go. Card 1 (light gray tint, labeled "MarkItDown"): a hammer icon at the top. Subtitle: "Extraction Only (Microsoft)." Bullet points stacked vertically: "Runs locally," "No storage or search," "Built-in MCP server," "Not our product." A small italic note at the bottom of the card: "Where it all starts." Card 2 (green tint, labeled "Personal"): a wrench icon at the top. Subtitle: "Free / Open Source." Bullet points: "Self-hosted," "API key auth," "Full pipeline: extract + store + search," "Single user + their agents." Card 3 (blue tint, labeled "Managed — $20/mo + infra"): a cloud icon at the top. Subtitle: "$20/mo + infra." Bullet points: "We manage security, backups, upgrades," "Own Railway Postgres + Weaviate," "BYO models or buy from us," "Single user + their agents." Card 4 (amber tint, labeled "Team"): a group-of-people icon at the top. Subtitle: "Shared Database." Bullet points: "Team agent ingests for everyone," "Dedup = coordination," "Collection permissions," "Multiple users + agents." Card 5 (purple tint, labeled "Enterprise"): a building icon at the top. Subtitle: "Custom Solutions." Bullet points: "Custom extraction pipelines," "Custom storage backends," "RBAC + full governance," "Graph representations (future)." A shared footer below all five cards reads: "Start anywhere. Grow when you need to." Caption at bottom: "From local extraction to enterprise knowledge infrastructure — pick where you need to be."

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_02 — Data Layer vs. MCP/Skills Layer**

A two-layer horizontal diagram. Top layer (light blue tint, labeled "MCP Server + Skills Layer"): a row of identical plug icons representing MCP clients — Claude Code, OpenClaw, Open Brain, Cursor, Claude Cowork — all connecting downward to a single horizontal bar labeled "MCP Server + Skills." A callout box attached to this bar reads: "Same tools for every tier. Doesn't know or care how many users are behind the data layer." Bottom layer (warm gray tint, labeled "Data Layer"): four columns underneath the bar, one per tier arranged left to right. Personal column: a single small database icon labeled "Personal (self-hosted)." Managed column: a small database icon (Postgres elephant) plus a small hexagon icon (Weaviate), both on a shared platform labeled "Railway," with the heading "Managed ($20/mo + infra) — Own DB, managed by us." Team column: a larger database icon with multiple user silhouettes around it and a robot icon labeled "Team Agent" feeding documents into the database. Enterprise column: a large database icon with a label "Per-customer deployment" and a small menu icon suggesting stack selection, labeled "Enterprise (Custom Stack)." An arrow from the MCP bar points down to all four columns equally, labeled "Same interface." A thick horizontal dividing line separates the two layers with a label on the line reading: "This boundary is the architecture." Caption at bottom: "Tier differences live below the line. The skills layer is the same for everyone."

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_03 — Dedup as Coordination (The Team Workflow)**

A two-part scene stacked vertically, top and bottom, with a dividing line between them. Top section (labeled "Step 1: Team Agent Ingests"): on the far left, a robot icon labeled "Team Agent." To its right, a stream of document icons flowing rightward along a conveyor belt — the documents are labeled "SEC Filings," "Regulatory Updates," "Research Papers." The belt passes through four labeled stations with simple icons above each: "Extract" (hammer), "Chunk" (scissors), "Embed" (magnet), "Store" (vault door). Documents exit into a large rounded rectangle on the far right labeled "Shared Data Store" — each document inside the vault has a small fingerprint stamp icon on it representing its content hash. Bottom section (labeled "Step 2: User Encounters Same Document"): on the far left, a person silhouette with a smaller robot beside them, labeled "User + Their Agent." They hold a single PDF document icon. An arrow sends the PDF toward the same vault from the top section. Between the PDF and the vault, a large fingerprint icon with two fingerprints side by side and a checkmark between them — representing the hash comparison. Instead of entering the vault, a card fans out from the vault toward the user showing rich metadata: "Already ingested by Team Agent," "Collection: Q1 Filings," "Ingested: March 15," "3 related documents available." The user's agent receives this card with a satisfied checkmark. A callout box positioned between the two sections reads: "The hash isn't just dedup — it's coordination." Caption at bottom: "The team agent does the heavy lifting. Everyone else gets instant access."

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_04 — DIY vs. Managed: What You're Really Paying For**

An engineering-document-style cost breakdown chart on a light warm-gray background. NOT marketing — this is a transparent line-item explanation of where every dollar goes. Tone is precise, technical, and honest. The audience is engineers who want to verify the math before recommending the system.

A heading bar at the top reads: "Where the money actually goes." A subheading underneath reads: "Token costs are nearly zero — our deterministic pipeline does the heavy lifting in pure code. Hosting is the real cost. Managed adds $20/mo for operations work."

---

**SECTION 1 — Per-document cost breakdown** (top half of the image)

A small four-row table titled "Cost per document" showing the actual pipeline steps:

| Step | What it does | Token cost |
|---|---|---|
| Pre-written extraction code (MarkItDown + format parsers) | Pure Python — parses PDF, DOCX, PPTX, XLSX, etc. directly | **$0** |
| Text chunking | Pure code — splits Markdown into ~500-token chunks | **$0** |
| Text embedding (small embedding model class, ~$0.02/M) | ~5K tokens per doc | **~$0.0001** |
| Image description (small multimodal model class, ~$0.14/M, only when images present) | ~3 images × 5K tokens per doc | **~$0.002** |

A small footnote underneath reads: "Total: ~$0.002 per document. The model landscape changes constantly — small multimodal models in this class include Gemma 4, Gemini Flash, and similar; we may move between them as the market shifts. Cost per unit of intelligence only goes down in this market."

---

**SECTION 2 — Monthly cost by volume** (middle of the image)

A four-row table with five columns. Column headers in bold: "Documents/month" | "Hosting (Railway)" | "Token costs" | "DIY total" | "Managed total (+$20 mgmt fee)"

| Documents/month | Hosting | Tokens | DIY total | Managed total |
|---|---|---|---|---|
| ~50 | $5 | ~$0.10 | **~$5** | **~$25** |
| ~300 | $5 | ~$0.60 | **~$6** | **~$26** |
| ~1,000 | $10 | ~$2 | **~$12** | **~$32** |
| ~10,000 | $30 | ~$20 | **~$50** | **~$70** |

A vertical "+$20 mgmt fee" bracket spans all four rows along the right edge of the "Managed total" column, labeled once: "Flat $20/mo at every volume — covers security, backups, and version upgrades."

---

**SECTION 3 — Frontier tokens saved by volume** (paired directly with Section 2, same visual treatment)

A four-row table immediately below Section 2 using the same row labels for direct comparison. Column headers in bold: "Documents/month" | "Frontier tokens saved/mo" | "Frontier $ saved/mo @ Sonnet-class (~$3/M)" | "Frontier $ saved/mo @ Opus-class (~$15/M)"

| Documents/month | Frontier tokens saved | Sonnet-class | Opus-class |
|---|---|---|---|
| ~50 | ~4.75M | **~$15/mo** | **~$70/mo** |
| ~300 | ~28.5M | **~$85/mo** | **~$430/mo** |
| ~1,000 | ~95M | **~$290/mo** | **~$1,430/mo** |
| ~10,000 | ~950M | **~$2,900/mo** | **~$14,300/mo** |

A small footnote underneath reads: "Anchor: ~95,000 frontier tokens saved per document retrieval (a 4,500-word doc is ~100K tokens raw, ~5K tokens as Markdown — 20x reduction). **Mechanism 1 only — floor, not ceiling.** The table counts the raw-PDF-to-Markdown savings times document count. It does NOT include Mechanism 2 (frontier tokens burned on the extraction loop itself), which is per-session and varies by workflow — real savings are larger. Back-of-the-napkin for a typical user; if an agent re-opens the same documents across many sessions, savings are larger, if it ingests once and never revisits, smaller. Per `TOKEN_SAVINGS_FRAMING.md`."

A horizontal bracket below the two stacked tables labeled: "What you pay us (Section 2) vs what you stop burning on frontier extraction (Section 3) — same row order, compare line by line." Visual emphasis: a thin arrow from each row in Section 2 pointing to the same row in Section 3, making the per-volume comparison unmistakable.

---

**SECTION 4 — Where the savings actually come from** (small panel at the bottom)

A separate small panel with a cool blue tint titled "What you'd otherwise pay for." The text reads:

"The savings come from frontier LLM tokens the user's agent would otherwise burn doing extraction itself. Two real mechanisms, both load-bearing:

(1) **Raw PDF bloat in the context window.** A 4,500-word document is ~100,000 tokens as a raw PDF but only ~5,000 tokens as clean Markdown — a 20x reduction per document just from format conversion.

(2) **The LLM-driven extraction loop — this is the big one.** Without a pipeline, a frontier model has to figure out extraction itself: write Python in the conversation, call pdfminer, debug table parsing, retry when OCR fails, look at images at frontier vision rates (~$5/M for an Opus-class vision model). We are using the most expensive possible tokens (~$3–$15/M for frontier-tier reasoning models, Sonnet-class through Opus-class) to do work a cheap specialized pipeline can do *better* — not just cheaper. A deterministic pipeline + purpose-built small models capture tables, layout structure, and image semantics more accurately than a frontier model improvising extraction code on the fly.

Our pipeline replaces both. MarkItDown + format parsers extract in pure Python for $0 in tokens. A small embedding model (~$0.02/M class) handles text. A small multimodal model (~$0.14/M class) handles images by default — BYOM supported. The frontier model only ever sees clean Markdown via a search interface."

A second small footer panel beside it (warm gray) labeled "Two audiences, two ways the savings feel": "Single users on Claude Code / Claude Cowork experience the savings as **runway** — hitting usage limits less often. Agentic systems buying tokens directly experience them as a **direct line-item cost reduction** on the monthly frontier bill. Same mechanism, different lived experience."

---

A footer bar spans the bottom reading: "What we charge is small. What you stop burning is large. The $20/mo is for the engineering time you don't spend on security, backups, and updates."

Caption at bottom: "Honest breakdown. The DIY math and the savings math are both right there — verify them yourself."

---

Visual style: This is an engineering document, not a marketing piece. Use clean tables with thin borders, monospaced numbers, no big colorful pills, no dramatic scale-breaks, no green-vs-amber theatrics. Think "white paper" or "technical RFC," not "pricing page." Colors should be muted — light gray table backgrounds, dark text, occasional blue tint for callouts. The reader should feel they're being shown the math, not sold to.

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_05 — Enterprise Stack Selection Menu**

A menu-style layout resembling a restaurant menu with distinct sections. At the top center, a heading in bold: "Enterprise Data Layer — Selected Per Customer." Below the heading, four horizontal rows stacked vertically, each a rounded rectangle card with a colored left-border accent and an icon on the far left. Row 1 (blue left-border accent, snowflake icon on the left): heading "Customer has Snowflake" — three items flowing rightward separated by arrow icons: "Snowflake Postgres → Native Tables," "Cortex Search," "Snowflake Graph." Row 2 (green left-border accent, hexagon icon on the left): heading "Starting fresh" — three items: "Postgres + Weaviate (our default)," "Managed vector search," "Graph representations (future)." Row 3 (amber left-border accent, puzzle piece icon on the left): heading "Has existing vector DB" — three items: "Integrate with theirs (Pinecone, Qdrant, Milvus)," "Their system," "Weaviate adapter or custom." Row 4 (gray left-border accent, lock icon on the left): heading "Strict data residency" — three items: "On-prem deployment," "Self-hosted Weaviate + Postgres," "Air-gapped option." At the bottom of all four rows, a shared footer bar reads: "Same Ariadne Core. Different foundations. We architect it for the customer's reality." Caption at bottom: "Not one stack. A menu. We pick what fits."

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_06 — The Two Token Economies**

A split scene divided vertically by a thin line. Left side (cool blue tint, labeled "Tokens We Charge For"): a small, calm scene. A modest API cloud icon at the top labeled "Small Multimodal Model (class)" with a single icon below it — a unified multimodal icon combining a magnet, camera-eye, and OCR document. Below the icon, a tiny price tag reading "pennies per million tokens." A banner across the middle of the left side reads "Included with Managed — or bring your own model." At the bottom of the left side, a small coin stack icon with the label "Our tokens: pennies." The overall impression is small, manageable, inexpensive. Right side (warm amber-red tint, labeled "Tokens We Save You"): a dramatically larger scene. A glowing brain icon at the top representing a frontier model (labeled "Frontier-Tier Models (Sonnet-class through Opus-class)"). Below the brain, a massive avalanche of raw PDF icons, spreadsheet grids, and slide decks — all crossed out with a large X. Next to the crossed-out avalanche, a single clean Markdown card with a checkmark. A token counter shows "100,000 tokens → 5,000 tokens" with a large "20x" callout. (Note: the correct anchor number is 20x — a 4,500-word document is ~100K tokens as a raw PDF and ~5K tokens as clean Markdown, per `TOKEN_SAVINGS_FRAMING.md`. Do not use 200x or 500 tokens — those are wrong.) At the bottom right, a towering stack of dollar bills labeled "Frontier tokens saved: $hundreds to $thousands/month (Mechanism 1 floor — real savings larger)." Between the two sides, a comparison callout reading: "We charge pennies. You save dollars." The left side should be deliberately small and the right side deliberately large to emphasize the scale difference. Caption at bottom: "The tokens we charge for are a rounding error on the tokens we save you."

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_07 — What You Pay vs. What You Save**

A side-by-side bar chart on a light warm-gray background. The image is paired with `pro-pricing.md` and uses the canonical anchor numbers from `TOKEN_SAVINGS_FRAMING.md` verbatim — no invented figures, no scale-break theatrics, no green-vs-amber drama. Tone is engineering-document precise.

Heading bar at the top reads: "What you pay us vs. what you stop burning on frontier extraction." Subheading underneath: "Per-month figures across four typical document volumes. Anchor: ~95,000 frontier tokens saved per document retrieval — a 4,500-word doc is ~100K tokens raw, ~5K tokens as clean Markdown."

---

**MAIN CHART — grouped horizontal bar chart**

Four rows, one per usage profile, listed top to bottom: "Light (~50 docs/mo)" / "Moderate (~300 docs/mo)" / "Heavy (~1,000 docs/mo)" / "Very heavy (~10,000 docs/mo)".

Each row contains **three horizontal bars** stacked vertically inside the row, with the bar lengths drawn to a single shared logarithmic dollar scale across all rows so the small numbers and large numbers are readable on the same chart. The three bars per row, in order, are:

1. **"What you pay us"** (cool blue tint) — the Managed total per profile. Light: $25. Moderate: $25–26. Heavy: $32. Very heavy: $65–70. Label each bar with its dollar value at the bar's right edge.
2. **"Frontier $ saved/mo @ Sonnet-class (~$3/M input)"** (medium amber tint) — Light: $15. Moderate: $85. Heavy: $290. Very heavy: $2,900. Same dollar-value labeling.
3. **"Frontier $ saved/mo @ Opus-class (~$15/M input)"** (deep amber tint) — Light: $70. Moderate: $430. Heavy: $1,430. Very heavy: $14,300. Same dollar-value labeling.

Use a logarithmic x-axis labeled in dollars from $1 to $20,000 with gridlines at $10, $100, $1,000, $10,000. A note tucked under the axis reads: "Log scale — necessary because frontier savings span four orders of magnitude across volumes." A second note: "Bars 2 and 3 are what the user does *not* pay (frontier tokens not burned). Only bar 1 is money the user pays us." A third note in smaller text: "Mechanism 1 only — floor, not ceiling. Counts raw-PDF-to-Markdown 20x reduction × document count. Does not include frontier tokens burned on the extraction loop itself, which is per-session and workflow-dependent. Real savings are larger. Back-of-the-napkin for a typical user."

---

**LEGEND PANEL — right side of the chart**

A small vertical legend with three swatches matching the three bar colors:

- Cool blue swatch — "What you pay us (Managed total: management fee + hosting + tokens)"
- Medium amber swatch — "Frontier $ saved/mo @ Sonnet-class rates (~$3/M input)"
- Deep amber swatch — "Frontier $ saved/mo @ Opus-class rates (~$15/M input)"

Below the legend, a small footnote: "Source: `pro-pricing.md` user-example tables, derived from anchor numbers in `TOKEN_SAVINGS_FRAMING.md`."

---

**TWO-AUDIENCE PANEL — directly below the chart**

A horizontal split panel with two equal halves and a thin divider between them:

- **Left half (cool blue tint), labeled "Single users on Claude Code / Claude Cowork":** A small icon of a single person at a laptop. Text reads: "Flat-rate frontier subscription. The dollar figure is invisible — what they feel is **runway**: hitting usage limits less often, longer productive sessions, more work per day before they get rate-limited."
- **Right half (warm amber tint), labeled "Agentic systems buying tokens directly":** A small icon of a server rack with arrows. Text reads: "OpenClaw, Open Brain, OB1, custom agents. The savings show up as a **direct line-item cost reduction** on the monthly frontier bill — predictable per document volume."

A horizontal bracket spans both halves with the label: "Same mechanism. Different lived experience. Both must be acknowledged in any pricing pitch."

---

**FOOTER BAR**

Spans the full width of the image: "What we charge is small. What you stop burning is large. Even at the Sonnet floor, a Moderate user comes out ~$60/mo ahead of DIY; a Heavy user is an order of magnitude ahead."

Caption at bottom: "Anchor numbers from `ariadne-core/docs/TOKEN_SAVINGS_FRAMING.md`. Source for the 20x and 10x figures: Nate Jones, 'Your Claude Sessions Cost 10x What They Should.'"

---

Visual style: Engineering document, not marketing piece. Clean horizontal bars with thin borders, monospaced dollar labels, no big colorful pills, no dramatic gradient fills. Think "white paper" or "technical RFC chart," not "pricing page hero." Colors should be muted — light gray background, dark text, blue and amber tints used only to distinguish the three bar series. The reader should feel they're being shown the math, not sold to.

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.

---

**img_08 — Tiered Storage with Distilled Summaries**

A horizontal three-layer architecture diagram flowing left to right. On the far left, a stream of document icons entering the system.

Top layer (blue tint, labeled "Active Store — Low Latency"): a fast-looking database icon (the Postgres elephant with a lightning bolt). Inside this layer, two types of content are shown: recent document chunks (represented as small Markdown cards with full text) and summary cards (represented as smaller, condensed cards with a "distilled" label and a beaker icon). Both types have small vector arrow icons next to them representing embeddings. A search magnifying glass icon sits above this layer with the label "Sub-50ms search" and an arrow pointing into both the document chunks and the summary cards — showing that searches hit both.

Middle layer (amber tint, labeled "Summarization"): a horizontal arrow flowing from the bottom layer upward to the top layer. Along the arrow, three icons in sequence: a metadata tag icon, a vector arrow icon, and a brain icon labeled "Open LLM." A callout reads: "Metadata + stored vectors → open LLM → distilled summary. No need to re-read the original." This arrow represents the process of generating summaries from archived documents using existing stored data.

Bottom layer (gray tint, labeled "Bulk Store — Archival"): a large, plain storage container icon (like a warehouse). Inside, full document Markdown files and their vectors are stored, each with a small clock icon indicating age. A dotted arrow goes from the top layer down to the bulk store, labeled "Documents age into bulk after configurable threshold." Another dotted arrow goes from the bulk store back up to the top layer, labeled "Full document on demand (seconds, not milliseconds)."

A callout box between the top and bottom layers reads: "Active storage costs plateau. Old docs age into cheap bulk. Summaries keep them searchable at full speed." Caption at bottom: "Recent data is fast. Old data is cheap. Summaries bridge the gap."

Colorblind-friendly, no hex codes. These images are for a team-facing roadmap document, not end-user marketing. They should be clear, professional, and accessible — designed to help the team understand the product strategy at a glance. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product strategy deck illustrations," not technical diagrams.
