# Changelog — ariadne-core-client

All notable changes to this package. Dates are UTC.

## [Unreleased]

### Changed (BREAKING)

- **Constructor signature.** `AriadneClient.__init__` no longer accepts
  `url=` or `api_key=`. The new signature is
  `AriadneClient(host=None, *, agent_type=None, initiated_by=None, model=None, timeout=60)`.
  Passing a value to `host=` wins; otherwise the resolution chain is
  `ARIADNE_HOST` env var → `~/.config/ariadne/default` (written by
  `ariadne login`) → `AriadneAuthError`. Migration:

    ```python
    # Before (0.1.0-legacy):
    client = AriadneClient(url="https://...", api_key="ak-...")

    # After:
    # 1) Run ``ariadne login --host https://...`` once.
    # 2) Construct with no args, or pass host= explicitly:
    client = AriadneClient()
    # or
    client = AriadneClient(host="https://...")
    ```

- **Authentication.** The client now issues
  `Authorization: Bearer <jwt>` on every request. The Bearer token is
  minted by `auth.get_access_token(host)` — proactive refresh from the
  cached refresh token, or the `ARIADNE_ACCESS_TOKEN` env var as an
  always-first escape hatch. The legacy `X-API-Key` header is not sent
  for any reason; the server-side middleware was removed in Pass 2 of
  the `ariadne--xft` epic and sending `X-API-Key` now just returns 401.

- **Fail-closed posture.** On token-acquisition failure
  (missing refresh token, refresh rejected by Auth0, keyring
  unreachable, etc.) the client raises `AriadneAuthError` **without
  issuing any HTTP request**. There is no unauthenticated fallback and
  no silent downgrade.

- **Removed `credentials.py`.** The `resolve_credentials()` helper and
  its `.env` / `.mcp.json` scanning path were entirely superseded by
  `auth.resolve_host()` + `auth.get_access_token()`. Importing
  `ariadne_core_client.credentials` now raises `ImportError`.

- **Removed env-template entries.** `ARIADNE_URL` and `ARIADNE_API_KEY`
  were removed from the `ariadne setup` .env template. The template
  now points at `ariadne login` and mentions `ARIADNE_HOST` /
  `ARIADNE_ACCESS_TOKEN` as optional overrides.

### Added

- **`--host` flag on every data-plane CLI subcommand** (`health`,
  `stats`, `list-collections`, `list-documents`, `search`, `ingest`).
  Matches the existing precedence: `--host` > `ARIADNE_HOST` >
  `~/.config/ariadne/default`.

- **`id_token` keyring slot.** `ariadne login` now persists the OIDC
  id_token alongside the refresh/access/expiry slots. `whoami` prefers
  the id_token for email display (it carries the OIDC `email` claim
  that Auth0 access tokens omit by default) while continuing to use
  the access_token as the authoritative source for the Bearer header
  and for expiry checks. `ariadne logout` clears the id_token slot too.

### Note for maintainers

The id_token is **display-only**. Do NOT generalize
`decode_jwt_unverified(id_token)` to replace the access_token at other
call-sites. Access tokens remain the authority for
`Authorization: Bearer` and for expiry; id_tokens are a separate OIDC
identity bundle. See the docstring on `auth.whoami` for the full
non-swap notice, and `TestWhoamiSyntheticJwt` for the regression
variants that lock this behavior.

## [xft.5.3] — Claude Code MCP `headersHelper` reads the keyring

`scripts/mcp_auth.py` (the Claude Code MCP `headersHelper` script) is
now wired to the same `auth.get_access_token(host)` path the rest of
the client uses. After a one-time `ariadne login`, Claude Code talks
to Ariadne over MCP without ever prompting the user for a JWT.

### Changed (BREAKING — operator-visible)

- **`scripts/mcp_auth.py` no longer emits `{}` on a missing
  credential.** The legacy fail-OPEN shape (`exit 1` + stdout `{}`,
  inherited from the X-API-Key era) is removed. On any
  auth-acquisition failure (no keyring entry, refresh rejected, host
  unresolvable, keyring backend broken without the env-var hatch),
  the script now exits `2` with empty stdout and a single
  human-readable diagnostic on stderr that names the user action
  (typically "run `ariadne login --host <url>`"). Operators who
  relied on the silent-skip behavior to bypass auth on a
  locally-running server with auth disabled must either set
  `ARIADNE_ACCESS_TOKEN` in the environment, or remove the
  `headersHelper` entry from `.mcp.json` for that local server.
- **`scripts/mcp_auth.py` no longer reads `.env`.** The legacy
  `find_env_file` / `read_token` helpers (which scanned for `.env`
  in cwd and three parents and pulled `ARIADNE_ACCESS_TOKEN` out of
  it) are gone. Resolution is now: `ARIADNE_ACCESS_TOKEN` env var
  (always-first hatch) > OS keyring (populated by `ariadne login`).

### Added

- `client/tests/test_mcp_auth.py` — hermetic CI test that invokes
  `scripts/mcp_auth.py` as a subprocess, locks the JSON wire-shape
  contract, asserts no token leaks to stderr, and exercises the
  fail-closed and broken-keyring paths via a stub `keyring` package
  on `PYTHONPATH`.
- `docs/smoke/xft5c_smoke.md` — operator-facing manual smoke script
  for the end-to-end Claude Code path: `ariadne login` → `.mcp.json`
  edit → restart → tool call works without JWT paste → `ariadne
  logout` produces an actionable error on the next call.
