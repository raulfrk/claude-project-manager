"""End-to-end tests for the integration config flow.

Covers: PluginSelectScreen -> WizardScreen -> TodoistConfigScreen -> ProgressScreen,
skip button, config persistence, and screen geometry.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from installer.app import InstallerApp
from installer.screens.integration_config import TodoistConfigScreen
from installer.screens.plugin_select import PluginStatusScreen
from installer.screens.wizard import WizardScreen

from .conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_marketplace_path(marketplace_json, monkeypatch):
    """Point all marketplace readers at the test marketplace.json."""
    monkeypatch.setattr("installer.tui._MARKETPLACE_PATH", marketplace_json)
    monkeypatch.setattr("installer.update._MARKETPLACE_PATH", marketplace_json)


@pytest.fixture()
def _fresh_install(mock_plugin_cli, monkeypatch):
    """Override mock_plugin_cli so get_installed_plugins returns empty (fresh install)."""
    mock_plugin_cli["get_installed_plugins"].return_value = []
    mock_plugin_cli["check_marketplace_registered"].return_value = False
    monkeypatch.setattr("installer.plugin_status.get_installed_plugins", lambda: [])


@pytest.fixture()
def _no_hooks_diff(monkeypatch):
    """Ensure hooks diff check returns no changes so the flow proceeds to install."""
    monkeypatch.setattr(
        "installer.hooks_diff.compute_hooks_diff",
        lambda *_a, **_kw: [],  # noqa: ARG005
    )


@pytest.fixture()
def _mock_httpx(monkeypatch):
    """Mock httpx.get to return 200 for API validation calls."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    monkeypatch.setattr("httpx.get", MagicMock(return_value=mock_resp))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _select_todoist_and_advance(app: InstallerApp, pilot) -> None:
    """Restrict install to todoist (+ core) on PluginStatusScreen and advance."""
    await pilot.pause()
    await pilot.pause()

    screen = app.screen
    assert isinstance(screen, PluginStatusScreen)

    # Restrict to todoist + core plugins that don't trigger other integration
    # config screens. Every remaining plugin gets action=skip.
    allowed = {"todoist", "router", "proj"}
    for plugin_name in list(screen._actions.keys()):
        if plugin_name not in allowed:
            screen._actions[plugin_name] = "skip"
    assert screen._actions["todoist"] == "install"

    btn = screen.query_one("#btn-confirm")
    await pilot.click(btn)
    await pilot.pause()
    await pilot.pause()

    # -- WizardScreen --
    screen = app.screen
    assert isinstance(screen, WizardScreen)

    btn = screen.query_one("#btn-submit")
    await pilot.click(btn)
    await pilot.pause()
    await pilot.pause()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIntegrationScreenNavigation:
    """Verify integration screens appear in the flow and can be skipped."""

    @pytest.mark.asyncio
    async def test_todoist_screen_appears_after_wizard(
        self, e2e_app, _fresh_install, mock_plugin_cli
    ):
        """Select todoist -> wizard submit -> TodoistConfigScreen is shown."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            # -- TodoistConfigScreen should be active --
            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)

    @pytest.mark.asyncio
    async def test_skip_integration_proceeds(
        self, e2e_app, _fresh_install, _no_hooks_diff, mock_plugin_cli
    ):
        """On TodoistConfigScreen, clicking Skip proceeds past integration."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            # -- TodoistConfigScreen --
            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)

            # Click Skip
            btn = screen.query_one("#btn-skip")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            # Should have moved past TodoistConfigScreen
            assert not isinstance(app.screen, TodoistConfigScreen)

            # Wait for install to complete
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            assert mock_plugin_cli["install_plugin"].called


