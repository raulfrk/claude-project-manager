from rich.console import Console

from installer.flow.migration_summary import MigrationOutcome, show_migration_summary


def test_migration_summary_all_ok_snapshot(snapshot) -> None:
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    outcomes = [
        MigrationOutcome(project="alpha", ok=True, resync_partial=False, backup="b1"),
        MigrationOutcome(project="beta", ok=True, resync_partial=False, backup="b2"),
    ]
    show_migration_summary(outcomes, console)
    assert snapshot == console.export_text()


def test_migration_summary_mixed_snapshot(snapshot) -> None:
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    outcomes = [
        MigrationOutcome(project="alpha", ok=True, resync_partial=False, backup="b1"),
        MigrationOutcome(project="beta", ok=True, resync_partial=True, backup="b2"),
        MigrationOutcome(
            project="gamma", ok=False, resync_partial=False, backup="b3", error="boom"
        ),
    ]
    show_migration_summary(outcomes, console)
    assert snapshot == console.export_text()
