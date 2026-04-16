"""Textual pilot tests for integration configuration screens."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Label, Static, Switch

from installer.screens.integration_config import (
    JiraConfigScreen,
    TodoistConfigScreen,
    TrelloConfigScreen,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TestApp(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ============================================================================
# TodoistConfigScreen
# ============================================================================


class TestTodoistConfigScreen:
    """Pilot tests for the Todoist integration config screen."""

    @pytest.mark.asyncio
    async def test_shows_sync_toggle_and_masked_token(self):
        """Screen contains a sync-enabled switch and a masked API token input."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#sync_enabled", Switch)
            assert switch is not None

            token_input = screen.query_one("#api_token", Input)
            assert token_input is not None
            assert token_input.password is True

    @pytest.mark.asyncio
    async def test_default_values_from_existing_config(self, mock_home: Path):
        """Existing config values are loaded into the form fields."""
        config_path = mock_home / ".claude" / "todoist.yaml"
        config_path.write_text(
            yaml.dump({"enabled": True, "api_token": "test-token-123"}),
            encoding="utf-8",
        )

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#sync_enabled", Switch)
            assert switch.value is True

            token_input = screen.query_one("#api_token", Input)
            assert token_input.value == "test-token-123"

    @pytest.mark.asyncio
    async def test_skip_returns_none(self):
        """Skip button dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-skip", Button)
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_continue_with_empty_token_shows_error(self, mock_home: Path):
        """Continue with an empty token shows a validation error."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            # Enable sync so validation is triggered
            sync_switch = screen.query_one("#sync_enabled", Switch)
            sync_switch.value = True
            await pilot.pause()

            # Ensure token is empty (mock_home gives a clean config dir)
            token_input = screen.query_one("#api_token", Input)
            assert token_input.value == ""

            btn = screen.query_one("#btn-continue", Button)
            await pilot.click(btn)
            # Give worker time to run
            await pilot.pause()
            await pilot.pause()

            error_label = screen.query_one("#validation-error", Label)
            assert "visible" in error_label.classes
            # Label stores its text via update(); access via str(render())
            text = str(error_label.render())
            assert "required" in text.lower()

    @pytest.mark.asyncio
    async def test_continue_button_is_auto_focused(self):
        """Continue button receives focus on mount."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            btn = screen.query_one("#btn-continue", Button)
            assert btn.has_focus


# ============================================================================
# TrelloConfigScreen
# ============================================================================


class TestTrelloConfigScreen:
    """Pilot tests for the Trello integration config screen."""

    @pytest.mark.asyncio
    async def test_shows_all_fields(self):
        """Screen contains sync toggle, masked API key, masked token.

        `default_board_id` is owned by proj.yaml via PROJ_YAML_PROMPTS and is
        no longer rendered here (506.8).
        """
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#sync_enabled", Switch)
            assert switch is not None

            api_key = screen.query_one("#api_key", Input)
            assert api_key.password is True

            token = screen.query_one("#token", Input)
            assert token.password is True

    def test_trello_credential_keys_exclude_default_board_id(self) -> None:
        """506: default_board_id must not be in TrelloConfigScreen._credential_keys."""
        screen = TrelloConfigScreen()
        assert "default_board_id" not in screen._credential_keys
        assert screen._credential_keys == ("api_key", "token")

    @pytest.mark.asyncio
    async def test_default_values_from_existing_config(self, mock_home: Path):
        """Existing config values are loaded into the form fields.

        default_board_id moved to proj.yaml and is no longer read here.
        """
        config_path = mock_home / ".claude" / "trello.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "enabled": True,
                    "api_key": "key-abc",
                    "token": "tok-xyz",
                }
            ),
            encoding="utf-8",
        )

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#sync_enabled", Switch).value is True
            assert screen.query_one("#api_key", Input).value == "key-abc"
            assert screen.query_one("#token", Input).value == "tok-xyz"

    @pytest.mark.asyncio
    async def test_skip_returns_none(self):
        """Skip button dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-skip", Button)
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_continue_with_missing_key_token_shows_error(self, mock_home: Path):
        """Continue with empty API key and token shows validation error."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            # Enable sync so validation is triggered
            sync_switch = screen.query_one("#sync_enabled", Switch)
            sync_switch.value = True
            await pilot.pause()

            btn = screen.query_one("#btn-continue", Button)
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            error_label = screen.query_one("#validation-error", Label)
            assert "visible" in error_label.classes
            text = str(error_label.render())
            assert "required" in text.lower()


# ============================================================================
# JiraConfigScreen
# ============================================================================


class TestJiraConfigScreen:
    """Pilot tests for the Jira integration config screen."""

    @pytest.mark.asyncio
    async def test_shows_all_fields(self):
        """Screen contains sync toggle, base URL, username, masked token, project."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#sync_enabled", Switch)
            assert switch is not None

            base_url = screen.query_one("#base_url", Input)
            assert base_url is not None
            assert base_url.password is False

            user = screen.query_one("#default_user", Input)
            assert user is not None

            token = screen.query_one("#personal_access_token", Input)
            assert token.password is True

            project = screen.query_one("#default_project", Input)
            assert project is not None

    @pytest.mark.asyncio
    async def test_default_values_from_existing_config(self, mock_home: Path):
        """Existing config values are loaded into the form fields."""
        config_path = mock_home / ".claude" / "jira.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "enabled": True,
                    "base_url": "https://example.atlassian.net",
                    "default_user": "user@example.com",
                    "personal_access_token": "jira-pat-xyz",
                    "default_project": "PROJ",
                }
            ),
            encoding="utf-8",
        )

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#sync_enabled", Switch).value is True
            assert (
                screen.query_one("#base_url", Input).value
                == "https://example.atlassian.net"
            )
            assert screen.query_one("#default_user", Input).value == "user@example.com"
            assert (
                screen.query_one("#personal_access_token", Input).value
                == "jira-pat-xyz"
            )
            assert screen.query_one("#default_project", Input).value == "PROJ"

    @pytest.mark.asyncio
    async def test_skip_returns_none(self):
        """Skip button dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-skip", Button)
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None


# ============================================================================
# Auto-sync toggle tests — per-screen
# ============================================================================


class TestTodoistAutoSync:
    """Auto-sync switch tests for TodoistConfigScreen."""

    @pytest.mark.asyncio
    async def test_auto_sync_switch_exists(self):
        """#auto_sync Switch widget exists and defaults to True."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#auto_sync", Switch)
            assert switch is not None
            assert switch.value is True

    @pytest.mark.asyncio
    async def test_auto_sync_in_collected_values(self, mock_home: Path):
        """Submit form and verify auto_sync key appears in collected values."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Fill in required token so validation passes
            token_input = screen.query_one("#api_token", Input)
            token_input.value = "test-token"

            with patch(
                "httpx.get",
                return_value=type("R", (), {"status_code": 200})(),
            ):
                btn = screen.query_one("#btn-continue", Button)
                await pilot.click(btn)
                await pilot.pause()
                await pilot.pause()

        assert len(results) == 1
        assert results[0] is not None
        assert "auto_sync" in results[0]
        assert results[0]["auto_sync"] is True

    @pytest.mark.asyncio
    async def test_auto_sync_prepopulated_from_config(self, mock_home: Path):
        """Existing config with auto_sync: false pre-populates switch as False."""
        config_path = mock_home / ".claude" / "todoist.yaml"
        config_path.write_text(
            yaml.dump({"enabled": True, "api_token": "tok", "auto_sync": False}),
            encoding="utf-8",
        )

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#auto_sync", Switch)
            assert switch.value is False


class TestTrelloAutoSync:
    """Auto-sync switch tests for TrelloConfigScreen."""

    @pytest.mark.asyncio
    async def test_auto_sync_switch_exists(self):
        """#auto_sync Switch widget exists and defaults to True."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#auto_sync", Switch)
            assert switch is not None
            assert switch.value is True

    @pytest.mark.asyncio
    async def test_auto_sync_in_collected_values(self, mock_home: Path):
        """Submit form and verify auto_sync key appears in collected values."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Fill in required fields
            screen.query_one("#api_key", Input).value = "key-abc"
            screen.query_one("#token", Input).value = "tok-xyz"

            with patch(
                "httpx.get",
                return_value=type("R", (), {"status_code": 200})(),
            ):
                btn = screen.query_one("#btn-continue", Button)
                await pilot.click(btn)
                await pilot.pause()
                await pilot.pause()

        assert len(results) == 1
        assert results[0] is not None
        assert "auto_sync" in results[0]
        assert results[0]["auto_sync"] is True

    @pytest.mark.asyncio
    async def test_auto_sync_prepopulated_from_config(self, mock_home: Path):
        """Existing config with auto_sync: false pre-populates switch as False."""
        config_path = mock_home / ".claude" / "trello.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "enabled": True,
                    "api_key": "k",
                    "token": "t",
                    "auto_sync": False,
                }
            ),
            encoding="utf-8",
        )

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#auto_sync", Switch)
            assert switch.value is False


class TestJiraAutoSync:
    """Auto-sync switch tests for JiraConfigScreen."""

    @pytest.mark.asyncio
    async def test_auto_sync_switch_exists(self):
        """#auto_sync Switch widget exists and defaults to True."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#auto_sync", Switch)
            assert switch is not None
            assert switch.value is True

    @pytest.mark.asyncio
    async def test_auto_sync_in_collected_values(self, mock_home: Path):
        """Submit form and verify auto_sync key appears in collected values."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Fill in required fields
            screen.query_one("#base_url", Input).value = "https://example.atlassian.net"
            screen.query_one("#personal_access_token", Input).value = "pat-123"

            with patch(
                "httpx.get",
                return_value=type("R", (), {"status_code": 200})(),
            ):
                btn = screen.query_one("#btn-continue", Button)
                await pilot.click(btn)
                await pilot.pause()
                await pilot.pause()

        assert len(results) == 1
        assert results[0] is not None
        assert "auto_sync" in results[0]
        assert results[0]["auto_sync"] is True

    @pytest.mark.asyncio
    async def test_auto_sync_prepopulated_from_config(self, mock_home: Path):
        """Existing config with auto_sync: false pre-populates switch as False."""
        config_path = mock_home / ".claude" / "jira.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "enabled": True,
                    "base_url": "https://example.atlassian.net",
                    "personal_access_token": "pat",
                    "auto_sync": False,
                }
            ),
            encoding="utf-8",
        )

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            switch = screen.query_one("#auto_sync", Switch)
            assert switch.value is False


# ============================================================================
# Rich CLI auto_sync tests
# ============================================================================


class TestRichCLIAutoSync:
    """Tests for auto_sync prompts in Rich CLI wizard functions."""

    def test_todoist_auto_sync_default_true(self, mock_home: Path):
        """Todoist auto_sync prompt defaults to True and is written to config."""
        from unittest.mock import MagicMock

        from installer.wizard import _setup_todoist_config

        console = MagicMock()

        with (
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=[True, True],  # enabled=True, auto_sync=True
            ),
            patch(
                "installer.wizard.Prompt.ask",
                return_value="test-token",
            ),
            patch(
                "httpx.get",
                return_value=type("R", (), {"status_code": 200})(),
            ),
        ):
            _setup_todoist_config(console)

        config_path = mock_home / ".claude" / "todoist.yaml"
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert data["auto_sync"] is True

    def test_todoist_auto_sync_existing_false(self, mock_home: Path):
        """Existing config with auto_sync: false is used as default for prompt."""
        from unittest.mock import MagicMock

        from installer.wizard import _setup_todoist_config

        # Write existing config with auto_sync=false
        config_path = mock_home / ".claude" / "todoist.yaml"
        config_path.write_text(
            yaml.dump({"enabled": True, "api_token": "old-tok", "auto_sync": False}),
            encoding="utf-8",
        )

        console = MagicMock()

        with (
            patch(
                "installer.wizard.Confirm.ask",
                side_effect=[True, False],  # enabled=True, auto_sync=False
            ),
            patch(
                "installer.wizard.Prompt.ask",
                return_value="new-token",
            ),
            patch(
                "httpx.get",
                return_value=type("R", (), {"status_code": 200})(),
            ),
        ):
            _setup_todoist_config(console)

        data = yaml.safe_load(config_path.read_text())
        assert data["auto_sync"] is False


# ============================================================================
# Unit tests: _write_all_configs and _compute_diff
# ============================================================================


class TestConfigWriteOnContinue:
    """Unit tests for _write_all_configs() and _compute_diff() on integration screens."""

    def test_write_all_configs_writes_service_yaml(self, mock_home: Path):
        """_write_all_configs writes credentials to service yaml and sync flags to proj.yaml."""
        screen = TodoistConfigScreen()
        screen._write_all_configs(
            {"api_token": "test-tok", "enabled": True, "auto_sync": True}
        )

        todoist_yaml = mock_home / ".claude" / "todoist.yaml"
        assert todoist_yaml.exists()
        data = yaml.safe_load(todoist_yaml.read_text())
        assert data["api_token"] == "test-tok"

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        assert proj_yaml.exists()
        proj_data = yaml.safe_load(proj_yaml.read_text())
        assert proj_data["sync"]["todoist"]["enabled"] is True
        assert proj_data["sync"]["todoist"]["auto_sync"] is True

    def test_write_all_configs_merges_existing(self, mock_home: Path):
        """_write_all_configs merges with existing service yaml, preserving extra keys."""
        todoist_yaml = mock_home / ".claude" / "todoist.yaml"
        todoist_yaml.write_text(
            yaml.dump({"api_token": "old", "extra_key": "keep"}),
            encoding="utf-8",
        )

        screen = TodoistConfigScreen()
        screen._write_all_configs(
            {"api_token": "new", "enabled": True, "auto_sync": False}
        )

        data = yaml.safe_load(todoist_yaml.read_text())
        assert data["api_token"] == "new"
        assert data["extra_key"] == "keep"

    def test_write_all_configs_writes_enabled_to_proj_yaml(self, mock_home: Path):
        """_write_all_configs writes enabled and auto_sync to existing proj.yaml."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text(
            yaml.dump({"version": "1", "tracking_dir": "~/t"}),
            encoding="utf-8",
        )

        screen = TodoistConfigScreen()
        screen._write_all_configs(
            {"api_token": "t", "enabled": True, "auto_sync": False}
        )

        data = yaml.safe_load(proj_yaml.read_text())
        assert data["sync"]["todoist"]["enabled"] is True
        assert data["sync"]["todoist"]["auto_sync"] is False
        # Existing keys preserved
        assert data["version"] == "1"
        assert data["tracking_dir"] == "~/t"

    def test_write_all_configs_jira_section(self, mock_home: Path):
        """JiraConfigScreen writes to jira section (not sync.jira) in proj.yaml."""
        screen = JiraConfigScreen()
        screen._write_all_configs(
            {
                "base_url": "https://x.atlassian.net",
                "default_user": "u",
                "personal_access_token": "pat",
                "default_project": "PROJ",
                "enabled": True,
                "auto_sync": False,
            }
        )

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        data = yaml.safe_load(proj_yaml.read_text())
        assert data["jira"]["enabled"] is True
        assert data["jira"]["auto_sync"] is False
        # Should NOT be nested under sync
        assert "sync" not in data or "jira" not in data.get("sync", {})

    def test_compute_diff_first_time(self, mock_home: Path):
        """_compute_diff returns is_first_time=True when no service config exists."""
        screen = TodoistConfigScreen()
        _diff_text, _has_changes, is_first_time = screen._compute_diff(
            {"api_token": "t", "enabled": True, "auto_sync": True}
        )
        assert is_first_time is True

    def test_compute_diff_no_changes(self, mock_home: Path):
        """_compute_diff returns has_changes=False when nothing changed."""
        todoist_yaml = mock_home / ".claude" / "todoist.yaml"
        todoist_yaml.write_text(
            yaml.dump({"api_token": "t"}),
            encoding="utf-8",
        )

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text(
            yaml.dump({"sync": {"todoist": {"enabled": True, "auto_sync": True}}}),
            encoding="utf-8",
        )

        screen = TodoistConfigScreen()
        _diff_text, has_changes, is_first_time = screen._compute_diff(
            {"api_token": "t", "enabled": True, "auto_sync": True}
        )
        assert is_first_time is False
        assert has_changes is False

    def test_compute_diff_detects_changes(self, mock_home: Path):
        """_compute_diff returns has_changes=True and non-empty diff_text when values differ."""
        todoist_yaml = mock_home / ".claude" / "todoist.yaml"
        todoist_yaml.write_text(
            yaml.dump({"api_token": "old"}),
            encoding="utf-8",
        )

        screen = TodoistConfigScreen()
        diff_text, has_changes, is_first_time = screen._compute_diff(
            {"api_token": "new", "enabled": True, "auto_sync": True}
        )
        assert is_first_time is False
        assert has_changes is True
        assert diff_text  # non-empty

    def test_write_all_configs_trello(self, mock_home: Path):
        """TrelloConfigScreen writes credentials to trello.yaml and flags to proj.yaml.

        506.8: default_board_id moved to proj.yaml via PROJ_YAML_PROMPTS and is
        no longer written by this screen. trello.yaml holds only api_key/token.
        """
        screen = TrelloConfigScreen()
        screen._write_all_configs(
            {
                "api_key": "k",
                "token": "t",
                "enabled": True,
                "auto_sync": True,
            }
        )

        trello_yaml = mock_home / ".claude" / "trello.yaml"
        data = yaml.safe_load(trello_yaml.read_text())
        assert data["api_key"] == "k"
        assert data["token"] == "t"
        assert "default_board_id" not in data, (
            "default_board_id must not be in trello.yaml (moved to proj.yaml)"
        )

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_data = yaml.safe_load(proj_yaml.read_text())
        assert proj_data["sync"]["trello"]["enabled"] is True
        assert proj_data["sync"]["trello"]["auto_sync"] is True


