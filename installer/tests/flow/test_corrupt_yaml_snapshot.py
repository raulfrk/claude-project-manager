# installer/tests/flow/test_corrupt_yaml_snapshot.py
"""Syrupy snapshots for show_corrupt_yaml_and_confirm flow helper."""

import pytest
import yaml
from rich.console import Console

from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm


def test_corrupt_yaml_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of corrupt YAML error display."""
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    errors = {
        "proj": yaml.YAMLError("bad token at line 5"),
        "worktree": yaml.YAMLError("mapping values are not allowed here"),
    }
    show_corrupt_yaml_and_confirm(errors, console)
    assert console.export_text() == snapshot


def test_corrupt_yaml_cancel_snapshot(
    snapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot of corrupt YAML with cancel response."""
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    errors = {
        "proj": yaml.YAMLError("bad token at line 5"),
    }
    show_corrupt_yaml_and_confirm(errors, console)
    assert console.export_text() == snapshot
