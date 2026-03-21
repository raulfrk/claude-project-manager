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
    _append_jira_comments,
    _format_jira_notes,
    _fuzzy_match_project,
    _parse_jira_priority,
    _slugify,
    _sync_root_issue_to_notes,
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
    issuetype: dict[str, object] | None = None,
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
    if issuetype is not None:
        issue["issuetype"] = issuetype
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


def _make_epic_issue(key: str, summary: str, **kwargs: object) -> dict[str, object]:
    """Helper to create an issue that IS an epic."""
    return _make_jira_issue(
        key, summary,
        issuetype={"name": "Epic"},
        **kwargs,
    )


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


# ── Epic-first grouping tests ────────────────────────────────────────────────


class TestComputeMapping:
    def test_empty_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_mapping([], cfg)
        assert plan.total_issues == 0
        assert len(plan.groups) == 0

    def test_epic_issue_creates_epic_group(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """An issue that IS an epic creates an epic group (is_epic=True)."""
        cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-5", "User Auth"),
            _make_jira_issue("PROJ-10", "Login page", parent=_make_epic_parent("PROJ-5", "User Auth")),
            _make_jira_issue("PROJ-11", "Register page", parent=_make_epic_parent("PROJ-5", "User Auth")),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert plan.total_issues == 3
        # Epic itself is not added as a sub-item, only the two child issues
        epic_groups = [g for g in plan.groups if g.is_epic]
        assert len(epic_groups) == 1
        assert epic_groups[0].source == "epic"
        assert epic_groups[0].jira_key == "PROJ-5"
        assert epic_groups[0].name == "User Auth"
        assert len(epic_groups[0].issues) == 2  # not 3 -- epic itself excluded

    def test_issues_with_epic_parent_grouped(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Issues whose parent is an epic are grouped under that epic."""
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Login page", parent=_make_epic_parent("PROJ-5", "User Auth")),
            _make_jira_issue("PROJ-11", "Register page", parent=_make_epic_parent("PROJ-5", "User Auth")),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert plan.total_issues == 2
        assert len(plan.groups) == 1
        assert plan.groups[0].source == "epic"
        assert plan.groups[0].is_epic is True
        assert plan.groups[0].jira_key == "PROJ-5"
        assert len(plan.groups[0].issues) == 2

    def test_standalone_issues_needs_user_decision(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Issues with no epic are standalone with needs_user_decision=True."""
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Standalone task"),
            _make_jira_issue("PROJ-11", "Another task"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        # Each standalone issue gets its own group
        standalone = [g for g in plan.groups if g.source == "standalone"]
        assert len(standalone) == 2
        for g in standalone:
            assert g.is_epic is False
            assert g.needs_user_decision is True
            assert g.suggested_project == ""
            assert len(g.issues) == 1

    def test_mixed_epic_and_standalone(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Epic task", parent=_make_epic_parent("PROJ-5", "Auth Epic")),
            _make_jira_issue("PROJ-20", "No epic task"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 2
        sources = {g.source for g in plan.groups}
        assert sources == {"epic", "standalone"}

    def test_jira_issue_key_match_on_project(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Projects with jira_issue_key are matched instantly (no fuzzy)."""
        cfg, name = cfg_with_project
        # Set jira_issue_key on existing project
        meta = storage.load_meta(cfg, "myapp")
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        issues = [
            _make_jira_issue("PROJ-10", "Task", parent=_make_epic_parent("PROJ-5", "Some Different Name")),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        assert plan.groups[0].matched_project == "myapp"
        assert plan.groups[0].project_exists is True

    def test_priority_mapping_in_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-1", "Critical task", priority="Critical", parent=_make_epic_parent("PROJ-5", "Tasks")),
            _make_jira_issue("PROJ-2", "Low task", priority="Low", parent=_make_epic_parent("PROJ-5", "Tasks")),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        priorities = [str(i.get("priority")) for i in plan.groups[0].issues]
        assert priorities == ["high", "low"]

    def test_project_name_override(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Task", parent=_make_epic_parent("PROJ-5", "Something")),
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
                parent=_make_epic_parent("PROJ-5", "Test Epic"),
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
                parent=_make_epic_parent("PROJ-5", "Test Epic"),
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

    def test_no_catchall_for_standalone(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Standalone issues have empty suggested_project -- no catchall."""
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("OTHER-1", "Random task"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        g = plan.groups[0]
        assert g.source == "standalone"
        assert g.needs_user_decision is True
        assert g.suggested_project == ""
        assert g.matched_project is None

    def test_standalone_fuzzy_match_by_summary(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """A standalone issue whose summary fuzzy-matches a project gets auto-mapped."""
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "myapp"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        g = plan.groups[0]
        assert g.source == "standalone"
        assert g.matched_project == "myapp"
        assert g.needs_user_decision is False
        assert g.project_exists is True


# ── Apply tests ──────────────────────────────────────────────────────────────


class TestApplyMapping:
    def test_create_todos_in_existing_project(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
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

    def test_epic_creates_project_with_jira_issue_key(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """When creating a project from an epic, jira_issue_key is set on ProjectMeta."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "user-auth",
            "project_exists": False,
            "create_project": True,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "User Auth Epic",
            "issues": [
                {"key": "PROJ-10", "summary": "Login page", "priority": "high", "status": "To Do"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["projects_created"] == 1
        assert counts["todos_created"] == 1

        # Verify jira_issue_key set on project meta
        meta = storage.load_meta(cfg, "user-auth")
        assert meta.jira_issue_key == "PROJ-5"

        # Verify in index
        index = storage.load_index(cfg)
        assert "user-auth" in index.projects

    def test_idempotent_apply_no_duplicates(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
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
            "is_epic": True,
            "jira_key": "PROJ-5",
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
            "is_epic": True,
            "jira_key": "NP-1",
            "name": "New Project Epic",
            "issues": [
                {"key": "NP-10", "summary": "First in new project", "priority": "high", "status": "To Do"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["projects_created"] == 1
        assert counts["todos_created"] == 1

        # Verify project was created with jira_issue_key
        index = storage.load_index(cfg)
        assert "new-project" in index.projects
        meta = storage.load_meta(cfg, "new-project")
        assert meta.jira_issue_key == "NP-1"

        # Verify todo exists
        todos = storage.load_todos(cfg, "new-project")
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "NP-10"

    def test_subtasks_create_children(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
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
            "is_epic": True,
            "jira_key": "PROJ-5",
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
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do", "labels": ["backend", "urgent"]},
            ],
        }])
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert todos[0].tags == ["backend", "urgent"]

    def test_unmapped_issues_skipped(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Groups with empty suggested_project are skipped (no catchall)."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "",
            "project_exists": False,
            "create_project": False,
            "is_epic": False,
            "jira_key": "PROJ-99",
            "name": "Unmapped issue",
            "issues": [
                {"key": "PROJ-99", "summary": "Orphan", "priority": "medium", "status": "To Do"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["todos_created"] == 0
        assert counts["projects_created"] == 0
        assert counts["skipped_unmapped"] == 1

    def test_rerun_sets_jira_issue_key_on_existing_project(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """On re-run, if project exists but has no jira_issue_key, it gets set."""
        cfg, name = cfg_with_project
        # myapp has no jira_issue_key initially
        meta = storage.load_meta(cfg, "myapp")
        assert meta.jira_issue_key is None

        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do"},
            ],
        }])
        apply_mapping(data, cfg)

        meta = storage.load_meta(cfg, "myapp")
        assert meta.jira_issue_key == "PROJ-5"

    def test_standalone_non_epic_does_not_set_jira_key(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Non-epic groups do NOT set jira_issue_key on project meta."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": False,
            "jira_key": "PROJ-99",
            "name": "Just a task",
            "issues": [
                {"key": "PROJ-99", "summary": "Task", "priority": "medium", "status": "To Do"},
            ],
        }])
        apply_mapping(data, cfg)

        meta = storage.load_meta(cfg, "myapp")
        assert meta.jira_issue_key is None  # not set for non-epic

    def test_rerun_idempotent_full_cycle(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Full cycle: create project from epic, add todos, re-run -- no duplicates."""
        cfg, name = cfg_with_project
        group = {
            "suggested_project": "auth-project",
            "project_exists": False,
            "create_project": True,
            "is_epic": True,
            "jira_key": "AUTH-1",
            "name": "Authentication",
            "issues": [
                {"key": "AUTH-10", "summary": "Login", "priority": "high", "status": "To Do"},
                {"key": "AUTH-11", "summary": "Logout", "priority": "low", "status": "To Do"},
            ],
        }

        # First run: creates project + todos
        counts1 = apply_mapping(JiraApplyInput(groups=[group]), cfg)
        assert counts1["projects_created"] == 1
        assert counts1["todos_created"] == 2

        # Re-run: project already exists, update only
        group_rerun = dict(group)
        group_rerun["project_exists"] = True
        group_rerun["create_project"] = False
        counts2 = apply_mapping(JiraApplyInput(groups=[group_rerun]), cfg)
        assert counts2["projects_created"] == 0
        assert counts2["todos_created"] == 0
        assert counts2["todos_updated"] == 2

        # Verify no duplicates
        todos = storage.load_todos(cfg, "auth-project")
        assert len(todos) == 2


# ── Verification: no catchall behavior (todo 229) ────────────────────────────


class TestNoCatchallBehavior:
    """Verify that compute_mapping never assigns a default/catchall project.

    These tests ensure that:
    1. Standalone issues with no epic and no fuzzy match get suggested_project=""
    2. needs_user_decision=True is set for unmapped standalone issues
    3. apply_mapping skips groups with empty suggested_project
    4. Multiple existing projects do not cause any to act as a catchall
    """

    def test_standalone_no_match_gets_empty_suggested_project(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Standalone issue with unrelated name gets empty suggested_project."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("ZZZZ-999", "Completely unrelated task name xyz")]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        g = plan.groups[0]
        assert g.suggested_project == ""
        assert g.needs_user_decision is True
        assert g.matched_project is None
        assert g.project_exists is False

    def test_multiple_projects_no_catchall(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Even with multiple local projects, unrelated issues stay unmapped."""
        cfg, name = cfg_with_project
        today = str(date.today())
        # Create a second project
        proj_dir = Path(cfg.tracking_dir) / "backend-api"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "archive.yaml").write_text("todos: []\n")
        meta = ProjectMeta(
            name="backend-api",
            repos=[],
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta)
        index = storage.load_index(cfg)
        index.projects["backend-api"] = ProjectEntry(
            name="backend-api", tracking_dir=str(proj_dir), created=today,
        )
        storage.save_index(cfg, index)

        # Issue that does NOT match either project
        issues = [_make_jira_issue("XYZ-1", "Completely unrelated item")]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        assert len(plan.groups) == 1
        g = plan.groups[0]
        assert g.suggested_project == ""
        assert g.needs_user_decision is True
        assert g.matched_project is None

    def test_apply_skips_unmapped_and_counts_them(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """apply_mapping skips groups with empty suggested_project and counts them."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[
            {
                "suggested_project": "",
                "project_exists": False,
                "create_project": False,
                "is_epic": False,
                "jira_key": "UNM-1",
                "name": "Unmapped 1",
                "issues": [
                    {"key": "UNM-1", "summary": "Orphan A", "priority": "medium", "status": "To Do"},
                ],
            },
            {
                "suggested_project": "",
                "project_exists": False,
                "create_project": False,
                "is_epic": False,
                "jira_key": "UNM-2",
                "name": "Unmapped 2",
                "issues": [
                    {"key": "UNM-2", "summary": "Orphan B", "priority": "low", "status": "To Do"},
                ],
            },
            {
                "suggested_project": "myapp",
                "project_exists": True,
                "create_project": False,
                "is_epic": False,
                "jira_key": "MAP-1",
                "name": "Mapped one",
                "issues": [
                    {"key": "MAP-1", "summary": "Real task", "priority": "high", "status": "To Do"},
                ],
            },
        ])
        counts = apply_mapping(data, cfg)
        assert counts["skipped_unmapped"] == 2
        assert counts["todos_created"] == 1
        assert counts["projects_created"] == 0

        # Only the mapped task was created
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "MAP-1"

    def test_compute_mapping_no_default_project_field(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """The mapping plan never invents a 'default' or 'misc' project for standalones."""
        cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("A-1", "Alpha task"),
            _make_jira_issue("B-2", "Beta task"),
            _make_jira_issue("C-3", "Gamma task"),
        ]
        plan = compute_mapping(issues, cfg)  # type: ignore[arg-type]
        for g in plan.groups:
            if g.source == "standalone" and g.matched_project is None:
                assert g.suggested_project == "", (
                    f"Standalone group {g.jira_key} has non-empty suggested_project "
                    f"'{g.suggested_project}' despite no match — catchall detected"
                )
                assert g.needs_user_decision is True


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
        issues = [_make_jira_issue("PROJ-1", "Test task", parent=_make_epic_parent("PROJ-5", "Epic"))]
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
                "is_epic": True,
                "jira_key": "PROJ-5",
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
                is_epic=True,
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
        assert group["is_epic"] is True  # type: ignore[index]
        assert group["needs_user_decision"] is False  # type: ignore[index]


# ── Description & comment sync tests (todo 236) ──────────────────────────────


class TestFormatJiraNotes:
    def test_formats_description(self) -> None:
        result = _format_jira_notes("PROJ-1", "This is the description")
        assert result == "## Jira: PROJ-1\n### Description\nThis is the description"

    def test_strips_whitespace(self) -> None:
        result = _format_jira_notes("PROJ-2", "  some text  \n")
        assert result == "## Jira: PROJ-2\n### Description\nsome text"


class TestAppendJiraComments:
    def test_appends_new_comments(self) -> None:
        todo = Todo(id="1", title="Test")
        comments = [
            {"id": "c1", "author": "Alice", "created": "2026-03-19T10:00:00", "body": "First comment"},
            {"id": "c2", "author": {"displayName": "Bob"}, "created": "2026-03-19T11:00:00", "body": "Second"},
        ]
        _append_jira_comments(todo, comments)
        assert "### Comments" in todo.notes
        assert "**Alice** (2026-03-19): First comment" in todo.notes
        assert "**Bob** (2026-03-19): Second" in todo.notes
        assert todo.jira_synced_comment_ids == ["c1", "c2"]

    def test_dedup_by_comment_id(self) -> None:
        todo = Todo(id="1", title="Test", jira_synced_comment_ids=["c1"])
        todo.notes = "### Comments\n**Alice** (2026-03-19): First"
        comments = [
            {"id": "c1", "author": "Alice", "created": "2026-03-19", "body": "First"},
            {"id": "c2", "author": "Bob", "created": "2026-03-20", "body": "New one"},
        ]
        _append_jira_comments(todo, comments)
        assert todo.notes.count("First") == 1  # c1 not duplicated
        assert "**Bob** (2026-03-20): New one" in todo.notes
        assert todo.jira_synced_comment_ids == ["c1", "c2"]

    def test_no_change_when_all_synced(self) -> None:
        todo = Todo(id="1", title="Test", jira_synced_comment_ids=["c1"])
        todo.notes = "### Comments\n**Alice** (2026-03-19): First"
        original_notes = todo.notes
        _append_jira_comments(todo, [{"id": "c1", "author": "Alice", "created": "2026-03-19", "body": "First"}])
        assert todo.notes == original_notes
        assert todo.jira_synced_comment_ids == ["c1"]

    def test_adds_header_when_missing(self) -> None:
        todo = Todo(id="1", title="Test", notes="## Jira: X\n### Description\nSome desc")
        _append_jira_comments(todo, [{"id": "c1", "author": "Alice", "created": "2026-03-19", "body": "Hi"}])
        assert "### Comments" in todo.notes
        assert "### Description" in todo.notes  # original preserved


class TestApplyDescriptionAndComments:
    def test_description_formatted_in_new_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Issue with description creates todo with formatted notes."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do",
                 "description": "Implement the login page"},
            ],
        }])
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert "## Jira: PROJ-1" in todos[0].notes
        assert "### Description" in todos[0].notes
        assert "Implement the login page" in todos[0].notes

    def test_comments_appended_to_new_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Comments passed via comments_by_key are appended to todo notes."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do",
                 "description": "Do stuff"},
            ],
        }])
        comments = {
            "PROJ-1": [
                {"id": "100", "author": "Alice", "created": "2026-03-19", "body": "Looks good"},
                {"id": "101", "author": {"displayName": "Bob"}, "created": "2026-03-20", "body": "Agreed"},
            ],
        }
        apply_mapping(data, cfg, comments_by_key=comments)
        todos = storage.load_todos(cfg, name)
        assert "### Comments" in todos[0].notes
        assert "**Alice** (2026-03-19): Looks good" in todos[0].notes
        assert "**Bob** (2026-03-20): Agreed" in todos[0].notes
        assert todos[0].jira_synced_comment_ids == ["100", "101"]

    def test_resync_same_comments_no_duplicates(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-syncing the same comments does not duplicate them."""
        cfg, name = cfg_with_project
        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do",
                 "description": "Desc"},
            ],
        }
        comments = {
            "PROJ-1": [
                {"id": "100", "author": "Alice", "created": "2026-03-19", "body": "First"},
            ],
        }

        # First sync
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments)
        todos = storage.load_todos(cfg, name)
        assert todos[0].jira_synced_comment_ids == ["100"]

        # Second sync with same comments
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments)
        todos = storage.load_todos(cfg, name)
        assert todos[0].jira_synced_comment_ids == ["100"]  # not ["100", "100"]
        assert todos[0].notes.count("First") == 1

    def test_resync_with_new_comments_appends_only_new(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-syncing with additional comments appends only the new ones."""
        cfg, name = cfg_with_project
        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do",
                 "description": "Desc"},
            ],
        }

        # First sync with one comment
        comments_v1 = {
            "PROJ-1": [{"id": "100", "author": "Alice", "created": "2026-03-19", "body": "First"}],
        }
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments_v1)

        # Second sync with old + new comment
        comments_v2 = {
            "PROJ-1": [
                {"id": "100", "author": "Alice", "created": "2026-03-19", "body": "First"},
                {"id": "200", "author": "Bob", "created": "2026-03-20", "body": "Second"},
            ],
        }
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments_v2)

        todos = storage.load_todos(cfg, name)
        assert todos[0].jira_synced_comment_ids == ["100", "200"]
        assert todos[0].notes.count("First") == 1  # not duplicated
        assert "**Bob** (2026-03-20): Second" in todos[0].notes

    def test_empty_description_no_jira_header(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Issue with empty description gets empty notes (no Jira header)."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do",
                 "description": ""},
            ],
        }])
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert todos[0].notes == ""

    def test_epic_notes_appended_on_project_creation(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """When creating a project from an epic, description/comments go to NOTES.md."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "new-epic-proj",
            "project_exists": False,
            "create_project": True,
            "is_epic": True,
            "jira_key": "EP-1",
            "name": "Epic Name",
            "description": "Epic overview text",
            "issues": [
                {"key": "EP-10", "summary": "Child task", "priority": "medium", "status": "To Do"},
            ],
        }])
        comments = {
            "EP-1": [{"id": "c1", "author": "PM", "created": "2026-03-19", "body": "Kick-off note"}],
        }
        apply_mapping(data, cfg, comments_by_key=comments)

        notes_text = storage.read_notes(cfg, "new-epic-proj")
        assert "## Jira: EP-1" in notes_text
        assert "### Description" in notes_text
        assert "Epic overview text" in notes_text
        assert "### Comments" in notes_text
        assert "**PM** (2026-03-19): Kick-off note" in notes_text

    def test_mcp_apply_passes_comments(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """proj_jira_apply MCP tool passes comments_by_key_json through."""
        cfg, name = cfg_with_project
        from unittest.mock import MagicMock
        from server.tools.jira_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        apply_fn = tools["proj_jira_apply"]

        mapping = {
            "groups": [{
                "suggested_project": "myapp",
                "project_exists": True,
                "create_project": False,
                "is_epic": True,
                "jira_key": "PROJ-5",
                "name": "Test",
                "issues": [
                    {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do",
                     "description": "Hello"},
                ],
            }],
        }
        cbk = {"PROJ-1": [{"id": "c1", "author": "X", "created": "2026-03-19", "body": "note"}]}
        result = json.loads(apply_fn(  # type: ignore[operator]
            mapping_json=json.dumps(mapping),
            project_name=name,
            comments_by_key_json=json.dumps(cbk),
        ))
        assert result["status"] == "ok"
        assert result["counts"]["todos_created"] == 1

        todos = storage.load_todos(cfg, name)
        assert "**X** (2026-03-19): note" in todos[0].notes
        assert todos[0].jira_synced_comment_ids == ["c1"]


# ── Root issue -> NOTES.md routing tests (todo 242) ──────────────────────────


class TestRootIssueToNotes:
    """When a Jira issue maps 1:1 to a project (issue_key == meta.jira_issue_key),
    its description and comments go to NOTES.md, not a todo."""

    def test_root_issue_goes_to_notes_not_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Root issue (key == meta.jira_issue_key) routes to NOTES.md."""
        cfg, name = cfg_with_project
        # Set jira_issue_key on the project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-5", "summary": "Root issue", "priority": "medium", "status": "To Do",
                 "description": "Root description"},
                {"key": "PROJ-10", "summary": "Child task", "priority": "high", "status": "To Do",
                 "description": "Child desc"},
            ],
        }])
        comments = {
            "PROJ-5": [{"id": "r1", "author": "PM", "created": "2026-03-19", "body": "Root comment"}],
            "PROJ-10": [{"id": "c1", "author": "Dev", "created": "2026-03-20", "body": "Child comment"}],
        }
        counts = apply_mapping(data, cfg, comments_by_key=comments)

        # Root issue should NOT create a todo
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1  # only the child
        assert todos[0].jira_issue_key == "PROJ-10"

        # Root issue should go to NOTES.md
        notes = storage.read_notes(cfg, name, max_chars=10000)
        assert "## Jira: PROJ-5" in notes
        assert "Root description" in notes
        assert "**PM** (2026-03-19): Root comment" in notes

        # meta should track root comment IDs
        meta = storage.load_meta(cfg, name)
        assert "r1" in meta.jira_synced_comment_ids

    def test_root_issue_description_dedup_on_resync(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-syncing root issue does not duplicate the description in NOTES.md."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-5", "summary": "Root", "priority": "medium", "status": "To Do",
                 "description": "The description"},
            ],
        }

        # First sync
        apply_mapping(JiraApplyInput(groups=[group]), cfg)
        notes_v1 = storage.read_notes(cfg, name, max_chars=10000)
        assert notes_v1.count("## Jira: PROJ-5") == 1

        # Second sync
        apply_mapping(JiraApplyInput(groups=[group]), cfg)
        notes_v2 = storage.read_notes(cfg, name, max_chars=10000)
        assert notes_v2.count("## Jira: PROJ-5") == 1  # not duplicated

    def test_root_issue_comment_id_dedup(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-syncing root issue with same comments does not duplicate them."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-5", "summary": "Root", "priority": "medium", "status": "To Do",
                 "description": "Desc"},
            ],
        }
        comments = {
            "PROJ-5": [{"id": "r1", "author": "Alice", "created": "2026-03-19", "body": "First"}],
        }

        # First sync
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments)
        meta = storage.load_meta(cfg, name)
        assert "r1" in meta.jira_synced_comment_ids

        # Second sync with same + new comment
        comments_v2 = {
            "PROJ-5": [
                {"id": "r1", "author": "Alice", "created": "2026-03-19", "body": "First"},
                {"id": "r2", "author": "Bob", "created": "2026-03-20", "body": "Second"},
            ],
        }
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments_v2)
        meta = storage.load_meta(cfg, name)
        assert meta.jira_synced_comment_ids.count("r1") == 1  # not duplicated
        assert "r2" in meta.jira_synced_comment_ids

        notes = storage.read_notes(cfg, name, max_chars=10000)
        assert notes.count("First") == 1  # not duplicated
        assert "**Bob** (2026-03-20): Second" in notes

    def test_epic_comment_tracking_on_creation(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """When creating project from epic, comment IDs are tracked in meta."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(groups=[{
            "suggested_project": "epic-proj",
            "project_exists": False,
            "create_project": True,
            "is_epic": True,
            "jira_key": "EP-1",
            "name": "Epic",
            "description": "Epic desc",
            "issues": [
                {"key": "EP-10", "summary": "Task", "priority": "medium", "status": "To Do"},
            ],
        }])
        comments = {
            "EP-1": [
                {"id": "ec1", "author": "PM", "created": "2026-03-19", "body": "Kickoff"},
                {"id": "ec2", "author": "Dev", "created": "2026-03-20", "body": "Started"},
            ],
        }
        apply_mapping(data, cfg, comments_by_key=comments)

        meta = storage.load_meta(cfg, "epic-proj")
        assert "ec1" in meta.jira_synced_comment_ids
        assert "ec2" in meta.jira_synced_comment_ids

    def test_child_issues_still_become_todos(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Non-root issues in same group still become todos as usual."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-5", "summary": "Root", "priority": "medium", "status": "To Do",
                 "description": "Root desc"},
                {"key": "PROJ-10", "summary": "Child A", "priority": "high", "status": "To Do"},
                {"key": "PROJ-11", "summary": "Child B", "priority": "low", "status": "Done"},
            ],
        }])
        counts = apply_mapping(data, cfg)
        assert counts["todos_created"] == 2

        todos = storage.load_todos(cfg, name)
        keys = {t.jira_issue_key for t in todos}
        assert "PROJ-10" in keys
        assert "PROJ-11" in keys
        assert "PROJ-5" not in keys  # root issue is NOT a todo

    def test_backward_compat_no_jira_synced_comment_ids(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Old projects without jira_synced_comment_ids on meta still work."""
        cfg, name = cfg_with_project
        # Simulate an old meta without jira_synced_comment_ids
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        # Save, then reload to prove from_dict handles missing field
        storage.save_meta(cfg, meta)

        # Manually strip jira_synced_comment_ids from the saved file
        meta_path = storage.tracking_dir(cfg, name) / "meta.yaml"
        import yaml
        raw = yaml.safe_load(meta_path.read_text())
        raw.pop("jira_synced_comment_ids", None)
        meta_path.write_text(yaml.dump(raw))

        # Reload — should default to empty list
        meta = storage.load_meta(cfg, name)
        assert meta.jira_synced_comment_ids == []

        # Apply should still work
        data = JiraApplyInput(groups=[{
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-5", "summary": "Root", "priority": "medium", "status": "To Do",
                 "description": "Desc"},
            ],
        }])
        comments = {
            "PROJ-5": [{"id": "r1", "author": "Alice", "created": "2026-03-19", "body": "Hello"}],
        }
        apply_mapping(data, cfg, comments_by_key=comments)

        meta = storage.load_meta(cfg, name)
        assert "r1" in meta.jira_synced_comment_ids
        notes = storage.read_notes(cfg, name, max_chars=10000)
        assert "## Jira: PROJ-5" in notes


