# installer/tests/flow/test_corrupt_yaml_snapshot.py
"""Syrupy snapshots for show_corrupt_yaml_and_confirm flow helper."""

from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm

# Deterministic home path so snapshots are CI-stable.
_FAKE_HOME = Path("/home/ci-user")


def test_corrupt_yaml_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of corrupt YAML error display."""
    monkeypatch.setattr("installer.flow.corrupt_yaml.ask_yn", lambda *a, **k: True)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    errors = {
        "proj": Exception("bad token at line 5"),
        "worktree": Exception("mapping values are not allowed here"),
    }
    with patch("installer.flow.corrupt_yaml.Path.home", return_value=_FAKE_HOME):
        show_corrupt_yaml_and_confirm(errors, console)
    assert console.export_text() == snapshot


def test_corrupt_yaml_cancel_snapshot(
    snapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot of corrupt YAML with cancel response."""
    monkeypatch.setattr("installer.flow.corrupt_yaml.ask_yn", lambda *a, **k: False)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    errors = {
        "proj": Exception("bad token at line 5"),
    }
    with patch("installer.flow.corrupt_yaml.Path.home", return_value=_FAKE_HOME):
        show_corrupt_yaml_and_confirm(errors, console)
    assert console.export_text() == snapshot
