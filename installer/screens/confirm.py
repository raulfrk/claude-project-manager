"""Reusable confirmation dialog screen."""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Static


@dataclass
class ConfirmOption:
    """A toggle option to display in the confirmation dialog."""

    key: str
    label: str
    default: bool = False


@dataclass
class ConfirmResult:
    """Result returned by ConfirmScreen via dismiss().

    Attributes:
        confirmed: True if the user confirmed, False if cancelled.
        options: Dict of option key -> boolean value for each toggle.
    """

    confirmed: bool
    options: dict[str, bool] = field(default_factory=dict)


class ConfirmScreen(Screen[ConfirmResult]):
    """Reusable confirmation dialog for reinstall/uninstall flows.

    Accepts a title, message, and list of toggle options. Returns a
    ConfirmResult with the user's choices via dismiss().

    Example usage for reinstall::

        screen = ConfirmScreen(
            title="Reinstall Plugins",
            message="This will reinstall the selected plugins.",
            options=[
                ConfirmOption(key="reset_configs", label="Reset configs", default=False),
            ],
        )

    Example usage for uninstall::

        screen = ConfirmScreen(
            title="Uninstall Plugins",
            message="This will remove all installed plugins.",
            options=[
                ConfirmOption(key="full_cleanup", label="Full cleanup (remove configs)", default=False),
            ],
        )
    """

    CSS = """
    ConfirmScreen {
        layout: vertical;
        align: center middle;
    }

    #confirm-dialog {
        width: 70;
        max-height: 80%;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    ConfirmScreen.--danger #confirm-dialog {
        border: round $error;
    }

    ConfirmScreen.--warning #confirm-dialog {
        border: round $warning;
    }

    #confirm-title {
        text-style: bold;
        color: $text;
        background: $accent;
        content-align: center middle;
        height: 3;
        padding: 0 2;
        margin: 0 0 1 0;
    }

    ConfirmScreen.--danger #confirm-title {
        background: $error;
    }

    ConfirmScreen.--warning #confirm-title {
        background: $warning;
    }

    #confirm-message {
        height: auto;
        max-height: 8;
        padding: 1 2;
        color: $text;
    }

    #confirm-options {
        height: auto;
        padding: 1 2;
        border-top: solid $primary-background;
        margin: 1 0 0 0;
    }

    #confirm-options Checkbox {
        margin: 0 0 1 0;
        padding: 0 1;
    }

    #confirm-button-bar {
        height: 5;
        min-height: 5;
        align: center middle;
        padding: 1 2;
        border-top: solid $primary-background;
    }

    #confirm-button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Confirm", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        title: str,
        message: str,
        options: list[ConfirmOption] | None = None,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        confirm_variant: str = "primary",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._title_text = title
        self._message_text = message
        self._options = options or []
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label
        self._confirm_variant = confirm_variant

    def on_mount(self) -> None:
        """Apply variant-based styling classes."""
        if self._confirm_variant == "error":
            self.add_class("--danger")
        elif self._confirm_variant == "warning":
            self.add_class("--warning")

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._title_text, id="confirm-title")
            yield Static(self._message_text, id="confirm-message")
            if self._options:
                with Vertical(id="confirm-options"):
                    for opt in self._options:
                        yield Checkbox(
                            opt.label,
                            value=opt.default,
                            id=f"opt-{opt.key}",
                        )
            with Horizontal(id="confirm-button-bar"):
                yield Button(
                    self._confirm_label,
                    variant=self._confirm_variant,
                    id="btn-confirm",
                )
                yield Button(
                    self._cancel_label,
                    variant="default",
                    id="btn-cancel",
                )
        yield Footer()

    def _gather_options(self) -> dict[str, bool]:
        """Collect current values from all option checkboxes."""
        result: dict[str, bool] = {}
        for opt in self._options:
            try:
                checkbox = self.query_one(f"#opt-{opt.key}", Checkbox)
                result[opt.key] = checkbox.value
            except Exception:
                result[opt.key] = opt.default
        return result

    def action_confirm(self) -> None:
        self.dismiss(ConfirmResult(confirmed=True, options=self._gather_options()))

    def action_cancel(self) -> None:
        self.dismiss(ConfirmResult(confirmed=False, options=self._gather_options()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.action_confirm()
        elif event.button.id == "btn-cancel":
            self.action_cancel()
