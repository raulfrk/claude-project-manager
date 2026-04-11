"""End-to-end tests for the fresh install flow.

Covers: PluginStatusScreen -> WizardScreen -> ProgressScreen,
empty selection exit, wizard cancel, and default preselection.
"""

from __future__ import annotations

import pytest

from installer.app import InstallerApp
from installer.screens.plugin_select import PluginStatusScreen
from installer.screens.wizard import WizardScreen

from .conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Helpers
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
    # plugin_status.py binds get_installed_plugins at import; rebind it too.
    monkeypatch.setattr("installer.plugin_status.get_installed_plugins", lambda: [])


def _install_only(screen, names: set[str]) -> None:
    """Mark every plugin outside *names* as skip on a PluginStatusScreen."""
    for plugin_name in list(screen._actions.keys()):
        if plugin_name not in names:
            screen._actions[plugin_name] = "skip"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullInstallFlow:
    """PluginSelectScreen -> WizardScreen -> ProgressScreen end-to-end."""

    @pytest.mark.asyncio
    async def test_full_install_flow(self, e2e_app, _fresh_install, mock_plugin_cli):
        """Fresh install: select plugins -> wizard -> progress -> completes."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            # -- PluginStatusScreen should be active --
            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)

            # Restrict install to the core plugin set that doesn't trigger
            # integration config screens (keeping parity with the original
            # DEFAULT_PRESELECT-based test).
            _install_only(screen, {"sandbox", "router", "proj"})

            btn = screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            # -- WizardScreen should be active --
            screen = app.screen
            assert isinstance(screen, WizardScreen)

            # Submit with default values
            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            # Wait for the install worker to complete.
            # With mocked plugin_cli functions the worker completes instantly,
            # so ProgressScreen may already have auto-dismissed.  Instead of
            # asserting a transient screen state, verify the flow executed by
            # checking the mocked install_plugin was called.
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            assert mock_plugin_cli["install_plugin"].called, (
                "install_plugin was never called — install flow did not complete"
            )

    @pytest.mark.asyncio
    async def test_geometry_on_each_screen(
        self, e2e_app, _fresh_install, mock_plugin_cli
    ):
        """Verify no hidden widgets on each screen during the install flow."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            # -- PluginStatusScreen geometry --
            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            assert_all_visible(screen)
            _install_only(screen, {"sandbox", "router", "proj"})

            btn = screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            # -- WizardScreen geometry --
            screen = app.screen
            assert isinstance(screen, WizardScreen)
            assert_all_visible(screen)

            # Submit wizard
            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            # Wait for the install worker to complete.
            # ProgressScreen auto-dismisses instantly with mocked functions,
            # so verify the flow completed instead of asserting the transient screen.
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            assert mock_plugin_cli["install_plugin"].called, (
                "install_plugin was never called — install flow did not complete"
            )


class TestEmptySelection:
    """Skipping all plugin actions should exit the app."""

    @pytest.mark.asyncio
    async def test_empty_selection_exits(self, e2e_app, _fresh_install):
        """Set every action to skip, confirm -> app exits."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)

            # Force every plugin's action to "skip" and confirm.
            for name in list(screen._actions.keys()):
                screen._actions[name] = "skip"
            screen.action_confirm()
            await pilot.pause()
            await pilot.pause()

        assert app.selected_plugins == []


class TestWizardCancel:
    """Pressing escape in the WizardScreen should return to the status screen."""

    @pytest.mark.asyncio
    async def test_wizard_cancel_returns_to_plugin_select(
        self, e2e_app, _fresh_install
    ):
        """Escape in WizardScreen -> back to PluginStatusScreen."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, PluginStatusScreen)

            # Confirm defaults to advance to wizard
            btn = app.screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            # -- WizardScreen --
            assert isinstance(app.screen, WizardScreen)

            # Cancel wizard
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, PluginStatusScreen)


class TestStatusScreenDefaults:
    """Verify fresh-install state seeds all marketplace plugins as 'available'."""

    @pytest.mark.asyncio
    async def test_fresh_install_plugins_are_available(self, e2e_app, _fresh_install):
        """With nothing installed, every status.state is 'available'."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            assert screen._statuses, "Expected marketplace plugins to be loaded"
            for status in screen._statuses:
                assert status.state == "available"
                assert screen._actions[status.name] == "install"


class TestFlowViaStatusScreen:
    """Full pilot-driven install through PluginStatusScreen -> wizard -> summary."""

    @pytest.mark.asyncio
    async def test_install_flow_via_status_screen(
        self, e2e_app, _fresh_install, mock_plugin_cli
    ):
        """Status screen -> wizard -> summary with install_plugin called."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, PluginStatusScreen)
            _install_only(app.screen, {"sandbox", "router", "proj"})
            btn = app.screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, WizardScreen)
            btn = app.screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()
            await pilot.pause()

            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            assert mock_plugin_cli["install_plugin"].called, (
                "install_plugin was never called — flow did not reach the worker"
            )
