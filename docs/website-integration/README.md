# Website Integration — Ariadne Core Visual Assets

Instructions for integrating Ariadne Core's walkthrough beats and interactive knowledge graph into [knowledgecrystal.com](https://knowledgecrystal.com).

**Author:** Denson Smith

---

## What's here

All embeddable assets live in `walkthrough_html/` at the repo root:

| File | Purpose | Embed-ready? |
|------|---------|-------------|
| `knowledge_graph_embed.html` | Interactive knowledge graph visualization (35 concepts, hover/click/pan/zoom) | **Yes** — transparent bg, light/dark auto-detect, container-relative sizing |
| `knowledge_graph.html` | Same graph, standalone dark theme (full-page) | Standalone only — uses `100vw`/`100vh` |
| `beat1.html` | Walkthrough Beat 1 — The Hook (Nate Jones video, 20x reduction) | Needs server for images |
| `beat2.html` | Walkthrough Beat 2 — Two mechanisms of waste | Needs server for images |
| `beat3.html` | Walkthrough Beat 3 — Who Are You? (subscription vs agentic) | Needs server for images |
| `style.css` | Shared CSS for beat pages (light theme) | — |
| `dynamic_*.html` | Generated during walkthrough sessions — not for website use | No |
| `*.png` | Images referenced by beat HTML files | Must be co-located |

---

## Knowledge Graph — Integration Options

The graph is a self-contained HTML file with zero dependencies. You have several ways to use it depending on context. Pick the pattern that fits.

### Option A: Iframe embed (simplest)

Best for: a dedicated "Explore our knowledge graph" section on a product page or docs site. The graph lives in its own sandbox — no CSS conflicts, no JS conflicts.

```html
<iframe
  src="/assets/knowledge_graph_embed.html"
  style="width: 100%; height: 600px; border: none; border-radius: 12px;"
  title="Ariadne Core Knowledge Graph"
  loading="lazy"
></iframe>
```

Pros: zero integration work, copy the file and point at it.
Cons: iframe scroll trapping (user scrolls into the graph and zoom captures the wheel). Add `tabindex="-1"` if this is a problem, or wrap with a "click to interact" overlay.

### Option B: Inline the SVG + JS into a page template

Best for: blog posts, landing pages, or anywhere you want the graph to feel like part of the page rather than a widget. Extract the `<svg>`, `<script>`, and minimal CSS from the embed file and drop them into your page's HTML.

Steps:
1. Copy the `<style>` block into your page's CSS (or a scoped `<style>` tag)
2. Copy the `#container` div (with legend, title, tooltip, and SVG) into your page body
3. Copy the `<script>` block into a `<script>` tag or external JS file
4. Set `#container` to a fixed height (e.g., `height: 600px`) since it reads container dimensions on load
5. Remove the `body` styles — your page already has those

Pros: no iframe, graph inherits your site's font/theme naturally, no scroll trapping.
Cons: your site's CSS might conflict with the graph's classes (`.node`, `.link`, etc.). Prefix the class names if needed.

### Option C: React/Next.js component wrapper

Best for: if knowledgecrystal.com is a React app and you want the graph as a component.

```jsx
function KnowledgeGraph({ height = 600 }) {
  return (
    <iframe
      src="/knowledge_graph_embed.html"
      style={{ width: '100%', height, border: 'none', borderRadius: 12 }}
      title="Ariadne Core Knowledge Graph"
      loading="lazy"
    />
  );
}
```

Or for tighter integration, convert the script to a React component that renders SVG directly. The data is a static array — no async fetching needed. The force simulation runs synchronously on mount.

### Option D: Static screenshot + link to interactive version

Best for: blog posts or newsletters where interactive embeds don't work (email, RSS, Markdown-rendered pages).

1. Take a screenshot of the graph with a few nodes highlighted
2. Use it as a hero image or inline figure
3. Link to the hosted interactive version: `<a href="/knowledge-graph">Explore the full interactive graph →</a>`

The graph's dark theme version (`knowledge_graph.html`) makes better screenshots than the transparent embed version.

### Option E: Adapt the data for a different visualization library

Best for: if you already use d3, vis.js, Cytoscape, or another graph library on your site.

The concept data is a plain JavaScript array in the HTML file — extract the `concepts` and `groups` objects and feed them into whatever library you prefer. Each concept has:
- `id` — unique identifier
- `name` — display label
- `one_line` — tooltip summary
- `see_also` — array of connected concept IDs (directed edges)

The canonical source is `skills/ariadne-core-walkthrough/project_knowledge_graph.yaml` if you want to parse YAML directly at build time.

