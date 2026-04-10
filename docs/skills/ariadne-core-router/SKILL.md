---
name: ariadne-core
description: |
  Routes users to the right Ariadne Core skill by name. Only triggers on
  explicit skill requests: "run the install skill", "run the deploy skill",
  "run the build skill", "run the document intelligence skill", "run the
  ariadne skill". For general questions like "what is ariadne core", "tell
  me about ariadne", or "how do I get started", the onboarding skill handles
  those directly.
author: Denson Smith
version: 3.1.0
---

# Ariadne Core — Router

This skill routes to the right place. It does NOT present content itself —
it loads the appropriate skill and hands off.

## Detect context

Before routing, figure out what's available:

1. **MCP connected?** Check if ariadne-core MCP tools are available
   (convert_document, search, etc.). If yes, the user already has a running
   deployment.
2. **Runtime?** Are you in Cowork (can show images, use AskUserQuestion) or
   Claude Code (terminal only)?

## Routing rules

Glob for the SKILL.md and hand off completely:

- "run the install skill" / "set it up" / "deploy ariadne" → `**/ariadne-core-install/SKILL.md`
- "run the deploy skill" / "deploy to railway" → `**/ariadne-core-deploy/SKILL.md`
- "run the build skill" / "modify the code" → `**/ariadne-core-build/SKILL.md`
- "run the onboarding skill" / "present ariadne" → `**/ariadne-core-walkthrough/SKILL.md`
- "run the document intelligence skill" / "how do I use the tools" → `**/ariadne-document-intelligence/SKILL.md`
- "run the ariadne skill" (generic) → `**/ariadne-core-walkthrough/SKILL.md`

## All skills

| Skill | Runtime | What it does |
|-------|---------|-------------|
| **ariadne-core-walkthrough** | Cowork | Visual walkthrough with illustrations |
| **ariadne-core-install** | Claude Code / terminal agent | Deploy and connect |
| **ariadne-core-deploy** | Claude Code / terminal agent | Platform-specific deployment |
| **ariadne-document-intelligence** | Any | Best practices for using the tools |
| **ariadne-core-build** | Claude Code / terminal agent | Developing on the codebase |

## Important

**Do NOT try to present onboarding content yourself.** You are a router. Load
the onboarding skill and let it handle the presentation. The onboarding skill
has its own pacing rules, image management, and audience routing — duplicating
that here will break things.

**The onboarding skill is now dynamic (v2.0).** It opens with a prewired
five-beat starter deck and then composes the rest of the presentation on the
fly from an image manifest (`docs/assets/image_manifest.yaml`) and a project
knowledge graph (`docs/project_knowledge_graph.yaml`). Hand off to it as
early as possible — do not try to pre-classify the user into a developer /
agent-builder / evaluator bucket before handoff. The presenter figures that
out itself from the conversation.
