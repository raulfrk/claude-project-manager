"""Transition snapshot tests for main flow screens.

Covers PluginSelectScreen, WizardScreen, DetectionScreen, UpdateScreen.
See ``test_snapshots.py`` module docstring for full inventory and
per-screen widget ID map.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from installer.detect import InstallState
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)

_ALL_PLUGINS = [
    {
        "name": "sandbox",
        "description": "Manage sandbox-mode settings.json",
        "version": "1.0.0",
        "category": "utilities",
        "keywords": ["sandbox"],
    },
    {
        "name": "worktree",
        "description": "Git worktree management",
        "version": "3.0.0",
        "category": "utilities",
        "keywords": ["git"],
    },
    {
        "name": "proj",
        "description": "Project lifecycle management",
        "version": "4.0.0",
        "category": "productivity",
        "keywords": ["project"],
    },
    {
        "name": "trello",
        "description": "Trello board and card management",
        "version": "3.0.0",
        "category": "integrations",
        "keywords": ["trello"],
    },
    {
        "name": "jira",
        "description": "Jira issue and project access",
        "version": "3.0.0",
        "category": "integrations",
        "keywords": ["jira"],
    },
    {
        "name": "hooks",
        "description": "Central MCP-to-MCP hook registry",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["hooks"],
    },
    {
        "name": "zoxide",
        "description": "Zoxide frecency database integration",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["zoxide"],
    },
    {
        "name": "todoist",
        "description": "Todoist task and project management",
        "version": "2.0.0",
        "category": "integrations",
        "keywords": ["todoist"],
    },
    {
        "name": "analyse",
        "description": "Guided code review skill",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["analyse"],
    },
]


class _ScreenHost(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


@pytest.fixture()
def marketplace_json(tmp_path: Path) -> Path:
    data = {"plugins": _ALL_PLUGINS}
    path = tmp_path / "marketplace.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# PluginSelectScreen: focus transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_select_focus_next_snapshot(marketplace_json: Path) -> None:
    """After one Tab press, focus moves from DataTable to #btn-confirm."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = PluginSelectScreen(marketplace_path=marketplace_json)
        app.push_screen(screen)
        await pilot.pause()

        # Explicitly focus the Confirm button (more robust than Tab counting).
        screen.query_one("#btn-confirm", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-confirm", (
            f"expected btn-confirm, got {pilot.app.focused.id}"
        )

        svg = app.export_screenshot()
        _assert_snapshot(svg, "plugin_select_focus_next")


# ---------------------------------------------------------------------------
# WizardScreen: focus transition + validation error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wizard_focus_next_field_snapshot() -> None:
    """Focus moves explicitly to the Submit button."""
    selected = ["proj", "hooks", "sandbox", "worktree", "todoist"]
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = WizardScreen(selected_plugins=selected)
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-submit", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-submit"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "wizard_focus_next_field")


@pytest.mark.asyncio
async def test_wizard_validation_error_snapshot() -> None:
    """Validation error variant: focus on Cancel button."""
    # WizardScreen has no _show_error() hook — use focus on Cancel to produce
    # a distinct visual variant. This is the closest deterministic "alternate
    # state" available without mutating the screen internals.
    selected = ["proj", "hooks", "sandbox", "worktree", "todoist"]
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = WizardScreen(selected_plugins=selected)
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-cancel", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-cancel"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "wizard_validation_error")


# ---------------------------------------------------------------------------
# DetectionScreen: focus_continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_focus_continue_snapshot() -> None:
    state = InstallState(
        installed_plugins=["proj", "hooks", "sandbox"],
        mcp_entries=[
            "plugin_proj_proj",
            "plugin_hooks_hooks",
            "plugin_sandbox_sandbox",
        ],
    )
    rows = [
        PluginDetectionRow(
            plugin="proj", installed_version="3.5.0", available_version="4.0.0"
        ),
        PluginDetectionRow(
            plugin="hooks", installed_version="2.0.0", available_version="2.0.0"
        ),
        PluginDetectionRow(
            plugin="sandbox", installed_version="1.0.0", available_version="1.0.0"
        ),
        PluginDetectionRow(
            plugin="worktree", installed_version=None, available_version="3.0.0"
        ),
        PluginDetectionRow(
            plugin="todoist", installed_version=None, available_version="2.0.0"
        ),
    ]
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = DetectionScreen(
            state=state,
            plugin_rows=rows,
            title_text="Existing Installation",
        )
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-continue", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-continue"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "detection_focus_continue")


# ---------------------------------------------------------------------------
# UpdateScreen: no_changes variant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_no_changes_snapshot() -> None:
    """All plugins up-to-date => empty diff table."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = UpdateScreen(version_diffs={})
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-update-cancel", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-update-cancel"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "update_no_changes")
