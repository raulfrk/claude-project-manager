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

from installer.migrations.types import PendingProject


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
