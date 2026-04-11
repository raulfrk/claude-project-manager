"""Transition snapshot tests for integration config screens.

Covers TodoistConfigScreen, TrelloConfigScreen, JiraConfigScreen. All
tests rely on the ``stub_httpx`` fixture from ``conftest.py`` to prevent
any real network call. Error states are triggered via direct
``_show_error()`` calls (not by pressing Continue with bad credentials).

See ``test_snapshots.py`` module docstring for full inventory and
per-screen widget ID map.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Select, Static, Switch

from installer.screens.integration_config import (
    JiraConfigScreen,
    TodoistConfigScreen,
    TrelloConfigScreen,
)
from installer.tests.e2e.test_snapshots import _assert_snapshot

_TERM_SIZE = (120, 40)


class _ScreenHost(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force Path.home() to a tmp dir so integration screens can't read
    real user config files during snapshot capture."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("HOME", str(home))
    return home


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# TodoistConfigScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_todoist_focus_skip_snapshot(stub_httpx) -> None:
    """Focus on #btn-skip (default focus is #btn-continue)."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = TodoistConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-skip", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-skip"

        screen._hide_loading()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_todoist_focus_skip")


@pytest.mark.asyncio
async def test_integration_todoist_error_invalid_token_snapshot(stub_httpx) -> None:
    """Error label visible via direct _show_error() (no real API call)."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = TodoistConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen._show_error("Invalid API token")
        screen._hide_loading()
        await pilot.pause()

        # Default focus is #btn-continue (set in on_mount).
        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-continue"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_todoist_error_invalid_token")


@pytest.mark.asyncio
async def test_integration_todoist_disabled_confirm_snapshot(stub_httpx) -> None:
    """Disable the Continue button via reactive property and snapshot."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = TodoistConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        # Flip sync_enabled OFF — this is the reactive state that normally
        # causes _on_continue to skip validation; combined with a disabled
        # button, it represents the "not actionable" variant.
        screen.query_one("#sync_enabled", Switch).value = False
        btn = screen.query_one("#btn-continue", Button)
        btn.disabled = True
        await pilot.pause()

        # Focus on the still-enabled Skip button for a deterministic focus.
        screen.query_one("#btn-skip", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-skip"

        screen._hide_loading()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_todoist_disabled_confirm")


# ---------------------------------------------------------------------------
# TrelloConfigScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_trello_initial_snapshot(stub_httpx) -> None:
    """Baseline Trello config form (no existing golden yet)."""
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = TrelloConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        # on_mount() sets focus to #btn-continue.
        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-continue"

        screen._hide_loading()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_trello_initial")


@pytest.mark.asyncio
async def test_integration_trello_focus_skip_snapshot(stub_httpx) -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = TrelloConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-skip", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-skip"

        screen._hide_loading()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_trello_focus_skip")


@pytest.mark.asyncio
async def test_integration_trello_error_invalid_credentials_snapshot(
    stub_httpx,
) -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = TrelloConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen._show_error("Invalid API key or token")
        screen._hide_loading()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-continue"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_trello_error_invalid_credentials")


# ---------------------------------------------------------------------------
# JiraConfigScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_jira_initial_snapshot(stub_httpx) -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = JiraConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-continue"

        screen._hide_loading()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_jira_initial")


@pytest.mark.asyncio
async def test_integration_jira_focus_skip_snapshot(stub_httpx) -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = JiraConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#btn-skip", Button).focus()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-skip"

        screen._hide_loading()
        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_jira_focus_skip")


@pytest.mark.asyncio
async def test_integration_jira_error_invalid_url_snapshot(stub_httpx) -> None:
    app = _ScreenHost()
    async with app.run_test(size=_TERM_SIZE) as pilot:
        screen = JiraConfigScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen._show_error("Cannot reach https://bogus.example — check URL and network")
        screen._hide_loading()
        await pilot.pause()

        assert pilot.app.focused is not None
        assert pilot.app.focused.id == "btn-continue"

        svg = app.export_screenshot()
        _assert_snapshot(svg, "integration_jira_error_invalid_url")


# ---------------------------------------------------------------------------
# Integration screens extended (todo 514.25 / 514.29)
# ---------------------------------------------------------------------------


