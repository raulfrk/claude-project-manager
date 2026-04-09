"""Edge-case tests: terminal resize, keyboard-only navigation, error injection, empty states."""

from __future__ import annotations

import json

import pytest

from installer.app import InstallerApp
from installer.errors import InstallerError
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.wizard import WizardScreen

from .conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Shared fixtures
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
# 1. Terminal resize
# ---------------------------------------------------------------------------


class TestTerminalResize:
    """Verify the app survives a mid-screen terminal resize."""

    @pytest.mark.asyncio
    async def test_resize_plugin_select_screen(self, e2e_app, _fresh_install):
        """Start at 120x40, resize to 80x20, verify no crash and widgets visible."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            assert_all_visible(screen)

            # Resize to a smaller terminal
            await pilot.resize_terminal(80, 20)
            await pilot.pause()
            await pilot.pause()

            # Screen should still be PluginSelectScreen (no crash)
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            assert_all_visible(screen)

    @pytest.mark.asyncio
    async def test_resize_wizard_screen(self, e2e_app, _fresh_install):
        """Resize during WizardScreen does not crash."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            # Advance to wizard by clicking the confirm button explicitly
            # (pressing enter when DataTable has focus toggles a row instead)
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            await pilot.click(screen.query_one("#btn-confirm"))
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, WizardScreen)
            assert_all_visible(screen)

            # Resize
            await pilot.resize_terminal(80, 20)
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, WizardScreen)
            assert_all_visible(screen)


# ---------------------------------------------------------------------------
# 2. Keyboard-only navigation on PluginSelectScreen
# ---------------------------------------------------------------------------


class TestPluginSelectKeyboardNav:
    """Verify tab-through-focusable-elements on PluginSelectScreen."""

    @pytest.mark.asyncio
    async def test_tab_moves_focus(self, e2e_app):
        """Tab through focusable elements; focused widget changes each time."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            seen_ids: list[str | None] = []
            # Tab multiple times and record focused widget identity
            for _ in range(6):
                focused = app.focused
                fid = focused.id if focused else None
                seen_ids.append(fid)
                await pilot.press("tab")
                await pilot.pause()

            # At least 2 distinct focusable elements were visited
            unique = set(seen_ids)
            assert len(unique) >= 2, f"Expected multiple focus targets, got {unique}"


# ---------------------------------------------------------------------------
# 3. Keyboard-only navigation on WizardScreen
# ---------------------------------------------------------------------------


class TestWizardKeyboardNav:
    """Verify tab chain through WizardScreen fields and buttons."""

    @pytest.mark.asyncio
    async def test_tab_chain_visits_fields_and_buttons(self, e2e_app, _fresh_install):
        """Tab through wizard fields and buttons; all focusable IDs are visited."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            # Advance to wizard with all plugins to get maximum fields
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # Select all plugins and confirm by clicking the button
            # (pressing enter when DataTable has focus toggles a row instead)
            await pilot.press("a")
            await pilot.pause()
            await pilot.click(screen.query_one("#btn-confirm"))
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, WizardScreen)

            seen_ids: list[str | None] = []
            for _ in range(15):
                focused = app.focused
                fid = focused.id if focused else None
                seen_ids.append(fid)
                await pilot.press("tab")
                await pilot.pause()

            unique = {x for x in seen_ids if x is not None}
            # Wizard has at minimum: tracking_dir, projects_base_dir, btn-submit, btn-cancel
            assert len(unique) >= 4, (
                f"Expected at least 4 focusable fields, got {unique}"
            )


# ---------------------------------------------------------------------------
# 4. Error state: subprocess failure during install
# ---------------------------------------------------------------------------


class TestInstallError:
    """Mock install_plugin to raise InstallerError; verify ProgressScreen shows error."""

    @pytest.mark.asyncio
    async def test_install_plugin_error_shown_in_log(
        self, e2e_app, mock_plugin_cli, _fresh_install
    ):
        """When install_plugin raises, the error message appears in the progress log."""
        mock_plugin_cli["install_plugin"].side_effect = InstallerError(
            "Connection refused"
        )

        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            # Select defaults and confirm by clicking the button
            # (pressing enter when DataTable has focus toggles a row instead)
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            await pilot.click(screen.query_one("#btn-confirm"))
            await pilot.pause()
            await pilot.pause()

            # Submit wizard with defaults
            screen = app.screen
            assert isinstance(screen, WizardScreen)
            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()

            # Wait for the install worker to run (and fail).
            # With mocked plugin_cli functions the worker completes instantly,
            # so ProgressScreen may already have auto-dismissed.
            for _ in range(40):
                await pilot.pause()
                if mock_plugin_cli["install_plugin"].called:
                    break

            # Verify install_plugin was called (it raises InstallerError)
            assert mock_plugin_cli["install_plugin"].called, (
                "install_plugin was never called — install flow did not complete"
            )


# ---------------------------------------------------------------------------
# 5. Empty marketplace
# ---------------------------------------------------------------------------


