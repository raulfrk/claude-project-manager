# installer/screens/migration_overview.py
from __future__ import annotations

from typing import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from installer.migrations.types import PendingProject


class MigrationOverviewScreen(Screen):
    """Screen 1: lists projects needing flat-todo migration."""

    BINDINGS = [
        Binding("enter", "review", "Review"),
        Binding("s", "skip_all", "Skip all"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    MigrationOverviewScreen > Vertical { padding: 1 2; }
    DataTable { height: 1fr; }
    """

    def __init__(
        self,
        pending: Iterable[PendingProject],
        integration_map: dict[str, set[str]],
        counts: dict[str, tuple[int, int]],
    ) -> None:
        super().__init__()
        self.pending = list(pending)
        self.integration_map = integration_map
        self.counts = counts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(
                f"{len(self.pending)} projects need migration to schema_version=2.",
                classes="summary",
            )
            table = DataTable()
            table.add_columns("Project", "Parents", "Children", "Remote")
            for p in self.pending:
                parents, children = self.counts.get(p.name, (0, 0))
                remote = ",".join(sorted(self.integration_map.get(p.name, []))) or "–"
                table.add_row(p.name, str(parents), str(children), remote)
            yield table
        yield Footer()

    def action_review(self) -> None:
        self.dismiss(("review", self.pending))

    def action_skip_all(self) -> None:
        self.dismiss(("skip_all", []))

    def action_quit(self) -> None:
        self.dismiss(("quit", []))
