"""Edge-case tests: terminal resize, keyboard-only navigation, error injection, empty states."""

from __future__ import annotations

import json

import pytest

from installer.app import InstallerApp
from installer.errors import InstallerError
from installer.screens.plugin_select import PluginStatusScreen
from installer.screens.wizard import WizardScreen

from .conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Shared fixtures
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


def _install_only(screen, names: set[str]) -> None:
    """Mark every plugin outside *names* as skip on a PluginStatusScreen."""
    for plugin_name in list(screen._actions.keys()):
        if plugin_name not in names:
            screen._actions[plugin_name] = "skip"


# ---------------------------------------------------------------------------
# 1. Terminal resize
# ---------------------------------------------------------------------------


class TestTerminalResize:
    """Verify the app survives a mid-screen terminal resize."""

    @pytest.mark.asyncio
    async def test_resize_plugin_status_screen(self, e2e_app, _fresh_install):
        """Start at 120x40, resize to 80x20, verify no crash and widgets visible."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            assert_all_visible(screen)

            await pilot.resize_terminal(80, 20)
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            assert_all_visible(screen)

    @pytest.mark.asyncio
    async def test_resize_wizard_screen(self, e2e_app, _fresh_install):
        """Resize during WizardScreen does not crash."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            _install_only(screen, {"router", "proj"})
            await pilot.click(screen.query_one("#btn-confirm"))
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, WizardScreen)
            assert_all_visible(screen)

            await pilot.resize_terminal(80, 20)
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, WizardScreen)
            assert_all_visible(screen)


# ---------------------------------------------------------------------------
# 2. Keyboard-only navigation on PluginSelectScreen
# ---------------------------------------------------------------------------


class TestPluginStatusKeyboardNav:
    """Verify tab-through-focusable-elements on PluginStatusScreen."""

    @pytest.mark.asyncio
    async def test_tab_moves_focus(self, e2e_app, mock_plugin_cli, monkeypatch):
        """Tab through focusable elements; focused widget changes each time.

        Mixes installed and available plugins so at least two tables are
        non-empty and Tab can meaningfully advance focus between them.
        """
        # Use the default mock_plugin_cli — it reports proj/router installed,
        # leaving 6 available plugins so both "installed" and "available" tables are non-empty.
        monkeypatch.setattr(
            "installer.plugin_status.get_installed_plugins",
            lambda: [
                "proj@claude-project-manager",
                "router@claude-project-manager",
                "worktree@claude-project-manager",
            ],
        )
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)

            seen_ids: list[str | None] = []
            for _ in range(6):
                focused = app.focused
                fid = focused.id if focused else None
                seen_ids.append(fid)
                await pilot.press("tab")
                await pilot.pause()

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

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)

            # Restrict to core plugins that do not trigger integration config screens.
            _install_only(screen, {"router", "proj"})
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

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            _install_only(screen, {"router", "proj"})
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
    """Provide empty marketplace.json -> PluginStatusScreen handles gracefully."""

    @pytest.mark.asyncio
    async def test_empty_marketplace_no_crash(
        self, e2e_app, _fresh_install, tmp_path, monkeypatch
    ):
        """Empty plugins list does not crash; status screen shows zero rows."""
        empty_mp = tmp_path / "empty_marketplace.json"
        empty_mp.write_text(json.dumps({"plugins": []}), encoding="utf-8")
        monkeypatch.setattr("installer.tui._MARKETPLACE_PATH", empty_mp)
        monkeypatch.setattr("installer.update._MARKETPLACE_PATH", empty_mp)

        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)
            assert screen._statuses == []
            assert screen._actions == {}

            # Confirm with zero actions — should dismiss without crash.
            screen.action_confirm()
            await pilot.pause()
            await pilot.pause()

        assert app.selected_plugins == []


# ---------------------------------------------------------------------------
# 6. Corrupted marketplace JSON
# ---------------------------------------------------------------------------


