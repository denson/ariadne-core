# Starter Deck — Ariadne Core Walkthrough

Three pre-made beats served as static HTML in the preview panel, followed by
dynamic branching based on the user's audience. Read this silently before
starting. All hard rules from `SKILL.md` apply.

---

## Beat 1 — The Hook

**File:** `walkthrough_html/beat1.html`
**Image:** `video_thumbnail.png`

Navigate preview to `http://localhost:8901/beat1.html`.

Chat text — hit the high points of Nate's argument in 2-3 sentences:
- Frontier rates for binary metadata, embedded fonts, layout junk
- 4,500-word doc: ~100,000 tokens raw PDF → ~5,000 clean Markdown = 20x reduction
- Wasteful 30-turn Opus session: $8-$10 → ~$1 done cleanly = the 10x
- We built the pipeline that does this automatically

Include video links:
- YouTube: https://youtu.be/5ztI_dbj6ek (deep-dive at https://youtu.be/5ztI_dbj6ek?t=260)
- Substack: https://natesnewsletter.substack.com/p/your-claude-sessions-cost-10x-what

AskUserQuestion: "Have you seen Nate's video, or would you rather jump straight
to how the pipeline works?"
Options:
- Yes, I've seen it
- No, but I'm interested
- Just show me how the pipeline works

---

## Beat 2 — The Problem

**File:** `walkthrough_html/beat2.html`
**Image:** `token_waste.png`

Navigate preview to `http://localhost:8901/beat2.html`.

Chat text — adapt based on beat 1 answer:

**If they've seen the video:** Review rather than re-pitch. "Then you know the
shape of this." Walk through both mechanisms briefly — the 20x PDF bloat and the
bigger LLM extraction loop. "We replace both."

**If they haven't:** Walk through Nate's argument. Two mechanisms: raw PDF bloat
(20x) and the LLM extraction loop (frontier model writing Python, debugging OCR,
all at ~$3-$15/M). Recommend the video — 12 minutes, document deep-dive at 4:20.

Both branches: "Not just cheaper — better. A deterministic pipeline captures
tables, layout, and image semantics more accurately than a frontier model
improvising extraction code."

AskUserQuestion: "Does this match what you're seeing in your own workflows, or
is your situation different?"
Options:
- Yes, this is us
- Partially — we've got some of this handled
- My situation is different
- Continue

---

## Beat 3 — Who Are You?

**File:** `walkthrough_html/beat3.html`
**Image:** `pay_vs_save.png`

Navigate preview to `http://localhost:8901/beat3.html`.

Chat text: The savings land differently. Subscription users (Claude Pro/Max)
feel it as runway — longer sessions, hitting limits less. Agentic systems buying
tokens directly see it as a line-item cost reduction. Same mechanism, different
experience.

AskUserQuestion: "Which sounds more like your situation?"
Options:
- Subscription (hitting limits)
- Agentic system (seeing a bill)
- Just curious
- Something else

---

## After beat 3 — Dynamic branching

Based on the user's answer, generate dynamic beats. Each dynamic beat:

1. Write HTML to `walkthrough_html/dynamic_N.html` using the template below.
2. Copy any needed image from `skills/ariadne-core-walkthrough/assets/images/`
   into `walkthrough_html/`.
3. Navigate preview panel to the new file.
4. Write chat text + AskUserQuestion. Stop and wait.

### Path A — Self-host on Railway

For users who want to deploy (subscription or agentic).

Dynamic beat content:
- One Dockerfile, `railway up`, ~5 minutes
- Show deployment illustration (use `architecture.png` or similar from assets)
- Mention: open source, self-installable, Claude Code connects with an API key

AskUserQuestion: "Ready to deploy? I can walk you through it right now."
Options:
- Yes, let's do it → hand off to **ariadne-core-install** skill
- Tell me more about the architecture first
- Not yet

### Path B — Don't want to manage infra

For users interested but not ready to self-host.

Dynamic beat content:
- Managed version coming — security, backups, upgrades handled
- Show cost breakdown: management fee vs savings at volume tiers
  (use anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md` verbatim)

AskUserQuestion: "Want me to note your interest, or explore self-hosted in
the meantime?"
Options:
- Note my interest
- Show me self-hosted anyway → pivot to Path A
- Tell me more about pricing

### Path C — Local MarkItDown only

For users who just want extraction without the full pipeline.

Dynamic beat content:
- MarkItDown is the open-source extraction layer Ariadne builds on
- Runs locally, converts 20+ formats, $0 tokens
- What you get: extraction only — no search, no embedding, no storage
- What Ariadne adds on top: semantic embeddings, metadata, vector search

AskUserQuestion: "Want me to help you set up MarkItDown locally right now?"
Options:
- Yes, let's set it up
- Actually, I want the full pipeline → pivot to Path A
- Tell me more about what Ariadne adds

---

## Dynamic HTML template

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ariadne Core — [Beat Title]</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="container">
    <div class="beat-tag">Ariadne Core</div>
    <h1>[Headline]</h1>
    <div class="image-frame">
      <img src="[filename].png" alt="[description]">
      <div class="caption">[Caption]</div>
    </div>
    <p>[Content paragraphs]</p>
  </div>
</body>
</html>
```

For beats without an image, omit the `.image-frame` div entirely.

---

## Continuing after exit paths

If the user doesn't fit any path or wants to explore further, compose dynamic
beats on the fly. Use `project_knowledge_graph.yaml` for concept content and
`image_manifest.yaml` to pick images. Track which images and concepts you've
shown — don't repeat unless asked.
