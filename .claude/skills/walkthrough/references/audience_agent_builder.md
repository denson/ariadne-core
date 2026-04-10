# Audience: Agent Builder — Connect an Agentic System

> **Note:** This file is a *seed angle* for the dynamic presenter, not a
> hard branch. The presenter may pull excerpts from here when a user's
> interests match this audience. It is also a fallback "standard tour" if
> the user explicitly asks for one (e.g. "walk me through the agent builder
> path"). See `SKILL.md` v2.0 for how the dynamic presenter works.


The person is building with Open Brain, OpenClaw, or a custom agent framework and needs
document memory. They care about integration patterns, API contracts, and how their
agents interact with stored documents. They may or may not be deploying Ariadne Core
themselves — they might be connecting to an existing instance.

## What to emphasize

- MCP is the primary interface for all clients — agent systems connect the same way Claude Code does
- API key auth is straightforward: one header on every request. OAuth available in Managed edition
- Provenance tracking: every agent call is recorded, even dedup skips
- Collections let different agents/workflows organize documents without conflict
- The upload endpoint handles remote file ingestion (no local filesystem needed)

## Flow

### 1. How agents connect

Agent systems connect via MCP, the same way Claude Code does. REST API is also available for scripts and automation.

Show the basic pattern:
```bash
curl -X POST https://ariadne-url/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: the-api-key" \
  -d '{"query": "termination clause", "top_k": 5}'
```

-> **Show `img_03.png`** (Many Clients, One Service) — point out that Open Brain and
OpenClaw, Open Brain, and Claude Code all connect via MCP. Claude Cowork uses MCP + OAuth (Managed edition).

-> **`AskUserQuestion`**: *"Which framework are you building with — Open Brain, OpenClaw, or something custom?"* Options: Open Brain / OpenClaw / Custom framework / Multiple / Continue

### 2. Key endpoints for agents

Walk through the endpoints their agents will actually use:

| What the agent does | Endpoint | Method |
|---------------------|----------|--------|
| Upload a file | `POST /api/upload` | multipart form |
| Convert and store | `POST /api/documents` | JSON body with URI |
| Search documents | `POST /api/search` | JSON body with query |
| Get full document | `GET /api/documents/{id}` | path param |
| List what's stored | `GET /api/documents` | query params |
| List collections | `GET /api/collections` | — |

The upload endpoint is important for remote agents — they can't pass local file paths.
Upload first, get a server-side path, then pass that to convert.

### 3. Provenance tracking

This is where Ariadne Core differs from a plain vector database. Every agent call
records:

- `agent_id` — which agent instance made the call
- `agent_type` — "ob1", "openclaw", "custom", etc.
- `model` — which LLM the agent is running
- `initiated_by` — human or system that triggered the agent

Show them how to pass this in request bodies:
```json
{
  "query": "quarterly revenue",
  "agent_id": "ob1-daily-capture",
  "agent_type": "ob1",
  "initiated_by": "cron:nightly-ingest"
}
```

Even when a document is a dedup skip (already processed), the interaction is recorded.
This means you can always answer "which agents have touched this document?"

-> **`AskUserQuestion`**: *"How many agents will be hitting this — one agent, or multiple agents that need to share documents?"* Options: Just one / Multiple agents / Not sure yet / Continue

### 4. Collections strategy

Collections are the primary organizing principle. Suggest patterns:

- One collection per agent workflow: `"ob1-daily-capture"`, `"openclaw-research"`
- One collection per project: `"project-alpha"`, `"q4-analysis"`
- Search defaults to all collections, or scope with `"collection": "name"`

### 5. Deployment (if they need it)

If they don't already have an Ariadne Core instance, explain that deployment is
handled in **Claude Code**. Tell them to switch to Claude Code and say **"deploy
ariadne core"** — the install skill will handle it autonomously. They need a Railway
account and an API key from any OpenAI-compatible provider.

If they already have a URL, skip straight to the integration patterns above.

-> **`AskUserQuestion`**: *"Do you already have an Ariadne Core instance running, or do you need to deploy one first?"* Options: Already have one / Need to deploy / Not sure / Continue

### 6. What's next

- Point them to `SPEC.md` for complete API documentation
- The **ariadne-document-intelligence** skill has best practices for search patterns
  and collection strategy
- Multiple agent systems can share the same deployment — they're just different
  `agent_type` values in the provenance records
- Come back to Cowork for visual guides or questions any time

## What NOT to do

- Don't explain MarkItDown internals or chunking strategies unless asked
- Don't assume they're deploying — they might already have an instance
- Don't oversell — they want to know the API contract, not the philosophy
