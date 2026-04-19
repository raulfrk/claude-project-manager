"""SVG golden-file snapshot tests for remaining TUI screens.

NOTE (2026-04-19, #672 phase 1): ProgressScreen removed — replaced by
installer/flow/install_plan.py::execute_install_plan which uses Rich.
Subsequent phases (P2-P7) will remove additional screens from this
inventory.

NOTE (2026-04-19, #672 phase 2): SummaryScreen, MigrationOverviewScreen,
MigrationReviewScreen removed — replaced by installer/flow/ helpers
(main.py failure loop + migration_flow.prompt_migration_action +
prompt_migration_review).

NOTE (2026-04-19, #672 phase 3): ConfirmScreen, DetectionScreen,
CorruptYamlScreen, HooksDiffScreen, UpdateScreen, PluginStatusScreen
removed — replaced by installer/flow/ helpers (confirm_with_options,
show_detection_and_confirm, show_corrupt_yaml_and_confirm,
review_hooks_diff, select_updates, select_plugin_actions). InstallerApp
deleted in the same phase; main.py now calls run_installer_flow.
ConfigDiffScreen remains (still used by P4's Textual integration_config
screens).

Each test renders a screen inside a minimal Textual App, exports an SVG
screenshot, and compares it against a golden file in
``installer/tests/e2e/snapshots/``.

On the first run (or when golden files are missing) the SVG is written as
the new golden file and the test passes.  To regenerate, delete the golden
file and re-run, or set ``SNAPSHOT_CREATE_MISSING=1``.

Passing ``SNAPSHOT_UPDATE=1`` forces overwrite of all golden files
regardless of whether they already exist.

================================================================================
SCREEN INVENTORY (after P3 cleanup)
================================================================================

Active ``Screen`` subclasses under ``installer/screens/``:

    1. ``wizard.py``          -> WizardScreen        (P4)
    2. ``advanced_config.py`` -> AdvancedConfigScreen (P4)
    3. ``integration_config.py``                      (P4)
        - BaseIntegrationScreen (abstract)
        - TodoistConfigScreen
        - TrelloConfigScreen
        - JiraConfigScreen
    4. ``config_diff.py`` -> ConfigDiffScreen (P4 — still used)

Snapshot tests for wizard: test_snapshots_main.py
Snapshot tests for integration: test_snapshots_integration.py
Snapshot tests for advanced: test_snapshots_advanced.py
Snapshot tests for config_diff: test_snapshots_config_diff.py
================================================================================
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

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

_TERMINAL_HASH_RE = re.compile(r"terminal-\d+-")


def _normalize_svg(svg: str) -> str:
    """Replace the non-deterministic `terminal-<hash>-` prefix that Rich/Textual
    generates per-render with a stable placeholder, so snapshot compares are
    byte-exact across runs.

    Only the hash-prefixed CSS class names are touched; all other SVG content
    passes through unchanged.
    """
    return _TERMINAL_HASH_RE.sub("terminal-XXX-", svg)


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

    The SVG is normalized before compare/write via `_normalize_svg` so that
    Rich's non-deterministic ``terminal-<digits>-`` CSS class prefix doesn't
    cause spurious mismatches between runs.
    """
    normalized = _normalize_svg(svg)
    golden = _SNAPSHOT_DIR / f"{name}.svg"
    if _FORCE_UPDATE:
        golden.write_text(normalized, encoding="utf-8")
        return
    if not golden.exists():
        if _CREATE_MISSING:
            golden.write_text(normalized, encoding="utf-8")
            return
        pytest.fail(
            f"Golden file missing for {name!r}: {golden}. "
            f"Run with SNAPSHOT_UPDATE=1 to generate."
        )
    expected = golden.read_text(encoding="utf-8")
    if normalized != expected:
        actual_path = _SNAPSHOT_DIR / f"{name}_actual.svg"
        actual_path.write_text(normalized, encoding="utf-8")
        pytest.fail(
            f"Snapshot mismatch for {name!r}. "
            f"Actual saved to {actual_path}. "
            f"Run with SNAPSHOT_UPDATE=1 to accept changes."
        )


# ---------------------------------------------------------------------------
# WizardScreen -- with proj plugins selected
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
# TodoistConfigScreen -- integration config form
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
