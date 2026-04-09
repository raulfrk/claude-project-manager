"""Hook diff review screen with per-hook Apply/Skip toggles."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Static

from installer.hooks_diff import HookDiff

# Status badge labels
_STATUS_BADGES: dict[str, str] = {
    "new": "[bold green]NEW[/]",
    "changed": "[bold yellow]CHANGED[/]",
    "removed": "[bold red]REMOVED[/]",
}


class HooksDiffScreen(Screen[dict[str, set[str]] | None]):
    """Show per-hook diffs with Apply/Skip toggles.

    Displays a scrollable list of hook diffs. Each diff shows the hook ID,
    a status badge (NEW/CHANGED/REMOVED), the unified diff text, and a
    checkbox to include or exclude it.

    Dismisses with ``{"apply": set[str], "remove": set[str]}`` when the
    user clicks Continue, or ``None`` on Cancel.

    Args:
        diffs: List of HookDiff objects from compute_hooks_diff().
    """

    CSS = """
    HooksDiffScreen {
        align: center middle;
    }

    #hooks-diff-dialog {
        width: 90;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    #hooks-diff-title {
        text-align: center;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 0;
        margin: 0 0 1 0;
    }

    #hooks-diff-scroll {
        height: 1fr;
        max-height: 100%;
        min-height: 3;
    }

    .hook-card {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        border: solid $primary-background;
    }

    .hook-header {
        height: auto;
        padding: 0 0 1 0;
    }

    .hook-id {
        text-style: bold;
        color: $text;
        width: 1fr;
        height: 1;
    }

    .hook-badge {
        width: auto;
        height: 1;
        padding: 0 1;
    }

    .hook-diff-text {
        height: auto;
        padding: 0 1;
        color: $text-muted;
        overflow-x: auto;
    }

    .hook-checkbox {
        margin: 1 0 0 0;
        padding: 0 1;
    }

    #hooks-diff-shortcut-bar {
        height: auto;
        min-height: 3;
        align: center middle;
        padding: 1 0;
    }

    #hooks-diff-shortcut-bar Button {
        margin: 0 1;
    }

    #hooks-diff-button-bar {
        height: auto;
        min-height: 3;
        align: center middle;
        border-top: solid $primary-background;
        padding: 1 2;
    }

    #hooks-diff-button-bar Button {
        margin: 0 1;
    }

    #hooks-diff-empty {
        height: auto;
        padding: 2 2;
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("a", "apply_all", "Apply All", show=True),
        Binding("s", "skip_all", "Skip All", show=True),
        Binding("enter", "continue_action", "Continue", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        diffs: list[HookDiff],
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._diffs = diffs

    def compose(self) -> ComposeResult:
        with Vertical(id="hooks-diff-dialog"):
            yield Static("Hook Configuration Updates", id="hooks-diff-title")

            if not self._diffs:
                yield Static(
                    "hooks.yaml is up to date — no changes needed.",
                    id="hooks-diff-empty",
                )
                with Horizontal(id="hooks-diff-button-bar"):
                    yield Button("Continue", variant="primary", id="btn-hooks-continue")
            else:
                with VerticalScroll(id="hooks-diff-scroll"):
                    for diff in self._diffs:
                        badge = _STATUS_BADGES.get(diff.status, diff.status.upper())
                        # Default: checked for new/changed, unchecked for removed
                        default_checked = diff.status != "removed"

                        with Vertical(classes="hook-card"):
                            with Horizontal(classes="hook-header"):
                                yield Static(diff.hook_id, classes="hook-id")
                                yield Static(badge, classes="hook-badge", markup=True)
                            yield Static(
                                diff.unified_diff or "(no diff)",
                                classes="hook-diff-text",
                            )
                            yield Checkbox(
                                "Include this hook",
                                value=default_checked,
                                id=f"hook-cb-{diff.hook_id}",
                                classes="hook-checkbox",
                            )

                with Horizontal(id="hooks-diff-shortcut-bar"):
                    yield Button(
                        "Apply All", variant="success", id="btn-hooks-apply-all"
                    )
                    yield Button("Skip All", variant="warning", id="btn-hooks-skip-all")

                with Horizontal(id="hooks-diff-button-bar"):
                    yield Button("Continue", variant="primary", id="btn-hooks-continue")
                    yield Button("Cancel", variant="default", id="btn-hooks-cancel")
        yield Footer()

    def _set_all_checkboxes(self, value: bool) -> None:
        """Set all hook checkboxes to the given value."""
        for diff in self._diffs:
            try:
                cb = self.query_one(f"#hook-cb-{diff.hook_id}", Checkbox)
                cb.value = value
            except Exception:
                pass

    def _collect_selections(self) -> dict[str, set[str]]:
        """Gather checked hooks into apply/remove sets based on status."""
        apply_ids: set[str] = set()
        remove_ids: set[str] = set()

        for diff in self._diffs:
            try:
                cb = self.query_one(f"#hook-cb-{diff.hook_id}", Checkbox)
                checked = cb.value
            except Exception:
                checked = False

            if not checked:
                continue

            if diff.status == "removed":
                remove_ids.add(diff.hook_id)
            else:
                apply_ids.add(diff.hook_id)

        return {"apply": apply_ids, "remove": remove_ids}

    # -- Actions --

    def action_apply_all(self) -> None:
        self._set_all_checkboxes(True)

    def action_skip_all(self) -> None:
        self._set_all_checkboxes(False)

    def action_continue_action(self) -> None:
        if not self._diffs:
            self.dismiss(None)
        else:
            self.dismiss(self._collect_selections())

    def action_cancel(self) -> None:
        self.dismiss(None)

    # -- Button events --

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-hooks-continue":
            self.action_continue_action()
        elif event.button.id == "btn-hooks-cancel":
            self.action_cancel()
        elif event.button.id == "btn-hooks-apply-all":
            self._set_all_checkboxes(True)
        elif event.button.id == "btn-hooks-skip-all":
            self._set_all_checkboxes(False)
