"""Textual pilot tests for installer screens (P4 screens only).

Screens for confirm, detection, plugin_select, and update were deleted in P3
(#672). This file retains tests for WizardScreen and AdvancedConfigScreen
which are P4 territory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from installer.screens.advanced_config import AdvancedConfigScreen
from installer.screens.wizard import WizardScreen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TestApp(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ============================================================================
# WizardScreen
# ============================================================================


class TestWizardScreen:
    """Pilot tests for the configuration wizard screen."""

    @pytest.mark.asyncio
    async def test_default_values_on_submit(self, mock_home: Path):
        """Submit with empty fields returns default values."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "hooks"])
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
        # default_worktree_dir lives in worktree.yaml (yaml_file="worktree"), not WizardScreen
        assert "default_worktree_dir" not in config

    @pytest.mark.asyncio
    async def test_custom_values_override(self, mock_home: Path):
        """Custom values typed into inputs override defaults."""
        from textual.widgets import Input

        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "hooks"])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            tracking_input = screen.query_one("#tracking_dir", Input)
            tracking_input.value = "/custom/tracking"
            await pilot.pause()

            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        config = results[0]
        assert config is not None
        assert config["tracking_dir"] == "/custom/tracking"

    @pytest.mark.asyncio
    async def test_worktree_dir_not_in_proj_wizard_basic_tier(self, mock_home: Path):
        """default_worktree_dir lives in worktree.yaml (514 dual-path), not WizardScreen basic tier."""
        from textual.css.query import NoMatches

        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "worktree"])
            app.push_screen(screen)
            await pilot.pause()

            with pytest.raises(NoMatches):
                screen.query_one("#default_worktree_dir")

    @pytest.mark.asyncio
    async def test_worktree_dir_hidden_without_worktree(self):
        """default_worktree_dir input is absent when worktree is not selected."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "hooks"])
            app.push_screen(screen)
            await pilot.pause()

            from textual.css.query import NoMatches

            with pytest.raises(NoMatches):
                screen.query_one("#default_worktree_dir")

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

    @pytest.mark.asyncio
    async def test_read_existing_all_yamls_populates_buckets(
        self, mock_home: Path
    ) -> None:
        """_read_existing_all_yamls loads every distinct yaml_file into its own bucket."""
        claude = mock_home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "proj.yaml").write_text("tracking_dir: /custom/proj\n")
        (claude / "worktree.yaml").write_text("default_worktree_dir: /custom/wt\n")
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj", "worktree"])
            app.push_screen(screen)
            await pilot.pause()
            assert screen._existing["proj"] == {"tracking_dir": "/custom/proj"}
            assert screen._existing["worktree"] == {
                "default_worktree_dir": "/custom/wt"
            }
            assert screen._existing_mtimes["proj"] > 0
            assert screen._existing_mtimes["worktree"] > 0

    @pytest.mark.asyncio
    async def test_read_existing_all_yamls_missing_files_empty(
        self, mock_home: Path
    ) -> None:
        """Missing yaml files produce empty buckets with mtime 0."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj"])
            app.push_screen(screen)
            await pilot.pause()
            assert screen._existing["proj"] == {}
            assert screen._existing_mtimes["proj"] == 0.0

    @pytest.mark.asyncio
    async def test_read_existing_all_yamls_corrupt_captured(
        self, mock_home: Path
    ) -> None:
        """Corrupt YAML captured in _load_errors; bucket falls back to {}."""
        claude = mock_home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "proj.yaml").write_text("foo: bar\n  baz: - - -\n}}\n")
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = WizardScreen(selected_plugins=["proj"])
            app.push_screen(screen)
            await pilot.pause()
            assert screen._existing["proj"] == {}
            assert "proj" in screen._load_errors

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
# AdvancedConfigScreen
# ============================================================================


class TestAdvancedConfigScreen:
    """Unit tests for the per-bucket existing dict contract."""

    def test_normalize_bucketed_passthrough(self) -> None:
        bucketed = {
            "proj": {"tracking_dir": "/a"},
            "worktree": {"default_worktree_dir": "/b"},
        }
        normalized = AdvancedConfigScreen._normalize_existing(bucketed)
        assert normalized == bucketed

    def test_normalize_flat_wraps_as_proj(self) -> None:
        flat = {"tracking_dir": "/a", "sync": {"todoist": {"enabled": True}}}
        normalized = AdvancedConfigScreen._normalize_existing(flat)
        assert normalized == {"proj": flat}

    def test_normalize_empty_stays_empty(self) -> None:
        assert AdvancedConfigScreen._normalize_existing({}) == {"proj": {}}

    def test_normalize_mixed_treated_as_flat(self) -> None:
        """A dict with a non-yaml_file key is treated as flat (safe fallback)."""
        flat_like = {"tracking_dir": "/a", "proj": {"nested": True}}
        normalized = AdvancedConfigScreen._normalize_existing(flat_like)
        assert normalized == {"proj": flat_like}

    @pytest.mark.asyncio
    async def test_submit_returns_dict(self, mock_home: Path) -> None:
        """AdvancedConfigScreen.dismiss returns dict[str, Any] (or None on cancel)."""
        app = _TestApp()
        results: list[dict | None] = []
        async with app.run_test(size=(120, 40)) as pilot:
            screen = AdvancedConfigScreen({"proj": {}}, [])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-submit")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is not None
        assert isinstance(results[0], dict)

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self, mock_home: Path) -> None:
        app = _TestApp()
        results: list[dict | None] = []
        async with app.run_test(size=(120, 40)) as pilot:
            screen = AdvancedConfigScreen({"proj": {}}, [])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-cancel")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None
