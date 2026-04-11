---
name: ariadne-core-walkthrough
description: "Interactive walkthrough of Ariadne Core. Triggers: what is ariadne core, tell me about ariadne, explain ariadne, ariadne overview."
---

# Ariadne Core — Walkthrough (Plugin-Level)

DO NOT use this skill when the user wants to deploy (use ariadne-core-deploy),
modify the codebase (use ariadne-core-build), process or search documents (use
ariadne-document-intelligence), or explicitly names a different skill (use
ariadne-core-router).

This skill runs in **Claude Code Desktop**. It does not work in Cowork.

## How it works

The walkthrough uses the **preview panel** to display rich HTML content with
images, while questions go in the chat via `AskUserQuestion`. A local Python
HTTP server serves static files from `walkthrough_html/`.

## Before your first message

1. Start the server: `preview_start` with name `"walkthrough"` (defined in `.claude/launch.json`).
2. Read `starter_deck.md` from this skill directory silently (do not show it).

## Rule 0: Beat 1 is the opening. Period.

Your first user-facing message is Beat 1. No warm-up, no overview, no
introduction. Beat 1 IS the opening.

You do **NOT**:
- Write your own overview before Beat 1
- Dump paragraphs about the pipeline, MCP tools, deployment, or auth
- Invent placeholder URLs — the real repo is
  `https://github.com/denson/ariadne-core`

## How to structure each beat — MANDATORY

Every beat follows this exact sequence:

1. Navigate the preview panel: `preview_eval` → `window.location.href = 'http://localhost:8901/beatN.html'`
2. Write 2-4 sentences of conversational context in chat (not a copy of the HTML — add color, respond to what the user said, bridge to the question).
3. Ask ONE question via `AskUserQuestion` with 2-4 options.
4. **STOP. Wait for the user to respond before proceeding.**

Never deliver two beats without a user response between them.

## The 3 pre-made beats

**Beat 1 — The Hook:** `http://localhost:8901/beat1.html`
Nate Jones's argument — frontier rates for junk bytes, 20x reduction, we built
the pipeline. Mention that Ariadne Core is a deployed service, not a local
library — trying it requires a Railway account (~$5/mo, free tier available) or
any Docker host, and takes about 5 minutes. This sets expectations before the
user tries to use tools that don't exist yet. Ask if they've seen the video.

**Beat 2 — The Problem:** `http://localhost:8901/beat2.html`
Two mechanisms of waste. Mechanism 1: raw PDF bloat. Mechanism 2: the LLM
extraction loop. Better, not just cheaper. Ask if this matches their workflows.

**Beat 3 — Who Are You?:** `http://localhost:8901/beat3.html`
Subscription = runway, agentic = cost reduction. Same mechanism, different
experience. Ask which sounds like their situation.

## After beat 3 — Dynamic branching

Based on the user's answer, branch into dynamic beats. For each:
1. Write HTML to `walkthrough_html/dynamic_N.html` using `style.css` and the
   template from `starter_deck.md`.
2. Copy any needed image from `assets/images/` (in this skill directory) into
   `walkthrough_html/`.
3. Navigate preview panel. Write chat text + `AskUserQuestion`. Stop and wait.

**Path A — Self-host on Railway:** Check if they have a Railway account (free tier
to try, ~$5/mo hobby plan). Deploy walkthrough → hand off to ariadne-core-install.
**Path B — Don't want to manage infra:** Managed version coming → interest capture.
**Path C — Local MarkItDown only:** Extraction-only setup, `pip install markitdown`.
No deployment needed — contrast with the full pipeline which requires hosting.

## Hard rules

1. **Anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md` verbatim.** Never invent figures.
2. **Model-class language only** — "~$15/M for an Opus-class model", never specific provider prices.
3. **Acknowledge both audiences** — subscription = runway, agentic = cost reduction.
4. **One beat per message.** Navigate preview, write chat text, ask question, STOP.
5. **Keep chat text to 2-4 sentences plus the question.** The HTML carries the detail.
6. **Images at original quality** — no resizing, no compression.
7. **Questions in chat (`AskUserQuestion`), content in the preview panel.**
8. **Authorship is Denson Smith.** Nate B. Jones is cited as source material, not author.

## Resources in this skill directory

- `starter_deck.md` — 3-beat structure + exit paths + dynamic template
- `image_manifest.yaml` — image descriptions, topics, audience tags
- `project_knowledge_graph.yaml` — concept entries for dynamic beats
- `assets/images/` — full 26-image set
- `references/` — audience-specific angle documents
- `saving_tokens_transcript.txt` — Nate Jones video transcript
- `stupid_button_prompt.txt` — diagnostic prompt for session waste
- `token_translator.txt` — per-session token math prompt

## Tone

Conversational but substantive. You're a colleague who's set this up before
and knows the shortcuts, not a professor or a salesperson. Respect the user's
intelligence. Be practical: move them from "what is this?" to "I have it
running" as efficiently as possible.
