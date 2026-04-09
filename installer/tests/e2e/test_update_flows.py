"""End-to-end tests for update, reinstall, and detection cancel flows."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.app import InstallerApp
from installer.screens.confirm import ConfirmScreen
from installer.screens.detection import DetectionScreen
from installer.screens.update import UpdateScreen
from installer.tests.e2e.conftest import assert_all_visible


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_compare_versions(monkeypatch, diffs: dict[str, tuple[str, str]]):
    """Mock ``installer.update.compare_versions`` to return *diffs*."""
    monkeypatch.setattr("installer.update.compare_versions", lambda *a, **kw: diffs)
    # Also patch the import in app.py which may bind at import time
    monkeypatch.setattr("installer.app.compare_versions", lambda *a, **kw: diffs)


def _patch_marketplace_versions(monkeypatch, versions: dict[str, str]):
    """Mock ``_read_marketplace_versions`` in both modules."""
    monkeypatch.setattr(
        "installer.update._read_marketplace_versions", lambda *a, **kw: versions
    )
    monkeypatch.setattr(
        "installer.app._read_marketplace_versions", lambda *a, **kw: versions
    )


def _patch_installed_version(monkeypatch, mapping: dict[str, str | None]):
    """Mock ``_read_installed_version`` to return from a name->version dict."""

    def _fake(cache_dir: Path, plugin_name: str) -> str | None:
        return mapping.get(plugin_name)

    monkeypatch.setattr("installer.update._read_installed_version", _fake)
    monkeypatch.setattr("installer.app._read_installed_version", _fake)


# ---------------------------------------------------------------------------
# 1. Update flow: Detection -> UpdateScreen -> select -> ProgressScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_flow_detection_to_progress(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """Update mode walks through Detection -> Update -> Progress screens."""
    diffs = {
        "proj": ("3.0.0", "4.0.0"),
        "hooks": ("1.5.0", "2.0.0"),
    }
    _patch_compare_versions(monkeypatch, diffs)
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "3.0.0", "hooks": "1.5.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="update")

    async with app.run_test(size=(120, 40)) as pilot:
        # Should start on DetectionScreen
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetectionScreen), (
            f"Expected DetectionScreen, got {type(screen).__name__}"
        )
        assert_all_visible(screen)

        # Click Continue to proceed
        await pilot.click("#btn-continue")
        await pilot.pause()

        # Should now be on UpdateScreen
        screen = app.screen
        assert isinstance(screen, UpdateScreen), (
            f"Expected UpdateScreen, got {type(screen).__name__}"
        )
        assert_all_visible(screen)

        # Verify outdated plugins are shown
        table = screen.query_one("#update-table")
        assert table.row_count == 2

        # Click "Update All" to proceed
        await pilot.click("#btn-update-all")
        await pilot.pause()

        # With mocked plugin_cli functions the worker completes instantly,
        # so ProgressScreen may already have auto-dismissed.  Verify the
        # flow executed by checking update_plugin was called.
        for _ in range(20):
            await pilot.pause()
            if mock_plugin_cli["update_plugin"].called:
                break

        assert mock_plugin_cli["update_plugin"].called, (
            "update_plugin was never called — update flow did not complete"
        )


# ---------------------------------------------------------------------------
# 2. Reinstall flow: Detection -> ConfirmScreen -> ProgressScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reinstall_flow_detection_to_progress(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """Reinstall mode walks through Detection -> Confirm -> Progress screens."""
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="reinstall")

    async with app.run_test(size=(120, 40)) as pilot:
        # Should start on DetectionScreen
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetectionScreen), (
            f"Expected DetectionScreen, got {type(screen).__name__}"
        )
        assert_all_visible(screen)

        # Click Continue
        await pilot.click("#btn-continue")
        await pilot.pause()

        # Should now be on ConfirmScreen with reset_configs toggle
        screen = app.screen
        assert isinstance(screen, ConfirmScreen), (
            f"Expected ConfirmScreen, got {type(screen).__name__}"
        )
        assert_all_visible(screen)

        # Verify the reset_configs checkbox is present
        checkbox = screen.query_one("#opt-reset_configs")
        assert checkbox is not None
        assert checkbox.value is False  # default is off

        # Click Confirm to proceed
        await pilot.click("#btn-confirm")
        await pilot.pause()

        # With mocked plugin_cli functions the worker completes instantly,
        # so ProgressScreen may already have auto-dismissed.  Verify the
        # flow executed by checking uninstall_plugin and install_plugin were called.
        for _ in range(20):
            await pilot.pause()
            if mock_plugin_cli["install_plugin"].called:
                break

        assert mock_plugin_cli["install_plugin"].called, (
            "install_plugin was never called — reinstall flow did not complete"
        )


# ---------------------------------------------------------------------------
# 3. Detection cancel: DetectionScreen -> app exits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_cancel_exits_app(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """Clicking Cancel on the DetectionScreen exits the app."""
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="update")

    async with app.run_test(size=(120, 40)) as pilot:
        # Should start on DetectionScreen
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetectionScreen), (
            f"Expected DetectionScreen, got {type(screen).__name__}"
        )

        # Click Cancel
        await pilot.click("#btn-cancel")
        await pilot.pause()

        # App should have exited (return code set or screen stack empty)
        # After exit, the app's return code is set
        assert app.return_code is not None or len(app.screen_stack) <= 1


# ---------------------------------------------------------------------------
# 4. Update with no outdated plugins: shows "up to date" message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_no_outdated_shows_message(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """When all plugins are up to date, the placeholder shows a message."""
    # Empty diffs = nothing outdated
    _patch_compare_versions(monkeypatch, {})
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="update")

    async with app.run_test(size=(120, 40)) as pilot:
        # Should start on DetectionScreen
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetectionScreen), (
            f"Expected DetectionScreen, got {type(screen).__name__}"
        )

        # Click Continue — no diffs, so it should NOT push UpdateScreen
        await pilot.click("#btn-continue")
        await pilot.pause()

        # Should NOT be on UpdateScreen; should be back on default screen
        screen = app.screen
        assert not isinstance(screen, UpdateScreen), (
            "Should not show UpdateScreen when nothing is outdated"
        )

        # The placeholder should show "up to date" message
        from textual.widgets import Static

        placeholder = app.query_one("#placeholder", Static)
        rendered = placeholder.render()
        assert "up to date" in str(rendered).lower()


# ---------------------------------------------------------------------------
# 5. Geometry: assert_all_visible on each screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_screen_geometry(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """All widgets on DetectionScreen have positive dimensions."""
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="update")

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetectionScreen)
        assert_all_visible(screen)


@pytest.mark.asyncio
async def test_update_screen_geometry(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """All widgets on UpdateScreen have positive dimensions."""
    diffs = {"proj": ("3.0.0", "4.0.0")}
    _patch_compare_versions(monkeypatch, diffs)
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "3.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="update")

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Navigate to UpdateScreen
        await pilot.click("#btn-continue")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, UpdateScreen)
        assert_all_visible(screen)


@pytest.mark.asyncio
async def test_confirm_screen_geometry(
    e2e_app,
    mock_detect,
    mock_plugin_cli,
    monkeypatch,
):
    """All widgets on ConfirmScreen (reinstall) have positive dimensions."""
    _patch_marketplace_versions(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )
    _patch_installed_version(
        monkeypatch, {"proj": "4.0.0", "hooks": "2.0.0", "sandbox": "1.0.0"}
    )

    app: InstallerApp = e2e_app(mode="reinstall")

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Navigate to ConfirmScreen
        await pilot.click("#btn-continue")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, ConfirmScreen)
        assert_all_visible(screen)
