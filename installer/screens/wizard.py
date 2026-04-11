"""Configuration wizard screen using Textual form widgets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static, Switch

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.wizard_specs import PROJ_YAML_PROMPTS, get_distinct_yaml_files


# Plugins that require proj.yaml configuration
_PROJ_PLUGINS = {"proj", "router", "sandbox", "todoist", "trello", "jira"}


class WizardScreen(Screen[dict[str, Any] | None]):
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
        width: 80;
        max-height: 85%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    #wizard-title {
        text-align: center;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 0;
        margin: 0 0 1 0;
    }

    .group-header {
        text-align: left;
        text-style: bold;
        color: $accent;
        padding: 0 1;
        margin: 1 0 0 0;
    }

    .field-row {
        height: 3;
        padding: 0 1;
        margin: 0;
    }

    .field-label {
        width: 32;
        padding: 1 1;
        color: $text;
    }

    Input {
        margin: 0 1;
        border: tall $primary-background;
    }

    Input:focus {
        border: tall $accent;
    }

    Switch {
        width: auto;
    }

    Select {
        width: 1fr;
    }

    #wizard-buttons {
        height: auto;
        min-height: 3;
        align: center middle;
        margin: 1 0 0 0;
        border-top: solid $primary-background;
        padding: 1 2;
    }

    #wizard-buttons Button {
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
        self._existing: dict[str, dict[str, Any]] = {}
        self._existing_mtimes: dict[str, float] = {}
        self._load_errors: dict[str, Exception] = {}
        self._read_existing_all_yamls()

    def _read_existing_all_yamls(self) -> None:
        """Load every distinct ~/.claude/<yaml_file>.yaml referenced by PROJ_YAML_PROMPTS.

        Populates self._existing (bucket → dict), self._existing_mtimes (bucket
        → st_mtime for TOCTOU re-check in the write path), and self._load_errors
        (bucket → exception, for the corrupt-YAML error surface in 515.8).

        Missing files produce empty buckets with mtime 0.0. ConfigLoadError on
        any bucket is captured in _load_errors but does NOT abort the wizard —
        the bucket falls back to {} and defaults.yaml provides the fallback.
        """
        claude_home = Path.home() / ".claude"
        for bucket in get_distinct_yaml_files(PROJ_YAML_PROMPTS):
            path = claude_home / f"{bucket}.yaml"
            try:
                self._existing[bucket] = load_existing_yaml(path)
            except ConfigLoadError as exc:
                self._existing[bucket] = {}
                self._load_errors[bucket] = exc
            try:
                self._existing_mtimes[bucket] = path.stat().st_mtime
            except FileNotFoundError:
                self._existing_mtimes[bucket] = 0.0
            except OSError:
                self._existing_mtimes[bucket] = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="wizard-form"):
            yield Static("Configuration Wizard", id="wizard-title")
            with VerticalScroll(id="wizard-scroll"):
                current_group: str | None = None
                proj_bucket = self._existing.get("proj", {})
                for spec in PROJ_YAML_PROMPTS:
                    if spec.yaml_file != "proj" or spec.tier != "basic":
                        continue
                    # Hard contract: conditions always read the proj bucket,
                    # regardless of the spec's own yaml_file.
                    if spec.condition is not None and not spec.condition(proj_bucket):
                        continue
                    if spec.group != current_group:
                        yield Static(f"── {spec.group} ──", classes="group-header")
                        current_group = spec.group
                    bucket = self._existing.get(spec.yaml_file, {})
                    default = spec.default_factory(bucket)
                    widget_id = spec.dotted_key.replace(".", "-")
                    row_id = f"row-{widget_id}"
                    if spec.type == "bool":
                        yield Horizontal(
                            Static(spec.label, classes="field-label"),
                            Switch(value=bool(default), id=widget_id),
                            classes="field-row",
                            id=row_id,
                        )
                    elif spec.type == "str":
                        yield Horizontal(
                            Static(spec.label, classes="field-label"),
                            Input(value=str(default), id=widget_id),
                            classes="field-row",
                            id=row_id,
                        )
                    elif spec.type == "choice":
                        choices = spec.choices or []
                        default_str = str(default)
                        selected = (
                            default_str
                            if default_str in choices
                            else (choices[0] if choices else "")
                        )
                        yield Horizontal(
                            Static(spec.label, classes="field-label"),
                            Select(
                                options=[(c, c) for c in choices],
                                value=selected,
                                id=widget_id,
                                allow_blank=False,
                            ),
                            classes="field-row",
                            id=row_id,
                        )
                    elif spec.type == "int":
                        yield Horizontal(
                            Static(spec.label, classes="field-label"),
                            Input(value=str(default), id=widget_id, type="integer"),
                            classes="field-row",
                            id=row_id,
                        )
            with Horizontal(id="wizard-buttons"):
                yield Button("Submit", id="btn-submit", variant="primary")
                yield Button("Advanced...", id="btn-advanced", variant="default")
                yield Button("Cancel", id="btn-cancel", variant="default")
        yield Footer()

    def _collect_values(self) -> dict[str, Any]:
        """Read every basic-tier widget keyed by dotted key."""
        answers: dict[str, Any] = {}
        for spec in PROJ_YAML_PROMPTS:
            if spec.yaml_file != "proj" or spec.tier != "basic":
                continue
            widget_id = spec.dotted_key.replace(".", "-")
            try:
                widget = self.query_one(f"#{widget_id}")
            except Exception:
                continue
            value = getattr(widget, "value", None)
            if spec.type == "bool":
                answers[spec.dotted_key] = bool(value)
            elif spec.type in ("str", "choice"):
                answers[spec.dotted_key] = str(value) if value is not None else ""
            elif spec.type == "int":
                try:
                    answers[spec.dotted_key] = int(value)
                except (TypeError, ValueError):
                    bucket = self._existing.get(spec.yaml_file, {})
                    answers[spec.dotted_key] = spec.default_factory(bucket)
        return answers

    @on(Switch.Changed, "#git_tracking-enabled")
    def _on_git_tracking_toggle(self, event: Switch.Changed) -> None:
        """Show/hide git_tracking sub-widgets when parent toggle flips."""
        for child_id in (
            "row-git_tracking-github_enabled",
            "row-git_tracking-github_repo_format",
        ):
            try:
                row = self.query_one(f"#{child_id}")
                row.display = bool(event.value)
            except Exception:
                pass

    # -- Actions & events --

    def action_cancel(self) -> None:
        """Cancel the wizard."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle submit/cancel/advanced button presses."""
        if event.button.id == "btn-submit":
            self.dismiss(self._collect_values())
        elif event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-advanced":
            basic = self._collect_values()
            try:
                from installer.screens.advanced_config import AdvancedConfigScreen  # type: ignore

                def _on_advanced(result: dict[str, Any] | None) -> None:
                    if result:
                        basic.update(result)
                    self.dismiss(basic)

                self.app.push_screen(
                    AdvancedConfigScreen(self._existing, []),
                    _on_advanced,
                )
            except ImportError:
                self.dismiss(basic)
