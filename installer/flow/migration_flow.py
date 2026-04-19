# installer/flow/migration_flow.py
"""Rich-based prompts for the migration flow.

Replaces:
  - MigrationOverviewScreen (deleted P2) → prompt_migration_action
  - MigrationReviewScreen   (deleted P2, Task 3) → prompt_migration_review
  - DryRunPreviewScreen     (deleted P2, Task 3) → show_dry_run_preview
"""

from __future__ import annotations

from typing import Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from installer.migrations.types import MigrationPlan, PendingProject


OverviewAction = Literal["review", "skip_all", "quit"]


def prompt_migration_action(
    pending: list[PendingProject],
    integration_map: dict[str, set[str]],
    counts: dict[str, tuple[int, int]],
    console: Console,
) -> OverviewAction:
    """Display project list + prompt for r/s/q.

    Returns one of ``"review"`` / ``"skip_all"`` / ``"quit"``.
    """
    console.print(
        f"[bold]{len(pending)} projects need migration to schema_version=2.[/]"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Parents")
    table.add_column("Children")
    table.add_column("Remote")
    for p in pending:
        parents, children = counts.get(p.name, (0, 0))
        remote = ",".join(sorted(integration_map.get(p.name, set()))) or "–"
        table.add_row(p.name, str(parents), str(children), remote)
    console.print(table)
    console.print("[dim]r[/]=review + migrate   [dim]s[/]=skip all   [dim]q[/]=quit")

    choice = Prompt.ask("Action", choices=["r", "s", "q"], default="r", console=console)
    return {"r": "review", "s": "skip_all", "q": "quit"}[choice]


ReviewAction = Literal["migrate", "skip", "quit"]


def show_dry_run_preview(plan: MigrationPlan, console: Console) -> None:
    """Print the dry-run preview (local diff sample + remote actions)."""
    console.print("[bold]Dry-run preview[/]")
    console.print("[bold]Local diff (sample of first 3 children):[/]")
    for c in plan.children[:3]:
        console.print(f"  - id={c.id}  parent={c.parent}  → tags+=group:{c.parent}")
    console.print()
    console.print("[bold]Remote actions:[/]")
    for integ, actions in plan.integration_actions.items():
        console.print(f"  [bold]{integ}[/] ({len(actions)} actions)")
        for a in actions[:20]:
            console.print(f"    • {a.kind}  target={a.target_id}")
        if len(actions) > 20:
            console.print(f"    … {len(actions) - 20} more")


def prompt_migration_review(
    plan: MigrationPlan, backup_preview: str, console: Console
) -> ReviewAction:
    """Render review panel + prompt for m/s/d/q. Loops on 'd' (dry-run).

    Returns one of ``"migrate"`` / ``"skip"`` / ``"quit"``. A ``"migrate"``
    response is gated by a y/n confirm prompt; ``"n"`` maps to ``"skip"``.
    """
    while True:
        console.print()
        console.print(f"[bold]Plan preview — {plan.project.name}[/]")
        console.print(f"  • {len(plan.parents)} parent todos → flat with group:<id>")
        console.print(
            f"  • {len(plan.children)} children → top-level with group:<parent>"
        )
        console.print("  • No parent/children fields after migration")
        totals = {k: len(v) for k, v in plan.integration_actions.items()}
        console.print(
            f"[bold]Remote resync[/]  Todoist: {totals.get('todoist', 0)}  "
            f"Trello: {totals.get('trello', 0)}  Jira: {totals.get('jira', 0)}"
        )
        console.print(f"[bold]Backup:[/] {backup_preview}")
        console.print(
            "[dim]m[/]=migrate  [dim]s[/]=skip  [dim]d[/]=dry-run preview  [dim]q[/]=quit"
        )

        choice = Prompt.ask(
            "Action", choices=["m", "s", "d", "q"], default="m", console=console
        )
        if choice == "d":
            show_dry_run_preview(plan, console)
            Prompt.ask("Press Enter to return", console=console)
            continue

        if choice == "m":
            total_actions = sum(len(v) for v in plan.integration_actions.values())
            confirm = Prompt.ask(
                f"Proceed with {total_actions} remote actions across "
                f"{len(plan.integration_actions)} integrations?",
                choices=["y", "n"],
                default="y",
                console=console,
            )
            return "migrate" if confirm == "y" else "skip"
        if choice == "s":
            return "skip"
        if choice == "q":
            return "quit"
