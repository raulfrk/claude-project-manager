# installer/flow/migration_summary.py
"""Display the read-only outcome summary after a migration run."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table


@dataclass(frozen=True)
class MigrationOutcome:
    """Result for a single project in a migration run."""

    project: str
    ok: bool
    resync_partial: bool
    backup: str
    error: str | None = None


def show_migration_summary(outcomes: list[MigrationOutcome], console: Console) -> None:
    """Render the post-migration outcome table to ``console``.

    Prints a counts-header line (``✓ N ok ◐ M partial-resync ✗ K failed``)
    followed by a table with one row per project.
    """
    ok = sum(1 for o in outcomes if o.ok and not o.resync_partial)
    partial = sum(1 for o in outcomes if o.ok and o.resync_partial)
    failed = sum(1 for o in outcomes if not o.ok)

    console.print(
        f"[bold]Results[/]  [green]✓ {ok} ok[/]  "
        f"[yellow]◐ {partial} partial-resync[/]  "
        f"[red]✗ {failed} failed[/]",
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", width=6)
    table.add_column("Project")
    table.add_column("Backup")
    table.add_column("Details")
    for o in outcomes:
        if not o.ok:
            status = "[red]✗[/]"
        elif o.resync_partial:
            status = "[yellow]◐[/]"
        else:
            status = "[green]✓[/]"
        table.add_row(status, o.project, o.backup, o.error or "")
    console.print(table)
