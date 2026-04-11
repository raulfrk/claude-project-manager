"""Modal screen shown when one or more ~/.claude/*.yaml files fail to parse.

Surfaces the specific bucket, path, and original exception so users can fix
the file out-of-band before re-running the wizard. Two outcomes:
- Continue: proceed with empty dict (wizard shows defaults.yaml fallbacks).
- Cancel: abort the wizard entirely.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static


class CorruptYamlScreen(Screen[bool]):
    """Modal shown when ~/.claude/*.yaml files fail to parse.

    Dismisses with True if the user opts to continue with defaults, False
    if they cancel.
    """

    CSS = """
    CorruptYamlScreen {
        align: center middle;
    }

    #corrupt-dialog {
        width: 80;
        max-height: 80%;
        padding: 1 2;
        border: round $error;
        background: $surface;
    }

    #corrupt-title {
        text-align: center;
        text-style: bold;
        color: $error;
        padding: 1 0;
        margin: 0 0 1 0;
    }

    #corrupt-body {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    .corrupt-entry {
        margin: 0 0 1 0;
        padding: 1;
        background: $primary-background;
        border: tall $error;
    }

    .corrupt-path {
        text-style: bold;
        color: $warning;
    }

    .corrupt-reason {
        color: $text-muted;
    }

    #corrupt-buttons {
        height: 3;
        align: center middle;
        margin: 1 0 0 0;
    }

    #corrupt-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        errors: dict[str, Exception],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._errors = errors

    def compose(self) -> ComposeResult:
        with Vertical(id="corrupt-dialog"):
            yield Static(
                "⚠ Corrupt Configuration File(s)",
                id="corrupt-title",
            )
            with VerticalScroll(id="corrupt-body"):
                yield Static(
                    "The following ~/.claude/*.yaml files could not be parsed. "
                    "You can continue with defaults (your existing values for the "
                    "affected files will NOT be preserved) or cancel to fix them "
                    "manually.",
                )
                for bucket, exc in self._errors.items():
                    path = Path.home() / ".claude" / f"{bucket}.yaml"
                    original = getattr(exc, "original", exc)
                    with Vertical(classes="corrupt-entry"):
                        yield Static(f"{bucket}.yaml", classes="corrupt-path")
                        yield Static(str(path), classes="corrupt-reason")
                        yield Static(f"Reason: {original}", classes="corrupt-reason")
            with Horizontal(id="corrupt-buttons"):
                yield Button(
                    "Continue with defaults", id="btn-continue", variant="primary"
                )
                yield Button("Cancel", id="btn-cancel", variant="error")
        yield Footer()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            self.dismiss(True)
        elif event.button.id == "btn-cancel":
            self.dismiss(False)
