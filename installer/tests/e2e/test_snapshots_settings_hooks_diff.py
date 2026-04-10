"""TUI snapshot + geometry tests for HooksDiffScreen in settings_hooks mode.

Covers every user action on the extended HooksDiffScreen when rendered with
``mode="settings_hooks"``. Goldens are seeded on first run via
``SNAPSHOT_CREATE_MISSING=1`` (same helper as ``test_snapshots_diff.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Static

from installer.screens.hooks_diff import HooksDiffScreen
from installer.settings_hooks import SettingsHookDiff
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)


def _mk_diff(
    cpm_id: str,
    kind: str,
    matchers: list[str] | None = None,
) -> SettingsHookDiff:
    mlist = matchers or ["startup"]
    desired: dict | None
    actual: dict | None
    if kind == "new":
        desired = {
            "id": cpm_id,
            "event": "SessionStart",
            "matchers": mlist,
            "command": "python3 /tmp/loader.py",
        }
        actual = None
    elif kind == "removed":
        desired = None
        actual = {
            "id": cpm_id,
            "event": "SessionStart",
            "matchers": mlist,
            "command": "python3 /tmp/old.py",
        }
    else:  # changed / unchanged
        desired = {
            "id": cpm_id,
            "event": "SessionStart",
            "matchers": mlist,
            "command": "python3 /tmp/new.py",
        }
        actual = {
            "id": cpm_id,
            "event": "SessionStart",
            "matchers": mlist,
            "command": "python3 /tmp/old.py",
        }
    return SettingsHookDiff(
        cpm_id=cpm_id,
        kind=kind,  # type: ignore[arg-type]
        event="SessionStart",
        matchers=mlist,
        desired=desired,
        actual=actual,
    )


def _empty_diffs() -> list[SettingsHookDiff]:
    return []


def _single_new_diff() -> list[SettingsHookDiff]:
    return [
        _mk_diff(
            "proj-session-start-all",
            "new",
            ["startup", "resume", "clear", "compact"],
        )
    ]


def _single_changed_diff() -> list[SettingsHookDiff]:
    return [_mk_diff("proj-session-start-all", "changed")]


def _single_removed_diff() -> list[SettingsHookDiff]:
    return [_mk_diff("orphan-hook", "removed")]


def _multi_diff_mixed() -> list[SettingsHookDiff]:
    return [
        _mk_diff("new-one", "new"),
        _mk_diff("changed-one", "changed"),
        _mk_diff("removed-one", "removed"),
    ]


class _ScreenHost(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ---------------------------------------------------------------------------
# Snapshot tests — render HooksDiffScreen(mode="settings_hooks") in every
# meaningful state and compare against goldens under snapshots/.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_hooks_diff_empty_snapshot() -> None:
    """Empty-state renders the 'up to date' message + lone Continue button."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_empty_diffs())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-continue"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_empty")


@pytest.mark.asyncio
async def test_settings_hooks_diff_single_new_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_single_new_diff())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_single_new")


@pytest.mark.asyncio
async def test_settings_hooks_diff_single_changed_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_single_changed_diff())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_single_changed")


@pytest.mark.asyncio
async def test_settings_hooks_diff_single_removed_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_single_removed_diff())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_single_removed")


@pytest.mark.asyncio
async def test_settings_hooks_diff_mixed_snapshot() -> None:
    """Baseline with one each of new/changed/removed."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_mixed")


@pytest.mark.asyncio
async def test_settings_hooks_diff_focus_apply_all_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-apply-all", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-apply-all"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_focus_apply_all")


@pytest.mark.asyncio
async def test_settings_hooks_diff_focus_skip_all_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-skip-all", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-skip-all"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_focus_skip_all")


@pytest.mark.asyncio
async def test_settings_hooks_diff_focus_cancel_snapshot() -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-hooks-cancel", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-hooks-cancel"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_focus_cancel")


@pytest.mark.asyncio
async def test_settings_hooks_diff_after_apply_all_action_snapshot() -> None:
    """After ``action_apply_all``, every checkbox (including removed) is on."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        screen.action_apply_all()
        await pilot.pause()

        for cb in screen.query(Checkbox):
            assert cb.value is True

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_after_apply_all")