class TestIntegrationConfigFlow:
    """Test config writing behavior with sync enabled/disabled."""

    @pytest.mark.asyncio
    async def test_disable_sync_skips_validation(
        self, e2e_app, _fresh_install, _no_hooks_diff, mock_plugin_cli, mock_home
    ):
        """Toggle sync off -> continue succeeds without API token, writes enabled=false."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            # -- TodoistConfigScreen --
            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)

            # Sync is off by default (no existing config), just click Continue
            btn = screen.query_one("#btn-continue")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            # Should have moved past integration (no validation needed)
            assert not isinstance(app.screen, TodoistConfigScreen)

            # Wait for install
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            assert mock_plugin_cli["install_plugin"].called

            # Verify proj.yaml has sync.todoist.enabled = false
            proj_yaml = mock_home / ".claude" / "proj.yaml"
            assert proj_yaml.exists()
            data = yaml.safe_load(proj_yaml.read_text())
            assert data["sync"]["todoist"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_todoist_first_time_writes_directly(
        self,
        e2e_app,
        _fresh_install,
        _no_hooks_diff,
        _mock_httpx,
        mock_plugin_cli,
        mock_home,
    ):
        """Fill token, enable sync -> first-time writes directly (no ConfigDiffScreen)."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            # -- TodoistConfigScreen --
            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)

            # Enable sync
            sync_switch = screen.query_one("#sync_enabled")
            sync_switch.value = True
            await pilot.pause()

            # Fill API token
            token_input = screen.query_one("#api_token")
            token_input.value = "test-todoist-token-abc123"
            await pilot.pause()

            # Click Continue
            btn = screen.query_one("#btn-continue")
            await pilot.click(btn)
            # Wait for async validation + write
            for _ in range(20):
                await pilot.pause()
                if not isinstance(app.screen, TodoistConfigScreen):
                    break

            # Should have moved past integration (first-time, no diff screen)
            assert not isinstance(app.screen, TodoistConfigScreen)

            # Wait for install
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            assert mock_plugin_cli["install_plugin"].called

            # Verify todoist.yaml was written with token
            todoist_yaml = mock_home / ".claude" / "todoist.yaml"
            assert todoist_yaml.exists()
            data = yaml.safe_load(todoist_yaml.read_text())
            assert data["api_token"] == "test-todoist-token-abc123"


class TestIntegrationConfigPersistence:
    """Verify config files are written correctly after the flow."""

    @pytest.mark.asyncio
    async def test_credentials_written_after_flow(
        self,
        e2e_app,
        _fresh_install,
        _no_hooks_diff,
        _mock_httpx,
        mock_plugin_cli,
        mock_home,
    ):
        """After completing flow with todoist, todoist.yaml and proj.yaml exist."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)

            # Enable sync and fill token
            screen.query_one("#sync_enabled").value = True
            screen.query_one("#api_token").value = "persist-test-token"
            await pilot.pause()

            btn = screen.query_one("#btn-continue")
            await pilot.click(btn)
            for _ in range(20):
                await pilot.pause()
                if not isinstance(app.screen, TodoistConfigScreen):
                    break

            # Wait for install
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            # Verify todoist.yaml
            todoist_yaml = mock_home / ".claude" / "todoist.yaml"
            assert todoist_yaml.exists()
            todoist_data = yaml.safe_load(todoist_yaml.read_text())
            assert todoist_data["api_token"] == "persist-test-token"

            # Verify proj.yaml has sync.todoist section
            proj_yaml = mock_home / ".claude" / "proj.yaml"
            assert proj_yaml.exists()
            proj_data = yaml.safe_load(proj_yaml.read_text())
            assert proj_data["sync"]["todoist"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_auto_sync_written_to_proj_yaml(
        self, e2e_app, _fresh_install, _no_hooks_diff, mock_plugin_cli, mock_home
    ):
        """Verify proj.yaml contains auto_sync value after flow."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)

            # Disable auto_sync, keep sync off (no validation needed)
            screen.query_one("#auto_sync").value = False
            await pilot.pause()

            btn = screen.query_one("#btn-continue")
            await pilot.click(btn)
            for _ in range(20):
                await pilot.pause()
                if not isinstance(app.screen, TodoistConfigScreen):
                    break

            # Wait for install
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            proj_yaml = mock_home / ".claude" / "proj.yaml"
            assert proj_yaml.exists()
            proj_data = yaml.safe_load(proj_yaml.read_text())
            assert proj_data["sync"]["todoist"]["auto_sync"] is False


class TestIntegrationScreenGeometry:
    """Verify widget visibility on integration screens."""

    @pytest.mark.asyncio
    async def test_todoist_screen_all_visible(
        self, e2e_app, _fresh_install, mock_plugin_cli
    ):
        """All widgets on TodoistConfigScreen are visible."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await _select_todoist_and_advance(app, pilot)

            screen = app.screen
            assert isinstance(screen, TodoistConfigScreen)
            assert_all_visible(screen)
