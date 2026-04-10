"""Transition snapshot tests for ConfigDiffScreen and HooksDiffScreen.

See ``test_snapshots.py`` module docstring for full inventory and
per-screen widget ID map.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from installer.hooks_diff import HookDiff
from installer.screens.config_diff import ConfigDiffScreen
from installer.screens.hooks_diff import HooksDiffScreen
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)

_DIFF_TEXT = (
    "--- current\n"
    "+++ proposed\n"
    "@@ -1,2 +1,2 @@\n"
    "-api_token: old-token-value\n"
    "+api_token: new-token-value\n"
    " \n"
    "-enabled: false\n"
    "+enabled: true\n"
)


class _ScreenHost(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ---------------------------------------------------------------------------
# ConfigDiffScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_diff_focus_apply_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ConfigDiffScreen(service_name="Todoist", diff_text=_DIFF_TEXT)
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-diff-apply", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-diff-apply"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "config_diff_focus_apply")


@pytest.mark.asyncio
async def test_config_diff_focus_cancel_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = ConfigDiffScreen(service_name="Todoist", diff_text=_DIFF_TEXT)
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-diff-cancel", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-diff-cancel"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "config_diff_focus_cancel")


# ---------------------------------------------------------------------------
# HooksDiffScreen
# ---------------------------------------------------------------------------


def _sample_hook_diffs() -> list[HookDiff]:
    return [
        HookDiff(
            hook_id="proj_on_todo_complete",
            status="new",
            current_yaml=None,
            proposed_yaml=(
                "trigger: todo_complete\n"
                "target: todoist_complete_task_hook\n"
                "condition: sync.todoist.enabled\n"
            ),
            unified_diff=(
                "+trigger: todo_complete\n"
                "+target: todoist_complete_task_hook\n"
                "+condition: sync.todoist.enabled\n"
            ),
        ),
        HookDiff(
            hook_id="worktree_post_create",
            status="changed",
            current_yaml="condition: zoxide_integration\n",
            proposed_yaml="condition: zoxide_integration and !test_mode\n",
            unified_diff=(
                "-condition: zoxide_integration\n"
                "+condition: zoxide_integration and !test_mode\n"
            ),
        ),
        HookDiff(
            hook_id="legacy_hook",
            status="removed",
            current_yaml="trigger: deprecated_tool\ntarget: noop\n",
            proposed_yaml=None,
            unified_diff="-trigger: deprecated_tool\n-target: noop\n",
        ),
    ]


@pytest.mark.asyncio
async def test_hooks_diff_initial_snapshot() -> None:
    """Baseline HooksDiff with 3 sample hooks (new/changed/removed)."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(diffs=_sample_hook_diffs())
        app.push_screen(screen)
        await pilot.pause()

        # Explicitly focus Continue so the assertion is deterministic.
        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-continue"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "hooks_diff_initial")


@pytest.mark.asyncio
async def test_hooks_diff_focus_apply_all_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(diffs=_sample_hook_diffs())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-apply-all", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-apply-all"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "hooks_diff_focus_apply_all")


@pytest.mark.asyncio
async def test_hooks_diff_focus_skip_all_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(diffs=_sample_hook_diffs())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-skip-all", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-skip-all"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "hooks_diff_focus_skip_all")
