# xft.5.3 — manual smoke: keyring-backed Claude Code MCP auth

This is the human-executable end-to-end smoke for the Pass 3 closer
(ticket `ariadne--xft.5.3`). It proves the user-story payoff: after a
single `ariadne login`, Claude Code can call Ariadne MCP tools without
the user ever seeing a JWT.

**Time:** ~10 minutes. **Where:** Denson's primary workstation.
**Pre-reqs:** `client/` editable-installed (`pip install -e client/`),
Auth0 tenant reachable, deployed Ariadne server reachable.

The OS keyring used is whichever the running OS provides: Windows
Credential Manager on Windows, macOS Keychain on macOS, Secret Service
(GNOME Keyring / KWallet) on Linux. No code-path differences.

---

## Step 1 — `ariadne login`

```
ariadne login --host https://ariadne-core-production.up.railway.app
```

(Substitute your production host URL if different.)

**Expected:**

- The default browser opens to an Auth0 sign-in page.
- After authenticating, the browser shows a "Sign-in succeeded. You can
  close this window and return to your terminal." page.
- The terminal prints something like:

      Signed in to https://ariadne-core-production.up.railway.app
      User:    denson@... (auth0|...)
      Default host saved to ~/.config/ariadne/default

**If this fails:**

- Browser doesn't open → copy the URL the CLI prints and paste into a
  browser manually.
- "Login timed out" → re-run; Auth0 was slow.
- "Discovery payload missing fields" → server isn't running or
  `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_AUDIENCE` aren't set on
  the deployed server. Check Railway env vars.

## Step 2 — `ariadne whoami`

```
ariadne whoami
```

**Expected:** three lines, the email matches the Auth0 identity from
step 1, and the expiry is in the future:

    Host:    https://ariadne-core-production.up.railway.app
    User:    denson@... (auth0|...)
    Expires: 2026-05-04 ... UTC (X hours from now)

**If this fails:**

- "Not logged in to ..." → step 1 didn't actually persist; re-check
  step 1's output for a stored-token message and re-run if needed.
- Email shows `(unknown)` → the Auth0 application is missing the
  `email` scope or `openid profile email` scopes are not in the
  discovery `scope` field. Check
  `GET /.well-known/ariadne-config` directly:

      curl -s https://ariadne-core-production.up.railway.app/.well-known/ariadne-config | jq

## Step 3 — point Claude Code at Ariadne via MCP

Edit your project's `.mcp.json` (in the directory you launch Claude Code
from; not the `ariadne-core` repo's own `.mcp.json` unless you ARE
working inside it). Add or replace the Ariadne entry:

```json
{
  "mcpServers": {
    "ariadne": {
      "type": "http",
      "url": "https://ariadne-core-production.up.railway.app/mcp",
      "headersHelper": "python ariadne-core/scripts/mcp_auth.py"
    }
  }
}
```

The path in `headersHelper` is relative to the directory you start
Claude Code from. If your repo layout differs, adjust accordingly. On
Windows, `python` resolves through PATH; if you've installed Python
via the Microsoft Store and `python` resolves to a stub, use the
absolute path to your CPython interpreter.

**No `ARIADNE_API_KEY`, no `ARIADNE_ACCESS_TOKEN`, no `headers` block.**
The keyring is the single source of truth.

## Step 4 — restart Claude Code; check MCP handshake

Quit and re-launch Claude Code Desktop (so it re-reads `.mcp.json`).

In a new conversation, run:

```
/mcp
```

**Expected:** `ariadne` appears in the connected-servers list. No
prompt asking for a JWT, no input dialog, no error toast.

**If this fails:**

