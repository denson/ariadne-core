---
name: conceptviz-prompt-generator
description: "Generate illustration prompts for ConceptViz. Triggers: add visuals, illustrate this, create diagrams, make this more visual, add images."
---

# ConceptViz Prompt Generator

You are helping a human create editorial illustrations for a document using
ConceptViz — an AI-powered diagram generator at https://conceptviz.app/.

ConceptViz has a preprocessing agent that detects the topic domain (e.g., computer
science, biology) and the visual style from the prompt itself. Users paste a plain-text
prompt and get a high-resolution diagram back. There is no API integration — the
output of this skill is text prompts the human pastes into ConceptViz manually.

This skill works in three phases: analyze the document and suggest placements,
iterate on feedback, then generate prompts.

## Why this matters

Illustrations make the difference between a document someone skims and one they
understand. But knowing *where* to put images and *how* to describe them for a
generation tool are separate skills from writing good prose. This skill handles both
so the human can focus on the content itself.

## Finding Reference Examples

The ariadne-core-walkthrough skill contains a proven library of ConceptViz prompts.
Use `Glob` to search for `**/ariadne-core-walkthrough/references/ConceptViz_prompts.md`.
Read that file when you need concrete examples of prompt structure, composition types,
or phrasing patterns. All guidance below is derived from those proven prompts.

---

## Phase 1: Analyze & Suggest Placements

Read the entire target document. Understand its structure, audience, and the concepts
it communicates. Then identify places where a diagram or illustration would help the
reader grasp something faster or more clearly than text alone.

### What to illustrate

Good candidates:

- **Value propositions** — before/after, with/without comparisons
- **Multi-step processes** — pipelines, workflows, sequential operations
- **Architecture** — system components and how they connect
- **Comparisons** — options, pricing tiers, auth methods, platform choices
- **Abstract concepts** — anything that requires holding 3+ ideas simultaneously
- **Configuration references** — environment variables, settings tables
- **Responsibility splits** — what the human does vs. what the agent does

### What NOT to illustrate

- Simple lists that are already scannable
- Code snippets or single commands
- Content that is already clear from the text alone
- Anything where adding an image would dilute rather than clarify

**Rule of thumb:** if the concept requires the reader to hold three or more things in
mind simultaneously, it is a good candidate for illustration.

### Insert placeholders

For each candidate, insert a visible placeholder at the appropriate location in the
document so the human can see exactly where each image would go and what it would
depict. The description should be detailed enough that the human can evaluate whether
the image is worth creating — they should be able to picture the finished illustration
from reading the placeholder alone.

```
> **[CONCEPTVIZ_01: The Token Waste Problem]**
>
> A split scene divided vertically. Left side shows a strained AI brain buried under
> an avalanche of raw documents (PDFs, spreadsheets, slide decks) with a token counter
> spinning at 98,000+. Right side shows the same brain relaxed and focused, reading a
> single clean Markdown card with the token counter at under 500. The contrast
> illustrates the 100x token reduction that extraction provides — the expensive model
> never touches raw documents.
>
> *Caption: "100,000 tokens of raw PDF, or 500 tokens of what matters."*
```

Format:

```
> **[CONCEPTVIZ_nn: Title]**
>
> [2-4 sentence description of what the finished illustration will show — the
> composition, the key visual elements, and what the viewer should take away.
> Write this as if describing the completed image to someone who can't see it.]
>
> *Caption: "[punchy one-liner takeaway]"*
```

Use blockquote formatting so placeholders stand out visually in any Markdown renderer.
The human needs to see these clearly during review and understand what they're
approving. These get replaced with actual image references after the prompts are
generated and the images created.

### Present the suggestions

After inserting all placeholders, present a numbered summary to the human:

```
## Suggested illustrations

1. **[CONCEPTVIZ_01: The Token Waste Problem]** (after paragraph 2)
   Why: This is the core value proposition — readers need to immediately
   understand the cost problem before they'll care about the solution.

2. **[CONCEPTVIZ_02: The Extraction Pipeline]** (after "How it works" heading)
   Why: The seven-step pipeline is too much to hold in your head from prose
   alone. A visual conveyor belt makes the flow and cost structure obvious.

3. ...
```

For each suggestion, state:
- Where it goes in the document (the placeholder itself is already there
  with the full image description)
- Why it helps the reader at that point

Then ask the human to review: accept, reject, or modify each suggestion.

---

## Phase 2: Iterate on Feedback

The human reviews the placeholders. They may:

- Accept a suggestion as-is
- Reject a suggestion (remove the placeholder)
- Modify the description or location
- Add new suggestions you missed

Update the placeholders accordingly and re-present the list. Continue until the human
approves the final set of placements.

---

## Phase 3: Generate Prompts

For each approved placeholder, generate a complete ConceptViz prompt. Collect all
prompts into a reference file at a path the human specifies. Default:
`references/ConceptViz_prompts.md` relative to the document's directory.

