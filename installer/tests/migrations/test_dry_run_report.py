# installer/tests/migrations/test_dry_run_report.py
from __future__ import annotations

from pathlib import Path

from installer.migrations.integrations.base import Action
from installer.migrations.report import write_dry_run_report
from installer.migrations.types import (
    MigrationPlan,
    PendingProject,
    RecoveryPath,
    TodoRef,
)


def _fake_plan(tmp_path: Path) -> MigrationPlan:
    project = PendingProject(
        name="cpm",
        path=tmp_path / "cpm",
        proj_yaml_path=tmp_path / "cpm" / "proj.yaml",
        current_version=1,
    )
    return MigrationPlan(
        project=project,
        parents=[TodoRef(id="1", title="p")],
        children=[TodoRef(id="1.1", title="c", parent="1", todoist_task_id="t1")],
        integration_actions={
            "todoist": [Action(kind="clear_parent", target_id="t1", payload={})],
            "trello": [],
            "jira": [],
        },
        recovery_path=RecoveryPath.NORMAL,
    )


def test_report_contains_per_project_section(tmp_path: Path) -> None:
    plans = [_fake_plan(tmp_path)]
    out = write_dry_run_report(plans, tmp_path / "report.md", run_ts="ts")
    assert out.exists()
    text = out.read_text()
    assert "# Flat-Todo Migration — Dry Run" in text
    assert "## cpm" in text
    assert "Parents: 1" in text
    assert "Children: 1" in text
    assert "clear_parent" in text


def test_report_empty_list(tmp_path: Path) -> None:
    out = write_dry_run_report([], tmp_path / "r.md", run_ts="ts")
    text = out.read_text()
    assert "No projects" in text
