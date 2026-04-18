# Fix: Setup script writes .env to wrong directory

## The problem

The setup script writes `.env` inside the cloned `ariadne-core/` repo. It writes `.mcp.json` to the project root (parent of the repo). The `.mcp.json` uses `${ARIADNE_API_KEY}` which Claude Code resolves from environment variables — but the `.env` with the actual key is one directory down inside the repo. Claude Code can't find it.

The user has to manually copy keys between directories. This defeats the entire purpose of an automated setup script.

## The fix

The setup script must write BOTH `.env` and `.mcp.json` to the same directory — the project root (parent of the cloned repo).

### Where to change

**File:** `scripts/setup.py`

1. Find where `env_path` is defined. It currently points to the repo directory (where `setup.py` lives). Change it to point to the project root:

```python
script_dir = Path(__file__).resolve().parent  # scripts/
repo_dir = script_dir.parent                   # ariadne-core/
project_dir = repo_dir.parent                  # the user's project root
env_path = project_dir / ".env"
```

2. This must match the MCP config path (already fixed in Step 10 to use `project_dir`).

3. The `.env` should still be gitignored — but since it's now OUTSIDE the repo, git won't see it anyway. No gitignore change needed.

4. Update any message that tells the user where `.env` was written to show the correct path.

5. The `.env.example` stays inside the repo (it's a template). The generated `.env` goes to the project root.

6. When the script detects an existing `.env` at startup, it should check the project root first, then fall back to the repo directory for backward compatibility with existing installs.

## Verify

After the fix, running `python scripts/setup.py` from inside `ariadne-core/` should produce:

```
D:\video_projects\world_bank_project_reports\
├── .env                    ← API keys live here
├── .mcp.json               ← references ${ARIADNE_API_KEY} from .env above
└── ariadne-core/           ← the cloned repo (no secrets in here)
    ├── scripts/setup.py
    ├── .env.example         ← template only
    └── ...
```

Claude Code, started from `D:\video_projects\world_bank_project_reports\`, loads `.mcp.json`, resolves `${ARIADNE_API_KEY}` from the `.env` in the same directory, and connects.

## Do not touch

- Anything in `src/pipeline/`
- SPEC.md, skills, docs

## Do not commit

Report when done. Leave for Bob.
