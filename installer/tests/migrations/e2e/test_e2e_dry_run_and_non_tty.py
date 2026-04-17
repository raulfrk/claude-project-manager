# installer/tests/migrations/e2e/test_e2e_dry_run_and_non_tty.py
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_dry_run_writes_report_exits_zero(home_with_projects: Path) -> None:
    env = {**os.environ, "HOME": str(home_with_projects)}
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate-flat-dry-run"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0
    assert "Dry-run report:" in r.stdout

    # Nothing mutated
    for name in ("cpm", "side", "legacy"):
        pj = home_with_projects / "projects" / name / "proj.yaml"
        data = yaml.safe_load(pj.read_text())
        assert "schema_version" not in data


def test_non_tty_exits_with_warning(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {**os.environ, "HOME": str(home_with_projects)}
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate-flat"],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,  # force non-TTY
    )
    assert r.returncode == 0
    assert "interactive terminal" in r.stdout
    # Still no mutation
    pj = home_with_projects / "projects" / "cpm" / "proj.yaml"
    data = yaml.safe_load(pj.read_text())
    assert "schema_version" not in data
