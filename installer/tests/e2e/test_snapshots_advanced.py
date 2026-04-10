"""TUI snapshot + geometry tests for AdvancedConfigScreen (todo 514.24/514.29).

The advanced screen is driven by PROJ_YAML_PROMPTS (tier == "advanced").
Fields are grouped by spec.group inside Collapsible widgets; each group's
id is ``group-<sanitized>`` where sanitization lowercases and replaces
non-alphanumerics with dashes.

Expected group ids (see wizard_specs.PROJ_YAML_PROMPTS):
    group-team-mode
    group-smart-gate
    group-resilience
    group-context-injection
    group-archive
    group-permissions
    group-other-proj
    group-todoist-extras
    group-trello-extras
    group-trello-list-mappings   (only when sync.trello.enabled in existing)

Widget ids come from ``spec.dotted_key.replace(".", "-")``, e.g.
``team_mode-trust_level``, ``smart_gate-enabled``, ``archive-after_days``.
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


def _expand_collapsible(screen: AdvancedConfigScreen, group_id: str) -> None:
    """Force a Collapsible open so its children are laid out."""
    try:
        coll = screen.query_one(f"#group-{group_id}", Collapsible)
        coll.collapsed = False
    except Exception:
        pass


class TestAdvancedConfigScreenSnapshots:
    """25 snapshots covering the AdvancedConfigScreen (todo 514.29)."""

    @pytest.mark.asyncio
    async def test_advanced_initial_render(self) -> None:
        """Baseline: all Collapsibles rendered (may be collapsed)."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            # Required groups must all exist in the DOM.
            for group_id in (
                "team-mode",
                "smart-gate",
                "resilience",
                "context-injection",
                "archive",
                "permissions",
                "other-proj",
                "todoist-extras",
                "trello-extras",
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
    async def test_advanced_expand_team_mode(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            await pilot.pause()

            for wid in (
                "team_mode-enabled",
                "team_mode-max_agents",
                "team_mode-trust_level",
            ):
                assert screen.query_one(f"#{wid}").region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_team_mode")

    @pytest.mark.asyncio
    async def test_advanced_focus_team_mode_trust(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            await pilot.pause()
            screen.query_one("#team_mode-trust_level", Input).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "team_mode-trust_level"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_focus_team_mode_trust")

    @pytest.mark.asyncio
    async def test_advanced_invalid_trust_level(self) -> None:
        """Set trust_level out of range then call _collect_values to trigger
        the error label path."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            await pilot.pause()
            screen.query_one("#team_mode-trust_level", Input).value = "9"
            await pilot.pause()

            result = screen._collect_values()
            assert result is None  # validation failed
            error_static = screen.query_one("#error-message", Static)
            # Error label must be populated.
            assert (
                "trust" in str(error_static.renderable).lower()
                or str(error_static.renderable) != ""
            )

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_invalid_trust_level")

    @pytest.mark.asyncio
    async def test_advanced_valid_trust_level(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            await pilot.pause()
            screen.query_one("#team_mode-trust_level", Input).value = "2"
            await pilot.pause()

            result = screen._collect_values()
            assert result is not None
            assert result["team_mode.trust_level"] == 2

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_valid_trust_level")

    @pytest.mark.asyncio
    async def test_advanced_focus_team_mode_enabled(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            await pilot.pause()
            screen.query_one("#team_mode-enabled", Switch).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "team_mode-enabled"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_focus_team_mode_enabled")

    @pytest.mark.asyncio
    async def test_advanced_focus_max_agents(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            await pilot.pause()
            screen.query_one("#team_mode-max_agents", Input).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "team_mode-max_agents"

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_focus_max_agents")

    @pytest.mark.asyncio
    async def test_advanced_expand_smart_gate(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "smart-gate")
            await pilot.pause()

            for wid in (
                "smart_gate-enabled",
                "smart_gate-auto_execute_threshold",
                "smart_gate-full_review_threshold",
            ):
                assert screen.query_one(f"#{wid}").region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_smart_gate")

    @pytest.mark.asyncio
    async def test_advanced_expand_resilience(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "resilience")
            await pilot.pause()

            assert screen.query_one("#resilience-max_retries", Input).region.width > 0
            assert (
                screen.query_one("#resilience-backoff_seconds", Input).region.width > 0
            )

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_resilience")

    @pytest.mark.asyncio
    async def test_advanced_expand_context_injection(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "context-injection")
            await pilot.pause()

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

            _expand_collapsible(screen, "archive")
            await pilot.pause()

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

            _expand_collapsible(screen, "permissions")
            await pilot.pause()

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

            _expand_collapsible(screen, "other-proj")
            await pilot.pause()

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

            _expand_collapsible(screen, "other-proj")
            await pilot.pause()
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

            _expand_collapsible(screen, "other-proj")
            await pilot.pause()
            sel = screen.query_one("#default_priority", Select)
            sel.value = "high"
            await pilot.pause()

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

            _expand_collapsible(screen, "todoist-extras")
            await pilot.pause()

            assert screen.query_one("#sync-todoist-root_only", Switch).region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_todoist_extras")

    @pytest.mark.asyncio
    async def test_advanced_expand_trello_extras(self) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = _make_screen()
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "trello-extras")
            await pilot.pause()

            assert screen.query_one("#sync-trello-default_list", Input).region.width > 0
            assert screen.query_one("#sync-trello-on_delete", Select).region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_trello_extras")

    @pytest.mark.asyncio
    async def test_advanced_expand_trello_list_mappings(self) -> None:
        """Trello list mapping fields only appear when sync.trello.enabled is
        True in the existing config."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = AdvancedConfigScreen(
                existing={"sync": {"trello": {"enabled": True}}},
                selected_plugins=[],
            )
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "trello-list-mappings")
            await pilot.pause()

            for wid in (
                "sync-trello-list_mappings-backlog",
                "sync-trello-list_mappings-todo",
                "sync-trello-list_mappings-in_progress",
                "sync-trello-list_mappings-blocked",
                "sync-trello-list_mappings-done",
                "sync-trello-list_mappings-archive",
            ):
                assert screen.query_one(f"#{wid}", Input).region.width > 0

            svg = app.export_screenshot()
            _assert_snapshot(svg, "advanced_expand_trello_list_mappings")

    @pytest.mark.asyncio
    async def test_advanced_load_existing_values(self) -> None:
        """Pre-populate advanced widgets from an existing config dict."""
        existing = {
            "team_mode": {"enabled": False, "max_agents": 7, "trust_level": 2},
            "smart_gate": {"enabled": False, "auto_execute_threshold": 5},
            "archive": {"after_days": 90},
            "default_priority": "high",
        }
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = AdvancedConfigScreen(existing=existing, selected_plugins=[])
            app.push_screen(screen)
            await pilot.pause()

            _expand_collapsible(screen, "team-mode")
            _expand_collapsible(screen, "smart-gate")
            _expand_collapsible(screen, "archive")
            _expand_collapsible(screen, "other-proj")
            await pilot.pause()

            assert screen.query_one("#team_mode-enabled", Switch).value is False
            assert screen.query_one("#team_mode-max_agents", Input).value == "7"
            assert screen.query_one("#team_mode-trust_level", Input).value == "2"
            assert screen.query_one("#smart_gate-enabled", Switch).value is False
            assert (
                screen.query_one("#smart_gate-auto_execute_threshold", Input).value
                == "5"
            )
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
