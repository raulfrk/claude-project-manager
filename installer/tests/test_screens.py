"""Textual pilot tests for installer screens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MARKETPLACE_DATA = {
    "plugins": [
        {
            "name": "sandbox",
            "description": "Sandbox management",
            "version": "0.2.0",
            "category": "core",
            "keywords": ["sandbox"],
        },
        {
            "name": "hooks",
            "description": "Hook dispatch",
            "version": "0.3.0",
            "category": "core",
            "keywords": ["hooks"],
        },
        {
            "name": "proj",
            "description": "Project management",
            "version": "1.0.0",
            "category": "productivity",
            "keywords": ["project"],
        },
        {
            "name": "worktree",
            "description": "Git worktrees",
            "version": "0.7.0",
            "category": "utilities",
            "keywords": ["git"],
        },
        {
            "name": "trello",
            "description": "Trello integration",
            "version": "0.5.0",
            "category": "integrations",
            "keywords": ["trello"],
        },
    ],
}


class _TestApp(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


@pytest.fixture()
def mp_path(tmp_path: Path) -> Path:
    """Write a test marketplace.json and return its path."""
    path = tmp_path / "marketplace.json"
    path.write_text(json.dumps(_MARKETPLACE_DATA), encoding="utf-8")
    return path


# ============================================================================
# PluginSelectScreen
# ============================================================================


class TestPluginSelectScreen:
    """Pilot tests for the plugin selection screen."""

    @pytest.mark.asyncio
    async def test_initial_defaults_selected(self, mp_path: Path):
        """Default plugins (sandbox, hooks, proj) are pre-selected."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen)
            await pilot.pause()

            assert "sandbox" in screen._selected
            assert "hooks" in screen._selected
            assert "proj" in screen._selected
            assert "worktree" not in screen._selected
            assert "trello" not in screen._selected

    @pytest.mark.asyncio
    async def test_toggle_selection_with_space(self, mp_path: Path):
        """Space key toggles the currently highlighted plugin row."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen)
            await pilot.pause()

            # Move cursor to a plugin row (skip category header at row 0)
            await pilot.press("down")
            await pilot.pause()

            current_plugin = screen._get_current_plugin()
            if current_plugin is not None:
                was_selected = current_plugin in screen._selected
                await pilot.press("space")
                await pilot.pause()
                is_selected = current_plugin in screen._selected
                assert is_selected != was_selected

    @pytest.mark.asyncio
    async def test_select_all_shortcut(self, mp_path: Path):
        """'a' key selects all plugins."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen)
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()

            assert len(screen._selected) == 5
            assert screen._selected == {
                "sandbox",
                "hooks",
                "proj",
                "worktree",
                "trello",
            }

    @pytest.mark.asyncio
    async def test_select_none_shortcut(self, mp_path: Path):
        """'n' key deselects all plugins."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen)
            await pilot.pause()

            await pilot.press("n")
            await pilot.pause()

            assert len(screen._selected) == 0

    @pytest.mark.asyncio
    async def test_confirm_returns_selected(self, mp_path: Path):
        """Confirm button dismisses with the selected plugin list."""
        app = _TestApp()
        results: list[list[str]] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert set(results[0]) == {"sandbox", "hooks", "proj"}

    @pytest.mark.asyncio
    async def test_cancel_returns_empty(self, mp_path: Path):
        """Cancel (q) dismisses with an empty list."""
        app = _TestApp()
        results: list[list[str]] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("q")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] == []

    @pytest.mark.asyncio
    async def test_dependency_warning_when_hooks_deselected(self, mp_path: Path):
        """Warning appears when hooks is deselected but dependents remain."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = PluginSelectScreen(marketplace_path=mp_path)
            app.push_screen(screen)
            await pilot.pause()

            # Deselect hooks via the internal method (avoids key-routing issues)
            screen._toggle_plugin("hooks")
            await pilot.pause()

            warning_bar = screen.query_one("#warning-bar")
            assert warning_bar.styles.display != "none"


# ============================================================================
# WizardScreen
# ============================================================================