# ── Summary & summary_only tests (todo 244) ──────────────────────────────────


class TestPlanSummary:
    def test_plan_to_dict_includes_summary(self) -> None:
        """Verify summary key exists in to_dict() with correct counts."""
        from server.tools.jira_sync import JiraGroup

        plan = JiraMappingPlan(
            groups=[
                JiraGroup(
                    source="epic", jira_key="EP-1", name="Auth",
                    suggested_project="auth", is_epic=True, project_exists=True,
                    needs_user_decision=False,
                    issues=[{"key": "EP-10", "summary": "Login"}],
                ),
                JiraGroup(
                    source="standalone", jira_key="PROJ-99", name="Orphan",
                    suggested_project="", is_epic=False, project_exists=False,
                    needs_user_decision=True,
                    issues=[{"key": "PROJ-99", "summary": "Orphan task"}],
                ),
            ],
            total_issues=3,
        )
        d = plan.to_dict()
        assert "summary" in d
        summary = d["summary"]
        assert summary["total_issues"] == 3
        assert summary["group_count"] == 2
        assert summary["auto_mapped_count"] == 1
        assert summary["needs_input_count"] == 1

    def test_plan_summary_needs_input_groups(self) -> None:
        """Verify needs_input_groups lists only groups requiring user decision."""
        from server.tools.jira_sync import JiraGroup

        plan = JiraMappingPlan(
            groups=[
                JiraGroup(
                    source="epic", jira_key="EP-1", name="Auth",
                    suggested_project="auth", is_epic=True, project_exists=True,
                    needs_user_decision=False,
                    issues=[{"key": "EP-10", "summary": "Login"}, {"key": "EP-11", "summary": "Logout"}],
                ),
                JiraGroup(
                    source="standalone", jira_key="PROJ-50", name="Bug Fix",
                    suggested_project="", is_epic=False, project_exists=False,
                    needs_user_decision=True,
                    issues=[{"key": "PROJ-50", "summary": "Fix it"}],
                ),
                JiraGroup(
                    source="standalone", jira_key="PROJ-60", name="Docs Update",
                    suggested_project="", is_epic=False, project_exists=False,
                    needs_user_decision=True,
                    issues=[{"key": "PROJ-60", "summary": "Update docs"}, {"key": "PROJ-61", "summary": "Review docs"}],
                ),
            ],
            total_issues=5,
        )
        d = plan.to_dict()
        summary = d["summary"]
        nig = summary["needs_input_groups"]
        assert len(nig) == 2
        keys = {g["jira_key"] for g in nig}
        assert keys == {"PROJ-50", "PROJ-60"}
        # Verify issue_count
        by_key = {g["jira_key"]: g for g in nig}
        assert by_key["PROJ-50"]["issue_count"] == 1
        assert by_key["PROJ-60"]["issue_count"] == 2


