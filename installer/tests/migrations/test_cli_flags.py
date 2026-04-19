# installer/tests/migrations/test_cli_flags.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_help_lists_migrate_flags() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--migrate" in r.stdout
    assert "--dry-run" in r.stdout
    assert "--backup-retain" in r.stdout
    assert "--strict-resync" in r.stdout
    # Consolidated: old flag names should be gone.
    assert "--migrate-flat" not in r.stdout
    assert "--migrate-sql-only" not in r.stdout


def test_dry_run_flag_exits_zero_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Build a real-shape registry so dry-run iterates projects.
    home = tmp_path / "home"
    tracking = home / "projects" / "tracking"
    (home / ".claude").mkdir(parents=True)

    # One project at v1 (no .schema-version file)
    proj_dir = tracking / "demo"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("[]\n")
    (proj_dir / "archive.yaml").write_text("[]\n")

    # Global config with tracking_dir
    (home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump({"tracking_dir": str(tracking)})
    )

    # Registry
    registry = {
        "projects": {
            "demo": {"tracking_dir": str(proj_dir), "archived": False},
        }
    }
    (tracking / "active-projects.yaml").write_text(yaml.safe_dump(registry))

    monkeypatch.setenv("HOME", str(home))

    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate", "--dry-run"],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": __import__("os").environ["PATH"]},
    )
    assert r.returncode == 0
    # Dry-run report should mention the project
    assert "demo" in r.stdout or "Dry-run" in r.stdout
    # Nothing mutated — .schema-version should NOT be created
    assert not (proj_dir / ".schema-version").exists()
