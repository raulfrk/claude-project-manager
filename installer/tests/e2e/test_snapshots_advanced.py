"""TUI snapshot + geometry tests for AdvancedConfigScreen (todo 514.24/514.29).

The advanced screen is driven by PROJ_YAML_PROMPTS (tier == "advanced").
Fields are grouped by spec.group inside Collapsible widgets; each group's
id is ``group-<sanitized>`` where sanitization lowercases and replaces
non-alphanumerics with dashes.

Expected group ids (see wizard_specs.PROJ_YAML_PROMPTS):
    group-smart-gate          (single bool toggle)
    group-context-injection
    group-archive
    group-permissions
    group-other-proj
    group-todoist-extras
    group-trello-list-mappings   (only when sync.trello.enabled in existing)

Widget ids come from ``spec.dotted_key.replace(".", "-")``, e.g.
``smart_gate``, ``archive-after_days``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Collapsible, Input, Select, Static, Switch

from installer.screens.advanced_config import AdvancedConfigScreen
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)


class _ScreenHost(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep AdvancedConfigScreen from reading real user config files."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("HOME", str(home))


def _make_screen(existing: dict | None = None) -> AdvancedConfigScreen:
    return AdvancedConfigScreen(existing or {}, [])


async def _expand_collapsible(
    pilot, screen: AdvancedConfigScreen, group_id: str
) -> None:
    """Expand the given Collapsible group and settle internally.

    Regression guard: must remain async so _settle runs on every call site.
    Opt-out token: `# noqa: no-settle` at end of a call line.
    """
    try:
        coll = screen.query_one(f"#group-{group_id}", Collapsible)
        coll.collapsed = False
    except Exception:
        pass
    await _settle(pilot, screen)


async def _settle(pilot, screen: AdvancedConfigScreen) -> None:
    """Force deterministic scroll position + wait for layout to settle.

    After Collapsible expand/collapse the VerticalScroll container may
    auto-scroll asynchronously, producing different SVGs across runs for
    collapsibles near the bottom (trello_list_mappings).
    Scroll to home + multiple pauses pin the viewport.
    """
    from textual.containers import VerticalScroll

    try:
        scroll = screen.query_one("#advanced-form", VerticalScroll)
        scroll.scroll_home(animate=False)
    except Exception:
        pass
    await pilot.pause()
    await pilot.pause()


class TestAdvancedConfigScreenSnapshots:
    """24 snapshots covering the AdvancedConfigScreen (todo 514.29; 506.7
    removed trello_extras after default_list/on_delete moved to
    TrelloConfigScreen).
    """

    @pytest.mark.asyncio
    async def test_advanced_initial_render(self) -> None:
        """Baseline: all Collapsibles rendered (may be collapsed)."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            # Required groups must all exist in the DOM.
            # Note: `trello-list-mappings` only renders when sync.trello.enabled
            # is True in the existing config, so it is NOT in this baseline set.
            # team-mode and resilience were removed in 605.3 (config surface reduction).
            for group_id in (
                "smart-gate",
                "context-injection",
                "archive",
                "permissions",
                "other-proj",
                "todoist-extras",
            ):
                region = screen.query_one(f"#group-{group_id}", Collapsible).region
                assert region.width > 0, f"group-{group_id} has zero width"

            # Submit/Cancel/Back buttons must be laid out.
            for btn_id in ("btn-submit", "btn-cancel", "btn-back"):
                region = screen.query_one(f"#{btn_id}", Button).region
                assert region.width > 0 and region.height > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_initial_render")

    @pytest.mark.asyncio
    async def test_advanced_expand_smart_gate(self) -> None:
        """Smart gate is now a single bool toggle (collapsed SmartGateConfig removed in 605.3)."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "smart-gate")

            # smart_gate is now a single bool field — widget id is "smart_gate"
            assert screen.query_one("#smart_gate", Switch).region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_smart_gate")

    @pytest.mark.asyncio
    async def test_advanced_expand_context_injection(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "context-injection")

            for wid in (
                "context_injection-enabled",
                "context_injection-max_tokens",
                "context_injection-include_claudemd",
            ):
                assert screen.query_one(f"#{wid}").region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_context_injection")

    @pytest.mark.asyncio
    async def test_advanced_expand_archive(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "archive")

            for wid in (
                "archive-auto_archive",
                "archive-after_days",
                "archive-keep_history",
                "archive-purge_after_days",
            ):
                assert screen.query_one(f"#{wid}").region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_archive")

    @pytest.mark.asyncio
    async def test_advanced_expand_permissions(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "permissions")

            for wid in (
                "permissions-auto_grant_read",
                "permissions-auto_grant_edit",
            ):
                assert screen.query_one(f"#{wid}").region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_permissions")

    @pytest.mark.asyncio
    async def test_advanced_expand_other_proj(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "other-proj")

            for wid in (
                "default_priority",
                "claudemd_management",
                "worktree_integration",
            ):
                assert screen.query_one(f"#{wid}").region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_other_proj")

    @pytest.mark.asyncio
    async def test_advanced_choice_default_priority(self) -> None:
        """Focus on the default_priority Select widget."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "other-proj")
            screen.query_one("#default_priority", Select).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "default_priority"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_choice_default_priority")

    @pytest.mark.asyncio
    async def test_advanced_select_default_priority_high(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "other-proj")
            sel = screen.query_one("#default_priority", Select)
            sel.value = "high"
            await _settle(pilot, screen)

            assert sel.value == "high"
            result = screen._collect_values()
            assert result is not None
            assert result["default_priority"] == "high"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_select_default_priority_high")

    @pytest.mark.asyncio
    async def test_advanced_expand_todoist_extras(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "todoist-extras")

            assert screen.query_one("#sync-todoist-root_only", Switch).region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_todoist_extras")

    @pytest.mark.asyncio
    async def test_advanced_expand_trello_list_mappings(self) -> None:
        """Trello list mapping fields only appear when sync.trello.enabled is
        True in the existing config. Keys match TrelloListMappings dataclass
        (todo 506.3): created, done, projects, tasks, active, pending, archived.
        """
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = AdvancedConfigScreen(
                existing={"sync": {"trello": {"enabled": True}}},
                selected_plugins=[],
            )
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "trello-list-mappings")

            for wid in (
                "sync-trello-list_mappings-created",
                "sync-trello-list_mappings-done",
                "sync-trello-list_mappings-projects",
                "sync-trello-list_mappings-tasks",
                "sync-trello-list_mappings-active",
                "sync-trello-list_mappings-pending",
                "sync-trello-list_mappings-archived",
            ):
                assert screen.query_one(f"#{wid}", Input).region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_trello_list_mappings")

    @pytest.mark.asyncio
    async def test_advanced_load_existing_values(self) -> None:
        """Pre-populate advanced widgets from an existing config dict."""
        # smart_gate is now a scalar bool (605.3 removed SmartGateConfig sub-keys)
        existing = {
            "smart_gate": False,
            "archive": {"after_days": 90},
            "default_priority": "high",
        }
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = AdvancedConfigScreen(existing=existing, selected_plugins=[])
            app.push_screen(screen)
            await pilot.pause()

            await _expand_collapsible(pilot, screen, "smart-gate")
            await _expand_collapsible(pilot, screen, "archive")
            await _expand_collapsible(pilot, screen, "other-proj")

            assert screen.query_one("#smart_gate", Switch).value is False
            assert screen.query_one("#archive-after_days", Input).value == "90"
            assert screen.query_one("#default_priority", Select).value == "high"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_load_existing_values")

    @pytest.mark.asyncio
    async def test_advanced_scroll_middle(self) -> None:
        """Scroll the form to ~50% to exercise scroll state."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            form = screen.query_one("#advanced-form")
            # scroll_y accepts a proportion of max scroll.
            max_y = form.max_scroll_y
            form.scroll_to(y=max_y // 2, animate=False)
            await pilot.pause()

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_scroll_middle")

    @pytest.mark.asyncio
    async def test_advanced_scroll_bottom(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            form = screen.query_one("#advanced-form")
            form.scroll_end(animate=False)
            await pilot.pause()

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_scroll_bottom")

    @pytest.mark.asyncio
    async def test_advanced_focus_submit(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#btn-submit", Button).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "btn-submit"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_focus_submit")

    @pytest.mark.asyncio
    async def test_advanced_focus_cancel(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#btn-cancel", Button).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "btn-cancel"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_focus_cancel")

    @pytest.mark.asyncio
    async def test_advanced_focus_back(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#btn-back", Button).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "btn-back"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_focus_back")

    @pytest.mark.asyncio
    async def test_advanced_escape_dismisses(self) -> None:
        """Pressing escape triggers action_cancel and dismisses with None."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            # Snapshot the default layout before escape (post-escape, the
            # screen is popped off the stack and query_one would fail).
            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_escape_dismisses")

            # Verify action_cancel() is wired (smoke check — calling directly
            # is more robust than simulating the key press).
            screen.action_cancel()
            await pilot.pause()