### Prompt anatomy

Every ConceptViz prompt has six parts:

**1. Identifier and title**

```
**img_01 — The Token Waste Problem**
```

Use `img_nn` numbering. The title should be concise and describe the concept, not the
visual technique.

**2. Scene composition**

Describe the spatial layout with precise language. Be explicit about what goes where:
left/right, top/bottom, inside/outside, rows/columns. The more spatially specific you
are, the better the output.

Bad: "Show the pipeline."
Good: "A horizontal conveyor belt flowing left to right across the full width. On the
far left, a pile of raw documents enters the belt. The belt passes through seven
clearly labeled stations..."

**3. Visual metaphors**

Map abstract concepts to concrete imagery:

- Brain icon = LLM / AI model
- Conveyor belt = processing pipeline
- Filing cabinet = raw document storage
- Scissors = chunking / splitting
- Magnet = embedding extraction
- Vault door = database storage
- Key icon = authentication
- Lock/shield = security
- Rocket = deployment
- Train = Railway (hosting)

Choose metaphors that are immediately recognizable. Avoid obscure symbols.

**4. Labels and annotations**

Specify every piece of text that should appear IN the image: station labels, badges
(e.g., "Free", "Optional"), callout boxes, subtitle text, and annotation lines.
Be explicit — if you don't specify it, it won't appear.

**5. Caption**

A punchy one-liner (under 15 words) that summarizes the takeaway. This appears at
the bottom of the image. It should answer: "What should the viewer remember?"

Examples:
- "100,000 tokens of raw PDF, or 500 tokens of what matters."
- "Seven steps. Four are free. Three use cheap API calls."
- "One deployment. Many clients. Two ways to authenticate."
- "Don't send the whole library. Search first, send what matters."

**6. Style block**

Append this standard suffix to every prompt (adapt the bracketed context note):

```
Colorblind-friendly, no hex codes. [These images are for the onboarding skill, not
technical documentation. They should be conceptual and accessible — designed to make
the project's value, architecture, and deployment process immediately clear to anyone.]
Style for all: flat design, editorial illustration, simple shapes, bold colors on a
light warm-gray background. Think "product landing page illustrations," not technical
diagrams.
```

Replace the bracketed text with a purpose note appropriate to the target document.

---

## Composition catalog

Choose the composition type that best fits the concept being illustrated. These are
the proven layouts from the existing prompt library:

### Split scene
Two halves divided by a vertical line, each with a different color tint. One side
shows the problem, the other shows the solution.

**Use for:** value propositions, before/after, with/without comparisons.

**Example:** img_01 (token waste), img_08 (search vs. send everything).

**Key details:** label each side, use contrasting color tints (warm vs. cool), include
a metric or comparison callout between the sides.

### Conveyor belt / flow
A horizontal belt or arrow flowing left to right with labeled stations or zones.

**Use for:** sequential pipelines, transformation processes, format conversions.

**Example:** img_02 (extraction pipeline), img_07 (format mosaic).

**Key details:** clearly label each station, add badges for cost/status (free,
optional, paid), show input on the left and output on the right.

### Comparison cards
Side-by-side cards (2–4) like a pricing page, each with a heading, icon, and bullet
points.

**Use for:** platform choices, auth tiers, deployment options, feature comparison.

**Example:** img_03 (auth methods), img_04 (hosting platforms).

**Key details:** highlight the recommended option with a subtle glow or badge, use a
shared footer for common traits, differentiate by both color AND shape/icon.

### Two-part (you vs. agent)
Top section shows what the human does (small, simple). Bottom section shows what the
agent does (larger, more detailed).

**Use for:** automation stories, agent-assisted workflows, setup processes.

**Example:** img_05 (deployment — human does 2 steps, agent does 5).

**Key details:** keep the human's section deliberately minimal to emphasize the
contrast. Use a timeline or numbered steps for the agent's section.

### Terminal + fan
A terminal window showing a command, with result cards fanning out below like a hand
of playing cards.

**Use for:** CLI tools, showing what capabilities a single command unlocks.

**Example:** img_06 (connect Claude Code — one command, six tools).

**Key details:** each card a different pastel shade, bold tool name with one-line
description.

### Architecture diagram
A large container with internal components arranged in layers, with external clients
connecting from outside.

**Use for:** system internals, service architecture, component relationships.

**Example:** architecture image (container internals with MCP, FastAPI, auth, pipeline,
Postgres).

**Key details:** use layers (top = API surface, middle = processing, bottom = storage),
show auth as a horizontal bar that all connections pass through.

### Reference card
Structured data presented as an infographic — a styled table with header, sections,
and color-coded borders.

**Use for:** environment variables, configuration options, settings reference.

**Example:** env_vars image (required vs. optional variables).

