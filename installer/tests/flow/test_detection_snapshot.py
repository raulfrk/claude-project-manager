# installer/tests/flow/test_detection_snapshot.py
"""Syrupy snapshots for show_detection_and_confirm flow helper."""

from pathlib import Path

import pytest
from rich.console import Console

from installer.detect import InstallState
from installer.flow.detection import PluginDetectionRow, show_detection_and_confirm


def _state(tmp_path: Path) -> InstallState:
    return InstallState(
        installed_plugins=["proj"],
    )


def _rows() -> list[PluginDetectionRow]:
    return [
        PluginDetectionRow(
            plugin="proj", installed_version="1.0.0", available_version="1.1.0"
        ),
        PluginDetectionRow(
            plugin="worktree", installed_version=None, available_version="2.0.0"
        ),
        PluginDetectionRow(
            plugin="router", installed_version="3.0.0", available_version=None
        ),
    ]


def test_detection_snapshot(
    snapshot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot of detection table with mixed version states."""
    monkeypatch.setattr("installer.flow.detection.ask_yn", lambda *a, **k: True)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    show_detection_and_confirm(
        state=_state(tmp_path),
        rows=_rows(),
        title="Plugin Status",
        console=console,
    )
    assert console.export_text() == snapshot


def test_detection_cancel_snapshot(
    snapshot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot of detection table with cancel response."""
    monkeypatch.setattr("installer.flow.detection.ask_yn", lambda *a, **k: False)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    show_detection_and_confirm(
        state=_state(tmp_path),
        rows=_rows(),
        title="Version Check",
        console=console,
    )
    assert console.export_text() == snapshot
