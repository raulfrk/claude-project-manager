# installer/tests/flow/test_migration_summary.py
from rich.console import Console

from installer.flow.migration_summary import MigrationOutcome, show_migration_summary


def test_summary_renders_counts_header() -> None:
    console = Console(record=True, width=80)
    outcomes = [
        MigrationOutcome(project="alpha", ok=True, resync_partial=False, backup="b1"),
        MigrationOutcome(project="beta", ok=True, resync_partial=True, backup="b2"),
        MigrationOutcome(
            project="gamma", ok=False, resync_partial=False, backup="b3", error="boom"
        ),
    ]

    show_migration_summary(outcomes, console)

    text = console.export_text()
    assert "1 ok" in text
    assert "1 partial-resync" in text
    assert "1 failed" in text


def test_summary_renders_per_project_row() -> None:
    console = Console(record=True, width=80)
    outcomes = [
        MigrationOutcome(
            project="demo",
            ok=False,
            resync_partial=False,
            backup="bdir",
            error="migration failed: xyz",
        ),
    ]
    show_migration_summary(outcomes, console)
    text = console.export_text()
    assert "demo" in text
    assert "bdir" in text
    assert "migration failed: xyz" in text


def test_summary_handles_empty_outcomes() -> None:
    console = Console(record=True, width=80)
    show_migration_summary([], console)
    text = console.export_text()
    assert "0 ok" in text
    assert "0 failed" in text