class TestWizardScreen:
    """Pilot tests for the configuration wizard screen."""

    @pytest.mark.asyncio
    async def test_default_values_on_submit(self):
        """Submit with empty fields returns default values."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "hooks", "sandbox"])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        config = results[0]
        assert config is not None
        assert config["tracking_dir"] == "~/projects/tracking"
        assert config["projects_base_dir"] == "~/projects"
        assert config["sandbox_integration"] is True
        assert config["zoxide_integration"] is False
        assert "worktree_dir" not in config  # absent when worktree not selected

    @pytest.mark.asyncio
    async def test_custom_values_override(self):
        """Custom values typed into inputs override defaults."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "hooks"])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            tracking_input = screen.query_one("#tracking_dir")
            await pilot.click(tracking_input)
            await pilot.pause()
            await pilot.press(*list("/custom/tracking"))
            await pilot.pause()

            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        config = results[0]
        assert config is not None
        assert config["tracking_dir"] == "/custom/tracking"

    @pytest.mark.asyncio
    async def test_worktree_dir_shown_when_worktree_selected(self):
        """worktree_dir input is present when worktree plugin is selected."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "worktree"])
            app.push_screen(screen)
            await pilot.pause()

            wt_input = screen.query_one("#worktree_dir")
            assert wt_input is not None

    @pytest.mark.asyncio
    async def test_worktree_dir_hidden_without_worktree(self):
        """worktree_dir input is absent when worktree is not selected."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "hooks"])
            app.push_screen(screen)
            await pilot.pause()

            from textual.css.query import NoMatches

            with pytest.raises(NoMatches):
                screen.query_one("#worktree_dir")

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self):
        """Cancel button dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj"])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-cancel")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_escape_cancels(self):
        """Escape key dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj"])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None

    # -- Integration fields no longer in WizardScreen --
    # (Sync toggles moved to dedicated integration config screens;
    #  see test_integration_screens.py for those tests.)

    @pytest.mark.asyncio
    async def test_no_integration_fields_with_base_only(self):
        """No integration widgets exist even when integration plugins selected."""
        from textual.css.query import NoMatches

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(
                selected_plugins=["proj", "todoist", "trello", "jira"]
            )
            app.push_screen(screen)
            await pilot.pause()

            for widget_id in (
                "#todoist_enabled",
                "#trello_enabled",
                "#trello_board_id",
                "#jira_enabled",
                "#jira_default_user",
            ):
                with pytest.raises(NoMatches):
                    screen.query_one(widget_id)


# ============================================================================
# DetectionScreen
# ============================================================================


class TestDetectionScreen:
    """Pilot tests for the detection screen."""

    @staticmethod
    def _make_rows() -> list[PluginDetectionRow]:
        return [
            PluginDetectionRow("proj", "1.0.0", "1.0.0"),
            PluginDetectionRow("hooks", "0.2.0", "0.3.0"),
            PluginDetectionRow("trello", None, "0.5.0"),
        ]

    @staticmethod
    def _make_state():
        """Create a minimal InstallState."""
        from installer.detect import InstallState

        return InstallState(
            installed_plugins=["proj", "hooks"],
            mcp_entries=["plugin_proj_proj"],
        )

    @pytest.mark.asyncio
    async def test_displays_correct_statuses(self):
        """Detection table shows up-to-date, outdated, not installed."""
        rows = self._make_rows()
        state = self._make_state()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = DetectionScreen(state=state, plugin_rows=rows)
            app.push_screen(screen)
            await pilot.pause()

            assert rows[0].status == "up-to-date"
            assert rows[1].status == "outdated"
            assert rows[2].status == "not installed"

    @pytest.mark.asyncio
    async def test_continue_dismisses_true(self):
        """Continue button dismisses with True."""
        rows = self._make_rows()
        state = self._make_state()
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = DetectionScreen(state=state, plugin_rows=rows)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-continue")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is True

    @pytest.mark.asyncio
    async def test_cancel_dismisses_false(self):
        """Cancel button dismisses with False."""
        rows = self._make_rows()
        state = self._make_state()
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = DetectionScreen(state=state, plugin_rows=rows)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-cancel")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is False

    @pytest.mark.asyncio
    async def test_keyboard_cancel(self):
        """'q' key dismisses with False."""
        rows = self._make_rows()
        state = self._make_state()
        app = _TestApp()
        results: list[bool] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = DetectionScreen(state=state, plugin_rows=rows)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("q")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is False

    @pytest.mark.asyncio
    async def test_summary_bar_content(self):
        """Summary bar shows correct counts."""
        rows = self._make_rows()
        state = self._make_state()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = DetectionScreen(state=state, plugin_rows=rows)
            app.push_screen(screen)
            await pilot.pause()

            summary = screen.query_one("#summary-bar")
            text = (
                summary.content
                if hasattr(summary, "content")
                else str(summary.render())
            )
            assert "1 up-to-date" in text
            assert "1 outdated" in text
            assert "1 not installed" in text


# ============================================================================
# UpdateScreen
# ============================================================================


