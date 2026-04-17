# installer/tests/migrations/test_cli_flags.py
from __future__ import annotations

import subprocess
import sys


def test_help_lists_migrate_flags() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--migrate-flat" in r.stdout
    assert "--migrate-flat-dry-run" in r.stdout
    assert "--backup-retain" in r.stdout
    assert "--strict-resync" in r.stdout


def test_dry_run_flag_exits_zero_without_mutation(tmp_path, monkeypatch) -> None:
    # Point fake home at tmp_path so no real config touched
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "proj.yaml").write_text("projects: []\n")
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate-flat-dry-run"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
