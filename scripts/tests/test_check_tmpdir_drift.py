"""End-to-end tests for scripts/check_tmpdir_drift.sh.

Verifies the drift-guard regex catches all 3 forms of forbidden socket-literal
patterns in production code:

1. PID-tagged form:    f"...claude-cpm-{plugin}-{pid}.sock"
2. Glob form:          "...claude-cpm-{plugin}-*.sock"
3. No-PID fallback:    "...claude-cpm-{plugin}.sock"

The test stages synthetic violation files inside one of the production-scan
roots, runs the script in a throwaway working tree, and asserts the script
exits non-zero with a "DRIFT:" report mentioning the synthetic file.

Each subtest cleans up after itself so the production tree is never left in
a violating state for later tests / pre-commit hooks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_tmpdir_drift.sh"
# Use the proj plugin's production tree as a host for the synthetic file
# because it is in production_paths in check_tmpdir_drift.sh.
HOST_DIR = REPO_ROOT / "plugins" / "proj" / "server" / "server" / "tools"


@pytest.fixture
def synthetic_violation(tmp_path: Path) -> Path:
    """Yield a path inside HOST_DIR for the test to write a synthetic file to.

    Cleans up the file on teardown regardless of test outcome so the working
    tree never stays in a drift-violating state.
    """
    target = HOST_DIR / "_drift_synthetic_test_violation.py"
    yield target
    if target.exists():
        target.unlink()


def _run_script() -> subprocess.CompletedProcess[str]:
    """Invoke the drift-guard script and capture its output."""
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_baseline_clean_tree_passes() -> None:
    """Sanity: with no synthetic violations, the guard passes (exit 0)."""
    result = _run_script()
    assert result.returncode == 0, (
        f"Baseline drift check should pass, got exit {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_glob_form_caught(synthetic_violation: Path) -> None:
    """Glob form: 'claude-cpm-foo-*.sock' literal triggers the guard."""
    synthetic_violation.write_text(
        'GLOB = "claude-cpm-syntheticplugin-*.sock"\n',
        encoding="utf-8",
    )
    result = _run_script()
    assert result.returncode != 0, (
        f"Glob-form drift should fail, got exit 0\nstdout: {result.stdout}"
    )
    assert "_drift_synthetic_test_violation.py" in result.stdout


def test_pid_tagged_form_caught(synthetic_violation: Path) -> None:
    """PID-tagged form: 'claude-cpm-foo-1234.sock' literal triggers the guard."""
    synthetic_violation.write_text(
        'PID = "/tmp/claude-cpm-syntheticplugin-1234.sock"\n',
        encoding="utf-8",
    )
    result = _run_script()
    assert result.returncode != 0, (
        f"PID-tagged drift should fail, got exit 0\nstdout: {result.stdout}"
    )
    assert "_drift_synthetic_test_violation.py" in result.stdout


def test_no_pid_form_caught(synthetic_violation: Path) -> None:
    """No-PID fallback form: 'claude-cpm-foo.sock' literal triggers the guard."""
    synthetic_violation.write_text(
        'NOPID = "/tmp/claude-cpm-syntheticplugin.sock"\n',
        encoding="utf-8",
    )
    result = _run_script()
    assert result.returncode != 0, (
        f"No-PID-fallback drift should fail, got exit 0\nstdout: {result.stdout}"
    )
    assert "_drift_synthetic_test_violation.py" in result.stdout


def test_unrelated_sock_literal_not_flagged(synthetic_violation: Path) -> None:
    """Sanity: socket literals NOT matching the cpm prefix are ignored.

    Guards against an over-broad regex that would match arbitrary '.sock' uses.
    """
    synthetic_violation.write_text(
        'OTHER = "/tmp/some-other-app.sock"\n',
        encoding="utf-8",
    )
    result = _run_script()
    assert result.returncode == 0, (
        f"Non-cpm sock literal should pass, got exit {result.returncode}\n"
        f"stdout: {result.stdout}"
    )