class TestUpdateScreen:
    """Pilot tests for the update screen."""

    @staticmethod
    def _make_diffs() -> dict[str, tuple[str, str]]:
        return {
            "hooks": ("0.2.0", "0.3.0"),
            "proj": ("0.9.0", "1.0.0"),
        }

    @pytest.mark.asyncio
    async def test_shows_outdated_plugins(self):
        """Only outdated plugins appear in the update table."""
        diffs = self._make_diffs()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen)
            await pilot.pause()

            assert len(screen._plugins) == 2
            assert set(screen._plugins) == {"hooks", "proj"}

    @pytest.mark.asyncio
    async def test_all_selected_by_default(self):
        """All outdated plugins are selected by default."""
        diffs = self._make_diffs()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen)
            await pilot.pause()

            assert screen._selected == {"hooks", "proj"}

    @pytest.mark.asyncio
    async def test_toggle_selection(self):
        """Space toggles selection on the current row."""
        diffs = self._make_diffs()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen)
            await pilot.pause()

            first_plugin = screen._plugins[0]
            assert first_plugin in screen._selected

            await pilot.press("space")
            await pilot.pause()

            assert first_plugin not in screen._selected

    @pytest.mark.asyncio
    async def test_update_selected_returns_list(self):
        """Update Selected button returns the selected plugins."""
        diffs = self._make_diffs()
        app = _TestApp()
        results: list[list[str]] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Deselect the first via space, keep second
            await pilot.press("space")
            await pilot.pause()

            # Use the button to confirm (enter on DataTable toggles rows)
            btn = screen.query_one("#btn-update-selected")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert len(results[0]) == 1

    @pytest.mark.asyncio
    async def test_select_all_shortcut(self):
        """'a' key selects all plugins."""
        diffs = self._make_diffs()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen)
            await pilot.pause()

            # Deselect one first
            await pilot.press("space")
            await pilot.pause()
            assert len(screen._selected) == 1

            await pilot.press("a")
            await pilot.pause()
            assert screen._selected == {"hooks", "proj"}

    @pytest.mark.asyncio
    async def test_select_none_shortcut(self):
        """'n' key deselects all plugins."""
        diffs = self._make_diffs()
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen)
            await pilot.pause()

            await pilot.press("n")
            await pilot.pause()
            assert len(screen._selected) == 0

    @pytest.mark.asyncio
    async def test_update_all_button(self):
        """Update All button returns all plugins regardless of selection."""
        diffs = self._make_diffs()
        app = _TestApp()
        results: list[list[str]] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Deselect one first
            await pilot.press("space")
            await pilot.pause()

            btn = screen.query_one("#btn-update-all")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert set(results[0]) == {"hooks", "proj"}

    @pytest.mark.asyncio
    async def test_cancel_returns_empty(self):
        """Cancel returns empty list."""
        diffs = self._make_diffs()
        app = _TestApp()
        results: list[list[str]] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = UpdateScreen(version_diffs=diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("q")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] == []


# ============================================================================
# ConfirmScreen
# ============================================================================


class TestConfirmScreen:
    """Pilot tests for the reusable confirmation dialog."""

    @pytest.mark.asyncio
    async def test_displays_title_and_message(self):
        """Title and message are rendered."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfirmScreen(
                title="Test Title",
                message="Test message body.",
            )
            app.push_screen(screen)
            await pilot.pause()

            title_widget = screen.query_one("#confirm-title")
            msg_widget = screen.query_one("#confirm-message")
            title_text = (
                title_widget.content
                if hasattr(title_widget, "content")
                else str(title_widget.render())
            )
            msg_text = (
                msg_widget.content
                if hasattr(msg_widget, "content")
                else str(msg_widget.render())
            )
            assert "Test Title" in title_text
            assert "Test message body." in msg_text

    @pytest.mark.asyncio
    async def test_confirm_returns_confirmed_true(self):
        """Confirm button returns ConfirmResult with confirmed=True."""
        app = _TestApp()
        results: list[ConfirmResult] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfirmScreen(
                title="Confirm",
                message="Proceed?",
            )
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0].confirmed is True

    @pytest.mark.asyncio
    async def test_cancel_returns_confirmed_false(self):
        """Cancel button returns ConfirmResult with confirmed=False."""
        app = _TestApp()
        results: list[ConfirmResult] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfirmScreen(
                title="Confirm",
                message="Proceed?",
            )
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-cancel")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0].confirmed is False

    @pytest.mark.asyncio
    async def test_option_defaults(self):
        """Options start with their default values."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfirmScreen(
                title="Confirm",
                message="Proceed?",
                options=[
                    ConfirmOption(key="opt_a", label="Option A", default=False),
                    ConfirmOption(key="opt_b", label="Option B", default=True),
                ],
            )
            app.push_screen(screen)
            await pilot.pause()

            from textual.widgets import Checkbox

            cb_a = screen.query_one("#opt-opt_a", Checkbox)
            cb_b = screen.query_one("#opt-opt_b", Checkbox)
            assert cb_a.value is False
            assert cb_b.value is True

    @pytest.mark.asyncio
    async def test_toggle_option_and_confirm(self):
        """Toggling a checkbox is reflected in the confirm result."""
        app = _TestApp()
        results: list[ConfirmResult] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfirmScreen(
                title="Confirm",
                message="Proceed?",
                options=[
                    ConfirmOption(
                        key="cleanup",
                        label="Full cleanup",
                        default=False,
                    ),
                ],
            )
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            from textual.widgets import Checkbox

            cb = screen.query_one("#opt-cleanup", Checkbox)
            await pilot.click(cb)
            await pilot.pause()

            btn = screen.query_one("#btn-confirm")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0].confirmed is True
        assert results[0].options["cleanup"] is True

    @pytest.mark.asyncio
    async def test_escape_cancels(self):
        """Escape key dismisses with confirmed=False."""
        app = _TestApp()
        results: list[ConfirmResult] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfirmScreen(
                title="Confirm",
                message="Proceed?",
            )
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

        assert len(results) == 1
        assert results[0].confirmed is False
