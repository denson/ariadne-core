# PLAYBOOK — Destructive Deploys on Railway

When a pass requires wiping the live Postgres schema (consolidated
migrations, column drops, anything not backward-compatible with the
existing DB), follow this playbook verbatim. Previous passes have
burned recovery round-trips by mis-ordering these steps.

This supersedes any ad-hoc `railway run psql` or `railway redeploy`
instructions in older spec files. Future specs should reference this
file by name instead of re-inventing the sequence.

**Live server:** `https://ariadne-core-production-579a.up.railway.app`
**Postgres service name on Railway:** `pgvector`
**App service name on Railway:** `ariadne-core`

---

## Why this playbook exists

Two facts about this specific Railway project make the "obvious"
commands fail:

1. **The `pgvector` service has no public TCP proxy.** The app gets
   at Postgres via `DATABASE_URL_PRIVATE`, which points at
   `pgvector.railway.internal`. `railway run psql "$DATABASE_URL"`
   runs `psql` on your **local** machine with the env injected, so
   it tries to connect to an internal-only hostname and hangs or
   errors. `railway connect pgvector` also doesn't work — the CLI's
   `connect` subcommand only recognizes a short allowlist of
   database service names and `pgvector` isn't on it.

2. **`railway redeploy` replays the latest deployment's commit, not
   `origin/main` HEAD.** If GitHub auto-deploy didn't fire for the
   commit you just pushed (which happens regularly on this project —
   see BL-9), `redeploy` rebuilds the previous image against the
   wiped schema. The stale image's migration runner then writes its
   migration versions into the fresh `schema_migrations` table, and
   when you finally get the target image running, its runner sees
   those versions as "already applied" and skips the new
   consolidated migration. The app then boots against a schema
   missing its expected columns.

The sequence below avoids both traps.

---

## Sequence

### Step 1 — Confirm you're at the right commit, on the right project

```
cd ariadne-core
git status --short              # should be clean
git rev-parse HEAD              # record this — it's the target SHA
git rev-parse origin/main       # must equal HEAD

railway status                  # confirm linked to the right project + env
```

If `HEAD != origin/main`, push first. If `railway status` shows the
wrong project, `railway link` it to the right one. Do not proceed
until both are clean.

### Step 2 — Wipe the Postgres schema

This is a `railway ssh` into the Postgres service, running `psql`
from inside the container where the local socket and env are set up.
The entire `psql` invocation is passed as **one argv item** so
Railway's SSH transport doesn't space-join it and strip the inner
quoting.

```
railway ssh --service pgvector "psql -U postgres -d railway -v ON_ERROR_STOP=1 --pset pager=off -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public; CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;'"
```

Expected output:

```
NOTICE:  drop cascades to N other objects
DROP SCHEMA
CREATE SCHEMA
CREATE EXTENSION
CREATE EXTENSION
```

`N` should match the count of tables + extensions in the current
schema. At the time of writing, a populated Ariadne schema has 8
tables (`collections`, `documents`, `document_interactions`,
`chunks`, `jobs`, `api_keys`, `search_log`, `schema_migrations`)
plus the two extensions for 10 objects.

If you see anything other than the four success lines above, **stop
and investigate** — do not proceed to the deploy step.

### Step 3 — Deploy the target commit

**Do not use `railway redeploy` yet.** Use `railway up` from a clean
worktree at the target SHA. `railway up` uploads the local source
tree and builds a fresh deployment from it, so it's guaranteed to
reflect your HEAD commit regardless of whether GitHub auto-deploy
fired.

```
# from the ariadne-core root, with HEAD at the target SHA
railway up --service ariadne-core
```

This starts a new deployment. Watch the output for the deployment
id (`e7a9b...` etc.) — save it, you'll want it for the log tail.

Alternatively, in the Railway dashboard: click the service →
"Deployments" tab → "Deploy from latest commit" button. That button
deploys `origin/main` HEAD, which is equivalent to `railway up` from
a clean tree if your local HEAD matches `origin/main`.

### Step 4 — Watch the boot logs

Railway streams logs in near-real-time:

```
railway logs --service ariadne-core
```

You are looking for, in order:

```
ariadne.stores INFO Initializing Postgres stores (backend=pgvector)
ariadne.stores INFO Creating connection pool for postgres://postgres:***@pgvector.railway.internal:5432/railway
ariadne.stores INFO Applying migration 001_initial.sql       ← per-migration line
ariadne.stores INFO Migrations applied: 1 file(s): 001_initial.sql   ← post-loop summary, easier to catch in a tail
ariadne.schema INFO Schema OK: chunks table exists with vector(1536)
ariadne.app    INFO Stores initialized (backend=pgvector)
INFO:          Application startup complete.
INFO:          Uvicorn running on http://0.0.0.0:8080
```

The summary line (`Migrations applied: ...`) was added specifically
so post-wipe boots have a single grep-able confirmation that doesn't
depend on catching the per-migration line in a narrow tail window.
If **both** the per-migration line and the summary line are missing
on a post-wipe boot, something is wrong. The DB state is the
authoritative answer — verify it in Step 5 regardless, but record
the missing-lines observation and investigate before closing the
pass.

### Step 5 — Verify DB state

```
railway ssh --service pgvector "psql -U postgres -d railway --pset pager=off -c 'SELECT version FROM schema_migrations ORDER BY version;'"
```

On a successful wipe + target deploy, this should return exactly
one row with the version string matching the consolidated migration
file in the target commit (e.g. `001_initial.sql`).

If multiple rows come back on a wipe scenario, an earlier deploy
wrote stale versions before the target image booted — roll back
(repeat steps 2-4) before smoking.

Also spot-check a couple of the schema changes the pass was meant
to introduce, e.g.:

```
railway ssh --service pgvector "psql -U postgres -d railway --pset pager=off -c 'SELECT column_name FROM information_schema.columns WHERE table_name=''documents'' ORDER BY column_name;'"
```

Columns should match the consolidated `001_initial.sql` in the
target commit.

### Step 6 — Smoke the live endpoints

Follow the Bob-smoke list from the relevant DAVE_* spec. At minimum:

- `GET /api/health` returns 200 and correct version
- `GET /api/documents/schema` returns the expected filter/include
  surface
- One ingest round-trip against a scratch collection that exercises
  whatever the pass was meant to change

---

## Recovery: you ran `redeploy` instead of `up` and got a stale image

Symptom: boot logs show the previous pass's migrations applying
(e.g. `002_add_agent_notes.sql` appears on a post-wipe boot that
should only apply the consolidated `001_initial.sql`), or
`schema_migrations` has multiple rows after a wipe.

Recovery: repeat the wipe, then `railway up` from a clean worktree
at the target SHA, then verify. There is no safe shortcut — the
wipe has to be redone because the stale image mutated the fresh DB.

---

## When the playbook does not apply

Non-destructive deploys (adding a column with a default, adding a
new migration on top of existing ones) do not require a wipe. Just
push, wait for auto-deploy (or trigger a manual one), and smoke.
This playbook is only for passes where the target schema is
incompatible with the pre-existing DB state.
