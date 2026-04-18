# Fix: Remove backward compatibility branch for .env location

## The problem

The setup script has a legacy branch that keeps using an existing `.env` inside the `ariadne-core/` repo directory. This causes `.env` and `.mcp.json` to be in different directories, breaking the `${ARIADNE_API_KEY}` reference.

We have zero users. There is no one to be backward compatible with.

## What to do

**File:** `scripts/setup.py`

Remove the entire backward compatibility branch. The `.env` ALWAYS goes to the project root (parent of the repo). No fallback, no legacy detection, no "existing .env inside repo" path.

If there's an old `.env` inside the repo, ignore it. The script writes a fresh one to the project root every time.

Find and remove:
- Any `legacy_env_path` variable
- Any `if legacy_env_path.exists()` branch
- The "Using existing .env inside repo" message
- Any logic that chooses between repo dir and project root for `.env`

The `.env` path should just be:
```python
project_dir = Path(__file__).resolve().parent.parent.parent
env_path = project_dir / ".env"
```

No conditionals. No fallback.

## Do not commit

Report when done. Leave for Bob.
