"""End-to-end tests for the fresh install flow.

Covers: PluginSelectScreen -> WizardScreen -> ProgressScreen,
empty selection exit, wizard cancel, and default preselection.
"""

from __future__ import annotations

import pytest

from installer.app import InstallerApp
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.wizard import WizardScreen
from installer.tui import DEFAULT_PRESELECT

from .conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_marketplace_path(marketplace_json, monkeypatch):
    """Point load_plugins at the test marketplace.json for all tests."""
    monkeypatch.setattr("installer.tui._MARKETPLACE_PATH", marketplace_json)


@pytest.fixture()
def _fresh_install(mock_plugin_cli):
    """Override mock_plugin_cli so get_installed_plugins returns empty (fresh install)."""
    mock_plugin_cli["get_installed_plugins"].return_value = []
    mock_plugin_cli["check_marketplace_registered"].return_value = False


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

            # -- PluginSelectScreen should be active --
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # Confirm defaults (sandbox, hooks, proj)
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

            # -- PluginSelectScreen geometry --
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            assert_all_visible(screen)

            # Confirm with defaults
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
    """Selecting no plugins should exit the app."""

    @pytest.mark.asyncio
    async def test_empty_selection_exits(self, e2e_app):
        """Select no plugins, confirm -> app exits."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # Deselect all, then confirm
            await pilot.press("n")  # select none
            await pilot.pause()

            btn = screen.query_one("#btn-confirm")
            await pilot.click(btn)  # confirm empty selection
            await pilot.pause()
            await pilot.pause()

        # App should have exited (no crash)
        assert app.selected_plugins == []


class TestWizardCancel:
    """Pressing escape in the WizardScreen should return to PluginSelectScreen."""

    @pytest.mark.asyncio
    async def test_wizard_cancel_returns_to_plugin_select(self, e2e_app):
        """Escape in WizardScreen -> back to PluginSelectScreen."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            # -- PluginSelectScreen --
            assert isinstance(app.screen, PluginSelectScreen)

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

            # Should be back at PluginSelectScreen
            assert isinstance(app.screen, PluginSelectScreen)


class TestDefaultPreselection:
    """Verify sandbox, hooks, proj are pre-selected on PluginSelectScreen."""

    @pytest.mark.asyncio
    async def test_default_plugins_preselected(self, e2e_app):
        """sandbox, hooks, proj are pre-selected by default."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # Verify preselection matches DEFAULT_PRESELECT
            assert screen._selected == DEFAULT_PRESELECT
            assert "sandbox" in screen._selected
            assert "hooks" in screen._selected
            assert "proj" in screen._selected

            # Non-default plugins should NOT be selected
            assert "worktree" not in screen._selected
            assert "trello" not in screen._selected
            assert "jira" not in screen._selected
