"""Configuration diff review screen with Apply/Cancel actions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static


class ConfigDiffScreen(Screen[bool]):
    """Show a unified YAML diff and let the user Apply or Cancel.

    Dismisses with ``True`` when the user clicks Apply, or ``False``
    on Cancel / Escape.

    Args:
        service_name: Human-readable service name (e.g. "Todoist").
        diff_text: Pre-computed unified diff string to display.
    """

    CSS = """
    ConfigDiffScreen {
        align: center middle;
    }

    #config-diff-dialog {
        width: 90;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    #config-diff-title {
        text-align: center;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 0;
        margin: 0 0 1 0;
    }

    #config-diff-scroll {
        height: 1fr;
        max-height: 100%;
        min-height: 3;
    }

    #config-diff-text {
        height: auto;
        padding: 1 2;
        color: $text-muted;
        overflow-x: auto;
    }

    #config-diff-button-bar {
        height: auto;
        min-height: 3;
        align: center middle;
        border-top: solid $primary-background;
        padding: 1 2;
    }

    #config-diff-button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "apply", "Apply", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        service_name: str,
        diff_text: str,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._service_name = service_name
        self._diff_text = diff_text

    def compose(self) -> ComposeResult:
        with Vertical(id="config-diff-dialog"):
            yield Static(
                f"Configuration Changes \u2014 {self._service_name}",
                id="config-diff-title",
            )
            with VerticalScroll(id="config-diff-scroll"):
                yield Static(
                    self._diff_text or "(no changes)",
                    id="config-diff-text",
                )
            with Horizontal(id="config-diff-button-bar"):
                yield Button("Apply", variant="primary", id="btn-diff-apply")
                yield Button("Cancel", variant="default", id="btn-diff-cancel")
        yield Footer()

    # -- Actions --

    def action_apply(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    # -- Button events --

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-diff-apply":
            self.dismiss(True)
        elif event.button.id == "btn-diff-cancel":
            self.dismiss(False)