class TestIntegrationScreensExtended:
    """Extended snapshots covering existing-value load paths and new Trello
    on_delete / Todoist root_only widgets added by the PromptSpec rework."""

    # --- Todoist ---------------------------------------------------------

    @pytest.mark.asyncio
    async def test_todoist_loads_existing_defaults(
        self, stub_httpx, _isolate_home: Path
    ) -> None:
        _write_yaml(
            _isolate_home / ".claude" / "todoist.yaml",
            {"api_token": "tok-existing", "enabled": True, "auto_sync": False},
        )
        _write_yaml(
            _isolate_home / ".claude" / "proj.yaml",
            {"sync": {"todoist": {"root_only": True}}},
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            # Existing api_token picked up.
            assert screen.query_one("#api_token", Input).value == "tok-existing"
            assert screen.query_one("#sync_enabled", Switch).value is True
            assert screen.query_one("#auto_sync", Switch).value is False
            assert screen.query_one("#todoist-root-only", Switch).value is True

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_todoist_loads_existing_defaults")

    @pytest.mark.asyncio
    async def test_todoist_focus_root_only(self, stub_httpx) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#todoist-root-only", Switch).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "todoist-root-only"

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_todoist_focus_root_only")

    @pytest.mark.asyncio
    async def test_todoist_toggle_root_only(self, stub_httpx) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TodoistConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            sw = screen.query_one("#todoist-root-only", Switch)
            sw.value = True
            sw.focus()
            await pilot.pause()

            assert sw.value is True
            values = screen._collect_values()
            assert values.get("sync.todoist.root_only") is True

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_todoist_toggle_root_only")

    # --- Trello ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_trello_loads_existing_defaults(
        self, stub_httpx, _isolate_home: Path
    ) -> None:
        # Post-506: default_board_id moved from trello.yaml (TrelloConfigScreen)
        # to proj.yaml sync.trello.default_board_id (PROJ_YAML_PROMPTS basic tier).
        # TrelloConfigScreen owns only credentials + display-local defaults now.
        _write_yaml(
            _isolate_home / ".claude" / "trello.yaml",
            {
                "api_key": "key-existing",
                "token": "tok-existing",
                "enabled": True,
                "auto_sync": True,
            },
        )
        _write_yaml(
            _isolate_home / ".claude" / "proj.yaml",
            {"sync": {"trello": {"default_list": "Inbox", "on_delete": "delete"}}},
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#api_key", Input).value == "key-existing"
            assert screen.query_one("#token", Input).value == "tok-existing"
            assert screen.query_one("#trello-default-list", Input).value == "Inbox"
            assert screen.query_one("#trello-on-delete", Select).value == "delete"

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_trello_loads_existing_defaults")

    @pytest.mark.asyncio
    async def test_trello_focus_default_list(self, stub_httpx) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#trello-default-list", Input).focus()
            await pilot.pause()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "trello-default-list"

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_trello_focus_default_list")

    @pytest.mark.asyncio
    async def test_trello_focus_on_delete(self, stub_httpx) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#trello-on-delete", Select).focus()
            await pilot.pause()

            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "trello-on-delete"

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_trello_focus_on_delete")

    @pytest.mark.asyncio
    async def test_trello_select_on_delete_delete(self, stub_httpx) -> None:
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = TrelloConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            sel = screen.query_one("#trello-on-delete", Select)
            sel.value = "delete"
            sel.focus()
            await pilot.pause()

            assert sel.value == "delete"
            values = screen._collect_values()
            assert values.get("sync.trello.on_delete") == "delete"

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_trello_select_on_delete_delete")

    # --- Jira ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_jira_loads_existing_defaults(
        self, stub_httpx, _isolate_home: Path
    ) -> None:
        _write_yaml(
            _isolate_home / ".claude" / "jira.yaml",
            {
                "base_url": "https://acme.atlassian.net",
                "default_user": "alice@example.com",
                "personal_access_token": "super-secret-pat",
                "default_project": "PROJ",
                "enabled": True,
                "auto_sync": True,
            },
        )
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            assert (
                screen.query_one("#base_url", Input).value
                == "https://acme.atlassian.net"
            )
            assert screen.query_one("#default_user", Input).value == "alice@example.com"
            assert screen.query_one("#default_project", Input).value == "PROJ"
            # Value is present but input is password-masked.
            pat = screen.query_one("#personal_access_token", Input)
            assert pat.value == "super-secret-pat"
            assert pat.password is True

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_jira_loads_existing_defaults")

    @pytest.mark.asyncio
    async def test_jira_masked_credential_display(self, stub_httpx) -> None:
        """Setting a PAT value directly must still render masked (password=True)."""
        app = _ScreenHost()
        async with app.run_test(size=_TERM_SIZE) as pilot:
            screen = JiraConfigScreen()
            app.push_screen(screen)
            await pilot.pause()

            pat = screen.query_one("#personal_access_token", Input)
            pat.value = "hunter2-should-be-masked"
            pat.focus()
            await pilot.pause()

            assert pat.password is True
            assert pat.value == "hunter2-should-be-masked"

            screen._hide_loading()
            svg = app.export_screenshot()
            _assert_snapshot(svg, "integration_jira_masked_credential_display")
