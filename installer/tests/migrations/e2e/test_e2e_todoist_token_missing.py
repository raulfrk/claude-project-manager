# installer/tests/migrations/e2e/test_e2e_todoist_token_missing.py
"""E2E: FlatTodoMigration with TodoistResync when no api_token is configured.

Verifies:
- Migration still commits (schema_version → 2)
- Local yaml is flattened (parent → group:* tag on children)
- TodoistResync aborts with a single synthetic FailedAction bearing the runbook
- No N-per-action error spam
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.types import PendingProject


def test_todoist_resync_skips_gracefully_when_no_token(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Overwrite proj.yaml: todoist.enabled=True but NO api_token anywhere.
    proj_yaml = home_with_projects / ".claude" / "proj.yaml"
    proj_yaml.write_text(
        yaml.safe_dump(
            {
                "tracking_dir": str(home_with_projects / "projects" / "tracking"),
                "sync": {
                    "todoist": {
                        "enabled": True,
                        "mcp_server": "claude_ai_Todoist",
                        # api_token intentionally absent
                    }
                },
            }
        )
    )
    # Defensive: remove any todoist.yaml the fixture may have created.
    todoist_yaml = home_with_projects / ".claude" / "todoist.yaml"
    if todoist_yaml.exists():
        todoist_yaml.unlink()

    # Use the cpm project already created by the fixture (has todoist_task_id fields).
    project_path = home_with_projects / "projects" / "tracking" / "cpm"

    project = PendingProject(
        name="cpm",
        path=project_path,
        schema_version_path=project_path / ".schema-version",
        current_version=1,
    )
    runner = FlatTodoMigration(
        project=project,
        run_ts="e2e-token-missing",
        backup_root=home_with_projects / ".claude" / "migrations",
        integrations=[TodoistResync()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()

    # Migration committed: schema bumped to 2.
    assert read_schema_version(project.schema_version_path) == 2

    # Local yaml is flat: child has group:<parent_id> tag.
    todos = yaml.safe_load((project_path / "todos.yaml").read_text())
    if isinstance(todos, dict):
        todos = todos.get("todos") or todos.get("items") or []
    child_tags: list[str] = []
    for t in todos:
        if isinstance(t, dict) and t.get("id") == "1.1":
            child_tags = t.get("tags", [])
    assert any(tag == "group:1" for tag in child_tags), (
        f"Expected 'group:1' tag on child todo, got tags: {child_tags}"
    )

    # TodoistResync aborted cleanly: exactly one synthetic FailedAction w/ runbook.
    assert len(runner.resync_failures) == 1, (
        f"Expected 1 resync failure, got {len(runner.resync_failures)}: "
        f"{runner.resync_failures}"
    )
    fail = runner.resync_failures[0]
    assert fail.error_class == "ConfigError"
    assert "api_token not found" in fail.message
    assert "/proj:todoist-sync" in fail.message
