"""Textual AdvancedConfigScreen — drilled-down wizard for advanced proj config.

Pushed from WizardScreen via its "Advanced..." button. Iterates PROJ_YAML_PROMPTS
filtered to tier == "advanced", groups fields by spec.group inside Collapsible
widgets, and returns a dict of dotted_key -> value on submit (or None on cancel).

Integration screens (Todoist/Trello/Jira) do their own credential prompts; this
screen only handles the proj.yaml advanced tier plus sync.todoist.root_only,
sync.trello.default_list, sync.trello.on_delete, and sync.trello.list_mappings.*
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Collapsible,
    Footer,
    Header,
    Input,
    Select,
    Static,
    Switch,
)

from installer.wizard_specs import PROJ_YAML_PROMPTS, PromptSpec


class AdvancedConfigScreen(Screen[dict[str, Any] | None]):
    """Advanced wizard tier. Iterates PromptSpec entries grouped by spec.group."""

    CSS = """
    AdvancedConfigScreen {
        align: center middle;
    }
    #advanced-form {
        width: 100%;
        height: 85%;
        border: round $primary;
        padding: 1 2;
    }
    .group-header {
        color: $accent;
        text-style: bold;
    }
    .field-row {
        height: 3;
        margin-bottom: 1;
    }
    .field-label {
        width: 40;
        padding-right: 2;
    }
    #error-message {
        color: $error;
        height: 1;
    }
    #advanced-buttons {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit"),
    ]

    def __init__(
        self,
        existing: dict[str, dict[str, Any]] | dict[str, Any],
        selected_plugins: list[str],
    ) -> None:
        """Initialize with per-bucket existing dict.

        Accepts two shapes for backwards compatibility during the 515.5–515.6
        transition:
        - dict[str, dict[str, Any]]: per-bucket keyed by yaml_file (proj,
          worktree, todoist, trello, jira). This is the canonical post-515.6
          shape passed by WizardScreen.
        - dict[str, Any]: a flat proj bucket. Wrapped as {"proj": existing}
          so pre-515.6 callers still work.

        Detection heuristic: if *any* value in `existing` is a dict AND the
        key matches a known yaml_file name, treat as per-bucket. Otherwise
        treat as a flat proj bucket.
        """
        super().__init__()
        self._existing: dict[str, dict[str, Any]] = self._normalize_existing(
            existing or {}
        )
        self._selected_plugins = selected_plugins or []

    @staticmethod
    def _normalize_existing(
        existing: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Coerce flat-or-bucketed shape into canonical per-bucket dict."""
        yaml_files = {"proj", "worktree", "todoist", "trello", "jira"}
        looks_bucketed = bool(existing) and all(
            k in yaml_files and isinstance(v, dict) for k, v in existing.items()
        )
        if looks_bucketed:
            return {k: v for k, v in existing.items()}
        return {"proj": existing}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="advanced-form"):
            groups: dict[str, list[PromptSpec]] = {}
            # Hard contract: conditions always read the proj bucket.
            proj_bucket = self._existing.get("proj", {})
            for spec in PROJ_YAML_PROMPTS:
                if spec.tier != "advanced":
                    continue
                if spec.condition is not None and not spec.condition(proj_bucket):
                    continue
                groups.setdefault(spec.group, []).append(spec)

            for group_name, specs in groups.items():
                with Collapsible(title=group_name, id=f"group-{_sanitize(group_name)}"):
                    for spec in specs:
                        yield from self._compose_field(spec)

            yield Static("", id="error-message")

        with Horizontal(id="advanced-buttons"):
            yield Button("Submit", id="btn-submit", variant="primary")
            yield Button("Cancel", id="btn-cancel", variant="default")
            yield Button("Back", id="btn-back", variant="default")
        yield Footer()

    def _compose_field(self, spec: PromptSpec) -> ComposeResult:
        bucket = self._existing.get(spec.yaml_file, {})
        default = spec.default_factory(bucket)
        widget_id = spec.dotted_key.replace(".", "-")
        label = spec.label
        if spec.type == "bool":
            yield Horizontal(
                Static(label, classes="field-label"),
                Switch(value=bool(default), id=widget_id),
                classes="field-row",
            )
        elif spec.type == "str":
            yield Horizontal(
                Static(label, classes="field-label"),
                Input(value=str(default), id=widget_id),
                classes="field-row",
            )
        elif spec.type == "int":
            yield Horizontal(
                Static(label, classes="field-label"),
                Input(value=str(default), id=widget_id, type="integer"),
                classes="field-row",
            )
        elif spec.type == "choice":
            choices = spec.choices or []
            effective_default = (
                str(default)
                if str(default) in choices
                else (choices[0] if choices else "")
            )
            yield Horizontal(
                Static(label, classes="field-label"),
                Select(
                    options=[(c, c) for c in choices],
                    value=effective_default,
                    id=widget_id,
                    allow_blank=False,
                ),
                classes="field-row",
            )

    def _collect_values(self) -> dict[str, Any] | None:
        """Read every advanced widget. Returns None on validation error."""
        answers: dict[str, Any] = {}
        for spec in PROJ_YAML_PROMPTS:
            if spec.tier != "advanced":
                continue
            widget_id = spec.dotted_key.replace(".", "-")
            try:
                widget = self.query_one(f"#{widget_id}")
            except Exception:
                continue
            if spec.type == "bool":
                answers[spec.dotted_key] = bool(widget.value)
            elif spec.type in ("str", "choice"):
                answers[spec.dotted_key] = (
                    str(widget.value) if widget.value is not None else ""
                )
            elif spec.type == "int":
                try:
                    value = int(widget.value)
                except (TypeError, ValueError):
                    self._show_error(f"{spec.label}: must be an integer")
                    return None
                if spec.int_range is not None:
                    low, high = spec.int_range
                    if not (low <= value <= high):
                        self._show_error(f"{spec.label}: must be in [{low}, {high}]")
                        return None
                answers[spec.dotted_key] = value
        self._show_error("")
        return answers

    def _show_error(self, msg: str) -> None:
        try:
            self.query_one("#error-message", Static).update(msg)
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        values = self._collect_values()
        if values is not None:
            self.dismiss(values)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            self.action_submit()
        elif event.button.id == "btn-cancel":
            self.action_cancel()
        elif event.button.id == "btn-back":
            self.dismiss(None)


def _sanitize(name: str) -> str:
    """Sanitize group name into a valid widget id."""
    out: list[str] = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    return "".join(out).strip("-") or "group"
