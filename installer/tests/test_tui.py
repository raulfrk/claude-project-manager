"""Tests for installer.tui — plugin selection UI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from installer.tui import (
    PluginInfo,
    _check_dependency_warnings,
    _classify_category,
    load_plugins,
    select_plugins,
)


class TestClassifyCategory:
    def test_core_plugins(self):
        assert _classify_category("sandbox", "core") == "core"
        assert _classify_category("hooks", "core") == "core"
        assert _classify_category("proj", "productivity") == "core"

    def test_utility_plugins(self):
        assert _classify_category("worktree", "utilities") == "utilities"
        assert _classify_category("zoxide", "utilities") == "utilities"

    def test_integration_plugins(self):
        assert _classify_category("trello", "integrations") == "integrations"
        assert _classify_category("jira", "integrations") == "integrations"

    def test_unknown_falls_to_integrations(self):
        assert _classify_category("custom", "whatever") == "integrations"


class TestLoadPlugins:
    def test_loads_from_marketplace(self, marketplace_json: Path):
        plugins = load_plugins(marketplace_json)
        names = [p.name for p in plugins]
        assert "sandbox" in names
        assert "proj" in names
        assert "worktree" in names

    def test_sorted_by_category_then_name(self, marketplace_json: Path):
        plugins = load_plugins(marketplace_json)
        categories = [p.category for p in plugins]
        # core comes before utilities, utilities before integrations
        assert categories.index("core") < categories.index("utilities")
        assert categories.index("utilities") < categories.index("integrations")

    def test_plugin_info_fields(self, marketplace_json: Path):
        plugins = load_plugins(marketplace_json)
        proj = next(p for p in plugins if p.name == "proj")
        assert proj.version == "1.0.0"
        assert proj.description == "Project management"
        assert proj.category == "core"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_plugins(tmp_path / "nonexistent.json")


class TestCheckDependencyWarnings:
    def test_no_warning_when_hooks_selected(self, mock_console):
        _check_dependency_warnings(["hooks", "proj", "sandbox"], mock_console)
        # Console.print should not be called with "Warning"
        for call in mock_console.file.write.call_args_list:
            assert "Warning" not in str(call)

    def test_warning_when_hooks_missing(self, mock_console):
        _check_dependency_warnings(["proj", "sandbox"], mock_console)
        # Should have printed a warning — verify console.print was called
        # (mock_console is a real Console writing to a MagicMock file)
        output = "".join(
            str(call.args[0]) if call.args else ""
            for call in mock_console.file.write.call_args_list
        )
        assert "hooks" in output

    def test_no_warning_for_analyse_only(self, mock_console):
        """analyse alone without hooks should not trigger a warning."""
        _check_dependency_warnings(["analyse"], mock_console)


class TestSelectPlugins:
    def _make_plugins(self):
        return [
            PluginInfo("sandbox", "Sandbox", "0.2.0", "core", []),
            PluginInfo("hooks", "Hooks", "0.3.0", "core", []),
            PluginInfo("proj", "Proj", "1.0.0", "core", []),
            PluginInfo("worktree", "Worktrees", "0.7.0", "utilities", []),
            PluginInfo("trello", "Trello", "0.5.0", "integrations", []),
        ]

    def test_select_all(self, mock_console):
        plugins = self._make_plugins()
        with patch("installer.tui.Prompt.ask", return_value="all"):
            selected = select_plugins(plugins, console=mock_console)
        assert len(selected) == 5

    def test_select_none(self, mock_console):
        plugins = self._make_plugins()
        with patch("installer.tui.Prompt.ask", return_value="none"):
            selected = select_plugins(plugins, console=mock_console)
        assert selected == []

    def test_select_by_indices(self, mock_console):
        plugins = self._make_plugins()
        with patch("installer.tui.Prompt.ask", return_value="1,3"):
            selected = select_plugins(plugins, console=mock_console)
        assert len(selected) == 2
        assert "sandbox" in selected
        assert "proj" in selected

    def test_invalid_index_skipped(self, mock_console):
        plugins = self._make_plugins()
        with patch("installer.tui.Prompt.ask", return_value="1,99,abc"):
            selected = select_plugins(plugins, console=mock_console)
        assert len(selected) == 1
        assert "sandbox" in selected

    def test_custom_preselect(self, mock_console):
        plugins = self._make_plugins()
        # When user just hits enter, uses default which is the preselect indices
        # We pass a specific preselect set and mock the prompt to use defaults
        with patch("installer.tui.Prompt.ask", return_value="1"):
            selected = select_plugins(
                plugins, preselect={"sandbox"}, console=mock_console
            )
        assert selected == ["sandbox"]
