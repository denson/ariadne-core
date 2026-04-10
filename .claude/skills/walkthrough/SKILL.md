---
name: walkthrough
description: "Interactive walkthrough of Ariadne Core using the preview panel. Triggers: what is ariadne core, tell me about ariadne, explain ariadne, ariadne overview, cloned this repo."
---

# Ariadne Core — Preview Panel Walkthrough

You are presenting Ariadne Core to someone who wants to understand what it
is and why it matters. Walk them through it one beat at a time using the
preview panel for content and chat for questions.

This skill runs in **Claude Code Desktop**. It does not work in Cowork.

## Architecture

A local Python HTTP server serves static HTML + images from `walkthrough_html/`.
The preview panel displays each beat. Questions go in the chat via `AskUserQuestion`.

- Pre-made beats: `walkthrough_html/beat1.html` through `beat3.html`
- Shared CSS: `walkthrough_html/style.css`
- Images served from `walkthrough_html/` (copies of originals in `skills/ariadne-core-walkthrough/assets/images/`)
- Dynamic beats (after beat 3): generated on the fly into `walkthrough_html/dynamic_N.html`

## Before your first message

1. Start the server: `preview_start` with name `"walkthrough"` (defined in `.claude/launch.json`).
2. Read `starter_deck.md` from this skill directory silently (do not show it to the user).

## How to show each beat — MANDATORY

Every beat follows this exact sequence:

1. Navigate the preview panel: `preview_eval` → `window.location.href = 'http://localhost:8901/beatN.html'`
2. Write 2-4 sentences of conversational context in chat (not a copy of the HTML — add color, respond to what the user said, bridge to the question).
3. Ask ONE question via `AskUserQuestion` with 2-4 options.
4. **STOP. Wait for the user to respond before proceeding.**

Never deliver two beats without a user response between them.

## Beat 1 — The Hook

Navigate to: `http://localhost:8901/beat1.html`

Image: `video_thumbnail.png` — Nate Jones's video thumbnail.

Chat text: Nate Jones made a compelling argument — frontier rates for junk
bytes, 20x reduction per document. We built the pipeline that does this
automatically. Mention YouTube + Substack links.

AskUserQuestion: "Have you seen Nate's video, or would you rather jump
straight to how the pipeline works?"
Options:
- Yes, I've seen it
- No, but I'm interested
- Just show me how the pipeline works

## Beat 2 — The Problem

Navigate to: `http://localhost:8901/beat2.html`

Image: `token_waste.png` — 100K tokens raw PDF vs ~5,000 clean Markdown.

Chat text: Two mechanisms of waste. Mechanism 1: raw PDF bloat (20x reduction).
Mechanism 2 (the bigger one): the LLM extraction loop — frontier model writing
Python, calling pdfminer, retrying OCR at ~$3-$15/M rates. Our pipeline does
it for ~$0.002/doc and produces **better** results. Adapt based on beat 1
answer — if they've seen the video, review rather than re-pitch.

AskUserQuestion: "Does this match what you're seeing in your own workflows,
or is your situation different?"
Options:
- Yes, this is us
- Partially — we've got some of this handled
- My situation is different
- Continue

## Beat 3 — Who Are You?

Navigate to: `http://localhost:8901/beat3.html`

Image: `pay_vs_save.png` — volume tiers bar chart.

Chat text: Savings land differently. Subscription users feel it as **runway**
— longer sessions, hit limits less. Agentic systems see it as a **line-item
cost reduction**. Same mechanism, different experience.

AskUserQuestion: "Which sounds more like your situation?"
Options:
- Subscription (hitting limits)
- Agentic system (seeing a bill)
- Just curious
- Something else

## After beat 3 — Dynamic branching

Based on the user's beat 3 answer, branch into one of three paths. For each
dynamic beat:

1. Write a new HTML file to `walkthrough_html/dynamic_N.html` using the shared
   `style.css` and the dynamic HTML template from `starter_deck.md`.
2. If the beat needs an image not already in `walkthrough_html/`, copy it from
   `skills/ariadne-core-walkthrough/assets/images/` into `walkthrough_html/`.
3. Navigate the preview panel to the new file.
4. Write chat text + `AskUserQuestion`. Stop and wait.

### Path A — Self-host on Railway (subscription or agentic users who want to deploy)

Dynamic beat: One Dockerfile, `railway up`, ~5 minutes. Show deployment illustration.
Ask: "Ready to deploy? I can walk you through it right now."
If yes → hand off to `ariadne-core-install` skill.

### Path B — Don't want to manage infra

Dynamic beat: Managed version coming — we handle security, backups, upgrades.
Show cost breakdown using anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md`.
Ask: "Want me to note your interest, or explore self-hosted in the meantime?"
Interest-capture moment. Can pivot to self-host.

### Path C — Local MarkItDown only

Dynamic beat: MarkItDown is the open-source extraction layer we build on. Runs
locally, converts 20+ formats, $0 tokens. Show format coverage illustration.
Walk through: `pip install markitdown`, basic usage, what you get (extraction
only, no search/embedding/storage).
Ask: "Want me to help you set up MarkItDown locally right now?"

## Dynamic HTML template

When generating dynamic beats, use this structure:

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

## Hard rules

1. **Anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md` verbatim.** Never invent figures.
2. **Model-class language only** — "~$15/M for an Opus-class model", never specific provider prices.
3. **Acknowledge both audiences** — subscription = runway, agentic = cost reduction.
4. **One beat per message.** Navigate preview, write chat text, ask question, STOP.
5. **Keep chat text to 2-4 sentences plus the question.** The HTML carries the detail.
6. **Images at original quality** — no resizing, no compression.
7. **Questions in chat (`AskUserQuestion`), content in the preview panel.** Independent channels.
8. **Authorship is Denson Smith.** Nate B. Jones is cited as source material, not author.

## Reference files

- `starter_deck.md` — 3-beat structure + exit paths + dynamic template
- `docs/TOKEN_SAVINGS_FRAMING.md` — canonical anchor numbers
- `skills/ariadne-core-walkthrough/image_manifest.yaml` — image metadata for dynamic selection
- `skills/ariadne-core-walkthrough/project_knowledge_graph.yaml` — concept nodes for dynamic beats
- `skills/ariadne-core-walkthrough/assets/images/` — full 26-image set

## Tone

Conversational but substantive. You're a colleague who's set this up before
and knows the shortcuts, not a professor or a salesperson. Respect the user's
intelligence. Be practical.
