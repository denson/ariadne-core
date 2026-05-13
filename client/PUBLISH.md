# Publishing `ariadne-core-client` to PyPI

One-page reference for publishing the Python client to PyPI so invitees can
`pip install ariadne-core-client` without ugly git-install strings.

## One-time setup (skip if already done)

1. **Create a PyPI account** at <https://pypi.org/account/register/> if you don't have one.

2. **Verify your email** on PyPI (required before first publish).

3. **Enable 2FA** on the account (PyPI requires this for publishing as of 2024).

4. **Create an API token** scoped to either "Entire account" or "Specific project: ariadne-core-client":
   <https://pypi.org/manage/account/token/>

5. **Configure twine credentials.** Either:
   - `pip install twine keyring` and run `keyring set https://upload.pypi.org/legacy/ __token__` (paste the token when prompted), OR
   - Create `~/.pypirc` with:
     ```ini
     [pypi]
       username = __token__
       password = pypi-<your-token-here>
     ```
     (chmod 600 if on a unix-y filesystem)

6. **Install the build toolchain** (one-time):
   ```bash
   pip install --upgrade build twine
   ```

## Pre-publish checks (every release)

From `ariadne-core/client/`:

1. **Bump version** in `pyproject.toml` (`version = "0.1.0"` → next).
2. **Update CHANGELOG** if one exists (or add a one-line note in the PR description).
3. **Run the test suite** from `ariadne-core/src/`:
   ```bash
   cd ../src && python -m pytest -q
   ```
4. **Smoke-build locally** to catch packaging errors:
   ```bash
   cd ../client && rm -rf dist/ build/ *.egg-info
   python -m build
   ls dist/   # expect: ariadne_core_client-X.Y.Z-py3-none-any.whl + .tar.gz
   ```

## Publish

### Option A: test on TestPyPI first (recommended for the very first publish)

```bash
cd ariadne-core/client
python -m build
twine upload --repository testpypi dist/*
```

Then on a clean Python env:
```bash
pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  ariadne-core-client
ariadne --help
```

If that works, proceed to real PyPI.

### Option B: publish to real PyPI

```bash
cd ariadne-core/client
rm -rf dist/ build/ *.egg-info   # always start clean
python -m build
twine check dist/*               # validates the wheel/sdist; should say PASSED
twine upload dist/*
```

Within ~60 seconds, `pip install ariadne-core-client` will work for anyone.

## Verification

From any machine with Python:
```bash
pip install --upgrade ariadne-core-client
ariadne --help
ariadne login --host https://ariadne-core-production.up.railway.app
ariadne whoami
```

If `ariadne whoami` shows your identity, the published package works end-to-end.

## Rollback / yank

If a release has a defect:
```bash
# Bump version + republish is the right fix in 99% of cases.
# If a release is actively harmful (security, secret leak), yank it:
twine yank ariadne-core-client X.Y.Z --reason "<short reason>"
```
Yanking hides the version from `pip install ariadne-core-client` (no version pin)
but doesn't delete it — existing pins still install.

## Why this lives in `client/` and not in the repo root

The `client/` directory is its own Python project (separate `pyproject.toml` from
`src/`). The `src/` package is the FastAPI server — it doesn't go to PyPI. This
file documents only the client publish flow; the server is deployed via Railway
(see `skills/ariadne-core-deploy/` for that path).
