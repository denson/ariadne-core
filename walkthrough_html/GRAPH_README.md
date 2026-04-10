# Ariadne Core — Knowledge Graph

Interactive visualization of the concepts that power Ariadne Core's
walkthrough presenter. 35 nodes, 6 groups, zero dependencies.

**Author:** Denson Smith

---

## Files in this directory

| File | Use case |
|------|----------|
| `knowledge_graph_embed.html` | Embed-ready: transparent bg, light/dark auto, container-relative |
| `knowledge_graph.html` | Standalone: dark theme, full-page, good for screenshots |

---

## Part 1: Why we built the knowledge graph

### The problem it solves

Ariadne Core has an interactive walkthrough skill that presents the project
to new users — one beat at a time, with images in a preview panel and
questions in the chat. The first three beats are scripted. After that, the
presenter goes dynamic: it reads the user's answers, picks a concept from
the knowledge graph, selects an image, writes HTML on the fly, and
continues the conversation.

The knowledge graph is the backing store for that dynamic presenter. Each
concept is an atomic unit the presenter can pull from — a 3-8 sentence
body written in the voice of the project's canonical framing doc, with
cross-links to related concepts and images. The presenter matches user
intent to a concept, paraphrases the body, picks an image, and composes a
follow-up question from the concept's `see_also` links.

Without the graph, the presenter either dumps the whole README into context
(expensive, unfocused) or guesses (wrong). The graph gives it the right
building blocks at the right grain size.

### How we built it — the iterative process

The graph wasn't designed top-down from a content outline. It was built by
testing a presenter against real questions and fixing the gaps.

**Phase 1 — Seed from the walkthrough.** The initial 22 concepts were
written by hand to support a scripted 5-beat onboarding demo. They covered
the token economics story well (both waste mechanisms, the 10x session
savings, anchor numbers, two-audience framing) and the product basics
(extraction pipeline, editions, deployment). This was enough for the
scripted beats but broke immediately when users went off-script.

