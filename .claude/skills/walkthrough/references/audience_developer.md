# Audience: Developer — Deploy and Use

> **Note:** This file is a *seed angle* for the dynamic presenter, not a
> hard branch. The presenter may pull excerpts from here when a user's
> interests match this audience. It is also a fallback "standard tour" if
> the user explicitly asks for one (e.g. "give me the full developer
> walkthrough"). See `SKILL.md` v2.0 for how the dynamic presenter works.


The person wants to get Ariadne Core running and start using it with Claude Code.
They're hands-on and want practical steps, not theory. Walk them through what the
deployment looks like visually here in Cowork, then hand them off to Claude Code
to actually run the commands.

## What to emphasize

- Speed: they can go from zero to live in ~5 minutes on Railway
- Simplicity: one Dockerfile, one CLI command to connect, the full tool set immediately available
- Cost: free tier works, pennies per document for API calls
- They don't need to understand the internals — just deploy, connect, use
- **The actual deployment happens in Claude Code** — this presentation shows them
  what to expect, then hands off

## Flow

### 1. Choose a platform

Most developers should use Railway unless they have a reason not to. Present the
decision simply:

- **Railway** — simplest, free tier, 5 minutes. Recommended unless they need something specific.
- **Fly.io** — if they want scale-to-zero (saves money when idle)
- **VPS** — if they want maximum control or already have a server

-> **Show `img_04.png`** (Hosting: Cheap or Free to Try)

-> **`AskUserQuestion`**: *"Are you leaning toward Railway, or do you already have a hosting preference?"* Options: Railway / Other / Continue

If they don't have a preference, say "Railway is the easiest, let's go with that" and
move on.

### 2. Show them what deployment looks like

Walk through what they'll see when they deploy. Show the commands so they know what
to expect, but frame it as a preview — the actual deployment happens in Claude Code.

The five steps on Railway:

1. `railway login` — authenticate
2. `railway init` — create a project
3. `railway add --database postgres` — add Postgres with pgvector
4. Set three env vars: `EMBEDDING_API_KEY`, `VISION_API_KEY`, `ARIADNE_API_KEY`
5. `railway up` — deploy

-> **Show `img_05.png`** (Your Agent Does the Heavy Lifting)

-> **`AskUserQuestion`**: *"Do you have a Railway account already, or do we need to set that up first?"* Options: I have one / Need to set up / Continue

**Important:** Railway sets `DATABASE_URL` and `PORT` automatically. They do NOT need
`DB_PASSWORD` or manual database setup. Don't mention it — it'll confuse them.

### 3. Show them how Claude Code connects

After deployment, one command in Claude Code connects everything:

```
claude mcp add ariadne-core https://your-url/mcp \
  --transport http --scope user \
  --header "X-API-Key:your-api-key"
```

Then restart Claude Code and the tool set becomes available.

-> **Show `img_06.png`** (Connect Claude Code)

-> **`AskUserQuestion`**: *"Want to see what the tools do before we get you set up?"* Options: Show me the tools / I'm ready to set up / Continue

### 4. How it works once connected

Walk through what their workflow will look like once they're set up:

1. **Upload a document:** "Give Claude Code a PDF and ask it to extract it"
2. **Search:** "Ask a question about the document — Claude Code searches and gets back
   just the relevant chunks"
3. **Collections:** "Organize documents by project or topic"

-> **Show `img_08.png`** (Search, Don't Send) — reinforce the pattern: search first, send
what matters.

-> **`AskUserQuestion`**: *"How are you currently handling documents with your agents — stuffing them into context, or do you have something in place already?"* Options: Stuffing into context / Have a system / Just exploring / Continue

### 5. Hand off to Claude Code

This is the transition. Tell them:

"I've shown you what Ariadne Core does and how deployment works. To actually get it
running, you'll need to switch to **Claude Code** — that's where the terminal commands
run. Once you're in Claude Code, just say **'deploy ariadne core'** or
**'set up ariadne core'** and the install skill will walk you through it step by step.
It'll run the commands for you."

Mention:
- They need a Railway account and the Railway CLI installed before starting
- An API key from any OpenAI-compatible provider (for embeddings)
- Claude Code handles the rest autonomously

-> **`AskUserQuestion`**: *"Ready to switch to Claude Code and get this deployed, or do you have more questions first?"* Options: Ready to deploy / Have questions / Tell me more about the tools

### 6. What's next

After the handoff, mention:

- The **ariadne-document-intelligence** skill teaches agents best practices for using
  the tools (collection strategy, caller metadata, search-first patterns)
- They can upload files via REST API too: `POST /api/upload`
- The deployment updates with `railway up` — no downtime
- Come back to Cowork any time for visual guides or questions

## What NOT to do

- Don't explain the architecture in detail — they can read SPEC.md if curious
- Don't walk through every environment variable — just the three required ones
- Don't mention Claude Desktop, STDIO, or local Docker — those aren't supported
- Don't explain how chunking, embedding, or dedup work unless they ask
- Don't slow them down with theory when they want to deploy
