from pathlib import Path

import pytest
from rich.console import Console

from installer.detect import InstallState
from installer.flow.detection import show_detection_and_confirm
from installer.screens.detection import PluginDetectionRow


def _state(tmp_path: Path) -> InstallState:
    # InstallState has all optional fields w/ defaults; only installed_plugins needed.
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


class TestShowDetectionAndConfirm:
    def test_confirmed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = show_detection_and_confirm(
            state=_state(tmp_path),
            rows=_rows(),
            title="Existing Installation",
            console=console,
        )
        assert result is True

    def test_cancelled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert (
            show_detection_and_confirm(
                state=_state(tmp_path),
                rows=_rows(),
                title="Existing Installation",
                console=console,
            )
            is False
        )

    def test_table_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        show_detection_and_confirm(
            state=_state(tmp_path),
            rows=_rows(),
            title="Install Check",
            console=console,
        )
        text = console.export_text()
        assert "Install Check" in text
        assert "proj" in text
        assert "worktree" in text
        assert "router" in text
        assert "1.0.0" in text
        assert "1.1.0" in text
        assert "outdated" in text or "up-to-date" in text or "not installed" in text

    def test_empty_rows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = show_detection_and_confirm(
            state=_state(tmp_path),
            rows=[],
            title="Empty",
            console=console,
        )
        assert result is True