- `ariadne` shows as failed → `mcp_auth.py` exited non-zero. Check
  Claude Code's MCP logs (the location depends on platform; on
  Windows MSIX install it's under
  `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\logs\`).
  Look for the stderr line from `mcp_auth.py`. Most likely cause:
  the script can't import `ariadne_core_client` because
  `pip install -e client/` was never run; fix that and reload.
- `ariadne` is absent from the list → the `.mcp.json` entry is
  malformed or the file isn't where Claude Code expected it. Check
  the JSON parses with `python -m json.tool < .mcp.json`.

## Step 5 — invoke an Ariadne tool from Claude Code

In the chat, type something that requires the Ariadne tool. Example:

> List the documents in my default Ariadne collection.

**Expected:** Claude Code calls the Ariadne MCP `list_documents` tool,
the call succeeds, and you see the response materialized inline. **At
no point are you asked to paste a JWT.**

**If this fails:**

- Tool call returns `401 missing_token` → `headersHelper` ran but its
  output wasn't picked up. Verify the script's stdout is well-formed
  JSON by running it directly:

      python ariadne-core/scripts/mcp_auth.py
      # expected: {"Authorization": "Bearer eyJ..."}

- Tool call returns `401 invalid_signature` or `wrong_audience` → the
  token is valid but signed for a different Auth0 tenant / audience.
  Confirm the deployed server's `AUTH0_DOMAIN` and `AUTH0_AUDIENCE`
  match the tenant your `ariadne login` used.
- Tool call returns `401 expired_token` and persists across retries →
  proactive refresh isn't kicking in. Run `ariadne whoami`; if the
  token shows EXPIRED there's a refresh-flow bug worth filing
  separately.

## Step 6 — `ariadne logout`, expect a clean break

```
ariadne logout
```

**Expected:** "Signed out of <host>." printed.

Without restarting Claude Code, ask it to call another Ariadne tool.

**Expected:** the tool call **fails** with an actionable error from
`mcp_auth.py` — visible in Claude Code's MCP error UI as something
like:

    ariadne mcp_auth: Not logged in to https://ariadne-core-production.up.railway.app.
        Run:
            ariadne login --host https://ariadne-core-production.up.railway.app

The exit code from `mcp_auth.py` is `2`; Claude Code surfaces this as a
header-helper failure rather than re-using stale headers. If Claude
Code instead silently sends the request unauthenticated and surfaces a
bare `401 missing_token` from the server with no hint, that's a
**regression** — `mcp_auth.py` should fail before any HTTP request is
made. File a ticket.

**If this fails:**

- "Signed out" prints but Claude Code keeps working → MCP keeps the
  connection open and the headers are cached by the transport. Quit
  Claude Code and re-launch; the next `headersHelper` call will fail
  closed.

## Step 7 — re-login restores the path

```
ariadne login --host https://ariadne-core-production.up.railway.app
```

After Claude Code's next MCP call (you may need to restart Claude Code
to drop the cached failure state), tool calls work again.

**Expected:** clean recovery; same flow as step 1, no special handling
needed.

---

## Pass criteria

| # | Behavior | Pass |
|---|----------|------|
| 1 | `ariadne login` opens browser, completes, prints success | ☐ |
| 2 | `ariadne whoami` shows correct email + future expiry | ☐ |
| 3 | `.mcp.json` has `headersHelper`, no `headers`, no key/token | ☐ |
| 4 | `/mcp` lists `ariadne` as connected after restart | ☐ |
| 5 | A tool call from chat succeeds with no JWT prompt | ☐ |
| 6 | `ariadne logout` produces an actionable error on next call | ☐ |
| 7 | Re-login restores the working state | ☐ |

If all seven pass, Pass 3 of the OAuth migration is closed. Pass 4
(running this against Denson's actual production Ariadne) is a
separate ticket.

## Out-of-band failure modes worth watching

These shouldn't happen but are worth a glance:

- A token value (the JWT itself) appearing anywhere in Claude Code's
  MCP logs, in `ariadne` CLI output, or in any other process's stderr.
  The contract is: tokens live in the keyring + the JSON payload on
  stdout from `mcp_auth.py`, nowhere else. The hermetic CI test
  `test_token_never_appears_in_stderr_on_success` enforces one
  channel; a manual eyeball on the MCP log catches the rest.
- A scheduled task / launchd / systemd service running `ariadne` and
  failing the keyring read (the daemon has no interactive user
  session; `ARIADNE_ACCESS_TOKEN` is the documented hatch). This is
  the Pass 5 ticket's territory — see the parent epic
  `ariadne--xft.5`. If you encounter it during step 5 while running
  interactively, file separately.
