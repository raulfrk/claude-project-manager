"""Post-install summary screen.

Displays the outcome of each plugin action (install / reinstall /
uninstall) after the status install worker finishes so the user can see
at a glance which operations succeeded and which failed.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static


@dataclass
class PluginOutcome:
    """Result of a single plugin action executed by the status install worker."""

    name: str
    action: str
    status: str
    error: str | None = None


class SummaryScreen(Screen[None]):
    """Show a table of per-plugin outcomes with a Close button."""

    CSS = """
    SummaryScreen {
        layout: vertical;
    }

    #summary-title {
        dock: top;
        height: 3;
        content-align: center middle;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 2;
    }

    #summary-container {
        height: 1fr;
        margin: 1 2;
        border: round $primary-background;
    }

    DataTable {
        height: 1fr;
    }

    #summary-empty {
        content-align: center middle;
        color: $text-muted;
    }

    #summary-buttons {
        dock: bottom;
        height: 3;
        align: center middle;
        padding: 0 2;
    }

    #summary-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    def __init__(
        self,
        outcomes: list[PluginOutcome],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._outcomes = outcomes

    def compose(self) -> ComposeResult:
        yield Static("Install Summary", id="summary-title")
        with Vertical(id="summary-container"):
            if not self._outcomes:
                yield Static(
                    "No actions were performed.",
                    id="summary-empty",
                )
            else:
                yield DataTable(
                    id="summary-table",
                    cursor_type="row",
                    zebra_stripes=True,
                )
        with Horizontal(id="summary-buttons"):
            yield Button("Close", variant="primary", id="btn-close")
        yield Footer()

    def on_mount(self) -> None:
        if not self._outcomes:
            return
        table = self.query_one("#summary-table", DataTable)
        table.add_columns("Plugin", "Action", "Status", "Error")
        for outcome in self._outcomes:
            table.add_row(
                outcome.name,
                outcome.action,
                outcome.status,
                outcome.error or "",
                key=f"outcome-{outcome.name}",
            )

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)
