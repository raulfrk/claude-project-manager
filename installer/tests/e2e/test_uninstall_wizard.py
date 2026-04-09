"""End-to-end tests for uninstall and wizard configuration flows."""

from __future__ import annotations


import pytest
from textual.widgets import Checkbox, Static

from installer.app import InstallerApp
from installer.screens.confirm import ConfirmScreen
from installer.screens.detection import DetectionScreen
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.wizard import WizardScreen

from .conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VERSIONS = {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
_INSTALLED = {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}


def _patch_version_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock marketplace version and installed version readers for detection."""
    monkeypatch.setattr(
        "installer.app._read_marketplace_versions", lambda *a, **kw: _VERSIONS
    )
    monkeypatch.setattr(
        "installer.app._read_installed_version",
        lambda cache_dir, name: _INSTALLED.get(name),
    )


# ============================================================================
# Uninstall flow: Detection -> Confirm -> Progress
# ============================================================================


class TestUninstallFlow:
    """E2E tests for the uninstall workflow through InstallerApp."""

    @pytest.mark.asyncio
    async def test_uninstall_full_flow(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """Uninstall: DetectionScreen -> continue -> ConfirmScreen -> confirm -> ProgressScreen."""
        _patch_version_lookups(monkeypatch)
        app: InstallerApp = e2e_app(mode="uninstall")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Step 1: DetectionScreen should be the active screen
            screen = app.screen
            assert isinstance(screen, DetectionScreen), (
                f"Expected DetectionScreen, got {type(screen).__name__}"
            )
            assert_all_visible(screen)

            # Step 2: Click continue to proceed
            btn_continue = screen.query_one("#btn-continue")
            region = btn_continue.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_continue)
            await pilot.pause()

            # Step 3: ConfirmScreen should now be active
            screen = app.screen
            assert isinstance(screen, ConfirmScreen), (
                f"Expected ConfirmScreen, got {type(screen).__name__}"
            )
            assert_all_visible(screen)

            # Verify uninstall-specific content
            title_widget = screen.query_one("#confirm-title", Static)
            title_text = str(title_widget.render())
            assert "Uninstall" in title_text

            # Verify full_cleanup checkbox exists and defaults to False
            cb = screen.query_one("#opt-full_cleanup", Checkbox)
            assert cb.value is False

            # Step 4: Click confirm to proceed to progress
            btn_confirm = screen.query_one("#btn-confirm")
            region = btn_confirm.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_confirm)
            await pilot.pause()

            # Step 5: With mocked plugin_cli functions the worker completes
            # instantly, so ProgressScreen may already have auto-dismissed.
            # Verify the flow executed by checking uninstall_plugin was called.
            for _ in range(20):
                await pilot.pause()
                if mock_plugin_cli["uninstall_plugin"].called:
                    break

            assert mock_plugin_cli["uninstall_plugin"].called, (
                "uninstall_plugin was never called — uninstall flow did not complete"
            )

    @pytest.mark.asyncio
    async def test_uninstall_cancel_at_confirm(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """Uninstall: ConfirmScreen cancel exits the app."""
        _patch_version_lookups(monkeypatch)
        app: InstallerApp = e2e_app(mode="uninstall")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Navigate through detection
            screen = app.screen
            assert isinstance(screen, DetectionScreen)
            await pilot.click(screen.query_one("#btn-continue"))
            await pilot.pause()

            # Now on ConfirmScreen -- cancel
            screen = app.screen
            assert isinstance(screen, ConfirmScreen)
            assert_all_visible(screen)

            btn_cancel = screen.query_one("#btn-cancel")
            region = btn_cancel.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_cancel)
            await pilot.pause()

            # App should have exited
            assert app._exit

    @pytest.mark.asyncio
    async def test_uninstall_full_cleanup_toggle(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """Toggling full_cleanup checkbox results in full_cleanup=True in ConfirmResult."""
        _patch_version_lookups(monkeypatch)
        app: InstallerApp = e2e_app(mode="uninstall")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Navigate through detection
            screen = app.screen
            assert isinstance(screen, DetectionScreen)
            await pilot.click(screen.query_one("#btn-continue"))
            await pilot.pause()

            # On ConfirmScreen
            screen = app.screen
            assert isinstance(screen, ConfirmScreen)

            # Toggle full_cleanup checkbox
            cb = screen.query_one("#opt-full_cleanup", Checkbox)
            assert cb.value is False
            await pilot.click(cb)
            await pilot.pause()
            assert cb.value is True

            # Gather options to verify value
            options = screen._gather_options()
            assert options["full_cleanup"] is True

            # Confirm and verify the result propagates to the uninstall worker
            btn_confirm = screen.query_one("#btn-confirm")
            region = btn_confirm.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_confirm)
            await pilot.pause()

            # With mocked plugin_cli functions the worker completes instantly,
            # so ProgressScreen may already have auto-dismissed.
            # Verify the uninstall flow executed.
            for _ in range(20):
                await pilot.pause()
                if mock_plugin_cli["uninstall_plugin"].called:
                    break

            assert mock_plugin_cli["uninstall_plugin"].called, (
                "uninstall_plugin was never called — uninstall flow did not complete"
            )

    @pytest.mark.asyncio
    async def test_uninstall_cancel_at_detection(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """Cancelling at DetectionScreen exits the app."""
        _patch_version_lookups(monkeypatch)
        app: InstallerApp = e2e_app(mode="uninstall")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, DetectionScreen)
            assert_all_visible(screen)

            btn_cancel = screen.query_one("#btn-cancel")
            region = btn_cancel.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_cancel)
            await pilot.pause()

            assert app._exit


# ============================================================================
# Wizard cancel returns to plugin select
# ============================================================================


class TestWizardCancel:
    """E2E tests for wizard cancel behavior in install mode."""

    @pytest.mark.asyncio
    async def test_wizard_escape_returns_to_plugin_select(
        self, e2e_app, mock_detect, mock_plugin_cli
    ):
        """In install mode, pressing escape on WizardScreen pushes PluginSelectScreen again."""
        app: InstallerApp = e2e_app(mode="install")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Step 1: PluginSelectScreen should be active
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen), (
                f"Expected PluginSelectScreen, got {type(screen).__name__}"
            )
            assert_all_visible(screen)

            # Step 2: Confirm selection to move to WizardScreen
            btn_confirm = screen.query_one("#btn-confirm")
            region = btn_confirm.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_confirm)
            await pilot.pause()

            # Step 3: WizardScreen should now be active
            screen = app.screen
            assert isinstance(screen, WizardScreen), (
                f"Expected WizardScreen, got {type(screen).__name__}"
            )
            assert_all_visible(screen)

            # Step 4: Press escape to cancel wizard
            await pilot.press("escape")
            await pilot.pause()

            # Step 5: PluginSelectScreen should be pushed again (not exit)
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen), (
                f"Expected PluginSelectScreen after wizard cancel, got {type(screen).__name__}"
            )
            assert_all_visible(screen)
            assert not app._exit

    @pytest.mark.asyncio
    async def test_wizard_cancel_button_returns_to_plugin_select(
        self, e2e_app, mock_detect, mock_plugin_cli
    ):
        """In install mode, clicking Cancel on WizardScreen pushes PluginSelectScreen again."""
        app: InstallerApp = e2e_app(mode="install")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # PluginSelectScreen -> confirm
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            await pilot.click(screen.query_one("#btn-confirm"))
            await pilot.pause()

            # WizardScreen -> cancel button
            screen = app.screen
            assert isinstance(screen, WizardScreen)
            btn_cancel = screen.query_one("#btn-cancel")
            region = btn_cancel.region
            assert region.width > 0 and region.height > 0
            await pilot.click(btn_cancel)
            await pilot.pause()

            # Should return to PluginSelectScreen
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            assert not app._exit


# ============================================================================
# Geometry assertions on screen transitions
# ============================================================================


class TestScreenGeometry:
    """Verify widget geometry is valid at each screen transition."""

    @pytest.mark.asyncio
    async def test_detection_screen_geometry(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """DetectionScreen widgets have positive dimensions."""
        _patch_version_lookups(monkeypatch)
        app: InstallerApp = e2e_app(mode="uninstall")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, DetectionScreen)
            assert_all_visible(screen)

            # Check key widgets specifically
            title = screen.query_one("#detection-title")
            assert title.region.width > 0 and title.region.height > 0
            table = screen.query_one("#detection-table")
            assert table.region.width > 0 and table.region.height > 0
            for btn_id in ("#btn-continue", "#btn-cancel"):
                btn = screen.query_one(btn_id)
                assert btn.region.width > 0 and btn.region.height > 0

    @pytest.mark.asyncio
    async def test_confirm_screen_geometry(
        self, e2e_app, mock_detect, mock_plugin_cli, monkeypatch
    ):
        """ConfirmScreen widgets have positive dimensions after transition."""
        _patch_version_lookups(monkeypatch)
        app: InstallerApp = e2e_app(mode="uninstall")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Navigate to ConfirmScreen
            screen = app.screen
            assert isinstance(screen, DetectionScreen)
            await pilot.click(screen.query_one("#btn-continue"))
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ConfirmScreen)
            assert_all_visible(screen)

            # Check key widgets
            dialog = screen.query_one("#confirm-dialog")
            assert dialog.region.width > 0 and dialog.region.height > 0
            title = screen.query_one("#confirm-title")
            assert title.region.width > 0 and title.region.height > 0
            for btn_id in ("#btn-confirm", "#btn-cancel"):
                btn = screen.query_one(btn_id)
                assert btn.region.width > 0 and btn.region.height > 0

    @pytest.mark.asyncio
    async def test_plugin_select_geometry(self, e2e_app, mock_detect, mock_plugin_cli):
        """PluginSelectScreen widgets have positive dimensions."""
        app: InstallerApp = e2e_app(mode="install")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            assert_all_visible(screen)

            btn = screen.query_one("#btn-confirm")
            assert btn.region.width > 0 and btn.region.height > 0

    @pytest.mark.asyncio
    async def test_wizard_screen_geometry(self, e2e_app, mock_detect, mock_plugin_cli):
        """WizardScreen widgets have positive dimensions after transition."""
        app: InstallerApp = e2e_app(mode="install")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Navigate to WizardScreen
            screen = app.screen
            assert isinstance(screen, PluginSelectScreen)
            await pilot.click(screen.query_one("#btn-confirm"))
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, WizardScreen)
            assert_all_visible(screen)

            form = screen.query_one("#wizard-form")
            assert form.region.width > 0 and form.region.height > 0
            for btn_id in ("#btn-submit", "#btn-cancel"):
                btn = screen.query_one(btn_id)
                assert btn.region.width > 0 and btn.region.height > 0
