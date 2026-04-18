# Add .env.example to repo + `ariadne setup` CLI subcommand

**For:** Dave  
**Context:** The client package resolves credentials from `.env` files, but there's no `.env.example` in the repo and no easy way to create one. The workspace has a `.env.example` at `C:\Users\denso\claude_projects\ariadne-core-workspace\.env.example` — that's the canonical template. We need to ship it in the repo and add a CLI subcommand that helps users create their `.env`.

---

## Step 1: Add `.env.example` to repo root

**File:** `ariadne-core/.env.example`

Copy the content exactly from the workspace `.env.example` (`C:\Users\denso\claude_projects\ariadne-core-workspace\.env.example`). Do not change any variable names or values.

---

## Step 2: Add `ariadne setup` CLI subcommand

**File:** `client/src/ariadne_core_client/cli.py`

Add a new `setup` subcommand that:

1. Looks for `.env.example` — first in the current directory, then walks up parent directories (same pattern as `credentials.py` walk-up). If not found, uses a built-in minimal template with just the two client vars.
2. If `.env` already exists in the current directory, warns and asks whether to overwrite (print a message and exit — the CLI is non-interactive, so it should NOT overwrite without an explicit `--force` flag).
3. Copies `.env.example` → `.env` in the current directory.
4. Prints what was created and reminds the user to fill in the `<your ... here>` placeholder values.

**Built-in template** (used when no `.env.example` is found nearby — this is the same content as the repo's `.env.example`):

```
# Database (local development only -- for docker compose)
# Railway users: skip this. Railway injects DATABASE_URL automatically.
DB_PASSWORD=local-dev-only

# --- Embedding Provider ---
ARIADNE_EMBEDDING_API_KEY=<your api key here>
ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
ARIADNE_EMBEDDING_DIMENSIONS=1536

# --- Vision Provider (for image descriptions in documents) ---
ARIADNE_IMAGE_ENRICHMENT_API_KEY=<your api key here>
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-3.1-flash-lite-preview
ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/

# --- Client Authentication ---
# Auto-generated. Clients connect with this key via X-API-Key header.
ARIADNE_API_KEY=<your api key here>


# --- Railway Deployment ---
ARIADNE_URL=https://your-deployment.up.railway.app
```

### Parser addition

In `_build_parser()`, add:

```python
# setup
p_setup = sub.add_parser(
    "setup",
    help="Create a .env file from .env.example template.",
    description=(
        "Creates a .env file in the current directory from the nearest "
        ".env.example template. Edit the file to fill in your credentials."
    ),
)
p_setup.add_argument(
    "--force",
    action="store_true",
    help="Overwrite existing .env file.",
)
p_setup.set_defaults(func=_cmd_setup)
```

### Module-level constant

Add a `_ENV_TEMPLATE` string constant near the top of `cli.py` (after imports, before the helper functions). This is the full `.env` template that ships with the pip package — identical to the repo's `.env.example`:

```python
_ENV_TEMPLATE = """\
# Database (local development only -- for docker compose)
# Railway users: skip this. Railway injects DATABASE_URL automatically.
DB_PASSWORD=local-dev-only

# --- Embedding Provider ---
ARIADNE_EMBEDDING_API_KEY=<your api key here>
ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
ARIADNE_EMBEDDING_DIMENSIONS=1536

# --- Vision Provider (for image descriptions in documents) ---
ARIADNE_IMAGE_ENRICHMENT_API_KEY=<your api key here>
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-3.1-flash-lite-preview
ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/

# --- Client Authentication ---
# Auto-generated. Clients connect with this key via X-API-Key header.
ARIADNE_API_KEY=<your api key here>


# --- Railway Deployment ---
ARIADNE_URL=https://your-deployment.up.railway.app
"""
```

### Implementation

```python
def _cmd_setup(args: argparse.Namespace) -> int:
    env_path = Path(".env")

    if env_path.exists() and not args.force:
        print(f".env already exists at {env_path.resolve()}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        return 1

    # Walk up looking for .env.example
    example_path = None
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        check = candidate / ".env.example"
        if check.is_file():
            example_path = check
            break

    if example_path:
        content = example_path.read_text(encoding="utf-8")
        print(f"Using template: {example_path}")
    else:
        content = _ENV_TEMPLATE
        print("No .env.example found — using built-in template.")

    env_path.write_text(content, encoding="utf-8")
    print(f"Created {env_path.resolve()}")
    print("Edit the file to fill in your credentials (look for placeholder values).")
    return 0
```

Note: `_cmd_setup` does NOT instantiate `AriadneClient()` — it runs before credentials exist. This is important — every other subcommand creates a client, but setup must not.

### Update module docstring

Add `setup` to the subcommand list at the top of the file:

```
- ``ariadne setup``                — Create .env from template.
```

---

## Step 3: Update the doc-intelligence skill

**File:** `skills/ariadne-document-intelligence/SKILL.md`

In the "Before using this skill — check connection" section (around line 29-48), add a paragraph after the resolution order list:

```markdown
If no credentials are configured yet, the client CLI can create a `.env` from the
project's `.env.example` template:

\`\`\`bash
ariadne setup
\`\`\`

This copies `.env.example` to `.env` in the current directory. Edit it to fill in
your `ARIADNE_URL` and `ARIADNE_API_KEY`. The full `.env.example` also includes
server-side configuration (embedding provider, vision provider, database) for
users running their own Ariadne Core deployment.
```

---

## Verify

```bash
# CLI should show setup in help
ariadne --help

# Setup help
ariadne setup --help

# Dry run (from a temp dir with no .env)
cd /tmp && ariadne setup && cat .env && rm .env
```

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`.
