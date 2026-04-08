"""Configuration wizard screen using Textual form widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, Switch


# Plugins that require proj.yaml configuration
_PROJ_PLUGINS = {"proj", "hooks", "sandbox", "todoist", "trello", "jira"}


class WizardScreen(Screen[dict[str, str | bool] | None]):
    """Post-install configuration wizard.

    Collects paths and integration toggles, then returns them as a dict
    via ``dismiss()``.  Returns ``None`` if the user cancels.

    Args:
        selected_plugins: Plugin names chosen in the previous step.
    """

    CSS = """
    WizardScreen {
        align: center middle;
    }

    #wizard-form {
        width: 70;
        max-height: 80%;
        padding: 1 2;
        border: solid $accent;
        background: $surface;
    }

    #wizard-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding: 1 0;
    }

    .field-group {
        height: auto;
        margin: 1 0 0 0;
    }

    .field-label {
        height: 1;
        padding: 0 1;
        color: $text;
    }

    .field-hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    Input {
        margin: 0 1;
    }

    .switch-row {
        height: 3;
        padding: 0 1;
    }

    .switch-row Label {
        padding: 1 1;
        width: 1fr;
    }

    .switch-row Switch {
        width: auto;
    }

    #button-bar {
        height: 3;
        align: center middle;
        margin: 1 0 0 0;
    }

    #button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        selected_plugins: list[str],
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._selected_plugins = selected_plugins
        self._needs_proj = bool(_PROJ_PLUGINS & set(selected_plugins))
        self._needs_worktree = "worktree" in selected_plugins

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="wizard-form"):
            yield Static("Configuration Wizard", id="wizard-title")
            yield Static(
                "Configure plugin settings. Leave blank for defaults.",
                classes="field-hint",
            )

            # -- Path fields --
            if self._needs_proj:
                with Vertical(classes="field-group"):
                    yield Label("Tracking directory", classes="field-label")
                    yield Input(
                        placeholder="~/projects/tracking",
                        id="tracking_dir",
                    )

                with Vertical(classes="field-group"):
                    yield Label("Projects base directory", classes="field-label")
                    yield Input(
                        placeholder="~/projects",
                        id="projects_base_dir",
                    )

            if self._needs_worktree:
                with Vertical(classes="field-group"):
                    yield Label("Default worktree directory", classes="field-label")
                    yield Input(
                        placeholder="~/worktrees",
                        id="worktree_dir",
                    )

            # -- Toggle switches --
            if self._needs_proj:
                with Horizontal(classes="switch-row"):
                    yield Label("Sandbox integration")
                    yield Switch(value=True, id="sandbox_integration")

                with Horizontal(classes="switch-row"):
                    yield Label("Zoxide integration")
                    yield Switch(value=False, id="zoxide_integration")

            # -- Buttons --
            with Horizontal(id="button-bar"):
                yield Button("Submit", variant="primary", id="btn-submit")
                yield Button("Cancel", variant="default", id="btn-cancel")
        yield Footer()

    def _collect_values(self) -> dict[str, str | bool]:
        """Read current widget values and apply defaults for blank fields."""
        config: dict[str, str | bool] = {}

        if self._needs_proj:
            tracking = self.query_one("#tracking_dir", Input).value.strip()
            config["tracking_dir"] = tracking or "~/projects/tracking"

            projects = self.query_one("#projects_base_dir", Input).value.strip()
            config["projects_base_dir"] = projects or "~/projects"

            config["sandbox_integration"] = self.query_one(
                "#sandbox_integration", Switch
            ).value
            config["zoxide_integration"] = self.query_one(
                "#zoxide_integration", Switch
            ).value

        if self._needs_worktree:
            wt_dir = self.query_one("#worktree_dir", Input).value.strip()
            config["worktree_dir"] = wt_dir or "~/worktrees"

        return config

    # -- Actions & events --

    def action_cancel(self) -> None:
        """Cancel the wizard."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle submit/cancel button presses."""
        if event.button.id == "btn-submit":
            self.dismiss(self._collect_values())
        elif event.button.id == "btn-cancel":
            self.dismiss(None)
