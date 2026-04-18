# installer/tests/migrations/test_jira_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.jira import JiraResync
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_jira(tmp_path: Path) -> PendingProject:
    root = tmp_path / "demo"
    root.mkdir()
    proj = root / "proj.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "name": "demo",
                "sync": {
                    "jira": {
                        "enabled": True,
                        "base_url": "https://example.atlassian.net",
                        "email": "u@example.com",
                        "api_token": "tok",
                        "epic_link_field": "customfield_10014",
                    },
                },
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


def _parent_epic() -> TodoRef:
    return TodoRef(id="1", title="epic", jira_issue_key="CPM-100")


def _parent_story() -> TodoRef:
    return TodoRef(id="1", title="story", jira_issue_key="CPM-50")


def _child_subtask(idx: int) -> TodoRef:
    return TodoRef(
        id=f"1.{idx}", title=f"st {idx}", parent="1", jira_issue_key=f"CPM-{100 + idx}"
    )


def test_plan_under_epic_preserves_epic_link(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1), _child_subtask(2)]
    actions = JiraResync().plan(project_with_jira, migrated)
    assert len(actions) == 2
    assert all(a.payload["epic_link"] == "CPM-100" for a in actions)


@respx.mock
def test_execute_type_conversion(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1)]
    actions = JiraResync().plan(project_with_jira, migrated)
    # PUT /rest/api/3/issue/<key>
    respx.put(
        url__regex=r"https://example\.atlassian\.net/rest/api/3/issue/CPM-101"
    ).mock(
        return_value=Response(204),
    )
    result = JiraResync().execute(project_with_jira, actions)
    assert not result.failed
    assert len(result.ok) == 1


@respx.mock
def test_execute_project_rejects_type_change(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1)]
    actions = JiraResync().plan(project_with_jira, migrated)
    respx.put(url__regex=r".*rest/api/3/issue/CPM-101").mock(
        return_value=Response(400, json={"errorMessages": ["type change not allowed"]}),
    )
    result = JiraResync().execute(project_with_jira, actions)
    assert len(result.failed) == 1
    assert result.failed[0].retryable is False
