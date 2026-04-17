# installer/screens/migration_progress.py
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static


@dataclass(frozen=True)
class MigrationOutcome:
    project: str
    ok: bool
    resync_partial: bool
    backup: str
    error: str | None = None


class MigrationProgressScreen(Screen):
    BINDINGS = [Binding("enter", "dismiss", "Close")]

    def __init__(self, outcomes: list[MigrationOutcome]) -> None:
        super().__init__()
        self.outcomes = outcomes

    def compose(self) -> ComposeResult:
        yield Header(name="Migration summary")
        with Vertical():
            ok = sum(1 for o in self.outcomes if o.ok)
            partial = sum(1 for o in self.outcomes if o.ok and o.resync_partial)
            failed = sum(1 for o in self.outcomes if not o.ok)
            yield Static(
                f"[bold]Results[/]  ✓ {ok} ok  ◐ {partial} partial-resync  ✗ {failed} failed",
            )
            table = DataTable()
            table.add_columns("Status", "Project", "Backup", "Details")
            for o in self.outcomes:
                if not o.ok:
                    status = "✗"
                elif o.resync_partial:
                    status = "◐"
                else:
                    status = "✓"
                table.add_row(status, o.project, o.backup, o.error or "")
            yield table
        yield Footer()

    def action_dismiss(self) -> None:
        self.dismiss()
