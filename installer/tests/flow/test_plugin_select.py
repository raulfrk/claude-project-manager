# installer/tests/flow/test_plugin_select.py
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from installer.flow.plugin_select import select_plugin_actions
from installer.plugin_status import PluginStatus


def _statuses() -> list[PluginStatus]:
    return [
        PluginStatus(
            name="proj",
            installed_version="1.0.0",
            available_version="1.1.0",
            state="outdated",
        ),
        PluginStatus(
            name="router",
            installed_version="3.0.0",
            available_version="3.0.0",
            state="installed",
        ),
        PluginStatus(
            name="worktree",
            installed_version=None,
            available_version="2.0.0",
            state="available",
        ),
    ]


class TestSelectPluginActions:
    def test_install_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 3 sequential checkboxlists: available, outdated, installed
        mock = MagicMock()
        mock.return_value.run.side_effect = [["worktree"], [], []]
        monkeypatch.setattr("installer.flow.plugin_select.checkboxlist_dialog", mock)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_plugin_actions(_statuses(), console)
        assert ("worktree", "install") in result
        assert not any(n == "proj" for n, _ in result)
        assert not any(n == "router" for n, _ in result)

    def test_update_and_reinstall(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        mock.return_value.run.side_effect = [[], ["proj"], ["router"]]
        monkeypatch.setattr("installer.flow.plugin_select.checkboxlist_dialog", mock)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_plugin_actions(_statuses(), console)
        assert ("proj", "install") in result
        assert ("router", "reinstall") in result

    def test_cancel_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        # Dialog returns None on cancel — first cancel short-circuits to [].
        mock.return_value.run.return_value = None
        monkeypatch.setattr("installer.flow.plugin_select.checkboxlist_dialog", mock)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert select_plugin_actions(_statuses(), console) == []

    def test_empty_statuses_returns_empty_without_dialog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = MagicMock()
        monkeypatch.setattr("installer.flow.plugin_select.checkboxlist_dialog", mock)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert select_plugin_actions([], console) == []
        mock.assert_not_called()

    def test_skips_empty_buckets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only `outdated` present → only 1 dialog should fire."""
        only_outdated = [
            PluginStatus(
                name="proj",
                installed_version="1.0.0",
                available_version="1.1.0",
                state="outdated",
            ),
        ]
        mock = MagicMock()
        mock.return_value.run.return_value = ["proj"]
        monkeypatch.setattr("installer.flow.plugin_select.checkboxlist_dialog", mock)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_plugin_actions(only_outdated, console)
        assert ("proj", "install") in result
        assert mock.call_count == 1  # only the outdated bucket dialog fired