**Key details:** use left border accents to differentiate sections, keep it readable
and scannable.

### Mosaic / grid
A grid of small uniform icons converging into a single output through a transformation
step.

**Use for:** format support, many-to-one conversions, feature inventories.

**Example:** img_07 (20+ input formats to Markdown).

**Key details:** keep icons small and uniform, make the output icon deliberately
larger to emphasize simplification.

---

## Prompt density

ConceptViz benefits from long, spatially explicit descriptions — the opposite of typical
image-generation advice. A good ConceptViz prompt is 150–400 words of scene description.
This is because ConceptViz renders diagrams with precise spatial relationships, labels,
and annotations, and it needs detailed instructions to place everything correctly.

Think of yourself as art-directing an illustrator who can't ask questions. If you say
"show the pipeline," you'll get something generic. If you describe every station on
the conveyor belt, what icon sits above it, what badge appears below it, and what
enters and exits — you'll get exactly what you need.

When in doubt, over-specify layout and under-specify aesthetic. ConceptViz handles the
visual style; your job is the spatial choreography.

---

## Complete worked example

Here is one full prompt to show how all six parts come together:

```
**img_01 — The Token Waste Problem**

A split scene divided vertically by a thin line. Left side (warm orange-red
tint, labeled "Without Ariadne Core"): a glowing brain icon (representing
an expensive LLM like Claude Opus) is buried under an avalanche of raw
document pages — oversized PDF icons, spreadsheet grids, slide decks, and
Word docs are piled on top of and around the brain, which looks strained
with stress lines radiating outward. A token counter in the corner spins
wildly showing "98,247 tokens" in alarming red. The brain is trying to read
through the mess, with tiny thought bubbles showing "where is the revenue
data?" lost among irrelevant pages. Right side (cool green-blue tint,
labeled "With Ariadne Core"): the same glowing brain, now relaxed and
focused, sitting comfortably. In front of it, a single clean card of
Markdown text with a few highlighted paragraphs — exactly the relevant
content. The token counter shows "487 tokens" in calm green. The brain has
a clear thought bubble: the answer, cleanly formed. Between the two sides,
a subtle arrow pointing from left to right with the label "100x fewer
tokens." Caption at bottom: "100,000 tokens of raw PDF, or 500 tokens of
what matters."

Colorblind-friendly, no hex codes. These images are for the onboarding
skill, not technical documentation. They should be conceptual and
accessible — designed to make the project's value, architecture, and
deployment process immediately clear to anyone. Style for all: flat design,
editorial illustration, simple shapes, bold colors on a light warm-gray
background. Think "product landing page illustrations," not technical
diagrams.
```

Notice the pattern: one dense paragraph of spatial description (where everything is,
what it looks like, what text appears), followed by the style block. The prompt is
~250 words — detailed enough that ConceptViz can render it faithfully.

---

## Guard rails

- **"Colorblind-friendly, no hex codes"** in every prompt. About 8% of men have some
  form of color vision deficiency — hex codes force specific colors that may be
  indistinguishable. Let ConceptViz pick accessible palettes instead.

- **Shape-based differentiation, not just color.** Use circle-X vs. checkmark-in-shield,
  not just red vs. green. This ensures the comparison is clear even in grayscale or to
  colorblind viewers.

- **Flat design only.** ConceptViz is optimized for editorial illustrations — flat shapes,
  bold colors, clean lines. Requesting photos, realistic imagery, or 3D renders works
  against the tool's strengths and produces worse results.

- **Every image needs a clear takeaway.** If you can't write a caption, the concept isn't
  ready for illustration. The caption forces you to distill the point — if you can't
  state it in one sentence, the image will be unfocused too.

- **Captions under 15 words.** Short captions get read; long ones get skipped. They
  should complete the thought "the viewer should remember that..."

- **Don't over-illustrate.** A document with 3 great illustrations beats one with 10
  mediocre ones. Each image should earn its place by making something genuinely clearer
  than text alone.

- **Be spatially precise.** "Show the pipeline" produces generic results. "A horizontal
  conveyor belt flowing left to right with seven labeled stations" produces what you
  actually want. ConceptViz interprets spatial instructions literally — use that.

- **Placeholders must be visible blockquotes** so the human can review them in any
  Markdown renderer. They get replaced with image references after prompts are
  generated and images created.

---

## Output format

The final reference file should follow this format:

```markdown
# ConceptViz Prompts for [Document Name]

---

**img_01 — [Title]**

[Full prompt text including scene composition, metaphors, labels, caption]

[Style block]

---

**img_02 — [Title]**

...
```

Separate each prompt with a horizontal rule. After generating the prompts file,
optionally update the original document to replace the `> **[CONCEPTVIZ_nn: ...]**`
blockquote placeholders with image references pointing to the expected filenames
(e.g., `assets/images/img_01.png`).
