# ConceptViz Prompts for Ariadne Core Onboarding Images

---

**img_01 — The Token Waste Problem**

A split scene divided vertically by a thin line. Left side (warm orange-red tint, labeled "Without Ariadne Core"): a glowing brain icon (representing an expensive LLM like Claude Opus) is buried under an avalanche of raw document pages — oversized PDF icons, spreadsheet grids, slide decks, and Word docs are piled on top of and around the brain, which looks strained with stress lines radiating outward. A token counter in the corner spins wildly showing "98,247 tokens" in alarming red. The brain is trying to read through the mess, with tiny thought bubbles showing "where is the revenue data?" lost among irrelevant pages. Right side (cool green-blue tint, labeled "With Ariadne Core"): the same glowing brain, now relaxed and focused, sitting comfortably. In front of it, a single clean card of Markdown text with a few highlighted paragraphs — exactly the relevant content. The token counter shows "487 tokens" in calm green. The brain has a clear thought bubble: the answer, cleanly formed. Between the two sides, a subtle arrow pointing from left to right with the label "100x fewer tokens." Caption at bottom: "100,000 tokens of raw PDF, or 500 tokens of what matters."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_02 — The Extraction Pipeline**

A horizontal conveyor belt flowing left to right across the full width of the image. On the far left, a pile of raw documents enters the belt: a PDF icon, a DOCX icon, a PPTX icon, an XLSX icon, and several smaller format icons (HTML, CSV, TXT) — all messy, overlapping, different sizes. The belt passes through seven clearly labeled stations, each with a simple icon above it:

Station 1 "Extract": a hammer icon labeled "MarkItDown" — the documents get flattened into uniform Markdown pages. A small badge reads "Free."
Station 2 "Dedup": a fingerprint stamp — duplicate documents get a checkmark and skip ahead. Badge: "Free."
Station 3 "Enrich": a camera-eye icon — images in documents get descriptions added. Badge: "Vision API (optional)."
Station 4 "Chunk": scissors cutting at dotted lines — documents split into semantic sections. Badge: "Free."
Station 5 "Embed": a magnet pulling small vector arrows out of each chunk. Badge: "Embedding API."
Station 6 "Store": a vault door with the Postgres elephant logo — chunks and vectors go in.
Station 7 "Track": a ledger book with entries — provenance recorded for every action.

On the far right, clean outputs exit: a neat stack of Markdown pages and a search results card showing ranked results with scores. Below the belt, a banner reads: "Extraction is free. Embedding and search cost pennies per document." Caption: "Seven steps. Four are free. Three use cheap API calls. The expensive model never touches raw documents."

A small note below the caption: "Only need extraction? Install MarkItDown directly — it's open source (Microsoft, MIT license). Claude Code or any coding agent can set it up for you."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_03 — Many Clients, One Service**

A cloud shape at the top center of the image, labeled "Ariadne Core" in bold. Inside the cloud, four small icons arranged in a 2x2 grid: MCP Server (plug icon), REST API (endpoint icon), Postgres (elephant), MarkItDown (hammer). The cloud has a single HTTPS padlock on its border.

Below the cloud, a two-column layout with two large rounded rectangle cards side by side:

Left card (gold/amber tinted): a key icon at the top with the heading "API Key" and subtitle "Personal Edition." Below the heading, four client icons stacked vertically with labels beside each:
- Laptop with terminal prompt: "Claude Code"
- Brain icon: "Open Brain"
- Claw icon: "OpenClaw"
- Cursor arrow icon: "Cursor"

Right card (blue tinted): a shield icon at the top with the heading "OAuth" and subtitle "Managed Edition." Below the heading, five client icons stacked vertically with labels beside each:
- Laptop with terminal prompt: "Claude Code"
- Brain icon: "Open Brain"
- Claw icon: "OpenClaw"
- Cursor arrow icon: "Cursor"
- Claude face icon: "Claude Cowork" with a small tag reading "OAuth only"

The four clients appear in both cards, showing they support both auth methods. Claude Cowork appears only in the right card.