class TestSummaryOnlyFlag:
    def _get_tools(self) -> dict[str, object]:
        from unittest.mock import MagicMock

        from server.tools.jira_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools

    def test_proj_jira_map_summary_only_true(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """When summary_only=True, only the summary key is returned."""
        cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        issues = [
            _make_epic_issue("PROJ-5", "Auth"),
            _make_jira_issue("PROJ-10", "Login", parent=_make_epic_parent("PROJ-5", "Auth")),
            _make_jira_issue("PROJ-20", "Standalone task"),
        ]
        result = json.loads(map_fn(  # type: ignore[operator]
            jira_issues_json=json.dumps(issues),
            project_name=name,
            summary_only=True,
        ))
        # Only summary key present, no groups
        assert "summary" in result
        assert "groups" not in result
        assert result["summary"]["total_issues"] == 3
        assert result["summary"]["group_count"] == 2  # 1 epic + 1 standalone

    def test_proj_jira_map_summary_only_false(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """When summary_only=False (default), full plan is returned (backward compat)."""
        cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        issues = [
            _make_epic_issue("PROJ-5", "Auth"),
            _make_jira_issue("PROJ-10", "Login", parent=_make_epic_parent("PROJ-5", "Auth")),
        ]
        result = json.loads(map_fn(  # type: ignore[operator]
            jira_issues_json=json.dumps(issues),
            project_name=name,
            summary_only=False,
        ))
        # Full plan includes both groups and summary
        assert "groups" in result
        assert "total_issues" in result
        assert "summary" in result
        assert result["total_issues"] == 2
