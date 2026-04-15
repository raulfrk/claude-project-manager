"""SVG golden-file snapshot tests for all TUI screens (baseline + transitions).

Each test renders a screen inside a minimal Textual App, exports an SVG
screenshot, and compares it against a golden file in
``installer/tests/e2e/snapshots/``.

On the first run (or when golden files are missing) the SVG is written as
the new golden file and the test passes.  To regenerate, delete the golden
file and re-run, or set ``SNAPSHOT_CREATE_MISSING=1``.

Passing ``SNAPSHOT_UPDATE=1`` forces overwrite of all golden files
regardless of whether they already exist.

================================================================================
SCREEN INVENTORY (todo 509.1)
================================================================================

The installer has these ``Screen`` subclasses under ``installer/screens/``:

    1. ``plugin_select.py``   -> PluginSelectScreen
    2. ``wizard.py``          -> WizardScreen
    3. ``detection.py``       -> DetectionScreen
    4. ``update.py``          -> UpdateScreen
    5. ``confirm.py``         -> ConfirmScreen
    6. ``progress.py``        -> ProgressScreen   (AUTO_FOCUS = "")
    7. ``integration_config.py``
        - BaseIntegrationScreen (abstract)
        - TodoistConfigScreen
        - TrelloConfigScreen
        - JiraConfigScreen
    8. ``config_diff.py``     -> ConfigDiffScreen
    9. ``hooks_diff.py``      -> HooksDiffScreen

The baseline snapshots below cover: plugin_select, wizard, detection,
update, confirm, progress, todoist_config, config_diff.

Per-screen transition snapshots live in sibling files:

    * ``test_snapshots_confirm_progress.py`` — confirm variants + progress
      state-based snapshots (no focus transitions — AUTO_FOCUS = "").
    * ``test_snapshots_integration.py``     — Todoist / Trello / Jira
      config focus + error states.
    * ``test_snapshots_diff.py``            — ConfigDiff + HooksDiff focus
      transitions.
    * ``test_snapshots_main.py``            — plugin_select / wizard /
      detection / update focus transitions.

================================================================================
PER-SCREEN WIDGET ID MAP (todo 509.1)
================================================================================

IDs are **not** uniform across screens.  Tests MUST use the IDs below and
MUST assert ``pilot.app.focused.id == <expected>`` before exporting.

    PluginSelectScreen:
        #btn-confirm    primary (Confirm)
        #btn-cancel     secondary (Cancel)
        #plugin-table   DataTable (initial focus goes here on mount)

    WizardScreen:
        #btn-submit     primary (Submit)
        #btn-cancel     secondary (Cancel)
        #tracking_dir   first Input (focused on mount if needs_proj)

    DetectionScreen:
        #btn-continue   primary (Continue)
        #btn-cancel     secondary (Cancel)

    UpdateScreen:
        #btn-update-selected   primary
        #btn-update-all        success variant
        #btn-update-cancel     secondary

    ConfirmScreen:
        #btn-confirm    primary (default focus = first focusable = confirm)
        #btn-cancel     secondary
        variants via ``confirm_variant=`` kwarg: "primary" | "warning" | "error"

    ProgressScreen:
        AUTO_FOCUS = ""   *** no focusable widgets — state-based only ***
        State is driven by ``.advance()``, ``.write_log()``, and the internal
        ``--complete`` CSS class.

    BaseIntegrationScreen (Todoist/Trello/Jira):
        #btn-continue        primary ("Confirm" label, auto-focused on_mount)
        #btn-skip            secondary ("Skip")
        #validation-error    Label (hidden unless .visible class set via _show_error)
        #validation-loading  LoadingIndicator (hidden via _hide_loading before export)
        #sync_enabled        Switch (drives validation skip path)
        TodoistConfigScreen:
            #api_token
        TrelloConfigScreen:
            #api_key, #token, #default_board_id
        JiraConfigScreen:
            #base_url, #default_user, #personal_access_token, #default_project

    ConfigDiffScreen:
        #btn-diff-apply     primary
        #btn-diff-cancel    secondary

    HooksDiffScreen:
        #btn-hooks-continue     primary (rendered in both empty and populated modes)
        #btn-hooks-cancel       secondary (only rendered when diffs is non-empty)
        #btn-hooks-apply-all    success   (only when diffs is non-empty)
        #btn-hooks-skip-all     warning   (only when diffs is non-empty)

================================================================================
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
_CREATE_MISSING = os.environ.get("SNAPSHOT_CREATE_MISSING", "") == "1"

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

    Modes:
    - ``SNAPSHOT_UPDATE=1``: overwrite all goldens (regenerate baseline).
    - ``SNAPSHOT_CREATE_MISSING=1``: create only missing goldens, compare existing.
    - Default: hard-fail on missing, exact-match on existing.
    """
    golden = _SNAPSHOT_DIR / f"{name}.svg"
    if _FORCE_UPDATE:
        golden.write_text(svg, encoding="utf-8")
        return
    if not golden.exists():
        if _CREATE_MISSING:
            golden.write_text(svg, encoding="utf-8")
            return
        pytest.fail(
            f"Golden file missing for {name!r}: {golden}. "
            f"Run with SNAPSHOT_UPDATE=1 to generate."
        )
    expected = golden.read_text(encoding="utf-8")
    if svg != expected:
        actual_path = _SNAPSHOT_DIR / f"{name}_actual.svg"
        actual_path.write_text(svg, encoding="utf-8")
        pytest.fail(
            f"Snapshot mismatch for {name!r}. "
            f"Actual saved to {actual_path}. "
            f"Run with SNAPSHOT_UPDATE=1 to accept changes."
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


@pytest.mark.asyncio
async def test_wizard_prefilled_from_existing_yamls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wizard snapshot with pre-seeded ~/.claude/proj.yaml + worktree.yaml.

    Regression for 515: WizardScreen must load existing values from
    ~/.claude/<bucket>.yaml so the user sees their current config on second
    run, not hardcoded defaults.
    """
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "proj.yaml").write_text(
        "tracking_dir: /custom/tracking\n"
        "default_priority: high\n"
        "git_tracking:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )
    (claude_dir / "worktree.yaml").write_text(
        "default_worktree_dir: /custom/worktrees\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    # Path.home() uses HOME on POSIX; WizardScreen reads via Path.home() / ".claude".

    selected = ["proj", "hooks", "sandbox", "worktree"]
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = WizardScreen(selected_plugins=selected)
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "wizard_prefilled")


# ---------------------------------------------------------------------------
# 3. DetectionScreen -- mixed installed/outdated/missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_snapshot() -> None:
    """Snapshot of the detection screen with mixed plugin states."""
    state = InstallState(
        installed_plugins=["proj", "router", "sandbox"],
        mcp_entries=[
            "plugin_proj_proj",
            "plugin_router_router",
            "plugin_sandbox_sandbox",
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
        screen.write_log("[bold]Checking marketplace...[/bold]")
        screen.write_log("  [green]Marketplace registered.[/green]")
        screen.advance(1, detail="Marketplace ready")
        screen.write_log("  Installing proj...")
        screen.write_log("  [green]proj installed[/green]")
        screen.advance(1, detail="Installed proj")
        screen.write_log("  Installing hooks...")
        screen.write_log("  [green]hooks installed[/green]")
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


# ---------------------------------------------------------------------------
# 10. PluginStatusScreen — three-column available/installed/outdated view
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_status_screen_snapshot() -> None:
    """Snapshot of the new PluginStatusScreen with a mixed-state fixture."""
    from installer.plugin_status import PluginStatus
    from installer.screens.plugin_select import PluginStatusScreen

    statuses = [
        PluginStatus(
            name="router",
            installed_version="2.0.0",
            available_version="2.0.0",
            state="installed",
        ),
        PluginStatus(
            name="proj",
            installed_version="3.5.0",
            available_version="4.0.0",
            state="outdated",
        ),
        PluginStatus(
            name="trello",
            installed_version=None,
            available_version="3.0.0",
            state="available",
        ),
    ]
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = PluginStatusScreen(statuses=statuses)
        app.push_screen(screen)
        await pilot.pause()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "plugin_status_screen")
