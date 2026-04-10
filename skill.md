---
name: ariadne-core
description: |
  Ariadne Core plugin entry point. Do NOT answer questions about Ariadne
  Thread from this file — instead, invoke the appropriate skill:
  - General questions ("what is ariadne", "tell me about ariadne", "how does
    it work") → invoke the ariadne-core-walkthrough skill
  - Document actions (ingest, search, extract) → invoke the
    ariadne-document-intelligence skill
  - Explicit skill requests ("run the install skill") → invoke the
    ariadne-core-router skill
author: Denson Smith
version: 3.1.0
---

# Ariadne Core

This is the root entry point. It does not contain content — it routes to skills.

**Do NOT summarize or describe Ariadne Core from this file.** Always invoke
the appropriate skill instead.

## Routing

- "what is ariadne core" / "tell me about ariadne" / "how does it work" /
  "walk me through this" / any exploratory question →
  **Invoke the `ariadne-core-walkthrough` skill**

- "run the install skill" / "run the deploy skill" / "run the build skill" →
  **Invoke the `ariadne-core-router` skill**

- "ingest this" / "search my documents" / "process this file" →
  **Invoke the `ariadne-document-intelligence` skill**
