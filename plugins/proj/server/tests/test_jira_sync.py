"""Tests for jira_sync tools (proj_jira_map and proj_jira_apply)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    JiraSync,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
    Todo,
)
from server.tools.jira_sync import (
    JiraApplyInput,
    JiraMappingPlan,
    _fuzzy_match_project,
    _parse_jira_priority,
    _slugify,
    apply_mapping,
    compute_mapping,
)


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


def _make_todo(cfg: ProjConfig, name: str, title: str, **kwargs: object) -> Todo:
    meta = storage.load_meta(cfg, name)
    today = str(date.today())
    todo = Todo(id=next_todo_id(meta), title=title, created=today, updated=today)
    for k, v in kwargs.items():
        setattr(todo, k, v)
    storage.save_meta(cfg, meta)
    return todo


def _make_jira_issue(
    key: str,
    summary: str,
    priority: str = "Medium",
    status: str = "To Do",
    parent: dict[str, object] | None = None,
    **kwargs: object,
) -> dict[str, object]:
    issue: dict[str, object] = {
        "key": key,
        "summary": summary,
        "priority": {"name": priority},
        "status": {"name": status},
        "labels": [],
        "description": "",
        "duedate": None,
        "assignee": None,
        "subtasks": [],
    }
    if parent is not None:
        issue["parent"] = parent
    issue.update(kwargs)
    return issue


def _make_epic_parent(key: str, summary: str) -> dict[str, object]:
    """Helper to create a parent reference that looks like an epic."""
    return {
        "key": key,
        "fields": {
            "issuetype": {"name": "Epic"},
            "summary": summary,
        },
    }


# ── Unit tests for helpers ────────────────────────────────────────────────────


class TestHelpers:
    def test_slugify_basic(self) -> None:
        assert _slugify("User Authentication") == "user-authentication"

    def test_slugify_special_chars(self) -> None:
        assert _slugify("My App (v2)!") == "my-app-v2"

    def test_slugify_empty(self) -> None:
        assert _slugify("") == "unnamed"

    def test_priority_critical(self) -> None:
        assert _parse_jira_priority({"priority": {"name": "Critical"}}) == "high"

    def test_priority_highest(self) -> None:
        assert _parse_jira_priority({"priority": {"name": "Highest"}}) == "high"

    def test_priority_high(self) -> None:
        assert _parse_jira_priority({"priority": {"name": "High"}}) == "medium"

    def test_priority_medium(self) -> None:
        assert _parse_jira_priority({"priority": {"name": "Medium"}}) == "medium"

    def test_priority_low(self) -> None:
        assert _parse_jira_priority({"priority": {"name": "Low"}}) == "low"

    def test_priority_lowest(self) -> None:
        assert _parse_jira_priority({"priority": {"name": "Lowest"}}) == "low"

    def test_priority_string_format(self) -> None:
        assert _parse_jira_priority({"priority": "Critical"}) == "high"

    def test_priority_missing(self) -> None:
        assert _parse_jira_priority({}) == "medium"

    def test_fuzzy_match_exact(self) -> None:
        assert _fuzzy_match_project("myapp", ["myapp", "other"]) == "myapp"

    def test_fuzzy_match_case_insensitive(self) -> None:
        assert _fuzzy_match_project("MyApp", ["myapp", "other"]) == "myapp"

    def test_fuzzy_match_no_match(self) -> None:
        assert _fuzzy_match_project("totally-different", ["myapp", "other"]) is None

    def test_fuzzy_match_slug(self) -> None:
        assert _fuzzy_match_project("User Auth", ["user-auth", "other"]) == "user-auth"


# ── Grouping tests ───────────────────────────────────────────────────────────


class TestComputeMapping:
    def test_empty_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_mapping([], cfg)
        assert plan.total_issues == 0
        assert len(plan.groups) == 0

    def test_group_by_epic(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Login page", parent=_make_epic_parent("PROJ-5", "User Auth")),
            _make_jira_issue("PROJ-11", "Register page", parent=_make_epic_parent("PROJ-5", "User Auth")),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert plan.total_issues == 2
        assert len(plan.groups) == 1
        assert plan.groups[0].source == "epic"
        assert plan.groups[0].jira_key == "PROJ-5"
        assert plan.groups[0].name == "User Auth"
        assert len(plan.groups[0].issues) == 2

    def test_group_by_project_key_no_epic(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Standalone task"),
            _make_jira_issue("PROJ-11", "Another task"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        assert plan.groups[0].source == "project"
        assert plan.groups[0].jira_key == "PROJ"
        assert plan.groups[0].name == "PROJ (no epic)"
        assert len(plan.groups[0].issues) == 2

    def test_mixed_epic_and_no_epic(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Epic task", parent=_make_epic_parent("PROJ-5", "Auth Epic")),
            _make_jira_issue("PROJ-20", "No epic task"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 2
        sources = {g.source for g in plan.groups}
        assert sources == {"epic", "project"}

    def test_existing_project_match(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("MYAPP-10", "Task in myapp project"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        assert plan.groups[0].project_exists is True
        assert plan.groups[0].matched_project == "myapp"

    def test_priority_mapping_in_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-1", "Critical task", priority="Critical"),
            _make_jira_issue("PROJ-2", "Low task", priority="Low"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        priorities = [str(i.get("priority")) for i in plan.groups[0].issues]
        assert priorities == ["high", "low"]

    def test_project_name_override(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Task"),
        ]
        plan = compute_mapping(issues, cfg, project_name="myapp")  # type: ignore[arg-type]
        assert plan.groups[0].suggested_project == "myapp"
        assert plan.groups[0].project_exists is True

    def test_issue_fields_preserved(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-1", "Test task",
                priority="High",
                status="In Progress",
                labels=["backend", "urgent"],
                duedate="2026-06-15",
                assignee={"displayName": "John Doe"},
            ),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        issue = plan.groups[0].issues[0]
        assert issue["key"] == "PROJ-1"
        assert issue["summary"] == "Test task"
        assert issue["priority"] == "medium"
        assert issue["status"] == "In Progress"
        assert issue["labels"] == ["backend", "urgent"]
        assert issue["duedate"] == "2026-06-15"
        assert issue["assignee"] == "John Doe"

    def test_subtasks_included(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-1", "Parent task",
                subtasks=[
                    {"key": "PROJ-1a", "fields": {"summary": "Sub 1", "status": {"name": "To Do"}}},
                    {"key": "PROJ-1b", "fields": {"summary": "Sub 2", "status": {"name": "Done"}}},
                ],
            ),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        issue = plan.groups[0].issues[0]
        subtasks = issue.get("subtasks", [])
        assert isinstance(subtasks, list)
        assert len(subtasks) == 2


# ── Apply tests ──────────────────────────────────────────────────────────────


class TestApplyMapping:
    def test_create_todos_in_existing_project(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "name": "Test Group",
            "issues": [
                {"key": "PROJ-1", "summary": "First task", "priority": "high", "status": "To Do"},
                {"key": "PROJ-2", "summary": "Second task", "priority": "low", "status": "In Progress"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["todos_created"] == 2
        assert counts["todos_updated"] == 0
        assert counts["projects_created"] == 0

        todos = storage.load_todos(cfg, name)
        assert len(todos) == 2
        assert todos[0].title == "First task"
        assert todos[0].jira_issue_key == "PROJ-1"
        assert todos[0].priority == "high"
        assert todos[1].title == "Second task"
        assert todos[1].jira_issue_key == "PROJ-2"

    def test_idempotent_apply_no_duplicates(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task one", "priority": "medium", "status": "To Do"},
            ],
        }

        # Apply once
        counts1 = apply_mapping(JiraApplyInput(groups=[group]), cfg)
        assert counts1["todos_created"] == 1

        # Apply again with same data
        counts2 = apply_mapping(JiraApplyInput(groups=[group]), cfg)
        assert counts2["todos_created"] == 0
        assert counts2["todos_updated"] == 1

        # Should still be only 1 todo
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "PROJ-1"

    def test_resolved_issue_creates_done_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Resolved task", "priority": "medium", "status": "Done"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["todos_created"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].status == "done"

    def test_create_project_when_needed(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "new-project",
            "project_exists": False,
            "create_project": True,
            "name": "New Project Epic",
            "issues": [
                {"key": "NP-1", "summary": "First in new project", "priority": "high", "status": "To Do"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["projects_created"] == 1
        assert counts["todos_created"] == 1

        # Verify project was created
        index = storage.load_index(cfg)
        assert "new-project" in index.projects

        # Verify todo exists
        todos = storage.load_todos(cfg, "new-project")
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "NP-1"

    def test_subtasks_create_children(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "name": "Test",
            "issues": [
                {
                    "key": "PROJ-1",
                    "summary": "Parent task",
                    "priority": "medium",
                    "status": "In Progress",
                    "subtasks": [
                        {"key": "PROJ-1a", "summary": "Child task", "status": "To Do"},
                    ],
                },
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["todos_created"] == 2  # parent + child

        todos = storage.load_todos(cfg, name)
        parent = next(t for t in todos if t.jira_issue_key == "PROJ-1")
        child = next(t for t in todos if t.jira_issue_key == "PROJ-1a")
        assert child.parent == parent.id
        assert child.id in parent.children

    def test_due_date_preserved(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do", "duedate": "2026-06-15"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["todos_created"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].due_date == "2026-06-15"

    def test_labels_as_tags(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do", "labels": ["backend", "urgent"]},
            ],
        }])
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert todos[0].tags == ["backend", "urgent"]


# ── MCP tool registration tests ──────────────────────────────────────────────


class TestMCPTools:
    def _get_tools(self) -> dict[str, object]:
        from unittest.mock import MagicMock

        from server.tools.jira_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools

    def test_proj_jira_map_returns_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        issues = [_make_jira_issue("PROJ-1", "Test task")]
        result = json.loads(map_fn(jira_issues_json=json.dumps(issues), project_name=name))  # type: ignore[operator]
        assert "groups" in result
        assert result["total_issues"] == 1

    def test_proj_jira_map_invalid_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        result = map_fn(jira_issues_json="not json", project_name=name)  # type: ignore[operator]
        assert "Invalid JSON" in result

    def test_proj_jira_apply_returns_counts(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        apply_fn = tools["proj_jira_apply"]
        mapping = {
            "groups": [{
                "suggested_project": "myapp",
                "project_exists": True,
                "create_project": False,
                "name": "Test",
                "issues": [
                    {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do"},
                ],
            }],
        }
        result = json.loads(apply_fn(mapping_json=json.dumps(mapping), project_name=name))  # type: ignore[operator]
        assert result["status"] == "ok"
        assert result["counts"]["todos_created"] == 1

    def test_proj_jira_apply_invalid_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tools = self._get_tools()
        apply_fn = tools["proj_jira_apply"]
        result = apply_fn(mapping_json="not json", project_name=name)  # type: ignore[operator]
        assert "Invalid JSON" in result


# ── Plan data structure tests ────────────────────────────────────────────────


class TestJiraMappingPlan:
    def test_empty_plan(self) -> None:
        plan = JiraMappingPlan()
        d = plan.to_dict()
        assert d["total_issues"] == 0
        assert d["groups"] == []

    def test_plan_to_dict(self) -> None:
        from server.tools.jira_sync import JiraGroup
        plan = JiraMappingPlan(
            groups=[JiraGroup(
                source="epic",
                jira_key="PROJ-5",
                name="Auth",
                suggested_project="auth",
                project_exists=True,
                issues=[{"key": "PROJ-10", "summary": "Login"}],
            )],
            total_issues=1,
        )
        d = plan.to_dict()
        assert d["total_issues"] == 1
        assert len(d["groups"]) == 1  # type: ignore[arg-type]
        group = d["groups"][0]  # type: ignore[index]
        assert group["source"] == "epic"  # type: ignore[index]
        assert group["jira_key"] == "PROJ-5"  # type: ignore[index]