Between the two cards, a small callout box reads: "API key auth included with Personal Edition. OAuth available in Managed and higher, or roll your own."

Caption: "One deployment. Many clients. Two ways to authenticate."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_04 — Hosting: Cheap or Free to Try**

A simple, friendly illustration — not a flowchart. Three platform cards arranged side by side, like product comparison cards on a pricing page.

Left card (largest, highlighted with a subtle glow as "recommended"): A train icon at the top. Title: "Railway." Subtitle: "Simplest setup." Bullet points: "Free tier to try", "~$5/mo hobby plan", "5 minutes to deploy", "Postgres included." A small badge: "We recommend this."

Center card: A paper airplane icon at the top. Title: "Fly.io." Subtitle: "Scales to zero." Bullet points: "Free tier available", "~$5/mo", "Sleeps when idle."

Right card: A server box icon at the top. Title: "Any Docker Host." Subtitle: "Full control." Bullet points: "Hetzner, DigitalOcean, your own server", "~$4.50/mo", "Bring your own HTTPS."

Below all three cards, a shared footer: "Same Dockerfile everywhere. Pick what fits your workflow."

Caption: "Cheap or free to try. A few dollars a month for always-on."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_05 — Your Agent Does the Heavy Lifting**

A two-part illustration. The top part shows what YOU do (small, simple). The bottom part shows what YOUR AGENT does (larger, detailed).

Top section, labeled "You (2 minutes)":
Two simple icons in a row with checkmarks:
1. A browser window icon with the Railway logo — "Create a Railway account"
2. A terminal icon with a download arrow — "Install the Railway CLI"
A small speech bubble: "That's it. Your agent handles the rest."

Bottom section, labeled "Your Agent (3 minutes)":
A vertical timeline flowing top to bottom with five numbered steps, each with a small icon to the left and a one-line command to the right.
Step 1: Key icon. Command: "railway login". Annotation: "Authenticate."
Step 2: Folder icon. Command: "railway init". Annotation: "Create project."
Step 3: Database cylinder icon with a small "pgvector" badge. Command: "railway add --plugin postgresql". Annotation: "Add database."
Step 4: Lock icon with three small tags (EMBEDDING_API_KEY, VISION_API_KEY, ARIADNE_API_KEY). Command: "railway variables set ...". Annotation: "Set keys."
Step 5: Rocket icon. Command: "railway up". Annotation: "Deploy."

Below the timeline, a finish line with a checkmark and a sample URL: "https://ariadne-core-production.up.railway.app". A clock icon showing "~5 minutes total."

Caption: "You create two accounts. Your agent does the rest."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_06 — Connect Claude Code**

Top half: a terminal window with a dark background showing the command: "claude mcp add ariadne-core https://your-url/mcp --transport http --scope user --header X-API-Key:your-key". A small "restart Claude Code" arrow below the terminal.

Bottom half: six cards arranged in a fan (like a hand of playing cards), each a different pastel shade. Each card shows a tool name in bold and a one-line description below it:

- "convert_document — Extract any document to Markdown"
- "search — Find relevant chunks by meaning"
- "get_document — Get full content by ID"
- "list_documents — Browse your document store"
- "list_collections — See how documents are organized"
- "ingest — Batch-process a directory"

Caption: "One command. Six tools. Ready to use."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_07 — Document Format Mosaic**

A clean left-to-right flow diagram with three distinct zones separated by generous whitespace.

Left zone — "Input Formats": Four rows of small, simple document icons arranged in a neat grid with plenty of spacing between them. Each icon is a small rounded rectangle with a file extension label below it. Row 1: PDF, DOCX, PPTX, XLSX, CSV. Row 2: HTML, XML, JSON, TXT, MD. Row 3: RTF, EPUB, EML, MSG, ZIP. Row 4: IPYNB, WAV, MP3, JPG, PNG. The icons should be small, uniform in size, and clearly separated — not touching or overlapping.

