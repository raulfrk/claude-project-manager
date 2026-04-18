# installer/tests/migrations/test_todoist_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_todoist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> PendingProject:
    root = tmp_path / "demo"
    root.mkdir()
    proj = root / "proj.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "name": "demo",
                "sync": {"todoist": {"enabled": True, "api_token": "tok"}},
            }
        ),
    )
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=1,
    )


def _make_children(n: int) -> list[TodoRef]:
    return [
        TodoRef(id=f"1.{i}", title=f"c{i}", todoist_task_id=f"task-{i}", parent="1")
        for i in range(n)
    ]


def test_enabled_for_requires_config_and_links(
    project_with_todoist: PendingProject,
) -> None:
    r = TodoistResync()
    assert r.enabled_for(project_with_todoist) is False  # no migrated todos yet
    # With at least one migrated child with a todoist_task_id
    # (enabled_for in this impl takes project + migrated list)
    actions = r.plan(project_with_todoist, _make_children(1))
    assert len(actions) == 1


def test_plan_emits_clear_parent_per_child(
    project_with_todoist: PendingProject,
) -> None:
    r = TodoistResync()
    actions = r.plan(project_with_todoist, _make_children(3))
    assert len(actions) == 3
    assert all(a.kind == "clear_parent" for a in actions)
    assert {a.target_id for a in actions} == {"task-0", "task-1", "task-2"}


def test_plan_skips_children_without_todoist_id(
    project_with_todoist: PendingProject,
) -> None:
    children = [
        TodoRef(id="1.1", title="c", todoist_task_id=None, parent="1"),
        TodoRef(id="1.2", title="c", todoist_task_id="t", parent="1"),
    ]
    actions = TodoistResync().plan(project_with_todoist, children)
    assert [a.target_id for a in actions] == ["t"]


@respx.mock
def test_execute_batches_successfully(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(3))
    respx.post("https://api.todoist.com/api/v1/sync").mock(
        return_value=Response(200, json={"sync_status": {}})
    )
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is False
    assert len(result.ok) == 3
    assert not result.failed


@respx.mock
def test_execute_logs_partial_batch_failure(
    project_with_todoist: PendingProject,
) -> None:
    actions = TodoistResync().plan(
        project_with_todoist, _make_children(60)
    )  # 2 batches
    # First batch ok, second 429
    route = respx.post("https://api.todoist.com/api/v1/sync")
    route.side_effect = [
        Response(200, json={}),
        Response(429, json={"error": "rate limited"}),
    ]
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is False
    assert len(result.ok) == 50
    assert len(result.failed) == 10
    assert result.failed[0].error_class == "HTTPStatusError"


@respx.mock
def test_execute_auth_failure_aborts(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(2))
    respx.post("https://api.todoist.com/api/v1/sync").mock(
        return_value=Response(401, json={})
    )
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is True
    assert len(result.failed) == 2
