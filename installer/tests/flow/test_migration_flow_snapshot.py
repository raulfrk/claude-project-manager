# installer/tests/flow/test_migration_flow_snapshot.py
"""Text-based snapshot tests for migration_flow output.

Syrupy-based golden tests replacing the Textual SVG snapshots that were
deleted in P2 Task 5 (overview/review/dry-run snapshots in
installer/tests/migrations/test_screens.py).
"""

from pathlib import Path

import pytest
from rich.console import Console

from installer.flow.migration_flow import (
    prompt_migration_action,
    prompt_migration_review,
    show_dry_run_preview,
)
from installer.migrations.types import MigrationPlan, PendingProject, TodoRef


def _p(name: str) -> PendingProject:
    return PendingProject(
        name=name,
        path=Path("/tmp") / name,
        schema_version_path=Path("/tmp") / name / ".schema-version",
        current_version=1,
    )


def _plan() -> MigrationPlan:
    parent = TodoRef(id="1", title="parent")
    c1 = TodoRef(id="1.1", title="child1", parent="1")
    c2 = TodoRef(id="1.2", title="child2", parent="1")
    return MigrationPlan(
        project=_p("alpha"),
        parents=[parent],
        children=[c1, c2],
        integration_actions={"todoist": [], "trello": []},
    )


def test_overview_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    prompt_migration_action(
        pending=[_p("alpha"), _p("beta")],
        integration_map={"alpha": {"todoist"}, "beta": set()},
        counts={"alpha": (2, 3), "beta": (0, 0)},
        console=console,
    )
    assert console.export_text() == snapshot


def test_review_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    prompt_migration_review(
        plan=_plan(), backup_preview="/tmp/backup/alpha", console=console
    )
    assert console.export_text() == snapshot


def test_dry_run_snapshot(snapshot) -> None:
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    show_dry_run_preview(_plan(), console)
    assert console.export_text() == snapshot
