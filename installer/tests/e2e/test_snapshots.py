"""SVG golden-file snapshot tests for all 6 TUI screens.

Each test renders a screen inside a minimal Textual App, exports an SVG
screenshot, and compares it against a golden file in ``installer/tests/e2e/snapshots/``.

On the first run (or when golden files are missing) the SVG is written as
the new golden file and the test passes.  To regenerate, delete the golden
file and re-run.

Passing ``SNAPSHOT_UPDATE=1`` as an environment variable forces overwrite of
all golden files regardless of whether they already exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from installer.detect import InstallState
from installer.screens.confirm import ConfirmOption, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.progress import ProgressScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

_FORCE_UPDATE = os.environ.get("SNAPSHOT_UPDATE", "") == "1"

# Consistent terminal size for reproducible screenshots
_TERM_SIZE = (120, 40)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ScreenHost(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


def _assert_snapshot(svg: str, name: str) -> None:
    """Compare *svg* against the golden file ``<name>.svg``.

    ``SNAPSHOT_UPDATE=1`` writes/overwrites the golden and passes.
    Missing golden without SNAPSHOT_UPDATE is a hard failure — forces
    goldens to be generated explicitly and committed.
    """
    golden = _SNAPSHOT_DIR / f"{name}.svg"
    if _FORCE_UPDATE:
        golden.write_text(svg, encoding="utf-8")
        return  # golden written/updated
    assert golden.exists(), (
        f"Golden file missing for {name!r}: {golden}. "
        f"Run with SNAPSHOT_UPDATE=1 to generate."
    )
    expected = golden.read_text(encoding="utf-8")
    assert svg == expected, (
        f"Snapshot mismatch for {name!r}. "
        f"Delete {golden} and re-run with SNAPSHOT_UPDATE=1 to regenerate."
    )


# ---------------------------------------------------------------------------
# Marketplace data
# ---------------------------------------------------------------------------

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


@pytest.fixture()
def marketplace_json(tmp_path: Path) -> Path:
    """Write a test marketplace.json and return its path."""
    data = {"plugins": _ALL_PLUGINS}
    path = tmp_path / "marketplace.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. PluginSelectScreen -- default marketplace data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_select_snapshot(marketplace_json: Path) -> None:
    """Snapshot of the plugin selection screen with default preselection."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = PluginSelectScreen(marketplace_path=marketplace_json)
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "plugin_select")


# ---------------------------------------------------------------------------
# 2. WizardScreen -- with proj plugins selected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wizard_snapshot() -> None:
    """Snapshot of the wizard screen with proj-related plugins selected."""
    selected = ["proj", "hooks", "sandbox", "worktree", "todoist"]
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = WizardScreen(selected_plugins=selected)
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "wizard")


# ---------------------------------------------------------------------------
# 3. DetectionScreen -- mixed installed/outdated/missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_snapshot() -> None:
    """Snapshot of the detection screen with mixed plugin states."""
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
        svg = app.export_screenshot()
        _assert_snapshot(svg, "detection")


# ---------------------------------------------------------------------------
# 4. UpdateScreen -- 2 outdated plugins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_snapshot() -> None:
    """Snapshot of the update screen with 2 outdated plugins."""
    diffs = {
        "proj": ("3.5.0", "4.0.0"),
        "hooks": ("1.9.0", "2.0.0"),
    }
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = UpdateScreen(version_diffs=diffs)
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "update")


# ---------------------------------------------------------------------------
# 5. ConfirmScreen -- reinstall confirmation with options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_snapshot() -> None:
    """Snapshot of a reinstall confirmation dialog with options."""
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
        svg = app.export_screenshot()
        _assert_snapshot(svg, "confirm")


# ---------------------------------------------------------------------------
# 6. ProgressScreen -- mid-progress state (3/5 steps done)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_snapshot() -> None:
    """Snapshot of a progress screen at 3/5 steps with log lines."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ProgressScreen(description="Installing plugins...", total=5)
        app.push_screen(screen)
        await pilot.pause()

        # Simulate mid-progress state
        screen.log("[bold]Checking marketplace...[/bold]")
        screen.log("  [green]Marketplace registered.[/green]")
        screen.advance(1, detail="Marketplace ready")
        screen.log("  Installing proj...")
        screen.log("  [green]proj installed[/green]")
        screen.advance(1, detail="Installed proj")
        screen.log("  Installing hooks...")
        screen.log("  [green]hooks installed[/green]")
        screen.advance(1, detail="Installed hooks")
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "progress")


# ---------------------------------------------------------------------------
# 7. TodoistConfigScreen -- integration config form
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todoist_config_snapshot() -> None:
    """Snapshot of the Todoist integration config screen."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        from installer.screens.integration_config import TodoistConfigScreen

        screen = TodoistConfigScreen()
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "todoist_config")


# ---------------------------------------------------------------------------
# 8. ConfigDiffScreen -- config change review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_diff_snapshot() -> None:
    """Snapshot of the config diff confirmation screen."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        from installer.screens.config_diff import ConfigDiffScreen

        diff_text = (
            "--- current\n"
            "+++ proposed\n"
            "@@ -1,2 +1,2 @@\n"
            "-api_token: old-token-value\n"
            "+api_token: new-token-value\n"
            " \n"
            "-enabled: false\n"
            "+enabled: true\n"
        )
        screen = ConfigDiffScreen(service_name="Todoist", diff_text=diff_text)
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "config_diff")