Center zone — "Conversion": A single large arrow pointing right, passing through a box labeled "MarkItDown" with a small "MIT License" badge underneath. The arrow is wide and clean, visually connecting the input grid to the output.

Right zone — "Output": A single large, clean Markdown document icon — a white page with faint horizontal lines suggesting formatted text, and a bold "MD" label. Much larger than the input icons to emphasize the simplification.

A small note below: "Extraction is just the first step. Ariadne Core adds embedding, search, and provenance on top — those require an API or local model."

Caption: "20+ formats in. Clean Markdown out. Extraction is free."

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**img_08 — Search, Don't Send**

Two panels side by side with a vertical divider.

Left panel (labeled with a red X in the corner, using a circle-X shape): A person struggling to stuff an entire filing cabinet (drawers open, papers flying) into a large envelope addressed to "Your AI Model." The envelope is bulging and overflowing. A price tag dangling from the envelope reads "$$$." The AI model recipient looks overwhelmed with spiral eyes.

Right panel (labeled with a green checkmark in the corner, using a checkmark-in-shield shape): The same person, now calm, typing a question into a simple search box labeled "Ariadne Core." Three small, neat cards float back — each showing a text snippet with a relevance score badge (0.94, 0.87, 0.82). The person picks up just these three cards and hands them to the AI model, who looks focused and happy. A price tag reads "$0.01."

A small note at the bottom: "Works with any OpenAI-compatible embedding provider — OpenAI, Google Gemini, Groq, DeepSeek, local models, and more."

Caption: "Don't send the whole library. Search first, send what matters."

Use the circle-X and checkmark-in-shield shapes (not just color) so the contrast is clear beyond color alone.

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**architecture — System Architecture**

A technical but clean diagram showing the container internals. A large rounded rectangle labeled "ariadne-core container" contains:

Top layer: two boxes side by side.
- Left box: "MCP Server" with endpoint "/mcp".
- Right box: "FastAPI" with endpoints "/api/upload", "/api/documents", "/api/search", "/api/health". A lock icon on all except /api/health.

Between them, a label: "Single-port mode — both share PORT 8000."

Middle layer: "Auth" spanning the full width — a thin bar labeled "API Key or OAuth."

Below that: "MarkItDown" box leading to "Post-Processing Pipeline" (box with sub-labels: fingerprint, enrich, chunk, embed, store).

Bottom layer: "Postgres + pgvector" (cylinder) with tables listed: documents, chunks, collections, document_interactions, api_keys.

Outside the container, four arrows point in from below: Claude Code, Open Brain, OpenClaw, and Claude Cowork (with a small "OAuth / Managed" label) — all passing through the auth layer.

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.

---

**env_vars — Environment Variables Reference**

A clean table visualization designed as an infographic reference card, not a spreadsheet screenshot.

Header row in dark blue: "Variable | Required | Default | What it does"

Required section (left border accent):
- DATABASE_URL | Auto (Railway) | — | Postgres connection
- EMBEDDING_API_KEY | Yes | — | API key for embeddings (any OpenAI-compatible provider)
- VISION_API_KEY | Yes | — | API key for image descriptions (any OpenAI-compatible provider)
- ARIADNE_API_KEY | Yes | — | Client authentication key

Optional section (different left border accent):
- PORT | Auto (Railway) | 8000 | HTTP port
- MCP_PORT | No | 8000 | MCP port (= PORT for single-port)
- EMBEDDING_MODEL | No | text-embedding-3-small | Model name
- VISION_MODEL | No | gpt-4o-mini | Model name
- EMBEDDING_BASE_URL | No | https://api.openai.com/v1 | API endpoint
- VISION_BASE_URL | No | https://api.openai.com/v1 | API endpoint

Clean, readable, with subtle color coding to distinguish required from optional.

Colorblind-friendly, no hex codes. These images are for the onboarding skill, not technical documentation. They should be conceptual and accessible — designed to make the project's value, architecture, and deployment process immediately clear to anyone. Style for all: flat design, editorial illustration, simple shapes, bold colors on a light warm-gray background. Think "product landing page illustrations," not technical diagrams.
