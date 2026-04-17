"""Tests for Bug B fix: apply_mapping uses flat-model group tags instead of nested kwargs.

Spec §6.1 — test_jira_apply_mapping_flat.py (4 tests).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import (
    JiraSync,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
)
from server.tools.jira_sync import JiraApplyInput, apply_mapping

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        jira=JiraSync(enabled=True),
    )
    storage.save_config(cfg)

    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "archive.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=today)},
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _make_group_with_subtask(
    suggested_project: str,
    parent_key: str = "PROJ-10",
    subtask_key: str = "PROJ-11",
) -> dict:
    """Build a minimal apply_mapping group dict with one issue and one subtask."""
    return {
        "suggested_project": suggested_project,
        "project_exists": True,
        "create_project": False,
        "is_epic": False,
        "jira_key": parent_key,
        "issues": [
            {
                "key": parent_key,
                "summary": "Parent task",
                "priority": "medium",
                "status": "in progress",
                "labels": [],
                "description": "",
                "subtasks": [
                    {
                        "key": subtask_key,
                        "summary": "Sub-task one",
                        "status": "open",
                    }
                ],
            }
        ],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_subtask_imports_as_flat_todo_with_group_tag(
    cfg_with_project: tuple[ProjConfig, str],
) -> None:
    """Sub-task becomes a flat (root-level) todo with group:<parent_id> tag."""
    cfg, name = cfg_with_project
    group = _make_group_with_subtask(name, parent_key="PROJ-10", subtask_key="PROJ-11")
    data = JiraApplyInput(groups=[group])
    result = apply_mapping(data, cfg)

    todos = storage.load_todos(cfg, name)
    # Find the subtask todo
    st_todo = next((t for t in todos if t.jira_issue_key == "PROJ-11"), None)
    assert st_todo is not None, "Sub-task todo not created"

    # Find the parent todo id
    parent_todo = next((t for t in todos if t.jira_issue_key == "PROJ-10"), None)
    assert parent_todo is not None, "Parent todo not created"

    # Sub-task should have group:<parent_id> tag
    assert f"group:{parent_todo.id}" in st_todo.tags, (
        f"Expected group:{parent_todo.id} in tags, got {st_todo.tags}"
    )

    assert result.counts["todos_created"] >= 2


def test_no_parent_or_children_kwargs_on_todo_constructor(
    cfg_with_project: tuple[ProjConfig, str],
) -> None:
    """Sub-task todo must have parent=None and children=[] (flat model)."""
    cfg, name = cfg_with_project
    group = _make_group_with_subtask(name, parent_key="PROJ-20", subtask_key="PROJ-21")
    data = JiraApplyInput(groups=[group])
    apply_mapping(data, cfg)

    todos = storage.load_todos(cfg, name)
    st_todo = next((t for t in todos if t.jira_issue_key == "PROJ-21"), None)
    assert st_todo is not None

    # Flat model: parent field must be None, children must be empty
    assert st_todo.parent is None, f"Expected parent=None, got parent={st_todo.parent!r}"
    assert st_todo.children == [], f"Expected children=[], got children={st_todo.children!r}"


def test_todos_list_contains_parent_and_subtask_as_siblings(
    cfg_with_project: tuple[ProjConfig, str],
) -> None:
    """Both parent and sub-task todos are at root level (siblings in todos list)."""
    cfg, name = cfg_with_project
    group = _make_group_with_subtask(name, parent_key="PROJ-30", subtask_key="PROJ-31")
    data = JiraApplyInput(groups=[group])
    apply_mapping(data, cfg)

    todos = storage.load_todos(cfg, name)
    parent = next((t for t in todos if t.jira_issue_key == "PROJ-30"), None)
    child = next((t for t in todos if t.jira_issue_key == "PROJ-31"), None)

    assert parent is not None
    assert child is not None

    # Both are siblings — neither id is nested under the other
    assert "." not in child.id or not child.id.startswith(parent.id + "."), (
        f"child.id={child.id!r} looks like a nested ID under parent {parent.id!r}"
    )

    # parent has no children in the children list
    assert child.id not in parent.children, (
        f"parent.children should not contain child id {child.id!r}"
    )


def test_empty_subtasks_list_noop(
    cfg_with_project: tuple[ProjConfig, str],
) -> None:
    """Issue with empty subtasks list creates only the parent todo, no extras."""
    cfg, name = cfg_with_project
    group = {
        "suggested_project": name,
        "project_exists": True,
        "create_project": False,
        "is_epic": False,
        "jira_key": "PROJ-40",
        "issues": [
            {
                "key": "PROJ-40",
                "summary": "Solo task",
                "priority": "low",
                "status": "open",
                "labels": [],
                "description": "",
                "subtasks": [],
            }
        ],
    }
    data = JiraApplyInput(groups=[group])
    result = apply_mapping(data, cfg)

    todos = storage.load_todos(cfg, name)
    assert len(todos) == 1, f"Expected exactly 1 todo, got {len(todos)}"
    assert todos[0].jira_issue_key == "PROJ-40"
    assert result.counts["todos_created"] == 1