**Phase 2 — Expose gaps with curveball questions.** During a live test,
the question "What if I want to use Ariadne in Claude Cowork?" exposed the
first gap: no concept covered authentication or client compatibility. The
presenter winged the answer and got the OAuth requirement wrong — it said
API keys work with Cowork (they don't). This was the trigger for a
systematic audit.

**Phase 3 — Parallel audit against source docs.** Three agents ran in
parallel, each auditing the knowledge graph against different source
documents:

- Agent 1 — SPEC.md, docint-architecture.md, README.md (tool signatures,
  auth, dedup, chunking, embedding models, performance)
- Agent 2 — All skill SKILL.md files, all docs/roadmap/ files,
  TOKEN_SAVINGS_FRAMING.md (edition differences, pricing, strategy,
  the "beyond extraction" story)
- Agent 3 — The knowledge graph itself: validated all cross-references,
  found orphaned images, checked body text for staleness

The audits identified ~20 topic areas missing from the graph.

**Phase 4 — Prioritize by "questions users actually ask."** Instead of
mirroring every document, we filtered the ~20 gaps by asking: what
questions would a walkthrough user likely ask that the presenter can't
answer today? This produced 10 new concepts in three tiers:

- Tier 1 (already exposed): auth/client compatibility, persistent memory
- Tier 2 (likely questions): embedding models, dedup/provenance, MCP tools,
  chunking strategies
- Tier 3 (freshness): vision/images, Gemma 4 economics, storage scaling,
  MarkItDown standalone

Plus 3 updates to existing concepts that needed auth details added.

**Phase 5 — Persona-based testing (25 questions).** Five user personas
were generated to represent the product's audience:

- **Maya** — solo developer on Claude Max, hits rate limits
- **Carlos** — platform engineer, agentic system, sees the monthly bill
- **Priya** — product manager evaluating tools, not technical
- **Derek** — data scientist, already uses MarkItDown, skeptical
- **Aisha** — Open Brain developer, multi-agent workflows, needs provenance

Five questions per persona (25 total) were tested against the graph. An
agent read every concept body and scored each question YES / PARTIAL / NO
based on whether the answer was findable in the body text — not inferable
from concept names, actually present.

Results after the first round: **14 YES, 8 PARTIAL, 3 NO.**

**Phase 6 — Fill the NOs, sharpen the PARTIALs.** The 3 outright failures
(data portability, performance benchmarks, scanned PDFs) were each filled
with a new concept built from targeted codebase research. 4 of the 8
PARTIALs were sharpened by adding 1-2 sentences to existing concept bodies
(grep vs semantic search, fully-local deployment, Open Brain connection,
agent-scoped search filters). The remaining 4 PARTIALs were judged
composable — the presenter can assemble the answer from multiple concepts.

**Phase 7 — Validation.** Final state: 35 concepts, 0 broken `see_also`
references, 0 broken image references, 1 known orphan image (legacy,
intentionally unlinked). Validated programmatically by parsing the YAML
and cross-referencing all IDs.

### What we'd do differently next time

- **Start with personas and questions before writing concepts.** We wrote
  22 concepts first and tested later. Reversing the order catches gaps
  before they embarrass you in a live demo.
- **Automate the persona test as a regression suite.** The 25 questions
  could run as a CI check: parse the YAML, match each question to
  concepts, flag any that score below a threshold.
- **Keep the graph lean.** The temptation is to add a concept for every
  doc section. Resist it. A presenter that can combine 3 concepts to
  answer a question is more resilient than one that needs an exact match.

---

## Part 2: How the visualization was generated

### Architecture

The visualization is a static HTML file with graph data hardcoded as a
JavaScript array. No build step, no runtime YAML parsing, no external
dependencies. The entire thing is inline HTML + CSS + JS in a single file.

### Data source

The canonical data lives in:
```
skills/ariadne-core-walkthrough/project_knowledge_graph.yaml
```

Each concept has these fields the visualization uses:
- `id` — unique identifier, used as node key
- `name` — display label on the node
- `one_line` — tooltip summary shown on hover
- `see_also` — array of concept IDs this node links to (directed edges)

The `groups` object that assigns each concept to a color-coded category
is NOT in the YAML — it was defined manually based on the section headers
in the YAML file (e.g., `# ========== TOKEN ECONOMICS ==========`).

### Generation steps

1. **Read the YAML** — extract all concepts with `id`, `name`, `one_line`,
   and `see_also`.

2. **Define groups** — assign each concept ID to a category:
   - Token Economics (amber `#f59e0b`)
   - Product & Architecture (cyan `#06b6d4`)
   - Deployment & Editions (purple `#8b5cf6`)
   - Onboarding / Education (green `#22c55e`)
   - Auth, Tools & Technical (pink `#ec4899`)
   - Data, Performance & Limits (orange `#f97316`)

3. **Build the HTML** — the `concepts` array and `groups` object are
   embedded in a `<script>` block. The rest is a self-contained force
   simulation + SVG renderer + event handlers.

4. **Force layout** — runs synchronously on page load (300-400 iterations).
   Nodes initialize near their group's angular position. Three forces:
   - Repulsion between all node pairs (inverse-square)
   - Attraction along edges (spring toward target distance)
   - Gravity toward center (prevents drift)
   Not animated — calculates final positions before rendering.

5. **Rendering** — SVG `<line>` for edges, `<g>` with `<circle>` + `<text>`
   for nodes. Node radius scales with connection count. Interactivity
   (hover, click, pan, zoom) via DOM event listeners.

### To regenerate after YAML changes

1. Parse the YAML, extract the concept list
2. Update the `concepts` array in the HTML:
   ```js
   { id: "concept_id", name: "Display Name", one_line: "Summary.", see_also: ["other_id"] }
   ```
3. If new concepts don't fit existing groups, add to `groups` or create new
4. Update node count in title text and `#stats` element
5. Update both HTML files — they share the same data structure

The force simulation adapts automatically to new nodes/edges.

### Tuning the layout

If the graph looks too cramped or spread out after adding concepts:

| Parameter | Location | Effect |
|-----------|----------|--------|
| Repulsion (`800`/`1000`) | `force = N / (dist * dist)` | Higher = nodes push apart more |
| Spring distance (`100`/`120`) | `(dist - N) * 0.005` | Higher = edges want to be longer |
| Spring strength (`0.005`/`0.006`) | `(dist - N) * N` | Higher = edges pull harder |
| Center gravity (`0.002`/`0.003`) | `(center - n.x) * N` | Higher = tighter cluster |
| Damping (`0.82`/`0.85`) | `n.vx *= N` | Higher = slower convergence, smoother |
| Iterations (`300`/`400`) | `for (let iter ...)` | More = better convergence, slower load |
| Node radius | `7 + see_also.length * 0.8` | Hub nodes appear larger |

---

## Part 3: How to use the visualization

### Interactive features

- **35 concept nodes** in 6 color-coded groups
- **Hover** any node — tooltip shows one-liner, outgoing (→) and incoming (←) connections, group badge
- **Click** a node to pin the highlight; click again or click background to unpin
- **Scroll wheel** to zoom (zooms toward cursor position)
- **Click + drag** background to pan
- **Double-click** to reset zoom/pan to default

### Theme behavior

The embed version uses `prefers-color-scheme` to auto-detect light/dark:
- Dark mode: light text, transparent bg, dark glassmorphism panels
- Light mode: dark text, transparent bg, light glassmorphism panels

Override with a wrapper `<div style="color-scheme: dark">` if your site
forces a specific scheme.

### Sizing

Container-relative — reads parent dimensions on load. In an iframe, fills
whatever dimensions you set. Minimum: **600×400px**. Best: **900×600px+**.

### Integration options

**Option A — Iframe (simplest).** Copy the file, point an iframe at it.

```html
<iframe src="/assets/knowledge_graph_embed.html"
  style="width:100%; height:600px; border:none; border-radius:12px;"
  title="Ariadne Core Knowledge Graph" loading="lazy"></iframe>
```

Zero integration work. Downside: scroll wheel gets captured by zoom when
cursor is over the graph. Add a "click to interact" overlay if needed.

**Option B — Inline into a page.** Extract the `<style>`, `#container`
div, and `<script>` from the embed file and drop into your page HTML.
Set `#container` to a fixed height. Graph inherits your site's fonts and
theme. Watch for CSS class conflicts (`.node`, `.link`).

**Option C — React component.** Wrap the iframe, or convert the script to
a component that renders SVG on mount. Data is a static array — no async.

```jsx
function KnowledgeGraph({ height = 600 }) {
  return (
    <iframe src="/knowledge_graph_embed.html"
      style={{ width: '100%', height, border: 'none', borderRadius: 12 }}
      title="Ariadne Core Knowledge Graph" loading="lazy" />
  );
}
```

**Option D — Static screenshot + link.** For email, RSS, or Markdown where
interactive embeds don't work. Screenshot the dark theme version (better
contrast), use as a figure, link to the hosted interactive version.

**Option E — Feed data to your own graph library.** Extract the `concepts`
and `groups` arrays and pipe into d3, vis.js, Cytoscape, or whatever you
already use. Or parse the YAML directly at build time.

### Suggested placements

- **Product page** — hero or mid-page section showing the breadth of the
  knowledge base. "35 concepts. Explore the graph."
- **Blog post about the walkthrough** — inline the graph to show what
  backs the presenter, with the build process as the narrative.
- **Docs / architecture page** — interactive concept map that visitors
  can explore alongside the prose.
- **README or GitHub repo page** — screenshot with a link to the live
  version.

---

## Canonical references

- **Knowledge graph YAML:** `skills/ariadne-core-walkthrough/project_knowledge_graph.yaml`
- **Image manifest:** `skills/ariadne-core-walkthrough/image_manifest.yaml`
- **Token savings numbers:** `docs/TOKEN_SAVINGS_FRAMING.md`
- **Website integration patterns:** `docs/website-integration/README.md`
- **Full image set (26 images):** `skills/ariadne-core-walkthrough/assets/images/`