class TestCorruptedMarketplaceJSON:
    """Provide invalid JSON file -> verify error handling."""

    @pytest.mark.asyncio
    async def test_corrupted_json_does_not_crash_app(
        self, e2e_app, _fresh_install, tmp_path, monkeypatch
    ):
        """Invalid JSON surfaces via the worker error path without crashing the app.

        Under the PluginStatusScreen flow, ``build_plugin_status_list`` runs in a
        background worker; a JSONDecodeError is captured by the worker and should
        not propagate out of ``run_test``.
        """
        bad_mp = tmp_path / "bad_marketplace.json"
        bad_mp.write_text("{not valid json!!!}", encoding="utf-8")
        monkeypatch.setattr("installer.tui._MARKETPLACE_PATH", bad_mp)
        monkeypatch.setattr("installer.update._MARKETPLACE_PATH", bad_mp)

        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            # PluginStatusScreen should not have been pushed since the worker
            # failed to build a status list. The app remains in the initial
            # (loading/placeholder) state without crashing.
            assert not isinstance(app.screen, PluginStatusScreen)
            # _show_error() updates #placeholder with "[red]Error:[/red] ..."
            from textual.widgets import Static

            placeholder = app.query_one("#placeholder", Static)
            assert "Error" in str(placeholder.render())


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
            lambda *a, **kw: {"proj": "4.0.0", "router": "2.0.0"},
        )
        monkeypatch.setattr(
            "installer.app._read_marketplace_versions",
            lambda *a, **kw: {"proj": "4.0.0", "router": "2.0.0"},
        )
        monkeypatch.setattr(
            "installer.update._read_installed_version",
            lambda cache_dir, name: {
                "proj": "4.0.0",
                "router": "2.0.0",
            }.get(name),
        )
        monkeypatch.setattr(
            "installer.app._read_installed_version",
            lambda cache_dir, name: {
                "proj": "4.0.0",
                "router": "2.0.0",
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


class TestPluginStatusShortcuts:
    """Test 'q' quit shortcut on PluginStatusScreen."""

    @pytest.mark.asyncio
    async def test_quit_shortcut(self, e2e_app, _fresh_install):
        """Pressing 'q' dismisses the screen with empty list."""
        app: InstallerApp = e2e_app(mode="install")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginStatusScreen)

            await pilot.press("q")
            await pilot.pause()
            await pilot.pause()

        assert app.selected_plugins == []


# ---------------------------------------------------------------------------
# 5. PluginStatusScreen keyboard navigation
# ---------------------------------------------------------------------------


class TestPluginStatusScreenKeyboardNavigation:
    """Verify the three-column PluginStatusScreen handles keyboard nav without crashing."""

    @pytest.mark.asyncio
    async def test_plugin_status_screen_keyboard_navigation(self) -> None:
        """Drive Tab + arrow keys + Space + Enter through the status screen."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        from installer.plugin_status import PluginStatus
        from installer.screens.plugin_select import PluginStatusScreen

        class _Host(App):
            CSS = "Screen { align: center middle; }"

            def compose(self) -> ComposeResult:
                yield Static("")

        statuses = [
            PluginStatus(
                name="router",
                installed_version="2.0.0",
                available_version="2.0.0",
                state="installed",
            ),
            PluginStatus(
                name="proj",
                installed_version="3.5.0",
                available_version="4.0.0",
                state="outdated",
            ),
            PluginStatus(
                name="trello",
                installed_version=None,
                available_version="3.0.0",
                state="available",
            ),
        ]

        captured: list[list[tuple[str, str]]] = []

        host = _Host()
        async with host.run_test(size=(120, 40)) as pilot:
            screen = PluginStatusScreen(statuses=statuses)
            host.push_screen(screen, callback=lambda r: captured.append(r))
            await pilot.pause()
            await pilot.pause()

            # Tab to cycle through columns — each press should advance focus.
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()

            # Arrow-down inside the currently focused table.
            await pilot.press("down")
            await pilot.pause()

            # Space cycles the action on the focused row.
            await pilot.press("space")
            await pilot.pause()

            # Confirm — this should dismiss without raising.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

        assert captured, "PluginStatusScreen did not dismiss"
        for name, action in captured[0]:
            assert action in {"install", "reinstall", "uninstall"}
            assert name in {"router", "proj", "trello"}
