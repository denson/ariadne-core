# Knowledge Graph Visualization

Interactive force-directed graph of the Ariadne Core knowledge base.
Two versions in this directory — see `docs/website-integration/README.md`
for embed options and integration patterns.

**Author:** Denson Smith

---

## Files

| File | Use case |
|------|----------|
| `knowledge_graph_embed.html` | Embed-ready: transparent bg, light/dark auto, container-relative |
| `knowledge_graph.html` | Standalone: dark theme, full-page, good for screenshots |

## How the visualization was generated

The visualization is a static HTML file with the graph data hardcoded as
a JavaScript array. There is no build step, no runtime YAML parsing, and
no external dependencies. Here's how it was created and how to regenerate
it when the knowledge graph changes.

### Data source

The canonical data lives in:
```
skills/ariadne-core-walkthrough/project_knowledge_graph.yaml
```

Each concept in that YAML has these fields the visualization uses:
- `id` — unique identifier, used as node key
- `name` — display label on the node
- `one_line` — tooltip summary shown on hover
- `see_also` — array of concept IDs this node links to (directed edges)

The visualization also uses a `groups` object that assigns each concept ID
to a color-coded category. This grouping is NOT in the YAML — it was
defined manually based on the comment headers in the YAML file (e.g.,
`# ========== TOKEN ECONOMICS ==========`).

### Generation process

1. **Read the YAML** — extract all concepts with their `id`, `name`,
   `one_line`, and `see_also` fields.

2. **Define groups** — assign each concept ID to one of the 6 categories:
   - Token Economics (amber)
   - Product & Architecture (cyan)
   - Deployment & Editions (purple)
   - Onboarding / Education (green)
   - Auth, Tools & Technical (pink)
   - Data, Performance & Limits (orange)

3. **Build the HTML** — the `concepts` array and `groups` object are
   embedded directly in a `<script>` block. The rest of the file is
   a self-contained force simulation + SVG renderer + event handlers.

4. **Force layout** — runs synchronously on page load (300-400 iterations).
   Nodes are initialized near their group's angular position around the
   center. Three forces act on each iteration:
   - Repulsion between all node pairs (inverse-square)
   - Attraction along `see_also` edges (spring toward target distance)
   - Gravity toward center (prevents drift)
   Nodes are clamped to stay within bounds. The simulation is not animated —
   it calculates final positions before rendering.

5. **Rendering** — SVG elements are created once: `<line>` for edges,
   `<g>` with `<circle>` + `<text>` for nodes. Node radius scales with
   connection count. All interactivity (hover, click, pan, zoom) is
   handled by DOM event listeners on the SVG elements.

### To regenerate after YAML changes

When concepts are added, removed, or re-linked in the YAML:

1. Parse the YAML and extract the concept list
2. Update the `concepts` array in the HTML — each entry needs:
   ```js
   { id: "concept_id", name: "Display Name", one_line: "Summary.", see_also: ["other_id", ...] }
   ```
3. If new concepts don't fit existing groups, add them to the appropriate
   group in the `groups` object, or create a new group with a color
4. Update the node count in the title text and the `#stats` element
5. Update both HTML files (standalone + embed) — they share the same data

The force simulation will automatically adapt to the new node/edge count.
No manual layout adjustments needed.

### What the force simulation parameters do

If the graph looks too cramped or too spread out after adding concepts:

| Parameter | Location | Effect |
|-----------|----------|--------|
| Repulsion strength (`800` or `1000`) | `force = N / (dist * dist)` | Higher = nodes push apart more |
| Spring target distance (`100` or `120`) | `(dist - N) * 0.005` | Higher = edges want to be longer |
| Spring strength (`0.005` or `0.006`) | `(dist - N) * N` | Higher = edges pull harder |
| Center gravity (`0.002` or `0.003`) | `(center - n.x) * N` | Higher = tighter cluster |
| Damping (`0.82` or `0.85`) | `n.vx *= N` | Higher = slower convergence, smoother |
| Iterations (`300` or `400`) | `for (let iter = 0; iter < N; ...)` | More = better convergence, slower load |
| Node radius | `7 + see_also.length * 0.8` | Hub nodes (many connections) appear larger |

### How the knowledge graph data was built

The YAML knowledge graph itself was built through an iterative
persona-based testing process. The full writeup is in
`docs/website-integration/README.md` under "How the knowledge graph was
built." The short version:

1. Seeded 22 concepts from the walkthrough's scripted beats
2. Tested with curveball questions — found the presenter couldn't answer
   questions about auth, embedding models, performance, or scanned PDFs
3. Ran 3 parallel audit agents against SPEC.md, architecture docs, README,
   all skills, and all roadmap docs
4. Generated 5 user personas (solo dev, platform engineer, PM, data
   scientist, multi-agent developer) with 5 questions each
5. Scored all 25 questions against the graph (YES / PARTIAL / NO)
6. Added 13 concepts to fill gaps, sharpened 4 existing concept bodies
7. Final state: 35 concepts, 0 broken references, validated programmatically

The process is designed to be repeatable. As the product evolves, run the
persona questions again, find new gaps, and add concepts to fill them.
