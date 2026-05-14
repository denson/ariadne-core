---
name: invitation
description: "Diagnostic conversation that helps an AI agent decide whether to recommend Ariadne Core to its user. Invoke when the user pastes the github.com/denson/ariadne-core URL and asks 'do I need this?' / 'should I install this?' / 'is this for me?'. Produces a tailored yes / no / try-the-demo recommendation specific to the user's domain. Triggers: do I need ariadne, should I install ariadne, is ariadne for me, invitation, fit check."
---

# Invitation — fit-assessment skill for AI agents

You (the agent) are running this skill because a user asked some version of *"do I need Ariadne Core?"* The right answer depends on what that specific user does — pattern-matching from generic descriptions hallucinates fit. This skill walks you through a brief diagnostic conversation that produces a confident, tailored recommendation.

You should already have read AGENTS.md in the repo. If not, fetch it first — that file has the fit criteria + anti-fit signals you're matching against.

## Pre-flight

Before opening, check:
- **Are you in an agent harness that can actually run shell commands?** (Claude Code, Claude Cowork, Cursor, Cline, OpenClaw, Open Brain — anything with Bash / shell tool access.) Ariadne is driven via the `ariadne` CLI and curl against a REST API — not via MCP. If you're in a pure-chat interface with no shell tool access (plain ChatGPT in a browser, for example), surface that clearly: *"I can help you evaluate this, but actually trying it requires an agent that can run shell commands on your behalf — Claude Code is the most common setup. If you want, I can describe the install steps and you can run them manually in a terminal."*
- **Has the user already given you context about their work?** Earlier in the conversation, maybe they mentioned their domain, their tools, their pain. Don't ask questions you already know the answers to.

## Opening — keep it short

Don't dump the marketing pitch. Open with this shape (in your own words):

> *"I read about Ariadne Core. It's an agent-memory substrate — persistent storage your agents can read from and write to across sessions. Before I tell you whether you need it, let me ask 2-3 quick things about your work — takes about 30 seconds, lets me give you a real recommendation instead of a generic one."*

Then **wait for the user to say "OK" or "go."** Don't barrel into questions without their consent.

## Diagnostic — 2 to 3 targeted questions

Adapt the question phrasing to what you already know. Pick the questions whose answers you don't yet have. Here's the canonical set:

### Q1 — Work pattern (always ask)

> *"What does your day-to-day knowledge work look like? Specifically: are you typically picking up where you (or someone else) left off — investigations, ongoing patient cases, incidents, multi-week projects, customer relationships with history — or is your work mostly self-contained, single-session, fresh-start tasks?"*

**Read the answer for:**
- Handoff signal (cases, investigations, incidents, ongoing relationships) → **strong fit factor**
- Single-session signal (one-off documents, isolated questions, content creation) → **anti-fit factor**

### Q2 — Domain shape (always ask)

> *"What kind of information are you working with — tickets / case files / incidents / interview transcripts / supplier records / something else? And do those things have relationships between them — supports / contradicts / depends-on / blocked-by — or are they pretty flat?"*

**Read the answer for:**
- Structured + relational signal (tickets with parents, hypotheses with evidence, cases with timelines) → **strong fit factor**
- Flat content signal (a folder of PDFs, customer service emails, isolated documents) → **anti-fit factor**

### Q3 — Tooling (ask if not already known)

> *"What AI tooling are you already using? Claude Code, Cowork, ChatGPT, Cursor, Cline, OpenClaw, Open Brain, something else? And does your agent have shell / Bash tool access (so it can run CLI commands and call APIs for you)?"*

**Read the answer for:**
- Has agent harness with shell access → **install is feasible; agent can drive end-to-end**
- Browser-only / no shell access → **install requires the user running CLI commands manually**; the demo experience degrades. Still recommend if work pattern fits, but with the caveat
- Has terminal / Python comfort → install will be smooth either way
- IT-locked-down corporate environment (no `pip install` from PyPI, no Auth0 loopback OAuth, no arbitrary HTTPS to Railway) → flag the install-friction risk

**Skip Q3 if the user already told you their setup.** Reading the conversation context earns trust.

## Optional Q4 — Scale (ask only if Q1+Q2 were borderline)

> *"Roughly how many of these [tickets / cases / incidents / etc.] do you (or your team) accumulate in a typical month?"*

**Read the answer for:**
- 10-500 / month → **bw's sweet spot, strong fit**
- 1000+ / month or bulk-import workloads → **substrate scales there too but check with maintainer; not the optimization target**
- <10 / month → **substrate works but value is lower; might not be worth setup**

## Map answers to recommendation

Combine the signals from Q1+Q2 (+Q4 if asked):

