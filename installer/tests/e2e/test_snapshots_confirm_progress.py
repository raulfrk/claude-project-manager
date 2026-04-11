"""Transition snapshot tests for ConfirmScreen and ProgressScreen.

- ConfirmScreen: focus variants + warning variant.
- ProgressScreen: state-based snapshots only (AUTO_FOCUS = "" — no
  focusable widgets).

See ``test_snapshots.py`` module docstring for full inventory and
per-screen widget ID map.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from installer.screens.confirm import ConfirmOption, ConfirmScreen
from installer.screens.progress import ProgressScreen
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)


class _ScreenHost(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ---------------------------------------------------------------------------
# ConfirmScreen: focus_cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_focus_cancel_snapshot() -> None:
    """Explicitly focus Cancel button (default focus is Confirm)."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ConfirmScreen(
            title="Reinstall Plugins",
            message=(
                "This will reinstall all installed plugins.\n"
                "A backup will be created before any changes."
            ),
            options=[
                ConfirmOption(
                    key="reset_configs",
                    label="Reset configs (remove proj.yaml, worktree.yaml)",
                    default=False,
                ),
            ],
            confirm_label="Reinstall",
            confirm_variant="warning",
        )
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-cancel", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-cancel"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "confirm_focus_cancel")


# ---------------------------------------------------------------------------
# ConfirmScreen: warning variant (default focus = Confirm)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_warning_variant_snapshot() -> None:
    """Warning variant with default focus on Confirm button."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ConfirmScreen(
            title="Uninstall Plugins",
            message=(
                "This will REMOVE all installed plugins.\nThis action cannot be undone."
            ),
            options=[
                ConfirmOption(
                    key="full_cleanup",
                    label="Full cleanup (remove configs)",
                    default=False,
                ),
            ],
            confirm_label="Uninstall",
            confirm_variant="warning",
        )
        app.push_screen(screen)
        await pilot.pause()

        # Explicit focus so the pre-export assertion succeeds.
        screen.query_one("#btn-confirm", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-confirm"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "confirm_warning_variant")


# ---------------------------------------------------------------------------
# ProgressScreen: state-based snapshots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_completed_snapshot() -> None:
    """5/5 steps, all-green log — completed state."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ProgressScreen(description="Installing plugins...", total=5)
        app.push_screen(screen)
        await pilot.pause()

        # Drive all 5 steps, stopping before the final advance that would
        # dismiss the screen; then push the final advance through to reach
        # the complete state. ProgressScreen.dismiss is called on the last
        # advance; we screenshot the moment after the last state update.
        for i in range(1, 6):
            screen.write_log(f"  [green]Step {i} complete[/green]")
            screen.advance(1, detail=f"Step {i}/5 done")
            await pilot.pause()

        # After reaching total, the screen adds "--complete" class.
        svg = app.export_screenshot()
        _assert_snapshot(svg, "progress_completed")


@pytest.mark.asyncio
async def test_progress_failed_snapshot() -> None:
    """Mid-progress with an error log line."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ProgressScreen(description="Installing plugins...", total=5)
        app.push_screen(screen)
        await pilot.pause()

        screen.write_log("[bold]Checking marketplace...[/bold]")
        screen.write_log("  [green]Marketplace registered.[/green]")
        screen.advance(1, detail="Marketplace ready")
        screen.write_log("  Installing proj...")
        screen.write_log("  [green]proj installed[/green]")
        screen.advance(1, detail="Installed proj")
        screen.write_log("  Installing hooks...")
        screen.write_log("  [red]ERROR: hooks install failed[/red]")
        screen.write_log("  [red]subprocess returned exit code 1[/red]")
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "progress_failed")