# ============================================================================
# InstallerApp._write_config_files
# ============================================================================


class TestWriteConfigFiles:
    """Tests for InstallerApp._write_config_files."""

    def test_writes_proj_yaml(self, mock_home: Path):
        """proj.yaml is created when proj plugin is selected."""
        from installer.app import InstallerApp

        app = InstallerApp()
        app.selected_plugins = ["proj", "hooks"]
        app._write_config_files(
            {
                "tracking_dir": "~/projects/tracking",
                "projects_base_dir": "~/projects",
                "sandbox_integration": True,
                "zoxide_integration": False,
            }
        )

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        assert proj_yaml.exists()
        content = proj_yaml.read_text()
        assert "version: 1" in content
        assert "tracking_dir: ~/projects/tracking" in content
        assert "sandbox_integration: true" in content

    def test_writes_worktree_yaml(self, mock_home: Path):
        """worktree.yaml is created when worktree plugin is selected."""
        from installer.app import InstallerApp

        app = InstallerApp()
        app.selected_plugins = ["worktree"]
        app._write_config_files(
            {
                "tracking_dir": "~/projects/tracking",
                "projects_base_dir": "~/projects",
                "sandbox_integration": False,
                "zoxide_integration": False,
                "default_worktree_dir": "~/worktrees",
            }
        )

        wt_yaml = mock_home / ".claude" / "worktree.yaml"
        assert wt_yaml.exists()
        content = wt_yaml.read_text()
        # dotted_key matches WorktreeConfig.default_worktree_dir (515.10 fix
        # of the 514 rename bug — yaml still uses the dataclass field name).
        assert "default_worktree_dir: ~/worktrees" in content

    def test_no_worktree_yaml_without_plugin(self, mock_home: Path):
        """worktree.yaml is NOT created when worktree is not selected."""
        from installer.app import InstallerApp

        app = InstallerApp()
        app.selected_plugins = ["proj"]
        app._write_config_files(
            {
                "tracking_dir": "~/t",
                "projects_base_dir": "~/p",
                "sandbox_integration": False,
                "zoxide_integration": False,
            }
        )

        wt_yaml = mock_home / ".claude" / "worktree.yaml"
        assert not wt_yaml.exists()

    def test_ensures_managed_section_in_claude_md(self, mock_home: Path):
        """_write_config_files creates managed section in CLAUDE.md."""
        from installer.app import InstallerApp
        from claudemd import MARKER_START

        app = InstallerApp()
        app.selected_plugins = ["proj"]
        app._write_config_files(
            {
                "tracking_dir": "~/t",
                "projects_base_dir": "~/p",
                "sandbox_integration": False,
                "zoxide_integration": False,
            }
        )

        claude_md = mock_home / ".claude" / "CLAUDE.md"
        assert claude_md.exists()
        assert MARKER_START in claude_md.read_text()
