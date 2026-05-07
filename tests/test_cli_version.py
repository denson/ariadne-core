"""ariadne--4d1: --version flag on the CLI entry point.

Pins three properties:
  1. ``python -m pipeline --version`` exits 0.
  2. Stdout contains the distribution name and the version reported by
     ``importlib.metadata.version("ariadne-core")``.
  3. ``-V`` is treated as a synonym for ``--version``.

A subprocess probe is used (rather than calling ``main()`` in-process)
because the regression the ticket reports is a user-facing one — the
shell exit code and the printed line as the user sees them — and main()
calls ``sys.exit`` which is awkward to assert through. Subprocess gives
the most faithful reproduction of the user's invocation.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version as _pkg_version


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m pipeline`` with the given args. Uses the same
    interpreter as pytest so the package's metadata is always resolvable.
    """
    return subprocess.run(
        [sys.executable, "-m", "pipeline", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_version_long_flag_exits_zero_and_prints_version() -> None:
    expected_version = _pkg_version("ariadne-core")

    result = _run_module("--version")

    assert result.returncode == 0, (
        f"--version should exit 0, got {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "ariadne-core" in result.stdout, (
        f"--version stdout should name the distribution; got {result.stdout!r}"
    )
    assert expected_version in result.stdout, (
        f"--version stdout should contain {expected_version!r}; "
        f"got {result.stdout!r}"
    )


def test_version_short_flag_matches_long_flag() -> None:
    long_result = _run_module("--version")
    short_result = _run_module("-V")

    assert short_result.returncode == 0, (
        f"-V should exit 0, got {short_result.returncode}; "
        f"stdout={short_result.stdout!r} stderr={short_result.stderr!r}"
    )
    assert short_result.stdout == long_result.stdout, (
        "-V should produce identical stdout to --version; "
        f"long={long_result.stdout!r} short={short_result.stdout!r}"
    )