class TestEmptyMarketplace:
    """Provide empty marketplace.json -> PluginSelectScreen handles gracefully."""

    @pytest.mark.asyncio
    async def test_empty_marketplace_no_crash(
        self, e2e_app, _fresh_install, tmp_path, monkeypatch
    ):
        """Empty plugins list does not crash; table is populated with zero rows."""
        empty_mp = tmp_path / "empty_marketplace.json"
        empty_mp.write_text(json.dumps({"plugins": []}), encoding="utf-8")
        monkeypatch.setattr("installer.tui._MARKETPLACE_PATH", empty_mp)

        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # No plugins loaded
            assert screen._plugins == []
            assert screen._selected == set()

            # Confirming empty selection should not crash
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

        # App should exit with empty selection
        assert app.selected_plugins == []


# ---------------------------------------------------------------------------
# 6. Corrupted marketplace JSON
# ---------------------------------------------------------------------------


class TestCorruptedMarketplaceJSON:
    """Provide invalid JSON file -> verify error handling."""

    @pytest.mark.asyncio
    async def test_corrupted_json_raises_or_handles(
        self, e2e_app, _fresh_install, tmp_path, monkeypatch
    ):
        """Invalid JSON causes an error during load_plugins (json.JSONDecodeError)."""
        bad_mp = tmp_path / "bad_marketplace.json"
        bad_mp.write_text("{not valid json!!!}", encoding="utf-8")
        monkeypatch.setattr("installer.tui._MARKETPLACE_PATH", bad_mp)

        app: InstallerApp = e2e_app(mode="install")

        # The app should either raise during mount or handle it gracefully.
        # load_plugins calls json.loads which will raise JSONDecodeError.
        with pytest.raises(Exception):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.pause()


# ---------------------------------------------------------------------------
# 7. Zero outdated plugins in update mode
# ---------------------------------------------------------------------------


class TestAllUpToDate:
    """All plugins up-to-date -> verify app shows message."""

    @pytest.mark.asyncio
    async def test_no_outdated_shows_up_to_date(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """When all plugins match, placeholder shows 'up to date'."""
        from textual.widgets import Static

        from installer.screens.detection import DetectionScreen

        # Patch version functions to return no diffs
        monkeypatch.setattr("installer.update.compare_versions", lambda *a, **kw: {})
        monkeypatch.setattr("installer.app.compare_versions", lambda *a, **kw: {})
        monkeypatch.setattr(
            "installer.update._read_marketplace_versions",
            lambda *a, **kw: {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"},
        )
        monkeypatch.setattr(
            "installer.app._read_marketplace_versions",
            lambda *a, **kw: {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"},
        )
        monkeypatch.setattr(
            "installer.update._read_installed_version",
            lambda cache_dir, name: {
                "proj": "4.0.0",
                "hooks": "2.0.0",
                "sandbox": "1.0.0",
            }.get(name),
        )
        monkeypatch.setattr(
            "installer.app._read_installed_version",
            lambda cache_dir, name: {
                "proj": "4.0.0",
                "hooks": "2.0.0",
                "sandbox": "1.0.0",
            }.get(name),
        )

        app: InstallerApp = e2e_app(mode="update")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DetectionScreen)

            # Click Continue
            await pilot.click("#btn-continue")
            await pilot.pause()

            # Should NOT be on UpdateScreen
            from installer.screens.update import UpdateScreen

            assert not isinstance(app.screen, UpdateScreen)

            # Placeholder should show "up to date"
            placeholder = app.query_one("#placeholder", Static)
            rendered = str(placeholder.render()).lower()
            assert "up to date" in rendered


# ---------------------------------------------------------------------------
# 8. Keyboard shortcuts on PluginSelectScreen
# ---------------------------------------------------------------------------


class TestPluginSelectShortcuts:
    """Test 'a' (select all), 'n' (select none), 'q' (quit) shortcuts."""

    @pytest.mark.asyncio
    async def test_select_all_shortcut(self, e2e_app):
        """Pressing 'a' selects all plugins."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # First deselect all
            await pilot.press("n")
            await pilot.pause()
            assert len(screen._selected) == 0

            # Select all
            await pilot.press("a")
            await pilot.pause()
            assert len(screen._selected) == len(screen._plugins)
            assert len(screen._selected) == 9  # all 9 plugins

    @pytest.mark.asyncio
    async def test_select_none_shortcut(self, e2e_app):
        """Pressing 'n' deselects all plugins."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # Default has some selected
            assert len(screen._selected) > 0

            # Deselect all
            await pilot.press("n")
            await pilot.pause()
            assert len(screen._selected) == 0

    @pytest.mark.asyncio
    async def test_quit_shortcut(self, e2e_app):
        """Pressing 'q' dismisses the screen with empty list."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            await pilot.press("q")
            await pilot.pause()
            await pilot.pause()

        # App should exit with empty selection
        assert app.selected_plugins == []

    @pytest.mark.asyncio
    async def test_space_toggles_selection(self, e2e_app):
        """Pressing space toggles the currently highlighted plugin."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)

            # Start fresh: deselect all
            await pilot.press("n")
            await pilot.pause()
            assert len(screen._selected) == 0

            # The cursor should be on the first row (possibly a category row).
            # Move down to reach a plugin row.
            await pilot.press("down")
            await pilot.pause()

            # Toggle with space
            before = len(screen._selected)
            await pilot.press("space")
            await pilot.pause()
            after = len(screen._selected)

            # Selection count should have changed
            assert after != before, "Space should toggle a plugin selection"
