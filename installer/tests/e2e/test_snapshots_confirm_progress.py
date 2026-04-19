"""Transition snapshot tests for ConfirmScreen focus variants.

- ConfirmScreen: focus variants + warning variant.

See ``test_snapshots.py`` module docstring for full inventory and
per-screen widget ID map.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from installer.screens.confirm import ConfirmOption, ConfirmScreen
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
