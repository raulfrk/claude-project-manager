"""TUI tests for HooksDiffScreen and Rich prompt tests for _hooks_diff_prompt."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Static

from installer.hooks_diff import HookDiff
from installer.screens.hooks_diff import HooksDiffScreen
from installer.settings_hooks import SettingsHookDiff

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TestApp(App):
    """Bare Textual app for testing screens in isolation."""

    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_NEW = HookDiff(
    hook_id="hook-new",
    status="new",
    current_yaml=None,
    proposed_yaml="id: hook-new\ntrigger: tool_a\ntarget: tool_b\n",
    unified_diff="+new hook",
)

SAMPLE_CHANGED = HookDiff(
    hook_id="hook-changed",
    status="changed",
    current_yaml="id: hook-changed\nold: true\n",
    proposed_yaml="id: hook-changed\nnew: true\n",
    unified_diff="-old\n+new",
)

SAMPLE_REMOVED = HookDiff(
    hook_id="hook-removed",
    status="removed",
    current_yaml="id: hook-removed\nold: true\n",
    proposed_yaml=None,
    unified_diff="-old",
)


@pytest.fixture()
def all_diffs() -> list[HookDiff]:
    return [SAMPLE_NEW, SAMPLE_CHANGED, SAMPLE_REMOVED]


# ============================================================================
# HooksDiffScreen — TUI tests
# ============================================================================


class TestHooksDiffScreenEmpty:
    """Tests for HooksDiffScreen with no diffs."""

    @pytest.mark.asyncio
    async def test_empty_diffs_shows_up_to_date(self):
        """Empty diffs show the 'up to date' message."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[])
            app.push_screen(screen)
            await pilot.pause()

            empty = screen.query_one("#hooks-diff-empty")
            text = empty.content if hasattr(empty, "content") else str(empty.render())
            assert "up to date" in text

    @pytest.mark.asyncio
    async def test_empty_diffs_continue_dismisses_none(self):
        """Continue on empty diffs dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[])
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-hooks-continue")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None


class TestHooksDiffScreenBadges:
    """Tests for status badges and default checkbox states."""

    @pytest.mark.asyncio
    async def test_new_hook_checked_by_default(self):
        """New hook checkbox is checked by default."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[SAMPLE_NEW])
            app.push_screen(screen)
            await pilot.pause()

            cb = screen.query_one("#hook-cb-hook-new", Checkbox)
            assert cb.value is True

    @pytest.mark.asyncio
    async def test_new_hook_shows_new_badge(self):
        """New hook card contains a NEW badge."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[SAMPLE_NEW])
            app.push_screen(screen)
            await pilot.pause()

            badges = screen.query(".hook-badge")
            badge_texts = [str(b.render()) for b in badges]
            assert any("NEW" in t for t in badge_texts)

    @pytest.mark.asyncio
    async def test_changed_hook_checked_by_default(self):
        """Changed hook checkbox is checked by default."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[SAMPLE_CHANGED])
            app.push_screen(screen)
            await pilot.pause()

            cb = screen.query_one("#hook-cb-hook-changed", Checkbox)
            assert cb.value is True

    @pytest.mark.asyncio
    async def test_changed_hook_shows_changed_badge(self):
        """Changed hook card contains a CHANGED badge."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[SAMPLE_CHANGED])
            app.push_screen(screen)
            await pilot.pause()

            badges = screen.query(".hook-badge")
            badge_texts = [str(b.render()) for b in badges]
            assert any("CHANGED" in t for t in badge_texts)

    @pytest.mark.asyncio
    async def test_removed_hook_unchecked_by_default(self):
        """Removed hook checkbox is unchecked by default."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[SAMPLE_REMOVED])
            app.push_screen(screen)
            await pilot.pause()

            cb = screen.query_one("#hook-cb-hook-removed", Checkbox)
            assert cb.value is False

    @pytest.mark.asyncio
    async def test_removed_hook_shows_removed_badge(self):
        """Removed hook card contains a REMOVED badge."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=[SAMPLE_REMOVED])
            app.push_screen(screen)
            await pilot.pause()

            badges = screen.query(".hook-badge")
            badge_texts = [str(b.render()) for b in badges]
            assert any("REMOVED" in t for t in badge_texts)


class TestHooksDiffScreenActions:
    """Tests for Apply All, Skip All, Continue, and Cancel actions."""

    @pytest.mark.asyncio
    async def test_apply_all_checks_all(self, all_diffs: list[HookDiff]):
        """Apply All button checks all checkboxes."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=all_diffs)
            app.push_screen(screen)
            await pilot.pause()

            btn = screen.query_one("#btn-hooks-apply-all")
            await pilot.click(btn)
            await pilot.pause()

            for diff in all_diffs:
                cb = screen.query_one(f"#hook-cb-{diff.hook_id}", Checkbox)
                assert cb.value is True, f"{diff.hook_id} should be checked"

    @pytest.mark.asyncio
    async def test_skip_all_unchecks_all(self, all_diffs: list[HookDiff]):
        """Skip All button unchecks all checkboxes."""
        app = _TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=all_diffs)
            app.push_screen(screen)
            await pilot.pause()

            btn = screen.query_one("#btn-hooks-skip-all")
            await pilot.click(btn)
            await pilot.pause()

            for diff in all_diffs:
                cb = screen.query_one(f"#hook-cb-{diff.hook_id}", Checkbox)
                assert cb.value is False, f"{diff.hook_id} should be unchecked"

    @pytest.mark.asyncio
    async def test_continue_collects_selections(self, all_diffs: list[HookDiff]):
        """Continue collects checked apply/remove IDs correctly."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=all_diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Default state: new=checked, changed=checked, removed=unchecked
            btn = screen.query_one("#btn-hooks-continue")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        result = results[0]
        assert result is not None
        assert result["apply"] == {"hook-new", "hook-changed"}
        assert result["remove"] == set()

    @pytest.mark.asyncio
    async def test_continue_with_removed_checked(self, all_diffs: list[HookDiff]):
        """When removed hook is checked, it appears in remove set."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=all_diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            # Apply all so removed hook gets checked too
            btn_apply = screen.query_one("#btn-hooks-apply-all")
            await pilot.click(btn_apply)
            await pilot.pause()

            btn = screen.query_one("#btn-hooks-continue")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        result = results[0]
        assert result is not None
        assert result["apply"] == {"hook-new", "hook-changed"}
        assert result["remove"] == {"hook-removed"}

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self, all_diffs: list[HookDiff]):
        """Cancel button dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=all_diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            btn = screen.query_one("#btn-hooks-cancel")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_escape_returns_none(self, all_diffs: list[HookDiff]):
        """Escape key dismisses with None."""
        app = _TestApp()
        results: list[dict | None] = []

        async with app.run_test(size=(120, 40)) as pilot:
            screen = HooksDiffScreen(diffs=all_diffs)
            app.push_screen(screen, callback=lambda r: results.append(r))
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

        assert len(results) == 1
        assert results[0] is None


# ============================================================================
# _hooks_diff_prompt — Rich prompt tests
# ============================================================================


class TestHooksDiffPromptRich:
    """Tests for the Rich (--no-tui) _hooks_diff_prompt function."""

    def test_no_diffs_prints_up_to_date(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """No diffs prints 'up to date' and does not prompt."""
        from rich.console import Console

        from installer.wizard import _hooks_diff_prompt

        console = Console(file=MagicMock())

        # Patch compute_hooks_diff to return empty list
        monkeypatch.setattr(
            "installer.wizard.compute_hooks_diff",
            lambda _path, _dirs: [],
        )

        # Should not call Confirm.ask at all
        ask_calls: list[str] = []
        monkeypatch.setattr(
            "installer.wizard.Confirm.ask",
            lambda *a, **kw: ask_calls.append("called") or True,
        )

        _hooks_diff_prompt([tmp_path], console=console)

        assert len(ask_calls) == 0

    def test_with_diffs_applies_selected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """With diffs, prompts per hook and calls apply_diffs with correct IDs."""
        from rich.console import Console

        from installer.wizard import _hooks_diff_prompt

        console = Console(file=MagicMock())

        diffs = [SAMPLE_NEW, SAMPLE_CHANGED, SAMPLE_REMOVED]

        monkeypatch.setattr(
            "installer.wizard.compute_hooks_diff",
            lambda _path, _dirs: diffs,
        )

        # Simulate: accept new (True), accept changed (True), skip removed (False)
        responses = iter([True, True, False])
        monkeypatch.setattr(
            "installer.wizard.Confirm.ask",
            lambda *a, **kw: next(responses),
        )

        apply_calls: list[tuple[Path, list[HookDiff], set[str], set[str]]] = []

        def mock_apply(path, diffs_arg, apply_ids, remove_ids):
            apply_calls.append((path, diffs_arg, apply_ids, remove_ids))

        monkeypatch.setattr("installer.wizard.apply_diffs", mock_apply)

        _hooks_diff_prompt([tmp_path], console=console)

        assert len(apply_calls) == 1
        _, _, apply_ids, remove_ids = apply_calls[0]
        assert apply_ids == {"hook-new", "hook-changed"}
        assert remove_ids == set()

    def test_with_diffs_removed_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When user accepts a removed hook, it goes into remove_ids."""
        from rich.console import Console

        from installer.wizard import _hooks_diff_prompt

        console = Console(file=MagicMock())

        diffs = [SAMPLE_REMOVED]

        monkeypatch.setattr(
            "installer.wizard.compute_hooks_diff",
            lambda _path, _dirs: diffs,
        )

        # Accept the removal
        monkeypatch.setattr(
            "installer.wizard.Confirm.ask",
            lambda *a, **kw: True,
        )

        apply_calls: list[tuple[Path, list[HookDiff], set[str], set[str]]] = []

        def mock_apply(path, diffs_arg, apply_ids, remove_ids):
            apply_calls.append((path, diffs_arg, apply_ids, remove_ids))

        monkeypatch.setattr("installer.wizard.apply_diffs", mock_apply)

        _hooks_diff_prompt([tmp_path], console=console)

        assert len(apply_calls) == 1
        _, _, apply_ids, remove_ids = apply_calls[0]
        assert apply_ids == set()
        assert remove_ids == {"hook-removed"}

    def test_all_skipped_no_apply_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When all diffs are skipped, apply_diffs is not called."""
        from rich.console import Console

        from installer.wizard import _hooks_diff_prompt

        console = Console(file=MagicMock())

        diffs = [SAMPLE_NEW, SAMPLE_CHANGED]

        monkeypatch.setattr(
            "installer.wizard.compute_hooks_diff",
            lambda _path, _dirs: diffs,
        )

        # Reject all
        monkeypatch.setattr(
            "installer.wizard.Confirm.ask",
            lambda *a, **kw: False,
        )

        apply_calls: list[tuple] = []

        def mock_apply(path, diffs_arg, apply_ids, remove_ids):
            apply_calls.append((path, diffs_arg, apply_ids, remove_ids))

        monkeypatch.setattr("installer.wizard.apply_diffs", mock_apply)

        _hooks_diff_prompt([tmp_path], console=console)

        assert len(apply_calls) == 0


# ---------------------------------------------------------------------------
# Settings-hooks mode: verify Removed section rendering + checkbox routing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_hooks_removed_diff_renders_and_routes_to_remove() -> None:
    """Pipe a `SettingsHookDiff(kind="removed")` through HooksDiffScreen and
    verify: (1) the Removed badge renders, (2) the checkbox defaults to
    UNCHECKED (safer — user opts in), (3) toggling it on routes the cpm_id
    into `_collect_selections()["remove"]`, not `apply`."""
    removed_diff = SettingsHookDiff(
        cpm_id="orphan-hook",
        kind="removed",
        event="SessionEnd",
        matchers=["shutdown"],
        desired=None,
        actual={
            "event": "SessionEnd",
            "matcher": {
                "matcher": "shutdown",
                "__cpm_id": "orphan-hook",
                "hooks": [{"command": "# cpm:orphan-hook\nrun", "type": "command"}],
            },
        },
    )

    app = _TestApp()
    async with app.run_test() as pilot:
        screen = HooksDiffScreen(mode="settings_hooks", diffs=[removed_diff])
        app.push_screen(screen)
        await pilot.pause()

        # The screen rendered — find the checkbox for the removed id.
        cb = screen.query_one("#hook-cb-orphan-hook", Checkbox)
        assert cb.value is False  # default UNCHECKED for removed

        # Unchecked → nothing collected.
        selections_empty = screen._collect_selections()
        assert selections_empty == {"apply": set(), "remove": set()}

        # Toggle on, re-collect — must route to `remove`, NOT `apply`.
        cb.value = True
        await pilot.pause()
        selections_on = screen._collect_selections()
        assert selections_on == {"apply": set(), "remove": {"orphan-hook"}}