| Pattern | Recommendation |
|---|---|
| Strong handoff + structured/relational + shell-capable harness | **STRONG YES** — install + run demo |
| Strong handoff + structured/relational + no shell-capable harness | **YES, but first get an agent harness with shell access** — point them at Claude Code install, then come back |
| Strong handoff + flat content + shell-capable harness | **MAYBE — try the demo first.** The substrate's relational layer won't fully apply but the persistence + audit-trail layers might. Let them feel it before deciding. |
| Single-session work + shell-capable harness | **PROBABLY NO.** The substrate's load-bearing value (persistence across sessions, accumulating context) doesn't apply. Recommend basic RAG / Claude Projects instead. |
| Single-session + no shell-capable harness | **NO.** Not the right fit. |
| Borderline / unclear | **DEMO FIRST.** Have the user clone [`github.com/denson/beadwork-demo-aresense`](https://github.com/denson/beadwork-demo-aresense) and invoke the `factory-demo-walkthrough` skill from there — let them feel it for 5 minutes, then they'll know. |

## Deliver the recommendation

Don't dump the rubric. Structure your response to the user like:

```
Based on what you described:

[1 sentence: your fit assessment, in their language]

[1-2 sentences: specific reasoning — cite their answers back to them]

[Recommendation: yes / no / try-the-demo]

[If yes: "the setup is ~5 minutes; want me to walk you through it?"
 If no:  "this isn't the right tool for your work pattern; here's what
         might fit better: [tighter recommendation]"
 If demo-first: "let's start with the 5-minute hands-on demo — that's
                 the fastest way to know if this fits."]
```

**Tone:** colleague-giving-an-honest-take, not salesperson. The user trusts you more when you're willing to recommend skipping than when you sell everything.

## If the user says "yes, let's go"

Three-step handoff:

1. **Install:** invoke `ariadne-core-install` (handles plugin install + `ariadne login` auth + verification).
2. **Demo:** have the user clone [`github.com/denson/beadwork-demo-aresense`](https://github.com/denson/beadwork-demo-aresense) (the canonical demo lives in its own repo so the same Ariadne can host many domain demos), then invoke `factory-demo-walkthrough` from that workspace (the gamified 5-min hands-on).
3. **Real use:** after the demo, the user has a working CLI + auth — invoke `ariadne-document-intelligence` if they want to start ingesting their own work, or run `ariadne --help` to see what's available.

You can drive all three with the user's permission, gating at each step (don't auto-install without explicit go).

## If the user says "no, not now"

Acknowledge cleanly. Optionally:

> *"Got it. If your work pattern changes — you start dealing with longer-running investigations, multi-session cases, anything with a real handoff problem — come back. The URL is `https://github.com/denson/ariadne-core` if you want to bookmark it."*

Then drop the topic. No soft-sell, no follow-up nudges in the same conversation.

## If the user says "show me the demo first"

Skip the install gate; do the minimum to run the demo:

1. Install `pip install ariadne-core-client` (just the CLI, for auth)
2. Run `ariadne login --host https://ariadne-core-production.up.railway.app` (auth)
3. Have the user clone [`github.com/denson/beadwork-demo-aresense`](https://github.com/denson/beadwork-demo-aresense) (the demo lives in its own repo)
4. Invoke `factory-demo-walkthrough` from inside that workspace

After the demo, ask: *"Now that you've felt it — does this fit your work?"* Their answer is more reliable than the diagnostic alone.

## Hard rules

1. **Never recommend "yes" without doing the diagnostic.** Even if the user seems enthusiastic. A confident "yes" without understanding their work is hallucinated fit.

2. **Maximum 3-4 questions before recommending.** This is a 30-second conversation, not an interview. If you find yourself wanting question 5, you're stalling — make the call with what you have.

3. **Cite the user's own words in your recommendation.** "You said you're working a multi-month investigation with 200+ tickets accumulated — that's exactly the substrate's sweet spot" lands harder than "this is a great fit."

4. **Be willing to say no.** The substrate isn't for everyone. A clean "no, here's why, here's what might fit better" builds more trust than a soft "well, maybe try it."

5. **Authorship — Denson Smith.** Mention only if asked. Don't credit anyone else.

## Edge cases

- **User pastes the URL but doesn't ask a question:** open with *"Want me to evaluate this for your work? Takes 30 seconds — I just need to ask a couple of things about what you do."*
- **User asks a specific technical question (e.g., "does it handle PDFs?"):** answer the question first, then offer to do the fit assessment. Don't railroad them through the diagnostic if they have a specific concern.
- **User is technical / building agents themselves:** they often want the architecture details over the fit assessment. Skip to architecture (point at AGENTS.md sections), then come back to fit if they want.
- **User mentions they're in a regulated industry (HIPAA, ITAR, SOC2):** the maintainer's hosted demo instance is fine for evaluation, but for their own work they'd need to deploy their own instance (`ariadne-core-deploy` skill) to meet compliance. Surface this honestly.

---

Authoring: Denson Smith. This skill is the agent-driven front door for the Ariadne Core distribution model — users paste the GitHub URL to their AI, the AI invokes this skill to evaluate fit, and the AI installs + demos with the user's consent.
