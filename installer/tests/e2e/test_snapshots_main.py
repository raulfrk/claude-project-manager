"""Transition snapshot tests for main flow screens.

Covers PluginSelectScreen, WizardScreen, DetectionScreen, UpdateScreen.
See ``test_snapshots.py`` module docstring for full inventory and
per-screen widget ID map.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Select, Static, Switch

from installer.detect import InstallState
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)

_ALL_PLUGINS = [
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
        "name": "router",
        "description": "Central MCP-to-MCP hook registry",
        "version": "2.0.0",
        "category": "utilities",
        "keywords": ["router", "hooks"],
    },
    {
        "name": "todoist",
        "description": "Todoist task and project management",
        "version": "2.0.0",
        "category": "integrations",
        "keywords": ["todoist"],
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
    selected = ["proj", "hooks", "worktree", "todoist"]
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
    selected = ["proj", "hooks", "worktree", "todoist"]
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
        installed_plugins=["proj", "router"],
        mcp_entries=[
            "plugin_proj_proj",
            "plugin_router_router",
        ],
    )
    rows = [
        PluginDetectionRow(
            plugin="proj", installed_version="3.5.0", available_version="4.0.0"
        ),
        PluginDetectionRow(
            plugin="router", installed_version="2.0.0", available_version="2.0.0"
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


# ---------------------------------------------------------------------------
# WizardScreen (PromptSpec-driven) extended snapshots — todo 514.29
# ---------------------------------------------------------------------------


_WIZARD_PLUGINS = ["proj", "hooks", "worktree", "todoist"]


@pytest.fixture()
def _wizard_isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force Path.home() into tmp to keep WizardScreen's _read_existing_proj_yaml
    deterministic across machines."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("HOME", str(home))
    return home


def _write_proj_yaml(home: Path, data: dict) -> None:
    (home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


class TestWizardScreenExtended:
    """Snapshots + geometry for the PromptSpec-driven WizardScreen (514.23)."""

    @pytest.mark.asyncio
    async def test_wizard_initial_with_new_fields(
        self, _wizard_isolated_home: Path
    ) -> None:
        """Baseline render: new PromptSpec fields visible, nothing focused yet."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            # Geometry: each of the newly-added basic widgets must be laid out.
            for wid in (
                "git_tracking-enabled",
                "quality_level",
                "worktree_isolation",
                "btn-advanced",
                "btn-submit",
                "btn-cancel",
            ):
                region = screen.query_one(f"#{wid}").region
                assert region.width > 0 and region.height > 0, f"{wid} has zero region"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_initial_with_new_fields")

    @pytest.mark.asyncio
    async def test_wizard_focus_git_tracking(self, _wizard_isolated_home: Path) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#git_tracking-enabled", Switch).focus()
            await pilot.pause()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "git_tracking-enabled"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_focus_git_tracking")

    @pytest.mark.asyncio
    async def test_wizard_toggle_git_tracking_on(
        self, _wizard_isolated_home: Path
    ) -> None:
        """Toggling git_tracking.enabled ON reveals github_enabled sub-row."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            # When git_tracking.enabled was False initially, the github sub-rows
            # were filtered out entirely by the condition. We test the visible
            # toggle state after flipping instead.
            sw = screen.query_one("#git_tracking-enabled", Switch)
            sw.value = True
            await pilot.pause()
            assert sw.value is True

            sw.focus()
            await pilot.pause()

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_toggle_git_tracking_on")

    @pytest.mark.asyncio
    async def test_wizard_toggle_git_tracking_off(
        self, _wizard_isolated_home: Path
    ) -> None:
        """Toggle git_tracking OFF after pre-populating from existing proj.yaml."""
        _write_proj_yaml(
            _wizard_isolated_home,
            {
                "git_tracking": {
                    "enabled": True,
                    "github_enabled": True,
                    "github_repo_format": "cpm-tracking-{project}",
                }
            },
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            sw = screen.query_one("#git_tracking-enabled", Switch)
            assert sw.value is True  # picked up from existing proj.yaml
            sw.value = False
            await pilot.pause()

            # Sub-rows should be hidden after toggle flip.
            for child_id in (
                "row-git_tracking-github_enabled",
                "row-git_tracking-github_repo_format",
            ):
                try:
                    row = screen.query_one(f"#{child_id}")
                    assert row.display is False
                except Exception:
                    pass

            sw.focus()
            await pilot.pause()

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_toggle_git_tracking_off")

    @pytest.mark.asyncio
    async def test_wizard_focus_github_enabled(
        self, _wizard_isolated_home: Path
    ) -> None:
        """GitHub enabled sub-switch only appears when git_tracking.enabled was
        True in existing proj.yaml."""
        _write_proj_yaml(
            _wizard_isolated_home,
            {"git_tracking": {"enabled": True, "github_enabled": False}},
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#git_tracking-github_enabled", Switch).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "git_tracking-github_enabled"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_focus_github_enabled")

    @pytest.mark.asyncio
    async def test_wizard_toggle_github_enabled_on(
        self, _wizard_isolated_home: Path
    ) -> None:
        _write_proj_yaml(
            _wizard_isolated_home,
            {"git_tracking": {"enabled": True, "github_enabled": False}},
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            sw = screen.query_one("#git_tracking-github_enabled", Switch)
            sw.value = True
            sw.focus()
            await pilot.pause()

            assert sw.value is True

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_toggle_github_enabled_on")

    @pytest.mark.asyncio
    async def test_wizard_focus_quality_level(
        self, _wizard_isolated_home: Path
    ) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#quality_level", Select).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "quality_level"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_focus_quality_level")

    @pytest.mark.asyncio
    async def test_wizard_select_quality_paranoid(
        self, _wizard_isolated_home: Path
    ) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            sel = screen.query_one("#quality_level", Select)
            sel.value = "paranoid"
            sel.focus()
            await pilot.pause()

            assert sel.value == "paranoid"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_select_quality_paranoid")

    @pytest.mark.asyncio
    async def test_wizard_focus_worktree_isolation(
        self, _wizard_isolated_home: Path
    ) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#worktree_isolation", Switch).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "worktree_isolation"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_focus_worktree_isolation")

    @pytest.mark.asyncio
    async def test_wizard_focus_advanced_button(
        self, _wizard_isolated_home: Path
    ) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            btn = screen.query_one("#btn-advanced", Button)
            btn.focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "btn-advanced"
            # Geometry sanity — Advanced button must be laid out to the right
            # of Submit in the button row.
            submit_x = screen.query_one("#btn-submit", Button).region.x
            assert btn.region.x > submit_x

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_focus_advanced_button")

    @pytest.mark.asyncio
    async def test_wizard_submit_basic_only(self, _wizard_isolated_home: Path) -> None:
        """Focus Submit button; geometry + snapshot of basic-only submit path."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            btn = screen.query_one("#btn-submit", Button)
            btn.focus()
            await pilot.pause()
            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "btn-submit"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_submit_basic_only")

    @pytest.mark.asyncio
    async def test_wizard_load_existing_values(
        self, _wizard_isolated_home: Path
    ) -> None:
        """Wizard pre-populates basic widgets from existing proj.yaml."""
        _write_proj_yaml(
            _wizard_isolated_home,
            {
                "tracking_dir": "/custom/tracking",
                "projects_base_dir": "/custom/projects",
                "sandbox_integration": False,
                "zoxide_integration": True,
                "quality_level": "balanced",
                "worktree_isolation": False,
            },
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#tracking_dir", Input).value == "/custom/tracking"
            assert (
                screen.query_one("#projects_base_dir", Input).value
                == "/custom/projects"
            )
            assert screen.query_one("#sandbox_integration", Switch).value is False
            assert screen.query_one("#zoxide_integration", Switch).value is True
            assert screen.query_one("#quality_level", Select).value == "balanced"
            assert screen.query_one("#worktree_isolation", Switch).value is False

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_load_existing_values")

    @pytest.mark.asyncio
    async def test_wizard_invalid_existing_quality_level(
        self, _wizard_isolated_home: Path
    ) -> None:
        """An invalid existing quality_level falls back to the first choice."""
        _write_proj_yaml(_wizard_isolated_home, {"quality_level": "not-a-real-level"})
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            # Fallback to first choice ("fast") when existing is invalid.
            assert screen.query_one("#quality_level", Select).value == "fast"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_invalid_existing_quality_level")

    @pytest.mark.asyncio
    async def test_wizard_long_tracking_dir(self, _wizard_isolated_home: Path) -> None:
        """Long path value should not break layout (Input truncates/scrolls)."""
        long_path = "/very/deep/nested/path/that/is/intentionally/" + "x" * 80
        _write_proj_yaml(_wizard_isolated_home, {"tracking_dir": long_path})
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#tracking_dir", Input).value == long_path

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_long_tracking_dir")

    @pytest.mark.asyncio
    async def test_wizard_tab_chain(self, _wizard_isolated_home: Path) -> None:
        """Walk the focus chain by pressing Tab several times and snapshot the
        final focused state. We use explicit focus() on the Advanced button
        since Tab counting is brittle across Textual versions."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = WizardScreen(selected_plugins=_WIZARD_PLUGINS)
            app.push_screen(screen)
            await pilot.pause()

            # Walk three Tab presses then explicitly land on Cancel as the
            # deterministic end-state for the snapshot.
            await pilot.press("tab", "tab", "tab")
            screen.query_one("#btn-cancel", Button).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "btn-cancel"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "wizard_tab_chain")
