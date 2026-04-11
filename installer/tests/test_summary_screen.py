"""Tests for ``installer.screens.summary.SummaryScreen``."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from installer.screens.summary import PluginOutcome, SummaryScreen


class _Host(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


@pytest.mark.asyncio
async def test_summary_screen_renders_outcomes() -> None:
    outcomes = [
        PluginOutcome(name="router", action="install", status="ok"),
        PluginOutcome(name="proj", action="reinstall", status="ok"),
    ]
    host = _Host()
    async with host.run_test(size=(120, 40)) as pilot:
        host.push_screen(SummaryScreen(outcomes=outcomes))
        await pilot.pause()
        table = host.screen.query_one("#summary-table", DataTable)
        assert table.row_count == 2
        assert [col.label.plain for col in table.ordered_columns] == [
            "Plugin",
            "Action",
            "Status",
            "Error",
        ]


@pytest.mark.asyncio
async def test_summary_screen_renders_failures_with_error() -> None:
    outcomes = [
        PluginOutcome(
            name="router",
            action="install",
            status="failed",
            error="network timeout",
        ),
        PluginOutcome(name="proj", action="install", status="ok"),
    ]
    host = _Host()
    async with host.run_test(size=(120, 40)) as pilot:
        host.push_screen(SummaryScreen(outcomes=outcomes))
        await pilot.pause()
        table = host.screen.query_one("#summary-table", DataTable)
        assert table.row_count == 2
        row = table.get_row_at(0)
        assert row[2] == "failed"
        assert row[3] == "network timeout"


@pytest.mark.asyncio
async def test_summary_screen_empty_list() -> None:
    host = _Host()
    async with host.run_test(size=(120, 40)) as pilot:
        host.push_screen(SummaryScreen(outcomes=[]))
        await pilot.pause()
        # No table should be queryable; an empty placeholder is shown instead.
        assert host.screen.query("#summary-table").__len__() == 0
        placeholder = host.screen.query_one("#summary-empty", Static)
        assert placeholder is not None
