# Factory Demo — Invitation

You've been invited to try a working agent-memory substrate, in the form of a
5-minute hands-on test. Here's everything you need.

## The premise

You're going to take over a quality investigation at a fictional sensor
manufacturer. The previous manager (Marcus) just left. Standup is in 5
minutes. Your AI partner has access to Marcus's six months of work via a
substrate called Ariadne Core. You drive; the agent retrieves and coaches.

There's no slide deck. Your agent does the demo by actually using the
substrate while you watch.

## Setup — once, ~5 minutes total

You'll need:

- **Claude Code Desktop** installed (the Microsoft Store / macOS app). Cowork
  works for some things; this demo wants Desktop specifically.
- **A Google account** (for sign-in).
- **Python 3.10+** with `pip` (most macOS / Linux already have it; Windows: from <https://python.org>).
- **~5 minutes** of focus.

### Step 1 — Install the Ariadne Python client

```bash
pip install ariadne-core-client
```

That gives you a CLI called `ariadne` for authentication.

> If `pip install` doesn't find it, the package isn't on PyPI yet — fall back to:
> ```bash
> pip install git+https://github.com/denson/ariadne-core.git@main#subdirectory=client
> ```

### Step 2 — Sign in

```bash
ariadne login --host https://ariadne-core-production.up.railway.app
```

This opens your browser to an Auth0 sign-in page, asks for your Google
account, then captures the callback on a local loopback port. Your token
lands in your OS keyring (no plaintext credential files).

Verify with:
```bash
ariadne whoami
```

Expected: your email + a token expiry timestamp. If you see `Not authenticated`,
re-run `ariadne login`.

### Step 3 — Install the ariadne-core plugin in Claude Code Desktop

In Claude Code Desktop:

1. Open the plugins panel (sidebar → Plugins, or `/plugins` in the input).
2. Add the **ariadne-core** plugin from the marketplace.
3. Wait for the plugin to sync — it ships the skills you need.

Once the plugin is loaded, the **factory-demo-walkthrough** skill is available.

### Step 4 — Configure the MCP server (one-time)

The Ariadne CLI handles auth; the MCP server is what lets your Claude Code
agent actually call Ariadne. If you've already run the
`ariadne-core-install` skill, you've done this. If not:

1. In Claude Code Desktop, type: **`run ariadne-core-install`**
2. Follow the prompts. The skill writes a small MCP server config that points
   at the same host you logged into in Step 2.
3. Restart Claude Code Desktop so the MCP config takes effect.

After restart, type **`ariadne_search "test"`** in a fresh chat — if you get
search results back, your MCP is wired up. (If not, re-run the install skill
and check that your token in Step 2 is still valid: `ariadne whoami`.)

## Running the demo

Open a **fresh Claude Code Desktop session** in any directory (your home, a
scratch dir — anything that isn't an active project). Type:

> **factory demo**

That's it. Your agent will:

1. Verify your auth + access to the `aresense` corpus
2. Open with the cold-open scene: *"You just took over for Marcus. Standup
   in 5 minutes. Where do you want to start?"*
3. Walk you through 5 beats — root cause, dead ends, active threads,
   what's still open — using actual substrate retrievals you can see
4. Step into Ravi's voice for the simulated standup challenge
5. Score your answer against the corpus
6. Then open the floor — ask anything else; the substrate is live

Total runtime: ~5-7 minutes. You can interrupt any beat with your own
question; the agent will follow the thread, then offer to continue.

## What you're looking for (the substrate test)

After 5 minutes, the questions to ask yourself:

- Did the agent feel like it had **persistent memory** (the kind that survives
  session deaths)? Or did it feel like it was making things up?
- When you asked something off-script, did it admit absence cleanly, or
  did it hallucinate confidently?
- Could you imagine running an investigation **you actually run** through
  this kind of substrate? What's missing for your domain?
- What was the moment that *clicked* — if any?

The point isn't to praise the demo. The point is to find out whether this
substrate shape fits the work you do.

## When things go sideways

| Symptom | Fix |
|---|---|
| `ariadne login` says "Could not reach Auth0" | Network issue — try again; if persistent, your firewall may be blocking the loopback port (default ~8765). |
| `ariadne whoami` says "Not authenticated" | Token expired; re-run `ariadne login`. Tokens last ~20 hours. |
| `ariadne_search` returns 401 from inside Claude Code | MCP config has stale token. Run `ariadne login` again, then **restart Claude Code Desktop**. |
| Typing "factory demo" — agent has no idea what you mean | Plugin didn't sync the new skill, or the wrong plugin is installed. Force-refresh `ariadne-core` plugin, or restart Claude Code Desktop. |
| Agent recites instead of retrieving | The MCP isn't actually being called. Ask the agent: *"are you retrieving from Ariadne or making this up?"* If it admits it's guessing, MCP config is wrong. |

## What's fictional, what's real

- **Fictional:** ARESense Technologies, the cast (Marcus Chen, Priya Iyer,
  Lim Boon-Hwa, etc.), the suppliers (PIP / Drysdale / Yamashiro / …), the
  6-month investigation. None of it happened.
- **Real:** the substrate architecture (`bw` + Ariadne pgvector + planned
  hypergraph + meta-agent projection), the auth flow, the actual retrievals
  your agent does. The thing you're evaluating is the architecture, not the
  company.

## Feedback

After your run, what surfaced? Honest feedback — including "this was
underwhelming and here's why" — is the most useful thing you can give back.

---

Authored by Denson Smith. The substrate identity (agent memory infrastructure
that outlives its author) is what the demo is built to show. The
factory-handoff frame is the felt version of that — Marcus is gone; the
substrate remains.
