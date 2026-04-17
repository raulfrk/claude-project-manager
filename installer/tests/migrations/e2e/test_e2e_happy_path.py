# installer/tests/migrations/e2e/test_e2e_happy_path.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.detect import read_schema_version
from installer.migrations.entry import MIGRATION_ROOT
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.jira import JiraResync
from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.types import PendingProject


@respx.mock
def test_happy_path_three_projects(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import installer.migrations.integrations.trello as t

    monkeypatch.setattr(t, "_update_local_trello_card_id", lambda *a, **k: None)

    # Mock all SaaS endpoints broadly
    respx.post("https://api.todoist.com/api/v1/sync").mock(
        return_value=Response(200, json={})
    )
    respx.post("https://api.trello.com/1/cards").mock(
        return_value=Response(200, json={"id": "new-card"}),
    )
    respx.get(url__regex=r"https://api\.trello\.com/1/cards/.*/idLabels").mock(
        return_value=Response(200, json=[]),
    )
    respx.delete(url__regex=r"https://api\.trello\.com/1/checklists/.*").mock(
        return_value=Response(200),
    )
    respx.put(url__regex=r"https://ex\.atlassian\.net/rest/api/3/issue/.*").mock(
        return_value=Response(204),
    )

    projects = [
        PendingProject(
            name=name,
            path=home_with_projects / "projects" / name,
            proj_yaml_path=home_with_projects / "projects" / name / "proj.yaml",
            current_version=1,
        )
        for name in ("cpm", "side", "legacy")
    ]
    integrations = [TodoistResync(), TrelloResync(), JiraResync()]
    outcomes = []
    for p in projects:
        runner = FlatTodoMigration(
            project=p,
            run_ts="e2e-happy",
            backup_root=MIGRATION_ROOT / "e2e-happy",
            integrations=integrations,
        )
        runner.plan()
        runner.confirm()
        runner.execute_local()
        runner.commit()
        outcomes.append(runner)

    for r in outcomes:
        assert read_schema_version(r.project.proj_yaml_path) == 2
        todos = yaml.safe_load((r.project.path / "todos.yaml").read_text())
        child = next(t for t in todos if t["id"] == "1.1")
        assert "group:1" in child["tags"]
        assert "parent" not in child
