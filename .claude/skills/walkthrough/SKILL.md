---
name: walkthrough
description: "Interactive walkthrough of Ariadne Core. Triggers: what is ariadne core, tell me about ariadne, explain ariadne, ariadne overview."
---

# Ariadne Core — Walkthrough

You are presenting Ariadne Core to someone who wants to understand what it
is and why it matters. Walk them through it one beat at a time.

## How to show images

Images are at: `${CLAUDE_SKILL_DIR}/assets/images/`

To display an image to the user:
1. Copy the image file to the current working directory using Bash:
   `cp "${CLAUDE_SKILL_DIR}/assets/images/<filename>.png" ./<filename>.png`
2. Then use `Read` on the local copy: `./<filename>.png`
   The image will render visually because Claude is multimodal.

You MUST copy first, then Read the local copy. Reading directly from the
skill directory may not work in all environments.

Before your first message:
1. Copy and Read the Beat 1 image: `video_thumbnail.png`
2. Read `${CLAUDE_SKILL_DIR}/starter_deck.md`
3. Read `${CLAUDE_SKILL_DIR}/image_manifest.yaml`

## How to pace the conversation

Each beat:
1. Copy and Read one image (see above)
2. Write 2-4 sentences of content
3. Use `AskUserQuestion` with 2-3 options plus "Something else"
4. Stop and wait

Never deliver two beats without a user response between them.

## Beat 1 — The problem

Read: `${CLAUDE_SKILL_DIR}/assets/images/video_thumbnail.png`

Nate Jones made a compelling argument: when you drop raw PDFs into a
frontier model's context, you're paying ~$3-$15/M tokens for binary
metadata, embedded fonts, and layout junk the model never uses. A
4,500-word document is ~100,000 tokens as raw PDF but only ~5,000 as
clean Markdown — a 20x reduction just from format conversion. We built
the pipeline that does this automatically.

AskUserQuestion: "Have you seen Nate's video?"
- Yes, I've seen it
- No, but I'm interested
- Just tell me about the pipeline

## Beat 2 — Two mechanisms of waste

Read: `${CLAUDE_SKILL_DIR}/assets/images/two_token_economies.png`

There are two ways frontier tokens get wasted on documents. First, raw
PDF bloat — binary junk in the context window. Second (and bigger): the
LLM-driven extraction loop, where an Opus or Sonnet model writes Python,
calls pdfminer, debugs table parsing, retries OCR — using $3-$15/M
tokens to do work a specialized pipeline does better for ~$0.002/doc.

AskUserQuestion: "Which interests you more?"
- The cost savings in detail
- How the pipeline actually works
- How this compares to just using MarkItDown

## Beat 3 — Who are you?

Read: `${CLAUDE_SKILL_DIR}/assets/images/pay_vs_save.png`

The savings hit differently depending on how you buy tokens. Subscription
users (Claude Pro/Max) feel it as runway — longer sessions, hitting
limits less often. Agentic systems buying tokens directly (OpenClaw,
Open Brain, custom agents) see it as a line-item cost reduction on their
monthly bill.

AskUserQuestion: "How do you use LLMs?"
- I'm on a Claude subscription
- I'm building an agentic system
- Both / it depends
- I'm just evaluating

## Beat 4 — The numbers

Read: `${CLAUDE_SKILL_DIR}/assets/images/cost_point.png`

Use the anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md` verbatim.
Never invent figures. Frame for the audience identified in Beat 3:
subscription users hear about runway, agentic builders hear about
per-document cost reduction.

Key numbers: 20x per-document reduction, 8-10x session cost reduction,
~$0.002 pipeline cost vs ~$0.29-$1.43 saved per doc (Sonnet-Opus range).

AskUserQuestion: "What would you like to explore next?"
- How do I set it up?
- Tell me about the architecture
- What about search and metadata?

## Beat 5 — Next steps

Read: `${CLAUDE_SKILL_DIR}/assets/images/architecture.png`

Ariadne Core runs as a hosted service — one deployment serves all clients
over HTTPS. Claude Code, OpenClaw, Open Brain, or any MCP client connects
with an API key. Beyond extraction, every document gets chunked, embedded,
and stored with agent-writable metadata — turning a pile of documents into
a searchable, annotatable knowledge base.

AskUserQuestion: "Ready to get started?"
- Walk me through installation
- I want to try it on a document first
- Tell me more about the metadata layer
- I have other questions

## After Beat 5 — Go dynamic

From here, compose each beat based on what the user asks. Pull content
from `${CLAUDE_SKILL_DIR}/project_knowledge_graph.yaml` and show images
from `${CLAUDE_SKILL_DIR}/assets/images/` using the `Read` tool. Use
`image_manifest.yaml` to pick the right image for each topic.

## Hard rules

1. Use anchor numbers from `docs/TOKEN_SAVINGS_FRAMING.md` verbatim. Never invent figures.
2. Use model-class language for rates — "~$15/M for an Opus-class model", never specific provider prices.
3. Acknowledge both audiences — subscription users feel savings as runway, agentic systems as cost reduction.
4. One beat per message. Always end with `AskUserQuestion`. Always stop and wait.
5. Keep beats to 2-4 sentences plus the image. Don't dump walls of text.

## Reference files in this directory

- `starter_deck.md` — the 5-beat structure
- `image_manifest.yaml` — every available image with descriptions and topics
- `project_knowledge_graph.yaml` — concept entries for dynamic beats
- `saving_tokens_transcript.txt` — Nate Jones video transcript
- `stupid_button_prompt.txt` — diagnostic prompt for session waste
- `token_translator.txt` — per-session token math prompt
- `references/` — audience-specific angle documents
