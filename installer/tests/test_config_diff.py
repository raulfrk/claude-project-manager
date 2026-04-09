"""TUI tests for ConfigDiffScreen."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from installer.screens.config_diff import ConfigDiffScreen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TestApp(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ============================================================================
# ConfigDiffScreen — Layout
# ============================================================================


class TestConfigDiffScreenLayout:
    """Tests for ConfigDiffScreen widget layout and content."""

    @pytest.mark.asyncio
    async def test_title_contains_service_name(self):
        """Title Static contains the service name."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Todoist", diff_text="some diff")
            app.push_screen(screen)
            await pilot.pause()

            title = screen.query_one("#config-diff-title", Static)
            text = str(title.render())
            assert "Todoist" in text

    @pytest.mark.asyncio
    async def test_diff_text_displayed(self):
        """Diff text is displayed in the #config-diff-text Static."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            diff_text = "-old_value\n+new_value"
            screen = ConfigDiffScreen(service_name="Test", diff_text=diff_text)
            app.push_screen(screen)
            await pilot.pause()

            diff_static = screen.query_one("#config-diff-text", Static)
            text = str(diff_static.render())
            assert "old_value" in text
            assert "new_value" in text

    @pytest.mark.asyncio
    async def test_buttons_present(self):
        """Apply and Cancel buttons exist."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Test", diff_text="diff")
            app.push_screen(screen)
            await pilot.pause()

            apply_btn = screen.query_one("#btn-diff-apply", Button)
            cancel_btn = screen.query_one("#btn-diff-cancel", Button)
            assert apply_btn is not None
            assert cancel_btn is not None


# ============================================================================
# ConfigDiffScreen — Actions
# ============================================================================


class TestConfigDiffScreenActions:
    """Tests for Apply, Cancel, Escape, and Enter actions."""

    @pytest.mark.asyncio
    async def test_apply_button_dismisses_true(self):
        """Clicking Apply dismisses with True."""
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Test", diff_text="diff")
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-diff-apply", Button)
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is True

    @pytest.mark.asyncio
    async def test_cancel_button_dismisses_false(self):
        """Clicking Cancel dismisses with False."""
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Test", diff_text="diff")
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-diff-cancel", Button)
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is False

    @pytest.mark.asyncio
    async def test_escape_dismisses_false(self):
        """Pressing Escape dismisses with False."""
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Test", diff_text="diff")
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is False

    @pytest.mark.asyncio
    async def test_enter_dismisses_true(self):
        """Pressing Enter dismisses with True."""
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Test", diff_text="diff")
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is True


# ============================================================================
# ConfigDiffScreen — Empty diff
# ============================================================================


class TestConfigDiffScreenEmpty:
    """Tests for ConfigDiffScreen with empty diff text."""

    @pytest.mark.asyncio
    async def test_empty_diff_shows_no_changes(self):
        """Empty diff_text shows '(no changes)' in the diff text area."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigDiffScreen(service_name="Test", diff_text="")
            app.push_screen(screen)
            await pilot.pause()

            diff_static = screen.query_one("#config-diff-text", Static)
            text = str(diff_static.render())
            assert "(no changes)" in text
