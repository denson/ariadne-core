# tests/ — running and writing test suites

This directory holds the server-side test suite. The client-side tests
live under [`client/tests/`](../client/tests/) and the verification
probes that pin per-ticket behavior live under
[`tests/verification/`](./verification/).

## Running tests

The server and client suites have **inconsistent** invocation idioms.
This is intentional pending a future refactor (see ariadne--nud §1);
the document below names the inconsistency so a contributor running
across both surfaces does not have to rediscover it.

### Server tests

```bash
# from the repo root
PYTHONPATH=src pytest tests/
```

The `pipeline` package is not editable-installed; `PYTHONPATH=src`
makes it importable. Verification probes under `tests/verification/`
also need this — they import `from pipeline...` exactly like the
top-level server tests.

### Client tests

```bash
cd client
PYTHONPATH=src pytest tests/
# (or with editable install: pip install -e ., then `pytest tests/`)
```

The client uses `pyproject.toml`'s `testpaths = ["tests"]` discovery
and expects `ariadne_core_client` to be importable. `PYTHONPATH=src`
satisfies that without an editable install; for repeated work,
`pip install -e client/` is the cleaner path.

### Why the inconsistency

The server is checked-in as a Python package layout under `src/`
without an editable install in CI; the client has an editable-install
contract because external consumers `pip install` it. Aligning the
two — likely by editable-installing the server too — is filed as
ariadne--nud §1; it is non-blocking and not part of this bundle.

## Writing tests — conftest.py imports vs fixtures

Two patterns appear in this codebase. Use this rule to pick:

* **Fixtures (`@pytest.fixture`)** — when the helper has *side
  effects* (monkeypatch, env-var manipulation, network capture,
  database state mutation, autouse setup/teardown). Pytest's fixture
  machinery handles the scope-and-yield lifecycle, including cleanup
  on test failure.

* **Module-level imports (plain functions / classes)** — when the
  helper is *pure*: a factory that returns a value, a constant, a
  builder that takes the test's `monkeypatch` as an argument and lets
  the test drive the side effects.

Examples in this codebase:

| Helper                                         | Pattern  | Why                                                                    |
|------------------------------------------------|----------|------------------------------------------------------------------------|
| `tests/conftest.py::pg_dedup_store`            | Fixture  | Allocates a session pool; teardown purges test collections.            |
| `tests/conftest.py::override_auth(app)`        | Function | Pure: takes an app, registers a dependency override on it; no state.   |
| `tests/conftest.py::_confirmation_secret_isolation` | Autouse fixture | Save/restore the per-process HMAC secret around each test. |
| `tests/verification/_shared.py::FIXTURE_TXT`   | Constant | A path. No state, no setup.                                            |
| `tests/verification/_shared.py::install_clean_state(monkeypatch)` | Function | Side-effecting, but the side effects are bound to the *caller's* `monkeypatch`. Each probe drives its own monkeypatch (often patching additional symbols in the same call site), so a fixture would force a particular shape unnecessarily. |
| `client/tests/conftest.py::captured_http`      | Fixture  | Monkeypatches `_http` module attrs; cleanup at fixture teardown.       |
| `client/tests/conftest.py::_confirm_required_body` | Function | Pure factory returning a dict — no I/O, no monkeypatch.            |

When in doubt, lean toward **function**. A function the test imports
and calls is harder to misuse than a fixture whose lifecycle the
caller has to reason about. Promote to fixture only when the helper
genuinely needs setup-and-teardown around the test body.

## Verification probes

Per-ticket probes that pin a specific behavior or contract live under
`tests/verification/<ticket-id>/`. Shared scaffolding (TestClient
wiring, in-memory dedup store, mock extractor) lives in
[`tests/verification/_shared.py`](./verification/_shared.py); each
ticket dir imports from there. Per-ticket-specific helpers stay in
the ticket's directory.

Probe directories do not have `__init__.py`; pytest discovers them
via rootdir auto-discovery. The shared module is imported as
`from tests.verification._shared import ...` which works because
PYTHONPATH=src puts `tests` on `sys.path` via the parent rootdir.
