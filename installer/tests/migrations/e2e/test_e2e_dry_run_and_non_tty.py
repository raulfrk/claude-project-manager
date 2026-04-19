# installer/tests/migrations/e2e/test_e2e_dry_run_and_non_tty.py
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_dry_run_writes_report_exits_zero(home_with_projects: Path) -> None:
    env = {**os.environ, "HOME": str(home_with_projects)}
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0
    assert "Dry-run report:" in r.stdout

    # Nothing mutated — .schema-version should not be created
    for name in ("cpm", "side", "legacy"):
        assert not (
            home_with_projects / "projects" / "tracking" / name / ".schema-version"
        ).exists()


def test_non_tty_exits_with_warning(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {**os.environ, "HOME": str(home_with_projects)}
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate"],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,  # force non-TTY
    )
    assert r.returncode == 0
    assert "interactive terminal" in r.stdout
    # Still no mutation
    assert not (
        home_with_projects / "projects" / "tracking" / "cpm" / ".schema-version"
    ).exists()
