# installer/tests/flow/test_config_diff_snapshot.py
"""Syrupy snapshots for review_config_diff flow helper."""

import pytest
from rich.console import Console

from installer.flow.config_diff import review_config_diff


def test_config_diff_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of config diff for a service."""
    monkeypatch.setattr("installer.flow.config_diff.ask_yn", lambda *a, **k: True)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    diff_text = (
        "--- /home/user/.claude/proj.yaml\n"
        "+++ /home/user/.claude/proj.yaml\n"
        " tracking_dir: /tmp/tracking\n"
        "-default_priority: low\n"
        "+default_priority: high\n"
        " git_enabled: true\n"
    )
    review_config_diff("proj", diff_text, console)
    assert console.export_text() == snapshot


def test_config_diff_empty_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of config diff with no changes."""
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = review_config_diff("worktree", "", console)
    assert result is True
    assert console.export_text() == snapshot
