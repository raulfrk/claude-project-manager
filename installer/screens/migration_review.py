# installer/screens/migration_review.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Static, TabbedContent, TabPane

from installer.migrations.types import MigrationPlan


class MigrationReviewScreen(Screen):
    BINDINGS = [
        Binding("m", "migrate", "Migrate"),
        Binding("s", "skip", "Skip"),
        Binding("d", "dry_run_preview", "Dry-run preview"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    MigrationReviewScreen > Vertical { padding: 1 2; }
    .label { margin-bottom: 1; }
    .hint { margin-top: 1; color: $text-muted; }
    """

    def __init__(self, plan: MigrationPlan, backup_preview: str) -> None:
        super().__init__()
        self.plan = plan
        self.backup_preview = backup_preview

    def compose(self) -> ComposeResult:
        yield Header(name=f"Migrate — {self.plan.project.name}")
        with Vertical():
            yield Static(
                f"[bold]Plan preview[/]\n"
                f"• {len(self.plan.parents)} parent todos → flat w/ group:<id>\n"
                f"• {len(self.plan.children)} children → top-level with group:<parent>\n"
                f"• No parent/children fields after migration",
                classes="label",
            )
            totals = {k: len(v) for k, v in self.plan.integration_actions.items()}
            yield Static(
                f"[bold]Remote resync[/]  "
                f"Todoist: {totals.get('todoist', 0)}  "
                f"Trello: {totals.get('trello', 0)}  "
                f"Jira: {totals.get('jira', 0)}",
                classes="label",
            )
            yield Static(f"[bold]Backup:[/] {self.backup_preview}", classes="label")
            yield Static(
                "Press [bold]m[/] to migrate this project, "
                "[bold]s[/] to skip, "
                "[bold]d[/] for dry-run preview, "
                "[bold]q[/] to quit.",
                classes="hint",
            )
        yield Footer()

    def action_migrate(self) -> None:
        self.app.push_screen(
            ConfirmDialog(
                prompt=(
                    f"Proceed with {sum(len(v) for v in self.plan.integration_actions.values())}"
                    f" remote actions across {len(self.plan.integration_actions)} integrations?"
                ),
            ),
            self._on_confirm,
        )

    def _on_confirm(self, yes: bool) -> None:
        self.dismiss(("migrate", self.plan) if yes else ("skip", None))

    def action_skip(self) -> None:
        self.dismiss(("skip", None))

    def action_dry_run_preview(self) -> None:
        self.app.push_screen(DryRunPreviewScreen(self.plan))

    def action_quit(self) -> None:
        self.dismiss(("quit", None))


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
    ]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt)
            with Horizontal():
                yield Button("Yes (y)", id="yes")
                yield Button("No (n)", id="no")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class DryRunPreviewScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, plan: MigrationPlan) -> None:
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        yield Header(name="Dry-run preview")
        with TabbedContent(initial="local"):
            with TabPane("Local diff", id="local"):
                sample = self.plan.children[:3]
                lines = ["[bold]Sample (first 3 children)[/]", ""]
                for c in sample:
                    lines.append(
                        f"- id={c.id}  parent={c.parent}  →  tags+=group:{c.parent}"
                    )
                yield Static("\n".join(lines))
            with TabPane("Remote actions", id="remote"):
                lines = []
                for integ, actions in self.plan.integration_actions.items():
                    lines.append(f"[bold]{integ} ({len(actions)} actions)[/]")
                    for a in actions[:20]:
                        lines.append(f"  • {a.kind}  target={a.target_id}")
                    if len(actions) > 20:
                        lines.append(f"  … {len(actions) - 20} more")
                    lines.append("")
                yield Static("\n".join(lines))
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()