@pytest.mark.asyncio
async def test_settings_hooks_diff_after_skip_all_action_snapshot() -> None:
    """After ``action_skip_all``, every checkbox is off."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        screen.action_skip_all()
        await pilot.pause()

        for cb in screen.query(Checkbox):
            assert cb.value is False

        screen.query_one("#btn-hooks-continue", Button).focus()
        await pilot.pause()

        svg = app.export_screenshot()
        _assert_snapshot(svg, "settings_hooks_diff_after_skip_all")


# ---------------------------------------------------------------------------
# Geometry / behavioral tests — no snapshots, just widget layout + dispatch.
# ---------------------------------------------------------------------------


def test_mode_dispatch_settings_hooks() -> None:
    screen = HooksDiffScreen(
        [Path("/tmp")], mode="settings_hooks", diffs=_single_new_diff()
    )
    assert screen._mode == "settings_hooks"


def test_mode_dispatch_yaml_hooks_default() -> None:
    screen = HooksDiffScreen([Path("/tmp")], diffs=[])
    assert screen._mode == "yaml_hooks"


def test_mode_dispatch_yaml_hooks_explicit() -> None:
    screen = HooksDiffScreen([Path("/tmp")], mode="yaml_hooks", diffs=[])
    assert screen._mode == "yaml_hooks"


@pytest.mark.asyncio
async def test_settings_hooks_diff_widget_ids_present() -> None:
    """All the expected widget IDs render for a non-empty diff list."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        for wid in (
            "#hooks-diff-dialog",
            "#hooks-diff-scroll",
            "#hooks-diff-shortcut-bar",
            "#hooks-diff-button-bar",
            "#btn-hooks-apply-all",
            "#btn-hooks-skip-all",
            "#btn-hooks-continue",
            "#btn-hooks-cancel",
            "#hook-cb-new-one",
            "#hook-cb-changed-one",
            "#hook-cb-removed-one",
        ):
            assert screen.query_one(wid) is not None


@pytest.mark.asyncio
async def test_settings_hooks_diff_empty_widget_ids() -> None:
    """Empty-state shows the empty message + only the Continue button."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=[])
        app.push_screen(screen)
        await pilot.pause()

        assert screen.query_one("#hooks-diff-empty") is not None
        assert screen.query_one("#btn-hooks-continue", Button) is not None
        assert len(list(screen.query("#btn-hooks-apply-all"))) == 0
        assert len(list(screen.query("#btn-hooks-skip-all"))) == 0
        assert len(list(screen.query("#btn-hooks-cancel"))) == 0


@pytest.mark.asyncio
async def test_settings_hooks_diff_default_checkbox_values() -> None:
    """new/changed start checked; removed starts unchecked."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        assert screen.query_one("#hook-cb-new-one", Checkbox).value is True
        assert screen.query_one("#hook-cb-changed-one", Checkbox).value is True
        assert screen.query_one("#hook-cb-removed-one", Checkbox).value is False


@pytest.mark.asyncio
async def test_settings_hooks_diff_collect_selections_routes_by_status() -> None:
    """``_collect_selections`` puts removed hooks under 'remove', others under 'apply'."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=_multi_diff_mixed())
        app.push_screen(screen)
        await pilot.pause()

        # Default: new + changed checked, removed unchecked.
        sel = screen._collect_selections()
        assert sel["apply"] == {"new-one", "changed-one"}
        assert sel["remove"] == set()

        # Check the removed box, uncheck new; removed should land in 'remove'.
        screen.query_one("#hook-cb-removed-one", Checkbox).value = True
        screen.query_one("#hook-cb-new-one", Checkbox).value = False
        await pilot.pause()

        sel2 = screen._collect_selections()
        assert sel2["apply"] == {"changed-one"}
        assert sel2["remove"] == {"removed-one"}