---

### What the graph does

- **35 concept nodes** organized into 6 color-coded groups:
  - Amber — Token Economics (6 nodes)
  - Cyan — Product & Architecture (5 nodes)
  - Purple — Deployment & Editions (7 nodes)
  - Green — Onboarding / Education (4 nodes)
  - Pink — Auth, Tools & Technical (10 nodes)
  - Orange — Data, Performance & Limits (3 nodes)
- **Hover** any node to see its one-line summary and connections (outgoing → and incoming ←)
- **Click** a node to pin the highlight
- **Scroll wheel** to zoom (zooms toward cursor)
- **Click + drag** background to pan
- **Double-click** to reset zoom/pan

### Theme behavior

The embed uses `prefers-color-scheme` to auto-detect light/dark mode:
- **Dark mode:** light text on transparent background, dark glassmorphism panels
- **Light mode:** dark text on transparent background, light glassmorphism panels

If your site forces a color scheme, the embed will match it. If you need to override, add a wrapper `<div>` with a forced `color-scheme: dark` or `color-scheme: light`.

### Sizing

The graph uses **container-relative dimensions** — it reads the width and height of its parent `#container` div on load. In an iframe, this means the graph fills whatever dimensions you give the iframe. Minimum recommended: **600×400px**. Looks best at **900×600px** or wider.

### Zero dependencies

No d3, no React, no build step. The file is self-contained HTML + inline CSS + inline JS. It runs a force-directed layout simulation on page load (not animated — just calculates positions), then renders static SVG with event handlers for interactivity. Lightweight enough for a product page.

---

## Beat Pages

The three beat pages (`beat1.html`, `beat2.html`, `beat3.html`) are designed for the Claude Code Desktop preview panel walkthrough, not directly for the website. However, they can be adapted:

### To use on the website

1. **Serve images from the same directory.** The HTML files reference images by relative path (`video_thumbnail.png`, `token_waste.png`, `pay_vs_save.png`). These must be co-located or the paths updated.

2. **The shared `style.css` is a light theme.** It uses `-apple-system` font stack, white background, max-width 720px container. Override or replace to match your site's design system.

