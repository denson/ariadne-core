# Fix Railway crash: missing python-multipart dependency

**For:** Dave  
**Context:** When we removed `mcp>=1.0.0` from `src/pyproject.toml` (MCP removal step 5), we lost `python-multipart` — it was a transitive dependency of `mcp` that FastAPI needs for file upload endpoints. Railway is crash-looping with `RuntimeError: Form data requires "python-multipart" to be installed`.

---

## Step 1: Add python-multipart to dependencies

**File:** `src/pyproject.toml`

Add `"python-multipart>=0.0.5"` to the `dependencies` list. It should go after the FastAPI line since it's a FastAPI companion package.

The dependencies block should look like:

```toml
dependencies = [
    "markitdown[all]>=0.1.0",
    "pydantic>=2.0",
    "fastapi>=0.115.0",
    "python-multipart>=0.0.5",
    "uvicorn[standard]>=0.30.0",
    "pyyaml>=6.0",
    "psycopg[binary]>=3.1",
    "psycopg_pool>=3.1",
]
```

That's the only change. One line added.

---

## Step 2: Verify locally

```bash
cd ariadne-core
pip install -e src/
python -c "import multipart; print('python-multipart OK')"
python -c "from pipeline.api.routes import router; print('routes import OK')"
```

All three should succeed.

---

## Do not commit — leave for Bob.

Write completion to `DAVE_DONE.md`.
