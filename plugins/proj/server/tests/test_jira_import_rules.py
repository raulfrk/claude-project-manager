"""Tests for Jira import rule tree (flat model).

Spec §6.1 — test_jira_import_rules.py (~10 tests for Task 4, 2 appended for Task 5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import (
    JiraSync,
    ProjConfig,
    ProjectIndex,
)
from server.tools.jira_sync import (
    ensure_project,
    import_jira_issues,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    config = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        jira=JiraSync(enabled=True),
    )
    storage.save_config(config)

    # Empty index
    index = ProjectIndex(projects={})
    storage.save_index(config, index)
    return config


# ── Helpers ────────────────────────────────────────────────────────────────────


def _issue(
    key: str,
    summary: str,
    issue_type: str = "Task",
    assignee: str = "me",
    subtasks: list[dict] | None = None,
    epic_key: str | None = None,
    parent_key: str | None = None,
    parent_type: str = "Task",
) -> dict:
    """Build a minimal Jira issue dict for testing."""
    issue: dict = {
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": issue_type},
            "assignee": {"displayName": assignee},
            "status": {"name": "In Progress"},
            "priority": {"name": "Medium"},
            "labels": [],
            "subtasks": subtasks or [],
        },
    }
    if epic_key:
        # Classic epic link
        issue["fields"]["parent"] = {
            "key": epic_key,
            "fields": {"issuetype": {"name": "Epic"}, "summary": f"Epic {epic_key}"},
        }
    if parent_key:
        issue["fields"]["parent"] = {
            "key": parent_key,
            "fields": {
                "issuetype": {"name": parent_type},
                "summary": f"Parent {parent_key}",
                "assignee": {"displayName": "other"},
            },
        }
    return issue


# ── Task 4 tests ──────────────────────────────────────────────────────────────


def test_epic_mine_with_tasks_mine_all_imported_as_todos(cfg: ProjConfig) -> None:
    """Epic I own → project epic:<key>. Tasks mine inside epic → todos in that project."""
    epic = _issue("E-1", "My Epic", issue_type="Epic")
    task1 = _issue("T-1", "Task one", issue_type="Task", assignee="me")
    task2 = _issue("T-2", "Task two", issue_type="Task", assignee="me")

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[epic],
        epic_issues_by_key={"E-1": [task1, task2]},
    )

    meta = storage.load_meta(cfg, "epic:E-1")
    assert meta.jira_issue_key == "E-1"
    todos = storage.load_todos(cfg, "epic:E-1")
    todo_keys = {t.jira_issue_key for t in todos}
    assert "T-1" in todo_keys
    assert "T-2" in todo_keys


def test_epic_mine_task_assigned_to_other_skipped(cfg: ProjConfig) -> None:
    """Tasks in my epic assigned to others are NOT imported as todos."""
    epic = _issue("E-2", "My Epic 2", issue_type="Epic")
    task_mine = _issue("T-3", "My task", issue_type="Task", assignee="me")
    task_other = _issue("T-4", "Other task", issue_type="Task", assignee="alice")

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[epic],
        epic_issues_by_key={"E-2": [task_mine, task_other]},
    )

    todos = storage.load_todos(cfg, "epic:E-2")
    todo_keys = {t.jira_issue_key for t in todos}
    assert "T-3" in todo_keys
    assert "T-4" not in todo_keys, "Task assigned to other should be skipped"


def test_task_with_epic_mine_skipped_at_task_pass_to_avoid_dup(cfg: ProjConfig) -> None:
    """Task whose epic_link is in my_epic_keys is skipped in Pass 2 (handled via epic rule)."""
    epic = _issue("E-3", "My Epic 3", issue_type="Epic")
    task_in_epic = _issue("T-5", "Task in epic", issue_type="Task", epic_key="E-3")

    # Both epic and task are in my_issues (as would happen with jira_get_user_issues)
    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[epic, task_in_epic],
        epic_issues_by_key={"E-3": [task_in_epic]},
    )

    # No standalone task:T-5 project should be created (only epic:E-3)
    index = storage.load_index(cfg)
    proj_names = list(index.projects.keys())
    assert "epic:E-3" in proj_names
    assert "task:T-5" not in proj_names, "task:T-5 should not be created (handled via epic)"


def test_task_with_epic_other_becomes_standalone_project(cfg: ProjConfig) -> None:
    """Task whose epic belongs to someone else becomes its own task:T project."""
    task = _issue("T-6", "Task in alien epic", issue_type="Task", epic_key="E-ALIEN")

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[task],
        epic_issues_by_key={},  # E-ALIEN not in my epics
    )

    index = storage.load_index(cfg)
    assert "task:T-6" in index.projects


def test_task_no_epic_becomes_project_with_subtask_todos(cfg: ProjConfig) -> None:
    """Task with no epic link + my subtasks → project task:T with subtask todos."""
    task = _issue(
        "T-7",
        "Standalone task",
        issue_type="Task",
        subtasks=[
            {
                "key": "ST-1",
                "fields": {
                    "summary": "Subtask one",
                    "issuetype": {"name": "Sub-task"},
                    "assignee": {"displayName": "me"},
                    "status": {"name": "open"},
                },
            },
        ],
    )

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[task],
        epic_issues_by_key={},
    )

    todos = storage.load_todos(cfg, "task:T-7")
    todo_keys = {t.jira_issue_key for t in todos}
    assert "ST-1" in todo_keys


def test_task_no_epic_no_subtasks_becomes_empty_project(cfg: ProjConfig) -> None:
    """Task with no epic and no subtasks → project task:T with zero todos."""
    task = _issue("T-8", "Solo task", issue_type="Task")

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[task],
        epic_issues_by_key={},
    )

    todos = storage.load_todos(cfg, "task:T-8")
    assert todos == []


def test_subtask_parent_mine_handled_via_task_rule(cfg: ProjConfig) -> None:
    """Sub-task whose parent task is mine → handled via task rule → skipped in sub-task pass."""
    task = _issue("T-9", "Parent task", issue_type="Task", assignee="me")
    subtask = _issue(
        "ST-2",
        "My subtask",
        issue_type="Sub-task",
        assignee="me",
        parent_key="T-9",
        parent_type="Task",
    )
    # Override parent assignee to "me" in the subtask's parent field
    subtask["fields"]["parent"]["fields"]["assignee"] = {"displayName": "me"}

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[task, subtask],
        epic_issues_by_key={},
    )

    # task:T-9 should exist; task:ST-2 should NOT be created (not orphan)
    index = storage.load_index(cfg)
    assert "task:T-9" in index.projects
    assert "task:ST-2" not in index.projects, (
        "Sub-task with parent_mine should not create its own project"
    )


def test_subtask_parent_other_epic_mine_handled_via_epic_rule(cfg: ProjConfig) -> None:
    """Sub-task whose parent task is not mine but epic IS mine → handled via epic rule."""
    epic = _issue("E-4", "My Epic 4", issue_type="Epic")
    subtask = _issue(
        "ST-3",
        "Epic subtask",
        issue_type="Sub-task",
        assignee="me",
        parent_key="T-OTHER",
        parent_type="Task",
    )
    # The subtask's epic link points to E-4 (mine)
    subtask["fields"]["parent"]["fields"]["parent"] = {
        "key": "E-4",
        "fields": {"issuetype": {"name": "Epic"}},
    }

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[epic, subtask],
        epic_issues_by_key={"E-4": []},
    )

    index = storage.load_index(cfg)
    assert "epic:E-4" in index.projects
    assert "task:ST-3" not in index.projects, (
        "Sub-task with epic_mine should not create orphan project"
    )


def test_orphan_subtask_becomes_own_project(cfg: ProjConfig) -> None:
    """Sub-task whose parent task + epic are both not mine → orphan placeholder project."""
    subtask = _issue(
        "ST-4",
        "Orphan subtask",
        issue_type="Sub-task",
        assignee="me",
        parent_key="T-OTHER",
        parent_type="Task",
    )
    # No epic in my epic keys (parent epic not in my_issues)

    import_jira_issues(
        cfg,
        current_user="me",
        my_issues=[subtask],
        epic_issues_by_key={},
    )

    index = storage.load_index(cfg)
    assert "task:ST-4" in index.projects

    # Orphan project has zero todos
    todos = storage.load_todos(cfg, "task:ST-4")
    assert todos == []


def test_ensure_project_idempotent(cfg: ProjConfig) -> None:
    """ensure_project called twice with same name returns same project, no duplicate."""
    issue = _issue("E-10", "Test epic", issue_type="Epic")
    meta1 = ensure_project(cfg, "epic:E-10", issue)
    meta2 = ensure_project(cfg, "epic:E-10", issue)

    assert meta1.name == meta2.name
    index = storage.load_index(cfg)
    # Should still be only one entry
    assert list(index.projects.keys()).count("epic:E-10") == 1