3. **Beat content uses anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md`.** If you change any numbers on the website, check them against that doc first — the numbers are canonical and used everywhere.

### Images

| Image | Size | Source | Used in |
|-------|------|--------|---------|
| `video_thumbnail.png` | 92 KB (279×211) | YouTube thumbnail — Nate Jones video | beat1.html |
| `token_waste.png` | 2.7 MB | ConceptViz — raw PDF vs clean Markdown | beat2.html |
| `pay_vs_save.png` | 2.0 MB | ConceptViz — volume tiers bar chart | beat3.html |

The larger images (`token_waste.png`, `pay_vs_save.png`) should be optimized for web delivery if used on the site — convert to WebP or compress. The originals are full-resolution ConceptViz output at `skills/ariadne-core-walkthrough/assets/images/`.

The `video_thumbnail.png` is small (279×211) and should display at its native size, not stretched. Beat 1's HTML already has a `.thumbnail` class that caps it at native width.

---

## Knowledge graph data source

The graph visualization is generated from `skills/ariadne-core-walkthrough/project_knowledge_graph.yaml`. If the knowledge graph is updated (new concepts, changed connections), the HTML files need to be regenerated to reflect the changes. The concept data is hardcoded in the HTML as a JavaScript array — there's no runtime YAML parsing.

To regenerate: read the YAML, extract `id`, `name`, `one_line`, and `see_also` for each concept, and update the `concepts` array in the HTML file. Group assignments are in the `groups` object at the top of the script.

---

## Files NOT for the website

| File/Pattern | Why |
|-------------|-----|
| `dynamic_*.html` | Generated on the fly during walkthrough sessions. Ephemeral. |
| `two_token_economies.png`, `many_clients.png` | Copied into walkthrough_html during dynamic beats. May or may not exist. |
| `style.css` | For the walkthrough preview panel, not your site's design system. |

---

## How the knowledge graph was built

The knowledge graph wasn't designed top-down. It was built iteratively by
testing a walkthrough presenter against real questions and fixing the gaps
it couldn't answer. The process is worth documenting because we'll likely
refine it as the product evolves.

### Phase 1 — Seed from the walkthrough

The initial 22 concepts were written by hand to support a 5-beat onboarding
walkthrough. They covered the token economics story well (both waste
mechanisms, the 10x session savings, anchor numbers, two-audience framing)
and the product basics (extraction pipeline, editions, deployment). This
was enough for a scripted demo but broke down immediately when users asked
anything off-script.

### Phase 2 — Expose gaps with curveball questions

During a live test of the walkthrough, the question "What if I want to use
Ariadne in Claude Cowork?" exposed the first gap: no concept covered
authentication or client compatibility. The presenter winged it and got the
OAuth requirement wrong — it said API keys work with Cowork (they don't).

This was the trigger for a systematic audit.

### Phase 3 — Parallel audit against source docs

Three agents ran in parallel, each auditing the knowledge graph against
different source documents:

1. **Agent 1** — SPEC.md, docint-architecture.md, README.md (tool
   signatures, auth, dedup, chunking, embedding models, performance)
2. **Agent 2** — All skill SKILL.md files, all docs/roadmap/ files,
   TOKEN_SAVINGS_FRAMING.md (edition differences, pricing, strategy,
   the "beyond extraction" story)
3. **Agent 3** — The knowledge graph itself: validated all cross-references,
   found orphaned images, checked body text for staleness

The audits identified ~20 topic areas missing from the graph.

### Phase 4 — Prioritize by "questions users actually ask"

Instead of trying to mirror every document, we prioritized gaps by asking:
"what questions would a walkthrough user likely ask that the presenter
can't answer today?" This filtered the ~20 gaps down to 10 new concepts
in three tiers:

- **Tier 1** (already exposed): auth/client compatibility, persistent
  memory across sessions
- **Tier 2** (likely questions): embedding model selection, dedup/provenance,
  MCP tools overview, chunking strategies
- **Tier 3** (freshness): vision/image handling, Gemma 4 economics,
  storage scaling, MarkItDown standalone

Plus 3 updates to existing concepts that needed auth details added.

### Phase 5 — Persona-based testing (25 questions)

Five user personas were generated to represent the product's audience
spread:

- **Maya** — solo developer on Claude Max, hits rate limits
- **Carlos** — platform engineer, agentic system, sees the monthly bill
- **Priya** — product manager evaluating tools, not technical
- **Derek** — data scientist, already uses MarkItDown, skeptical
- **Aisha** — Open Brain developer, multi-agent workflows, needs provenance

Five questions per persona (25 total) were tested against the graph. An
agent read every concept body and scored each question YES / PARTIAL / NO
based on whether the answer was findable in the text — not inferable from
concept names, but actually present in the body.

**Results after the first 10 new concepts:** 14 YES, 8 PARTIAL, 3 NO.

### Phase 6 — Fill the NOs, sharpen the PARTIALs

The 3 outright failures:
- **Data portability** — no concept said "you own the Postgres, pg_dump it"
- **Performance benchmarks** — no latency numbers anywhere in the graph
- **Scanned PDFs** — no concept acknowledged the Phase 1 limitation

Each gap was filled with targeted research (agents searching the codebase
for specific facts), then a new concept written from the findings.

4 of the 8 PARTIALs were sharpened by adding 1-2 sentences to existing
concept bodies (grep vs semantic search, fully-local deployment, Open Brain
connection, agent-scoped search filters).

The remaining 4 PARTIALs were judged composable — the presenter can
assemble the answer from existing concepts without a dedicated entry.

### Phase 7 — Validation

Final state: **35 concepts, 0 broken references, 1 known orphan image**
(legacy, intentionally unlinked). The graph was validated programmatically:
all `see_also` IDs resolve to real concept IDs, all `images` entries exist
in the image manifest.

### What we'd do differently next time

- **Start with personas and questions before writing concepts.** We wrote
  22 concepts first and tested later. Reversing the order would have
  caught the auth gap before it embarrassed us in a live demo.
- **Automate the persona test as a regression suite.** The 25 questions
  could run as a CI check: parse the YAML, match each question to concepts,
  flag any that drop below a threshold.
- **Keep the graph lean.** The temptation is to add a concept for every
  doc section. Resist it. The graph should contain composable building
  blocks, not narrow Q&A pairs. A presenter that can combine 3 concepts
  to answer a question is more resilient than one that needs an exact match.

---

## Canonical references

- **Token savings numbers:** `docs/TOKEN_SAVINGS_FRAMING.md` — never invent figures
- **Knowledge graph concepts:** `skills/ariadne-core-walkthrough/project_knowledge_graph.yaml`
- **Image metadata:** `skills/ariadne-core-walkthrough/image_manifest.yaml`
- **Full image set (26 images):** `skills/ariadne-core-walkthrough/assets/images/`
