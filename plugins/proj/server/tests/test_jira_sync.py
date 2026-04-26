"""Tests for jira_sync tools (proj_jira_map and proj_jira_apply)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    JiraSync,
    JsonDict,
    JsonValue,
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
    _deterministic_map,
    _extract_keywords,
    _format_jira_notes,
    _fuzzy_match_project,
    _match_standalone,
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
    parent: JsonDict | None = None,
    issuetype: JsonDict | None = None,
    **kwargs: JsonValue,
) -> JsonDict:
    issue: JsonDict = {
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


def _make_epic_parent(key: str, summary: str) -> JsonDict:
    """Helper to create a parent reference that looks like an epic."""
    return {
        "key": key,
        "fields": {
            "issuetype": {"name": "Epic"},
            "summary": summary,
        },
    }


def _make_epic_issue(key: str, summary: str, **kwargs: JsonValue) -> JsonDict:
    """Helper to create an issue that IS an epic."""
    return _make_jira_issue(
        key,
        summary,
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

    @pytest.mark.parametrize(
        ("jira_name", "expected"),
        [
            ("Critical", "high"),
            ("Highest", "high"),
            ("High", "medium"),
            ("Medium", "medium"),
            ("Low", "low"),
            ("Lowest", "low"),
        ],
    )
    def test_priority_dict_format(self, jira_name: str, expected: str) -> None:
        assert _parse_jira_priority({"priority": {"name": jira_name}}) == expected

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

    def test_fuzzy_match_difflib(self) -> None:
        """Difflib fuzzy match path: similar but not exact/slug match."""
        assert (
            _fuzzy_match_project("authenticaton", ["authentication", "other"]) == "authentication"
        )

    # ── _extract_keywords tests ───────────────────────────────────────────

    def test_extract_keywords_basic(self) -> None:
        result = _extract_keywords("Implement the login page for users")
        assert "implement" in result
        assert "login" in result
        assert "page" in result
        assert "users" in result
        # stopwords/short words removed
        assert "the" not in result
        assert "for" not in result

    def test_extract_keywords_removes_stopwords(self) -> None:
        result = _extract_keywords("the and a but or nor")
        assert result == set()

    def test_extract_keywords_removes_short_words(self) -> None:
        result = _extract_keywords("go do it up ok")
        assert result == set()  # all < 3 chars

    def test_extract_keywords_lowercases(self) -> None:
        result = _extract_keywords("Deploy Backend API")
        assert "deploy" in result
        assert "backend" in result
        assert "api" in result

    def test_extract_keywords_empty_string(self) -> None:
        assert _extract_keywords("") == set()


# ── Epic-first grouping tests ────────────────────────────────────────────────


class TestComputeMapping:
    def test_empty_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        plan = compute_mapping([], cfg)
        assert plan.total_issues == 0
        assert len(plan.groups) == 0

    def test_epic_issue_creates_epic_group(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """An issue that IS an epic creates an epic group (is_epic=True)."""
        cfg, _name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-5", "User Auth"),
            _make_jira_issue(
                "PROJ-10", "Login page", parent=_make_epic_parent("PROJ-5", "User Auth")
            ),
            _make_jira_issue(
                "PROJ-11", "Register page", parent=_make_epic_parent("PROJ-5", "User Auth")
            ),
        ]
        plan = compute_mapping(issues, cfg)
        assert plan.total_issues == 3
        # Epic itself is not added as a sub-item, only the two child issues
        epic_groups = [g for g in plan.groups if g.is_epic]
        assert len(epic_groups) == 1
        assert epic_groups[0].source == "epic"
        assert epic_groups[0].jira_key == "PROJ-5"
        assert epic_groups[0].name == "User Auth"
        assert len(epic_groups[0].issues) == 2  # not 3 -- epic itself excluded

    def test_issues_with_epic_parent_grouped(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Issues whose parent is an epic are grouped under that epic."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-10", "Login page", parent=_make_epic_parent("PROJ-5", "User Auth")
            ),
            _make_jira_issue(
                "PROJ-11", "Register page", parent=_make_epic_parent("PROJ-5", "User Auth")
            ),
        ]
        plan = compute_mapping(issues, cfg)
        assert plan.total_issues == 2
        assert len(plan.groups) == 1
        assert plan.groups[0].source == "epic"
        assert plan.groups[0].is_epic is True
        assert plan.groups[0].jira_key == "PROJ-5"
        assert len(plan.groups[0].issues) == 2

    def test_standalone_issues_needs_user_decision(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Issues with no epic are standalone with needs_user_decision=True."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Standalone task"),
            _make_jira_issue("PROJ-11", "Another task"),
        ]
        plan = compute_mapping(issues, cfg)
        # Each standalone issue gets its own group
        standalone = [g for g in plan.groups if g.source == "standalone"]
        assert len(standalone) == 2
        for g in standalone:
            assert g.is_epic is False
            assert g.needs_user_decision is True
            # With strategy chain, recent_suggestion may suggest a project
            assert g.matched_strategy in {"recent_suggestion", "none"}
            assert len(g.issues) == 1

    def test_mixed_epic_and_standalone(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-10", "Epic task", parent=_make_epic_parent("PROJ-5", "Auth Epic")
            ),
            _make_jira_issue("PROJ-20", "No epic task"),
        ]
        plan = compute_mapping(issues, cfg)
        assert len(plan.groups) == 2
        sources = {g.source for g in plan.groups}
        assert sources == {"epic", "standalone"}

    def test_jira_issue_key_match_on_project(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Projects with jira_issue_key are matched instantly (no fuzzy)."""
        cfg, _name = cfg_with_project
        # Set jira_issue_key on existing project
        meta = storage.load_meta(cfg, "myapp")
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        issues = [
            _make_jira_issue(
                "PROJ-10", "Task", parent=_make_epic_parent("PROJ-5", "Some Different Name")
            ),
        ]
        plan = compute_mapping(issues, cfg)
        assert len(plan.groups) == 1
        assert plan.groups[0].matched_project == "myapp"
        assert plan.groups[0].project_exists is True

    def test_priority_mapping_in_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-1",
                "Critical task",
                priority="Critical",
                parent=_make_epic_parent("PROJ-5", "Tasks"),
            ),
            _make_jira_issue(
                "PROJ-2", "Low task", priority="Low", parent=_make_epic_parent("PROJ-5", "Tasks")
            ),
        ]
        plan = compute_mapping(issues, cfg)
        assert len(plan.groups) == 1
        priorities = [str(i.get("priority")) for i in plan.groups[0].issues]
        assert priorities == ["high", "low"]

    def test_project_name_override(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "Task", parent=_make_epic_parent("PROJ-5", "Something")),
        ]
        plan = compute_mapping(issues, cfg, project_name="myapp")
        assert plan.groups[0].suggested_project == "myapp"
        assert plan.groups[0].project_exists is True

    def test_issue_fields_preserved(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-1",
                "Test task",
                priority="High",
                status="In Progress",
                labels=["backend", "urgent"],
                duedate="2026-06-15",
                assignee={"displayName": "John Doe"},
                parent=_make_epic_parent("PROJ-5", "Test Epic"),
            ),
        ]
        plan = compute_mapping(issues, cfg)
        issue = plan.groups[0].issues[0]
        assert issue["key"] == "PROJ-1"
        assert issue["summary"] == "Test task"
        assert issue["priority"] == "medium"
        assert issue["status"] == "In Progress"
        assert issue["labels"] == ["backend", "urgent"]
        assert issue["duedate"] == "2026-06-15"
        assert issue["assignee"] == "John Doe"

    def test_subtasks_included(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-1",
                "Parent task",
                parent=_make_epic_parent("PROJ-5", "Test Epic"),
                subtasks=[
                    {"key": "PROJ-1a", "fields": {"summary": "Sub 1", "status": {"name": "To Do"}}},
                    {"key": "PROJ-1b", "fields": {"summary": "Sub 2", "status": {"name": "Done"}}},
                ],
            ),
        ]
        plan = compute_mapping(issues, cfg)
        issue = plan.groups[0].issues[0]
        subtasks = issue.get("subtasks", [])
        assert isinstance(subtasks, list)
        assert len(subtasks) == 2

    def test_no_catchall_for_standalone(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Standalone issues with no match still require user decision (no auto-assign)."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue("OTHER-1", "Random task"),
        ]
        plan = compute_mapping(issues, cfg)
        assert len(plan.groups) == 1
        g = plan.groups[0]
        assert g.source == "standalone"
        assert g.needs_user_decision is True
        # With strategy chain, recent_suggestion may suggest a project but still needs decision
        assert g.matched_strategy in {"recent_suggestion", "none"}

    def test_standalone_fuzzy_match_by_summary(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """A standalone issue whose summary fuzzy-matches a project gets auto-mapped."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue("PROJ-10", "myapp"),
        ]
        plan = compute_mapping(issues, cfg)
        g = plan.groups[0]
        assert g.source == "standalone"
        assert g.matched_project == "myapp"
        assert g.needs_user_decision is False
        assert g.project_exists is True


# ── Apply tests ──────────────────────────────────────────────────────────────


class TestApplyMapping:
    def test_create_todos_in_existing_project(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test Group",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "First task",
                            "priority": "high",
                            "status": "To Do",
                        },
                        {
                            "key": "PROJ-2",
                            "summary": "Second task",
                            "priority": "low",
                            "status": "In Progress",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
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

    def test_epic_creates_project_with_jira_issue_key(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When creating a project from an epic, jira_issue_key is set on ProjectMeta."""
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "user-auth",
                    "project_exists": False,
                    "create_project": True,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "User Auth Epic",
                    "issues": [
                        {
                            "key": "PROJ-10",
                            "summary": "Login page",
                            "priority": "high",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
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
        counts1 = apply_mapping(JiraApplyInput(groups=[group]), cfg).counts
        assert counts1["todos_created"] == 1

        # Apply again with same data
        counts2 = apply_mapping(JiraApplyInput(groups=[group]), cfg).counts
        assert counts2["todos_created"] == 0
        assert counts2["todos_updated"] == 1

        # Should still be only 1 todo
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "PROJ-1"

    def test_resolved_issue_creates_done_todo(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Resolved task",
                            "priority": "medium",
                            "status": "Done",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["todos_created"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].status == "done"

    def test_create_project_when_needed(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "new-project",
                    "project_exists": False,
                    "create_project": True,
                    "is_epic": True,
                    "jira_key": "NP-1",
                    "name": "New Project Epic",
                    "issues": [
                        {
                            "key": "NP-10",
                            "summary": "First in new project",
                            "priority": "high",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
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
        data = JiraApplyInput(
            groups=[
                {
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
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["todos_created"] == 2  # parent + child

        todos = storage.load_todos(cfg, name)
        parent = next(t for t in todos if t.jira_issue_key == "PROJ-1")
        child = next(t for t in todos if t.jira_issue_key == "PROJ-1a")
        # Flat model (post-636 Phase 2): relationship is via group:<parent-id> tag,
        # not via parent/children fields (which were removed from the Todo dataclass).
        assert f"group:{parent.id}" in child.tags

    def test_due_date_preserved(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                            "duedate": "2026-06-15",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["todos_created"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].due_date == "2026-06-15"

    def test_labels_as_tags(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                            "labels": ["backend", "urgent"],
                        },
                    ],
                }
            ]
        )
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert todos[0].tags == ["backend", "urgent"]

    def test_unmapped_issues_skipped(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Groups with empty suggested_project are skipped (no catchall)."""
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "",
                    "project_exists": False,
                    "create_project": False,
                    "is_epic": False,
                    "jira_key": "PROJ-99",
                    "name": "Unmapped issue",
                    "issues": [
                        {
                            "key": "PROJ-99",
                            "summary": "Orphan",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["todos_created"] == 0
        assert counts["projects_created"] == 0
        assert counts["skipped_unmapped"] == 1

    def test_rerun_sets_jira_issue_key_on_existing_project(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """On re-run, if project exists but has no jira_issue_key, it gets set."""
        cfg, _name = cfg_with_project
        # myapp has no jira_issue_key initially
        meta = storage.load_meta(cfg, "myapp")
        assert meta.jira_issue_key is None

        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        apply_mapping(data, cfg)

        meta = storage.load_meta(cfg, "myapp")
        assert meta.jira_issue_key == "PROJ-5"

    def test_standalone_sets_jira_key_on_project(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """All groups (including non-epic) set jira_issue_key on project meta."""
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": False,
                    "jira_key": "PROJ-99",
                    "name": "Just a task",
                    "issues": [
                        {
                            "key": "PROJ-99",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        apply_mapping(data, cfg)

        meta = storage.load_meta(cfg, "myapp")
        assert meta.jira_issue_key == "PROJ-99"

    def test_rerun_idempotent_full_cycle(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Full cycle: create project from epic, add todos, re-run -- no duplicates."""
        cfg, _name = cfg_with_project
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
        counts1 = apply_mapping(JiraApplyInput(groups=[group]), cfg).counts
        assert counts1["projects_created"] == 1
        assert counts1["todos_created"] == 2

        # Re-run: project already exists, update only
        group_rerun = dict(group)
        group_rerun["project_exists"] = True
        group_rerun["create_project"] = False
        counts2 = apply_mapping(JiraApplyInput(groups=[group_rerun]), cfg).counts
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

    def test_standalone_no_match_needs_user_decision(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Standalone issue with unrelated name needs user decision (recent_suggestion)."""
        cfg, _name = cfg_with_project
        issues = [_make_jira_issue("ZZZZ-999", "Completely unrelated task name xyz")]
        plan = compute_mapping(issues, cfg)
        assert len(plan.groups) == 1
        g = plan.groups[0]
        assert g.needs_user_decision is True
        # Strategy chain falls through to recent_suggestion
        assert g.matched_strategy in {"recent_suggestion", "none"}

    def test_multiple_projects_no_catchall(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Even with multiple local projects, unrelated issues stay unmapped."""
        cfg, _name = cfg_with_project
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
            name="backend-api",
            tracking_dir=str(proj_dir),
            created=today,
        )
        storage.save_index(cfg, index)

        # Issue that does NOT match either project
        issues = [_make_jira_issue("XYZ-1", "Completely unrelated item")]
        plan = compute_mapping(issues, cfg)
        assert len(plan.groups) == 1
        g = plan.groups[0]
        assert g.needs_user_decision is True
        # Strategy chain may suggest via recent_suggestion but still needs decision
        assert g.matched_strategy in {"recent_suggestion", "none"}

    def test_apply_skips_unmapped_and_counts_them(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """apply_mapping skips groups with empty suggested_project and counts them."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "",
                    "project_exists": False,
                    "create_project": False,
                    "is_epic": False,
                    "jira_key": "UNM-1",
                    "name": "Unmapped 1",
                    "issues": [
                        {
                            "key": "UNM-1",
                            "summary": "Orphan A",
                            "priority": "medium",
                            "status": "To Do",
                        },
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
                        {
                            "key": "UNM-2",
                            "summary": "Orphan B",
                            "priority": "low",
                            "status": "To Do",
                        },
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
                        {
                            "key": "MAP-1",
                            "summary": "Real task",
                            "priority": "high",
                            "status": "To Do",
                        },
                    ],
                },
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["skipped_unmapped"] == 2
        assert counts["todos_created"] == 1
        assert counts["projects_created"] == 0

        # Only the mapped task was created
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "MAP-1"

    def test_compute_mapping_no_auto_assign_for_multiple_unmatched(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Multiple unmatched standalones all need user decision (no auto-assign)."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue("A-1", "Alpha task"),
            _make_jira_issue("B-2", "Beta task"),
            _make_jira_issue("C-3", "Gamma task"),
        ]
        plan = compute_mapping(issues, cfg)
        low_confidence = {
            "recent_suggestion",
            "none",
            "tag_match_ambiguous",
            "keyword_match_ambiguous",
        }
        for g in plan.groups:
            if g.source == "standalone" and g.matched_strategy in low_confidence:
                assert g.needs_user_decision is True, (
                    f"Standalone group {g.jira_key} with strategy "
                    f"'{g.matched_strategy}' should need user decision"
                )


# ── MCP tool registration tests ──────────────────────────────────────────────


class TestMCPTools:
    def _get_tools(self) -> dict[str, Callable[..., str]]:
        from unittest.mock import MagicMock

        from server.tools.jira_sync import register

        app = MagicMock()
        tools: dict[str, Callable[..., str]] = {}
        app.tool = lambda **kw: (lambda fn: tools.update({fn.__name__: fn}) or fn)
        register(app)
        return tools

    def test_proj_jira_map_returns_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        issues = [
            _make_jira_issue("PROJ-1", "Test task", parent=_make_epic_parent("PROJ-5", "Epic"))
        ]
        result = json.loads(map_fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert "groups" in result
        assert result["total_issues"] == 1

    def test_proj_jira_map_invalid_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        result = map_fn(jira_issues_json="not json", project_name=name)
        assert "Invalid JSON" in result

    def test_proj_jira_apply_returns_counts(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        apply_fn = tools["proj_jira_apply"]
        mapping = {
            "groups": [
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ],
        }
        result = json.loads(apply_fn(mapping_json=json.dumps(mapping), project_name=name))
        assert result["status"] == "ok"
        assert result["counts"]["todos_created"] == 1

    def test_proj_jira_apply_invalid_json(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        apply_fn = tools["proj_jira_apply"]
        result = apply_fn(mapping_json="not json", project_name=name)
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
            groups=[
                JiraGroup(
                    source="epic",
                    jira_key="PROJ-5",
                    name="Auth",
                    suggested_project="auth",
                    is_epic=True,
                    project_exists=True,
                    issues=[{"key": "PROJ-10", "summary": "Login"}],
                )
            ],
            total_issues=1,
        )
        d = plan.to_dict()
        assert d["total_issues"] == 1
        groups = d["groups"]
        assert isinstance(groups, list)
        assert len(groups) == 1
        group = groups[0]
        assert isinstance(group, dict)
        assert group["source"] == "epic"
        assert group["jira_key"] == "PROJ-5"
        assert group["is_epic"] is True
        assert group["needs_user_decision"] is False


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
            {
                "id": "c1",
                "author": "Alice",
                "created": "2026-03-19T10:00:00",
                "body": "First comment",
            },
            {
                "id": "c2",
                "author": {"displayName": "Bob"},
                "created": "2026-03-19T11:00:00",
                "body": "Second",
            },
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
        _append_jira_comments(
            todo, [{"id": "c1", "author": "Alice", "created": "2026-03-19", "body": "First"}]
        )
        assert todo.notes == original_notes
        assert todo.jira_synced_comment_ids == ["c1"]

    def test_adds_header_when_missing(self) -> None:
        todo = Todo(id="1", title="Test", notes="## Jira: X\n### Description\nSome desc")
        _append_jira_comments(
            todo, [{"id": "c1", "author": "Alice", "created": "2026-03-19", "body": "Hi"}]
        )
        assert "### Comments" in todo.notes
        assert "### Description" in todo.notes  # original preserved


class TestApplyDescriptionAndComments:
    def test_description_formatted_in_new_todo(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Issue with description creates todo with formatted notes."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "Implement the login page",
                        },
                    ],
                }
            ]
        )
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert "## Jira: PROJ-1" in todos[0].notes
        assert "### Description" in todos[0].notes
        assert "Implement the login page" in todos[0].notes

    def test_comments_appended_to_new_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Comments passed via comments_by_key are appended to todo notes."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "Do stuff",
                        },
                    ],
                }
            ]
        )
        comments = {
            "PROJ-1": [
                {"id": "100", "author": "Alice", "created": "2026-03-19", "body": "Looks good"},
                {
                    "id": "101",
                    "author": {"displayName": "Bob"},
                    "created": "2026-03-20",
                    "body": "Agreed",
                },
            ],
        }
        apply_mapping(data, cfg, comments_by_key=comments)
        todos = storage.load_todos(cfg, name)
        assert "### Comments" in todos[0].notes
        assert "**Alice** (2026-03-19): Looks good" in todos[0].notes
        assert "**Bob** (2026-03-20): Agreed" in todos[0].notes
        assert todos[0].jira_synced_comment_ids == ["100", "101"]

    def test_resync_dedup_and_incremental_append(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Re-syncing same comments deduplicates; adding new ones appends only new."""
        cfg, name = cfg_with_project
        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {
                    "key": "PROJ-1",
                    "summary": "Task",
                    "priority": "medium",
                    "status": "To Do",
                    "description": "Desc",
                },
            ],
        }

        # First sync with one comment
        comments_v1 = {
            "PROJ-1": [{"id": "100", "author": "Alice", "created": "2026-03-19", "body": "First"}],
        }
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments_v1)
        todos = storage.load_todos(cfg, name)
        assert todos[0].jira_synced_comment_ids == ["100"]

        # Second sync with same comments — no duplication
        apply_mapping(JiraApplyInput(groups=[group]), cfg, comments_by_key=comments_v1)
        todos = storage.load_todos(cfg, name)
        assert todos[0].jira_synced_comment_ids == ["100"]  # not ["100", "100"]
        assert todos[0].notes.count("First") == 1

        # Third sync with old + new comment — only new appended
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

    def test_empty_description_no_jira_header(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Issue with empty description gets empty notes (no Jira header)."""
        cfg, name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "",
                        },
                    ],
                }
            ]
        )
        apply_mapping(data, cfg)
        todos = storage.load_todos(cfg, name)
        assert todos[0].notes == ""

    def test_epic_notes_appended_on_project_creation(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When creating a project from an epic, description/comments go to NOTES.md."""
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "new-epic-proj",
                    "project_exists": False,
                    "create_project": True,
                    "is_epic": True,
                    "jira_key": "EP-1",
                    "name": "Epic Name",
                    "description": "Epic overview text",
                    "issues": [
                        {
                            "key": "EP-10",
                            "summary": "Child task",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        comments = {
            "EP-1": [
                {"id": "c1", "author": "PM", "created": "2026-03-19", "body": "Kick-off note"}
            ],
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
            "groups": [
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "Hello",
                        },
                    ],
                }
            ],
        }
        cbk = {"PROJ-1": [{"id": "c1", "author": "X", "created": "2026-03-19", "body": "note"}]}
        result = json.loads(
            apply_fn(
                mapping_json=json.dumps(mapping),
                project_name=name,
                comments_by_key_json=json.dumps(cbk),
            )
        )
        assert result["status"] == "ok"
        assert result["counts"]["todos_created"] == 1

        todos = storage.load_todos(cfg, name)
        assert "**X** (2026-03-19): note" in todos[0].notes
        assert todos[0].jira_synced_comment_ids == ["c1"]


# ── Root issue -> NOTES.md routing tests (todo 242) ──────────────────────────


class TestRootIssueToNotes:
    """When a Jira issue maps 1:1 to a project (issue_key == meta.jira_issue_key),
    its description and comments go to NOTES.md, not a todo."""

    def test_root_issue_goes_to_notes_not_todo(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Root issue (key == meta.jira_issue_key) routes to NOTES.md."""
        cfg, name = cfg_with_project
        # Set jira_issue_key on the project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-5",
                            "summary": "Root issue",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "Root description",
                        },
                        {
                            "key": "PROJ-10",
                            "summary": "Child task",
                            "priority": "high",
                            "status": "To Do",
                            "description": "Child desc",
                        },
                    ],
                }
            ]
        )
        comments = {
            "PROJ-5": [
                {"id": "r1", "author": "PM", "created": "2026-03-19", "body": "Root comment"}
            ],
            "PROJ-10": [
                {"id": "c1", "author": "Dev", "created": "2026-03-20", "body": "Child comment"}
            ],
        }
        apply_mapping(data, cfg, comments_by_key=comments)

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

    def test_root_issue_description_dedup_on_resync(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
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
                {
                    "key": "PROJ-5",
                    "summary": "Root",
                    "priority": "medium",
                    "status": "To Do",
                    "description": "The description",
                },
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
                {
                    "key": "PROJ-5",
                    "summary": "Root",
                    "priority": "medium",
                    "status": "To Do",
                    "description": "Desc",
                },
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

    def test_epic_comment_tracking_on_creation(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When creating project from epic, comment IDs are tracked in meta."""
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "epic-proj",
                    "project_exists": False,
                    "create_project": True,
                    "is_epic": True,
                    "jira_key": "EP-1",
                    "name": "Epic",
                    "description": "Epic desc",
                    "issues": [
                        {
                            "key": "EP-10",
                            "summary": "Task",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
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

    def test_child_issues_still_become_todos(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Non-root issues in same group still become todos as usual."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        storage.save_meta(cfg, meta)

        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-5",
                            "summary": "Root",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "Root desc",
                        },
                        {
                            "key": "PROJ-10",
                            "summary": "Child A",
                            "priority": "high",
                            "status": "To Do",
                        },
                        {
                            "key": "PROJ-11",
                            "summary": "Child B",
                            "priority": "low",
                            "status": "Done",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["todos_created"] == 2

        todos = storage.load_todos(cfg, name)
        keys = {t.jira_issue_key for t in todos}
        assert "PROJ-10" in keys
        assert "PROJ-11" in keys
        assert "PROJ-5" not in keys  # root issue is NOT a todo

    def test_backward_compat_no_jira_synced_comment_ids(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Old projects without jira_synced_comment_ids on meta still work."""
        cfg, name = cfg_with_project
        # Simulate an old meta without jira_synced_comment_ids
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-5"
        # Save, then reload to prove from_dict handles missing field
        storage.save_meta(cfg, meta)

        # Manually strip jira_synced_comment_ids from the SQLite row
        import json

        from server.lib.db import db_path, get_connection

        db = db_path(cfg, name)
        conn = get_connection(db)
        row = conn.execute("SELECT data FROM project_meta WHERE name=?", (name,)).fetchone()
        raw = json.loads(row["data"])
        raw.pop("jira_synced_comment_ids", None)
        conn.execute("UPDATE project_meta SET data=? WHERE name=?", (json.dumps(raw), name))
        conn.commit()
        conn.close()

        # Reload — should default to empty list
        meta = storage.load_meta(cfg, name)
        assert meta.jira_synced_comment_ids == []

        # Apply should still work
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-5",
                            "summary": "Root",
                            "priority": "medium",
                            "status": "To Do",
                            "description": "Desc",
                        },
                    ],
                }
            ]
        )
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
                    source="epic",
                    jira_key="EP-1",
                    name="Auth",
                    suggested_project="auth",
                    is_epic=True,
                    project_exists=True,
                    needs_user_decision=False,
                    issues=[{"key": "EP-10", "summary": "Login"}],
                ),
                JiraGroup(
                    source="standalone",
                    jira_key="PROJ-99",
                    name="Orphan",
                    suggested_project="",
                    is_epic=False,
                    project_exists=False,
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
                    source="epic",
                    jira_key="EP-1",
                    name="Auth",
                    suggested_project="auth",
                    is_epic=True,
                    project_exists=True,
                    needs_user_decision=False,
                    issues=[
                        {"key": "EP-10", "summary": "Login"},
                        {"key": "EP-11", "summary": "Logout"},
                    ],
                ),
                JiraGroup(
                    source="standalone",
                    jira_key="PROJ-50",
                    name="Bug Fix",
                    suggested_project="",
                    is_epic=False,
                    project_exists=False,
                    needs_user_decision=True,
                    issues=[{"key": "PROJ-50", "summary": "Fix it"}],
                ),
                JiraGroup(
                    source="standalone",
                    jira_key="PROJ-60",
                    name="Docs Update",
                    suggested_project="",
                    is_epic=False,
                    project_exists=False,
                    needs_user_decision=True,
                    issues=[
                        {"key": "PROJ-60", "summary": "Update docs"},
                        {"key": "PROJ-61", "summary": "Review docs"},
                    ],
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
    def _get_tools(self) -> dict[str, Callable[..., str]]:
        from unittest.mock import MagicMock

        from server.tools.jira_sync import register

        app = MagicMock()
        tools: dict[str, Callable[..., str]] = {}
        app.tool = lambda **kw: (lambda fn: tools.update({fn.__name__: fn}) or fn)
        register(app)
        return tools

    def test_proj_jira_map_summary_only_true(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When summary_only=True, only the summary key is returned."""
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        issues = [
            _make_epic_issue("PROJ-5", "Auth"),
            _make_jira_issue("PROJ-10", "Login", parent=_make_epic_parent("PROJ-5", "Auth")),
            _make_jira_issue("PROJ-20", "Standalone task"),
        ]
        result = json.loads(
            map_fn(
                jira_issues_json=json.dumps(issues),
                project_name=name,
                summary_only=True,
            )
        )
        # Only summary key present, no groups
        assert "summary" in result
        assert "groups" not in result
        assert result["summary"]["total_issues"] == 3
        assert result["summary"]["group_count"] == 2  # 1 epic + 1 standalone

    def test_proj_jira_map_summary_only_false(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When summary_only=False (default), full plan is returned (backward compat)."""
        _cfg, name = cfg_with_project
        tools = self._get_tools()
        map_fn = tools["proj_jira_map"]
        issues = [
            _make_epic_issue("PROJ-5", "Auth"),
            _make_jira_issue("PROJ-10", "Login", parent=_make_epic_parent("PROJ-5", "Auth")),
        ]
        result = json.loads(
            map_fn(
                jira_issues_json=json.dumps(issues),
                project_name=name,
                summary_only=False,
            )
        )
        # Full plan includes both groups and summary
        assert "groups" in result
        assert "total_issues" in result
        assert "summary" in result
        assert result["total_issues"] == 2


# ── Matching strategy chain tests (todo 252.7.1) ─────────────────────────────


class TestMatchStandalone:
    """Tests for the _match_standalone() strategy chain."""

    def test_jira_issue_key_strategy(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 1: jira_issue_key lookup matches instantly."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-10"
        storage.save_meta(cfg, meta)

        issue = _make_jira_issue("PROJ-10", "Totally unrelated name")
        matched, strategy, suggestions = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"
        assert strategy == "jira_issue_key"
        assert suggestions == []

    def test_fuzzy_name_strategy(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 2: fuzzy name match on summary."""
        cfg, _name = cfg_with_project
        issue = _make_jira_issue("PROJ-10", "myapp")
        matched, strategy, _suggestions = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"
        assert strategy == "fuzzy_name"

    def test_tag_match_single(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 3: tag match with exactly one project matching."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.tags = ["Backend", "API"]
        storage.save_meta(cfg, meta)

        issue = _make_jira_issue("XYZ-1", "Totally unrelated name xyz", labels=["backend"])
        matched, strategy, _suggestions = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"
        assert strategy == "tag_match"

    def test_tag_match_case_insensitive(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Tag matching is case-insensitive."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.tags = ["FRONTEND"]
        storage.save_meta(cfg, meta)

        issue = _make_jira_issue("XYZ-1", "Unrelated xyz", labels=["frontend"])
        matched, strategy, _ = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"
        assert strategy == "tag_match"

    def test_tag_match_ambiguous(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 3: ambiguous tag match (2 projects share a tag)."""
        cfg, name = cfg_with_project
        today = str(date.today())

        # Set tag on myapp
        meta = storage.load_meta(cfg, name)
        meta.tags = ["shared-tag"]
        storage.save_meta(cfg, meta)

        # Create second project with same tag
        proj_dir = Path(cfg.tracking_dir) / "other-proj"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "archive.yaml").write_text("todos: []\n")
        meta2 = ProjectMeta(
            name="other-proj",
            tags=["shared-tag"],
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta2)
        index = storage.load_index(cfg)
        index.projects["other-proj"] = ProjectEntry(
            name="other-proj",
            tracking_dir=str(proj_dir),
            created=today,
        )
        storage.save_index(cfg, index)

        issue = _make_jira_issue("XYZ-1", "Unrelated xyz", labels=["shared-tag"])
        matched, strategy, suggestions = _match_standalone(
            issue,
            ["myapp", "other-proj"],
            cfg,
        )
        assert matched is None
        assert strategy == "tag_match_ambiguous"
        assert set(suggestions) == {"myapp", "other-proj"}

    def test_keyword_match_by_project_name(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 4: keyword from summary matches project name."""
        cfg, _name = cfg_with_project
        # "myapp" is 5 chars so it passes keyword extraction
        issue = _make_jira_issue(
            "XYZ-1",
            "Fix bug in myapp module",
            labels=[],  # no labels to skip tag strategy
        )
        matched, strategy, _ = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"
        assert strategy == "keyword_match"

    def test_keyword_match_by_description(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 4: keyword from description matches project description."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.description = "Authentication service for the platform"
        storage.save_meta(cfg, meta)

        issue = _make_jira_issue(
            "XYZ-1",
            "Unrelated xyz title",
            labels=[],
            description="Update the authentication service",
        )
        matched, strategy, _ = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"
        assert strategy == "keyword_match"

    def test_recent_suggestion_fallthrough(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 5: falls through to recently-active suggestion."""
        cfg, _name = cfg_with_project
        # Issue that matches nothing by key, name, tags, or keywords
        issue = _make_jira_issue(
            "XYZ-999",
            "Zzzzz qqqq wwww",
            labels=[],
            description="",
        )
        matched, strategy, suggestions = _match_standalone(issue, ["myapp"], cfg)
        assert matched == "myapp"  # only project, so it's the top
        assert strategy == "recent_suggestion"
        assert suggestions == ["myapp"]

    def test_strategy_priority_tag_wins_over_keyword(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Tag match (strategy 3) takes priority over keyword match (strategy 4)."""
        cfg, name = cfg_with_project
        today = str(date.today())

        # myapp has tag "deploy" and description with keyword "platform"
        meta = storage.load_meta(cfg, name)
        meta.tags = ["deploy"]
        meta.description = "Platform project"
        storage.save_meta(cfg, meta)

        # Create second project with description matching keyword "deploy"
        proj_dir = Path(cfg.tracking_dir) / "deploy-svc"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "archive.yaml").write_text("todos: []\n")
        meta2 = ProjectMeta(
            name="deploy-svc",
            description="Deployment service tools",
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta2)
        index = storage.load_index(cfg)
        index.projects["deploy-svc"] = ProjectEntry(
            name="deploy-svc",
            tracking_dir=str(proj_dir),
            created=today,
        )
        storage.save_index(cfg, index)

        # Issue has label "deploy" (matches myapp tag) and keyword
        # "deploy" (would match deploy-svc name)
        issue = _make_jira_issue("XYZ-1", "Unrelated zzz", labels=["deploy"])
        matched, strategy, _ = _match_standalone(
            issue,
            ["myapp", "deploy-svc"],
            cfg,
        )
        assert matched == "myapp"
        assert strategy == "tag_match"  # tag wins over keyword

    def test_keyword_match_ambiguous(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Strategy 4: ambiguous keyword match (2 projects share a keyword)."""
        cfg, name = cfg_with_project
        today = str(date.today())

        meta = storage.load_meta(cfg, name)
        meta.description = "Platform logging service"
        storage.save_meta(cfg, meta)

        proj_dir = Path(cfg.tracking_dir) / "logging-svc"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "archive.yaml").write_text("todos: []\n")
        meta2 = ProjectMeta(
            name="logging-svc",
            description="Centralized logging infrastructure",
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta2)
        index = storage.load_index(cfg)
        index.projects["logging-svc"] = ProjectEntry(
            name="logging-svc",
            tracking_dir=str(proj_dir),
            created=today,
        )
        storage.save_index(cfg, index)

        issue = _make_jira_issue(
            "XYZ-1",
            "Unrelated zzz title",
            labels=[],
            description="Fix the logging pipeline",
        )
        matched, strategy, suggestions = _match_standalone(
            issue,
            ["myapp", "logging-svc"],
            cfg,
        )
        assert matched is None
        assert strategy == "keyword_match_ambiguous"
        assert set(suggestions) == {"myapp", "logging-svc"}

    def test_no_projects_returns_none(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """With no existing projects, returns (None, 'none', [])."""
        cfg, _ = cfg_with_project
        issue = _make_jira_issue("XYZ-1", "Something")
        matched, strategy, suggestions = _match_standalone(issue, [], cfg)
        assert matched is None
        assert strategy == "none"
        assert suggestions == []


class TestMatchedStrategyField:
    """Tests for the matched_strategy field on JiraGroup."""

    def test_matched_strategy_in_to_dict(self) -> None:
        from server.tools.jira_sync import JiraGroup

        g = JiraGroup(
            source="standalone",
            jira_key="X-1",
            name="Test",
            suggested_project="myapp",
            matched_project="myapp",
            matched_strategy="tag_match",
            issues=[],
        )
        d = g.to_dict()
        assert d["matched_strategy"] == "tag_match"

    def test_matched_strategy_omitted_when_empty(self) -> None:
        from server.tools.jira_sync import JiraGroup

        g = JiraGroup(
            source="standalone",
            jira_key="X-1",
            name="Test",
            suggested_project="",
            matched_strategy="",
            issues=[],
        )
        d = g.to_dict()
        assert "matched_strategy" not in d


class TestComputeMappingWithStrategies:
    """Integration tests: compute_mapping Phase 3 uses strategy chain."""

    def test_standalone_tag_match_sets_strategy(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Standalone issue matched by tag has matched_strategy set."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.tags = ["infra"]
        storage.save_meta(cfg, meta)

        issues = [_make_jira_issue("XYZ-1", "Unrelated xyz", labels=["infra"])]
        plan = compute_mapping(issues, cfg)
        g = plan.groups[0]
        assert g.matched_project == "myapp"
        assert g.matched_strategy == "tag_match"
        assert g.needs_user_decision is False

    def test_standalone_recent_suggestion_needs_decision(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Standalone with no match falls to recent_suggestion with needs_user_decision."""
        cfg, _name = cfg_with_project
        issues = [_make_jira_issue("XYZ-999", "Zzzzz qqqq wwww")]
        plan = compute_mapping(issues, cfg)
        g = plan.groups[0]
        assert g.matched_strategy == "recent_suggestion"
        assert g.needs_user_decision is True

    def test_standalone_keyword_match_sets_strategy(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Standalone matched by keyword has matched_strategy='keyword_match'."""
        cfg, _name = cfg_with_project
        # "myapp" as keyword in summary
        issues = [_make_jira_issue("XYZ-1", "Fix bug in myapp module", labels=[])]
        plan = compute_mapping(issues, cfg)
        g = plan.groups[0]
        # fuzzy_name should match first since "myapp" is in the summary
        # but the issue name as a whole doesn't fuzzy-match "myapp" at 0.6 threshold
        # Actually _fuzzy_match_project checks the full summary, not keywords.
        # "Fix bug in myapp module" won't fuzzy match "myapp" (too different).
        # So it falls through to keyword_match.
        assert g.matched_project == "myapp"
        assert g.matched_strategy == "keyword_match"
        assert g.needs_user_decision is False

    def test_standalone_ambiguous_tag_needs_decision(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Ambiguous tag match sets needs_user_decision=True."""
        cfg, name = cfg_with_project
        today = str(date.today())

        meta = storage.load_meta(cfg, name)
        meta.tags = ["shared"]
        storage.save_meta(cfg, meta)

        proj_dir = Path(cfg.tracking_dir) / "other"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "archive.yaml").write_text("todos: []\n")
        meta2 = ProjectMeta(
            name="other",
            tags=["shared"],
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta2)
        index = storage.load_index(cfg)
        index.projects["other"] = ProjectEntry(
            name="other",
            tracking_dir=str(proj_dir),
            created=today,
        )
        storage.save_index(cfg, index)

        issues = [_make_jira_issue("XYZ-1", "Unrelated xyz", labels=["shared"])]
        plan = compute_mapping(issues, cfg)
        g = plan.groups[0]
        assert g.matched_strategy == "tag_match_ambiguous"
        assert g.needs_user_decision is True
        assert g.matched_project is None

    def test_project_name_override_sets_strategy(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When project_name is provided, strategy is 'project_name_override'."""
        cfg, _name = cfg_with_project
        issues = [_make_jira_issue("XYZ-1", "Something")]
        plan = compute_mapping(issues, cfg, project_name="myapp")
        g = plan.groups[0]
        assert g.matched_project == "myapp"
        assert g.matched_strategy == "project_name_override"
        assert g.needs_user_decision is False


# ── Per-issue resilience tests (todo 252.7.3) ────────────────────────────────


class TestPerIssueResilience:
    """Verify that apply_mapping processes each issue independently and
    returns per-issue status in JiraApplyResult."""

    def test_per_issue_status_created(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Newly created issues get 'created' in per_issue."""
        cfg, _name = cfg_with_project
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Task A",
                            "priority": "medium",
                            "status": "To Do",
                        },
                        {
                            "key": "PROJ-2",
                            "summary": "Task B",
                            "priority": "low",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        result = apply_mapping(data, cfg)
        assert result.per_issue["PROJ-1"] == "created"
        assert result.per_issue["PROJ-2"] == "created"

    def test_per_issue_status_updated(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-run marks existing issues as 'updated' in per_issue."""
        cfg, _name = cfg_with_project
        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task", "priority": "medium", "status": "To Do"},
            ],
        }
        # First run creates
        apply_mapping(JiraApplyInput(groups=[group]), cfg)
        # Second run updates
        result = apply_mapping(JiraApplyInput(groups=[group]), cfg)
        assert result.per_issue["PROJ-1"] == "updated"
        assert result.counts["todos_updated"] == 1

    def test_partial_failure_other_issues_succeed(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When one issue fails, other issues in the same group still succeed."""
        cfg, name = cfg_with_project
        from unittest.mock import patch

        original_next_todo_id = next_todo_id
        call_count = 0

        def flaky_next_todo_id(meta, parent=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated failure")
            return original_next_todo_id(meta, parent=parent)

        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Will fail",
                            "priority": "medium",
                            "status": "To Do",
                        },
                        {
                            "key": "PROJ-2",
                            "summary": "Will succeed",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        with patch("server.tools.jira_sync.next_todo_id", side_effect=flaky_next_todo_id):
            result = apply_mapping(data, cfg)

        # PROJ-1 failed, PROJ-2 succeeded
        assert result.per_issue["PROJ-1"].startswith("failed:")
        assert result.per_issue["PROJ-2"] == "created"
        assert result.counts["todos_created"] == 1

        # Verify PROJ-2 was actually saved
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "PROJ-2"

    def test_all_issues_fail(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """When all issues fail, counts stay at zero and all are in per_issue."""
        cfg, name = cfg_with_project
        from unittest.mock import patch

        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Test",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Fail A",
                            "priority": "medium",
                            "status": "To Do",
                        },
                        {
                            "key": "PROJ-2",
                            "summary": "Fail B",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                }
            ]
        )
        with patch("server.tools.jira_sync.next_todo_id", side_effect=RuntimeError("boom")):
            result = apply_mapping(data, cfg)

        assert result.counts["todos_created"] == 0
        assert result.counts["todos_updated"] == 0
        assert result.per_issue["PROJ-1"].startswith("failed:")
        assert result.per_issue["PROJ-2"].startswith("failed:")

        # No todos saved
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0

    def test_project_creation_failure_marks_all_issues_failed(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """If project creation raises, all issues in that group are marked failed."""
        cfg, _name = cfg_with_project
        from unittest.mock import patch

        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "bad-project",
                    "project_exists": False,
                    "create_project": True,
                    "is_epic": True,
                    "jira_key": "BAD-1",
                    "name": "Bad Epic",
                    "issues": [
                        {
                            "key": "BAD-10",
                            "summary": "Task A",
                            "priority": "medium",
                            "status": "To Do",
                        },
                        {
                            "key": "BAD-11",
                            "summary": "Task B",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                },
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": True,
                    "jira_key": "PROJ-5",
                    "name": "Good Group",
                    "issues": [
                        {
                            "key": "PROJ-1",
                            "summary": "Good task",
                            "priority": "medium",
                            "status": "To Do",
                        },
                    ],
                },
            ]
        )

        original_tracking_dir = storage.tracking_dir

        def bad_tracking_dir(c, pname):
            if pname == "bad-project":
                raise OSError("disk full")
            return original_tracking_dir(c, pname)

        with patch.object(storage, "tracking_dir", side_effect=bad_tracking_dir):
            result = apply_mapping(data, cfg)

        # Bad group: all issues failed
        assert result.per_issue["BAD-10"].startswith("failed: project creation failed:")
        assert result.per_issue["BAD-11"].startswith("failed: project creation failed:")
        # Good group: processed normally
        assert result.per_issue["PROJ-1"] == "created"
        assert result.counts["todos_created"] == 1
        assert result.counts["projects_created"] == 0

    def test_rerun_after_partial_failure(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-run after partial failure: previously created todos are updated,
        previously failed issues are retried and succeed."""
        cfg, name = cfg_with_project
        from unittest.mock import patch

        original_next_todo_id = next_todo_id

        group = {
            "suggested_project": "myapp",
            "project_exists": True,
            "create_project": False,
            "is_epic": True,
            "jira_key": "PROJ-5",
            "name": "Test",
            "issues": [
                {"key": "PROJ-1", "summary": "Task A", "priority": "medium", "status": "To Do"},
                {"key": "PROJ-2", "summary": "Task B", "priority": "medium", "status": "To Do"},
                {"key": "PROJ-3", "summary": "Task C", "priority": "medium", "status": "To Do"},
            ],
        }

        # First run: PROJ-2 and PROJ-3 fail
        call_idx = 0

        def fail_some(meta, parent=None):
            nonlocal call_idx
            call_idx += 1
            if call_idx in (2, 3):  # second and third issue
                raise RuntimeError("transient error")
            return original_next_todo_id(meta, parent=parent)

        with patch("server.tools.jira_sync.next_todo_id", side_effect=fail_some):
            result1 = apply_mapping(JiraApplyInput(groups=[group]), cfg)

        assert result1.counts["todos_created"] == 1
        assert result1.per_issue["PROJ-1"] == "created"
        assert result1.per_issue["PROJ-2"].startswith("failed:")
        assert result1.per_issue["PROJ-3"].startswith("failed:")

        # Second run (no failures): PROJ-1 updated, PROJ-2 and PROJ-3 created
        result2 = apply_mapping(JiraApplyInput(groups=[group]), cfg)
        assert result2.counts["todos_updated"] == 1  # PROJ-1
        assert result2.counts["todos_created"] == 2  # PROJ-2, PROJ-3
        assert result2.per_issue["PROJ-1"] == "updated"
        assert result2.per_issue["PROJ-2"] == "created"
        assert result2.per_issue["PROJ-3"] == "created"

        # Verify final state
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 3


# ── Early jira_issue_key linking tests (todo 252.7.2) ────────────────────────


class TestLinkStandaloneKey:
    """Verify that compute_mapping with link_keys=True creates minimal todos
    with jira_issue_key during the map phase for auto-matched standalone issues."""

    def test_link_keys_creates_todo_during_map(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Standalone issue matching a project gets a todo with jira_issue_key during map."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("PROJ-10", "myapp")]  # fuzzy matches "myapp"
        plan = compute_mapping(issues, cfg, link_keys=True)

        g = plan.groups[0]
        assert g.matched_project == "myapp"
        assert g.needs_user_decision is False

        # Todo should have been created with jira_issue_key
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "PROJ-10"
        assert todos[0].title == "myapp"
        assert todos[0].status == "pending"

    def test_link_keys_idempotent(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Running compute_mapping twice does not create duplicate todos."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("PROJ-10", "myapp")]

        compute_mapping(issues, cfg, link_keys=True)
        compute_mapping(issues, cfg, link_keys=True)

        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "PROJ-10"

    def test_link_keys_false_skips_linking(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """link_keys=False means no storage writes for jira_issue_key (dry-run)."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("PROJ-10", "myapp")]
        plan = compute_mapping(issues, cfg, link_keys=False)

        # Match should still happen in the plan
        assert plan.groups[0].matched_project == "myapp"

        # But no todo should have been written
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0

    def test_link_keys_storage_failure_logs_warning(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Storage failure during key linking logs warning but returns the plan."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("PROJ-10", "myapp")]

        # Make save_todos raise to simulate storage failure
        def _boom(*args: object, **kwargs: object) -> None:
            msg = "disk full"
            raise OSError(msg)

        monkeypatch.setattr(storage, "save_todos", _boom)

        plan = compute_mapping(issues, cfg, link_keys=True)

        # Plan should still be returned
        assert plan.total_issues == 1
        assert plan.groups[0].matched_project == "myapp"

        # No todo created (save failed)
        monkeypatch.undo()
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0

    def test_apply_after_map_link_updates_not_duplicates(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """apply_mapping after map-phase linking updates the pre-linked todo."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("PROJ-10", "myapp")]

        # Map phase creates minimal todo
        compute_mapping(issues, cfg, link_keys=True)
        todos_before = storage.load_todos(cfg, name)
        assert len(todos_before) == 1
        assert todos_before[0].jira_issue_key == "PROJ-10"

        # Apply phase should update the existing todo, not duplicate
        data = JiraApplyInput(
            groups=[
                {
                    "suggested_project": "myapp",
                    "project_exists": True,
                    "create_project": False,
                    "is_epic": False,
                    "jira_key": "PROJ-10",
                    "name": "myapp",
                    "issues": [
                        {
                            "key": "PROJ-10",
                            "summary": "myapp updated",
                            "priority": "high",
                            "status": "To Do",
                            "description": "Full description",
                        },
                    ],
                }
            ]
        )
        counts = apply_mapping(data, cfg).counts
        assert counts["todos_updated"] == 1
        assert counts["todos_created"] == 0

        todos_after = storage.load_todos(cfg, name)
        assert len(todos_after) == 1
        assert todos_after[0].jira_issue_key == "PROJ-10"
        assert todos_after[0].title == "myapp updated"
        assert todos_after[0].priority == "high"

    def test_deleted_todo_recreated_on_next_map(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """If a todo linked during map is deleted, next compute_mapping re-creates it."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("PROJ-10", "myapp")]

        # First map: creates todo
        compute_mapping(issues, cfg, link_keys=True)
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1

        # Delete the todo
        storage.save_todos(cfg, name, [])

        # Second map: re-creates it
        compute_mapping(issues, cfg, link_keys=True)
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].jira_issue_key == "PROJ-10"

    def test_needs_user_decision_not_linked(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Standalone issues that need user decision are NOT linked during map."""
        cfg, name = cfg_with_project
        issues = [_make_jira_issue("ZZZ-999", "Completely unrelated task name xyz")]
        plan = compute_mapping(issues, cfg, link_keys=True)

        g = plan.groups[0]
        assert g.needs_user_decision is True

        # No todo should have been created
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0


# ── proj_jira_full_sync tests ────────────────────────────────────────────────


class TestStandaloneBucketingRegression:
    """Regression tests for the silent mis-bucketing fix in _run_jira_full_sync.

    Pre-fix bug: ``_run_jira_full_sync`` called ``require_project(project_name)``
    and unconditionally rebound ``project_name`` to the resolved active project,
    so every standalone Jira issue (Case C) was bucketed under whichever project
    happened to be active. These tests target ``_deterministic_map`` directly
    to pin its contract: ``name=None`` MUST route through the per-issue
    standalone path (creation + dedup), regardless of cfg state.

    Spec: docs/superpowers/specs/2026-04-26-jira-sync-standalone-bucketing-design.md
    """

    def test_standalone_creates_per_issue_projects_when_name_is_none(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """name=None → standalone issue gets its own dedicated project."""
        cfg, _existing = cfg_with_project
        issues = [_make_jira_issue("STAND-1", "Some standalone task")]
        apply_input, _diagnostics = _deterministic_map(issues, cfg, name=None)
        assert len(apply_input.groups) == 1
        group = apply_input.groups[0]
        assert group["source"] == "standalone"
        assert group["create_project"] is True
        assert group["jira_key"] == "STAND-1"
        assert "jira-standalone" in group.get("labels", [])
        # suggested_project is derived from issue key + summary, slugified.
        suggested = group["suggested_project"]
        assert isinstance(suggested, str)
        assert "stand-1" in suggested

    def test_standalone_does_not_fall_back_to_existing_project_when_name_is_none(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Pinned regression: even when cfg has an existing project loaded,
        name=None must NOT bucket the standalone issue under that project.

        The bug in ``_run_jira_full_sync`` was rebinding ``project_name`` to
        the resolved active project before invoking ``_deterministic_map``.
        This test pins that ``_deterministic_map`` itself respects name=None
        and never auto-falls-back to an existing project name.
        """
        cfg, existing_name = cfg_with_project  # "myapp" is registered.
        issues = [_make_jira_issue("STAND-2", "Another standalone task")]
        apply_input, _diagnostics = _deterministic_map(issues, cfg, name=None)
        assert len(apply_input.groups) == 1
        group = apply_input.groups[0]
        assert group["source"] == "standalone"
        assert group["create_project"] is True
        # Critical assertion: standalone is NOT bucketed under the existing project.
        assert group["suggested_project"] != existing_name

    def test_standalone_dedups_via_todo_key_index_when_name_is_none(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """When an existing project already has a todo with the issue's
        jira_issue_key, the standalone path dedups via ``todo_key_index``
        instead of creating a duplicate standalone project. Pre-fix, the
        override branch (``if name:``) skipped this dedup entirely.
        """
        cfg, existing_name = cfg_with_project  # "myapp" — pre-populated by fixture.
        # Inject a todo linked to STAND-3 under "myapp" via the storage API.
        today = str(date.today())
        existing_todo = Todo(
            id="1",
            title="existing-todo",
            created=today,
            updated=today,
            jira_issue_key="STAND-3",
        )
        storage.save_todos(cfg, existing_name, [existing_todo])
        issues = [_make_jira_issue("STAND-3", "Already linked task")]
        apply_input, _diagnostics = _deterministic_map(issues, cfg, name=None)
        assert len(apply_input.groups) == 1
        group = apply_input.groups[0]
        assert group["source"] == "standalone"
        # Dedup hit: no new project, route to the project that already has
        # the linked todo.
        assert group["suggested_project"] == existing_name
        assert group["create_project"] is False
        assert group["project_exists"] is True


class TestProjJiraFullSync:
    """Tests for _deterministic_map and the full-sync flow."""

    def test_full_success_returns_summary(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Full sync with epic issues produces groups and diagnostics."""
        cfg, _name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2", "Login page", parent=_make_epic_parent("PROJ-1", "Auth Epic")
            ),
            _make_jira_issue(
                "PROJ-3", "Register page", parent=_make_epic_parent("PROJ-1", "Auth Epic")
            ),
        ]
        apply_input, diagnostics = _deterministic_map(issues, cfg)
        assert len(apply_input.groups) == 1
        assert diagnostics["epic_count"] == 1
        assert diagnostics["standalone_count"] == 0
        assert len(diagnostics["warnings"]) == 0

        # Apply and check results
        result = apply_mapping(apply_input, cfg)
        assert result.counts["projects_created"] == 1
        assert result.counts["todos_created"] == 2

    def test_auto_create_epic_project(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """A new epic with no matching project triggers auto-create."""
        cfg, _name = cfg_with_project
        issues = [
            _make_epic_issue("NEW-1", "Brand New Feature"),
            _make_jira_issue(
                "NEW-2", "Sub-task", parent=_make_epic_parent("NEW-1", "Brand New Feature")
            ),
        ]
        apply_input, diagnostics = _deterministic_map(issues, cfg)
        assert diagnostics["projects_to_create"] == 1

        # The group should be flagged for creation
        group = apply_input.groups[0]
        assert group["create_project"] is True
        assert group["suggested_project"] == "brand-new-feature"

        # Apply and verify project was created
        result = apply_mapping(apply_input, cfg)
        assert result.counts["projects_created"] == 1
        index = storage.load_index(cfg)
        assert "brand-new-feature" in index.projects

    def test_standalone_without_catchall_creates_standalone_project(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Standalone issues with no catch-all get their own project."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue("LONE-1", "Orphan task zzz unique xyz"),
        ]
        apply_input, diagnostics = _deterministic_map(issues, cfg)
        assert diagnostics["standalone_count"] == 1
        # A standalone project group should be created
        assert len(apply_input.groups) == 1
        group = apply_input.groups[0]
        assert group["source"] == "standalone"
        assert group["create_project"] is True
        assert group["jira_key"] == "LONE-1"
        assert "jira-standalone" in group.get("labels", [])

    def test_empty_issues_returns_up_to_date(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Empty issue list produces empty mapping."""
        cfg, _name = cfg_with_project
        apply_input, diagnostics = _deterministic_map([], cfg)
        assert len(apply_input.groups) == 0
        assert diagnostics["epic_count"] == 0
        assert diagnostics["standalone_count"] == 0

    def test_jira_done_status_completes_local_todo(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """A Jira issue with Done status sets local todo to done."""
        cfg, name = cfg_with_project
        # Set jira_issue_key on project meta so epic matches
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-1"
        storage.save_meta(cfg, meta)

        # Create a pending todo linked to a Jira issue
        todo = _make_todo(cfg, name, "Login page", jira_issue_key="PROJ-2", status="pending")
        todos = storage.load_todos(cfg, name)
        todos.append(todo)
        storage.save_todos(cfg, name, todos)

        issues = [
            _make_epic_issue("PROJ-1", "myapp"),
            _make_jira_issue(
                "PROJ-2", "Login page", status="Done", parent=_make_epic_parent("PROJ-1", "myapp")
            ),
        ]
        apply_input, _diag = _deterministic_map(issues, cfg)
        result = apply_mapping(apply_input, cfg)
        assert result.counts["todos_updated"] >= 1

        todos = storage.load_todos(cfg, name)
        matched = [t for t in todos if t.jira_issue_key == "PROJ-2"]
        assert len(matched) == 1
        assert matched[0].status in {"done", "Done"}

    def test_reopened_jira_issue_sets_local_pending(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """A Jira issue reopened (not-done) with local done status gets set to pending."""
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        meta.jira_issue_key = "PROJ-1"
        storage.save_meta(cfg, meta)

        # Create a done todo
        todo = _make_todo(cfg, name, "Login page", jira_issue_key="PROJ-2", status="done")
        todos = storage.load_todos(cfg, name)
        todos.append(todo)
        storage.save_todos(cfg, name, todos)

        # Jira issue is "In Progress" (reopened)
        issues = [
            _make_epic_issue("PROJ-1", "myapp"),
            _make_jira_issue(
                "PROJ-2",
                "Login page",
                status="In Progress",
                parent=_make_epic_parent("PROJ-1", "myapp"),
            ),
        ]
        _apply_input, _diag = _deterministic_map(issues, cfg)

        # The deterministic_map should have set the todo to pending
        todos = storage.load_todos(cfg, name)
        matched = [t for t in todos if t.jira_issue_key == "PROJ-2"]
        assert len(matched) == 1
        assert matched[0].status == "pending"


# ── Self-fetch path tests for proj_jira_full_sync ────────────────────────────


class TestSelfFetchFullSync:
    """Tests for the self-fetch (jira_issues_json=None) path in proj_jira_full_sync."""

    def _get_full_sync_fn(self):
        from server.tools.jira_sync import _run_jira_full_sync

        return _run_jira_full_sync

    def test_self_fetch_successful(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When jira_issues_json=None, _fetch_jira_issues is called and sync proceeds."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2",
                "Login page",
                parent=_make_epic_parent("PROJ-1", "Auth Epic"),
            ),
        ]
        monkeypatch.setattr(
            "server.tools.jira_full_sync._fetch_jira_issues",
            lambda: (issues, len(issues)),
        )
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=None, project_name=name))
        assert result["status"] == "success"
        assert result["summary"]["groups_processed"] >= 1
        assert result["summary"]["epic_count"] >= 1

    def test_self_fetch_socket_unreachable(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the Jira socket is unreachable, returns error with guidance."""
        import httpx

        _cfg, name = cfg_with_project

        def _raise_connect_error():
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(
            "server.tools.jira_full_sync._fetch_jira_issues",
            _raise_connect_error,
        )
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=None, project_name=name))
        assert result["status"] == "error"
        assert "guidance" in result

    def test_self_fetch_config_missing_jira(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When there is no project config, returns error."""
        config_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
        monkeypatch.delenv("PROJ_CONFIG", raising=False)

        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=None, project_name="nonexistent"))
        assert result["status"] == "error"

    def test_self_fetch_zero_issues(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Self-fetch returns empty list — sync returns success without error."""
        _cfg, name = cfg_with_project
        monkeypatch.setattr(
            "server.tools.jira_full_sync._fetch_jira_issues",
            lambda: ([], 0),
        )
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=None, project_name=name))
        assert result["status"] == "success"
        assert (
            "up to date" in result["summary"].get("message", "").lower()
            or result["summary"].get("message") == "Everything up to date"
        )

    def test_self_fetch_backward_compat_legacy_json(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Passing jira_issues_json='[...]' still works (legacy path unchanged)."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2",
                "Login page",
                parent=_make_epic_parent("PROJ-1", "Auth Epic"),
            ),
        ]
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert result["status"] == "success"
        assert result["summary"]["groups_processed"] >= 1

    def test_self_fetch_backward_compat_envelope_json(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Legacy path unwraps {"issues": [...]} envelope from jira_issues_json."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2",
                "Login page",
                parent=_make_epic_parent("PROJ-1", "Auth Epic"),
            ),
        ]
        envelope = {"issues": issues, "total": len(issues)}
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=json.dumps(envelope), project_name=name))
        assert result["status"] == "success"
        assert result["summary"]["groups_processed"] >= 1

    def test_empty_dict_input_returns_up_to_date(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Passing an empty dict {} handles gracefully (no 'issues' key)."""
        _cfg, name = cfg_with_project
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=json.dumps({}), project_name=name))
        assert result["status"] == "success"
        assert (
            "up to date" in result["summary"].get("message", "").lower()
            or result["summary"].get("message") == "Everything up to date"
        )


class TestDedupGuards:
    """Tests for dedup guards in apply_mapping."""

    def test_dedup_project_creation_skipped_when_meta_exists(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """meta.yaml already exists; project creation skipped; warning logged."""
        cfg, _name = cfg_with_project

        # Create a project directory with meta.yaml already present (simulating partial prior run)
        new_project_name = "auth-epic"
        proj_dir = storage.tracking_dir(cfg, new_project_name)
        proj_dir.mkdir(parents=True, exist_ok=True)
        meta = ProjectMeta(
            name=new_project_name,
            description="Auth Epic",
            dates=ProjectDates(created=str(date.today()), last_updated=str(date.today())),
            jira_issue_key="PROJ-1",
        )
        storage.save_meta(cfg, meta)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "archive.yaml").write_text("todos: []\n")

        # Now try to apply a mapping that would create this project
        apply_input = JiraApplyInput(
            groups=[
                {
                    "suggested_project": new_project_name,
                    "create_project": True,
                    "project_exists": False,
                    "is_epic": True,
                    "jira_key": "PROJ-1",
                    "name": "Auth Epic",
                    "issues": [
                        _make_jira_issue("PROJ-2", "Login page"),
                    ],
                }
            ]
        )

        result = apply_mapping(apply_input, cfg)
        # Project was not recreated but the index was repaired
        assert result.counts["projects_created"] == 1  # index repair counts as create
        # The todo from the issue was still created
        assert result.counts["todos_created"] == 1

    def test_dedup_retry_issue_filter_skips_existing_jira_key(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Issue already has jira_issue_key in existing todos; filtered out from retry batch."""
        cfg, name = cfg_with_project

        # Create a second project where the jira key is already linked
        new_proj = "other-project"
        new_proj_dir = storage.tracking_dir(cfg, new_proj)
        new_proj_dir.mkdir(parents=True, exist_ok=True)
        new_meta = ProjectMeta(
            name=new_proj,
            description="Other",
            dates=ProjectDates(created=str(date.today()), last_updated=str(date.today())),
        )
        storage.save_meta(cfg, new_meta)
        (new_proj_dir / "todos.yaml").write_text("todos: []\n")
        (new_proj_dir / "archive.yaml").write_text("todos: []\n")
        new_index = storage.load_index(cfg)
        new_index.projects[new_proj] = ProjectEntry(
            name=new_proj,
            tracking_dir=str(new_proj_dir),
            created=str(date.today()),
        )
        storage.save_index(cfg, new_index)

        other_todo = _make_todo(cfg, new_proj, "Login page", jira_issue_key="PROJ-2")
        storage.save_todos(cfg, new_proj, [other_todo])

        # Build cross-project index pointing to other-project
        cross_index = {"PROJ-2": (new_proj, other_todo.id)}

        apply_input = JiraApplyInput(
            groups=[
                {
                    "suggested_project": name,
                    "create_project": False,
                    "project_exists": True,
                    "is_epic": False,
                    "jira_key": "",
                    "name": "Standalone",
                    "issues": [
                        _make_jira_issue("PROJ-2", "Login page"),
                        _make_jira_issue("PROJ-3", "Register page"),
                    ],
                }
            ]
        )

        result = apply_mapping(apply_input, cfg, todo_key_index=cross_index)
        # PROJ-2 was skipped due to cross-project dedup
        assert result.counts.get("skipped_dedup", 0) == 1
        # PROJ-3 was created normally
        assert result.counts["todos_created"] == 1


# ── Routing, dedup, and counts tests ───────────────────────────────────────


class TestJiraRouting:
    """Tests for epic routing, dedup idempotency, and sync counts."""

    def _get_full_sync_fn(self):
        from server.tools.jira_sync import _run_jira_full_sync

        return _run_jira_full_sync

    def test_epic_routing_maps_to_project(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Epic issue routes to a project (not a todo). Verify epics_mapped >= 1."""
        cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("EPIC-1", "Platform Overhaul"),
            _make_jira_issue(
                "TASK-1",
                "Migrate DB",
                parent=_make_epic_parent("EPIC-1", "Platform Overhaul"),
            ),
        ]
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert result["status"] == "success"
        assert result["counts"]["epics_mapped"] >= 1
        assert result["counts"]["total_issues"] == 2
        # Epic itself should NOT appear as a todo
        todos = storage.load_todos(cfg, name)
        epic_todos = [t for t in todos if t.jira_issue_key == "EPIC-1"]
        assert len(epic_todos) == 0

    def test_epic_child_routing_same_user(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Issue with epic link where epic is in same user's
        issues -> todo inside epic's project."""
        cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("EPIC-1", "Platform Overhaul"),
            _make_jira_issue(
                "TASK-1",
                "Migrate DB",
                parent=_make_epic_parent("EPIC-1", "Platform Overhaul"),
            ),
            _make_jira_issue(
                "TASK-2",
                "Update API",
                parent=_make_epic_parent("EPIC-1", "Platform Overhaul"),
            ),
        ]
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert result["status"] == "success"
        assert result["counts"]["todos_created"] >= 2
        # Both children should be todos in the project
        todos = storage.load_todos(cfg, name)
        jira_keys = {t.jira_issue_key for t in todos if t.jira_issue_key}
        assert "TASK-1" in jira_keys
        assert "TASK-2" in jira_keys

    def test_epic_child_routing_foreign_epic(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Issue linked to an epic NOT in the user's issues -> standalone project."""
        cfg, _name = cfg_with_project
        issues = [
            _make_jira_issue(
                "TASK-1",
                "Orphan with foreign epic zzzunique",
                parent=_make_epic_parent("FOREIGN-1", "Someone Elses Epic"),
            ),
        ]
        apply_input, diagnostics = _deterministic_map(issues, cfg)
        assert diagnostics["standalone_count"] == 1
        # The issue should route as standalone (not under an epic project)
        assert len(apply_input.groups) == 1
        group = apply_input.groups[0]
        assert group["source"] == "standalone"

    def test_dedup_idempotency(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Run sync twice with same issues -> second run shows
        duplicates_skipped or no new items."""
        cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("EPIC-1", "Auth"),
            _make_jira_issue(
                "TASK-1",
                "Login page",
                parent=_make_epic_parent("EPIC-1", "Auth"),
            ),
        ]
        fn = self._get_full_sync_fn()
        # First sync
        r1 = json.loads(fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert r1["status"] == "success"
        todos_after_first = storage.load_todos(cfg, name)
        count_first = len(todos_after_first)

        # Second sync (same issues)
        r2 = json.loads(fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert r2["status"] == "success"
        todos_after_second = storage.load_todos(cfg, name)
        count_second = len(todos_after_second)
        # No new todos created on second run
        assert count_second == count_first
        # Second run should show updates (not creates) or skips
        assert r2["counts"]["todos_created"] == 0

    def test_legacy_name_fallback(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Todo exists without jira_issue_key but matching title
        -> matched by title (not duplicated)."""
        cfg, name = cfg_with_project
        # Create a todo without jira_issue_key but with a title that matches
        todo = _make_todo(cfg, name, "Login page redesign")
        todos = storage.load_todos(cfg, name)
        todos.append(todo)
        storage.save_todos(cfg, name, todos)

        issues = [
            _make_jira_issue("TASK-1", "Login page redesign"),
        ]
        apply_input, _diagnostics = _deterministic_map(issues, cfg)
        # Should find the existing project via legacy title match
        matched_group = apply_input.groups[0]
        assert matched_group["project_exists"] is True
        assert matched_group["create_project"] is False


# ── Response shape tests for proj_jira_full_sync ─────────────────────────────


class TestFullSyncResponseShape:
    """Tests that full-sync responses are compact and well-shaped."""

    def _get_full_sync_fn(self):
        from server.tools.jira_sync import _run_jira_full_sync

        return _run_jira_full_sync

    def test_success_response_keys(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Success response has exactly status, summary, counts."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2", "Login page", parent=_make_epic_parent("PROJ-1", "Auth Epic")
            ),
        ]
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json=json.dumps(issues), project_name=name))
        assert result["status"] == "success"
        assert set(result.keys()) == {"status", "summary", "counts"}
        assert "warnings" in result["summary"]

    def test_partial_success_errors_compact(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Partial-success errors contain only issue_key and error (no retry_payload/retryable)."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2", "Login page", parent=_make_epic_parent("PROJ-1", "Auth Epic")
            ),
        ]
        # Force a per-issue failure by monkeypatching apply_mapping
        original_apply = apply_mapping

        def _patched_apply(inp, cfg_obj, **kw):
            result = original_apply(inp, cfg_obj, **kw)
            result.per_issue["PROJ-2"] = "failed: forced test error"
            return result

        monkeypatch.setattr("server.tools.jira_sync.apply_mapping", _patched_apply)
        fn = self._get_full_sync_fn()
        raw = fn(jira_issues_json=json.dumps(issues), project_name=name)
        result = json.loads(raw)
        assert result["status"] == "partial_success"
        for err in result["errors"]:
            assert set(err.keys()) == {"issue_key", "error"}
            assert "retry_payload" not in err
            assert "retryable" not in err

    def test_exception_path_errors_compact(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When apply_mapping raises, errors still have compact shape."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2", "Login page", parent=_make_epic_parent("PROJ-1", "Auth Epic")
            ),
        ]

        call_count = 0

        def _exploding_apply(inp, cfg_obj, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            return apply_mapping(inp, cfg_obj, **kw)

        monkeypatch.setattr("server.tools.jira_sync.apply_mapping", _exploding_apply)
        fn = self._get_full_sync_fn()
        raw = fn(jira_issues_json=json.dumps(issues), project_name=name)
        result = json.loads(raw)
        assert result["status"] == "partial_success"
        for err in result["errors"]:
            assert set(err.keys()) == {"issue_key", "error"}

    def test_success_response_size_under_2kb(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Success response JSON is under 2 KB."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-1", "Auth Epic"),
            _make_jira_issue(
                "PROJ-2", "Login page", parent=_make_epic_parent("PROJ-1", "Auth Epic")
            ),
        ]
        fn = self._get_full_sync_fn()
        raw = fn(jira_issues_json=json.dumps(issues), project_name=name)
        assert len(raw) < 2048, f"Response too large: {len(raw)} bytes"

    def test_error_response_shape(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Error responses have status and error keys."""
        fn = self._get_full_sync_fn()
        result = json.loads(fn(jira_issues_json="NOT VALID JSON {{{"))
        assert result["status"] == "error"
        assert "error" in result

    def test_warnings_are_strings(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Warnings in summary are always plain strings, never Warning objects."""
        _cfg, name = cfg_with_project
        issues = [
            _make_jira_issue("LONE-1", "Orphan task unique xyz"),
        ]
        fn = self._get_full_sync_fn()
        raw = fn(jira_issues_json=json.dumps(issues), project_name=name)
        result = json.loads(raw)
        for w in result.get("summary", {}).get("warnings", []):
            assert isinstance(w, str), f"Warning is not a string: {type(w)}"


# ── Retry path tests for proj_jira_full_sync ─────────────────────────────────


class TestRetryPath:
    """Tests for the retry_failures parameter in proj_jira_full_sync."""

    def _get_full_sync_fn(self):
        from server.tools.jira_sync import _run_jira_full_sync

        return _run_jira_full_sync

    def _make_retry_token(self, errors: list[JsonDict], ts: float | None = None) -> str:
        import base64
        import time as _time

        token_data = {
            "ts": ts if ts is not None else _time.time(),
            "errors": errors,
        }
        return base64.b64encode(json.dumps(token_data).encode()).decode()

    def test_invalid_retry_token_returns_error(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Invalid base64 retry_failures returns error."""
        _cfg, name = cfg_with_project
        fn = self._get_full_sync_fn()
        result = json.loads(fn(retry_failures="not-valid-base64!!!", project_name=name))
        assert result["status"] == "error"
        assert "Invalid retry_token" in result["error"]

    def test_expired_retry_token_returns_error(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Retry token older than 30 minutes is rejected."""
        import time as _time

        _cfg, name = cfg_with_project
        old_ts = _time.time() - 3600  # 1 hour ago
        token = self._make_retry_token([], ts=old_ts)
        fn = self._get_full_sync_fn()
        result = json.loads(fn(retry_failures=token, project_name=name))
        assert result["status"] == "error"
        assert "expired" in result["error"].lower()

    def test_retry_with_no_retryable_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Retry token with empty errors list returns success with no-retry message."""
        _cfg, name = cfg_with_project
        token = self._make_retry_token([])
        fn = self._get_full_sync_fn()
        result = json.loads(fn(retry_failures=token, project_name=name))
        assert result["status"] == "success"
        assert "No retryable issues" in result["summary"]["message"]

    def test_retry_with_valid_issues(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Retry token with valid issue payloads re-processes them."""
        _cfg, name = cfg_with_project
        errors = [
            {
                "retry_payload": {
                    "issue": {
                        "key": "PROJ-100",
                        "summary": "Retry task",
                        "priority": {"name": "Medium"},
                        "status": {"name": "To Do"},
                        "labels": [],
                        "description": "",
                        "duedate": None,
                        "assignee": None,
                        "subtasks": [],
                        "parent": {
                            "key": "PROJ-5",
                            "fields": {
                                "issuetype": {"name": "Epic"},
                                "summary": "Test Epic",
                            },
                        },
                    }
                }
            }
        ]
        token = self._make_retry_token(errors)
        fn = self._get_full_sync_fn()
        result = json.loads(fn(retry_failures=token, project_name=name))
        # Should attempt to process the retry issue
        assert result["status"] in ("success", "partial_success")

    def test_retry_dedup_skips_already_applied(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Retry skips issues whose jira_issue_key already exists as a todo."""
        cfg, name = cfg_with_project
        # Pre-create a todo with jira_issue_key = "PROJ-100"
        todo = _make_todo(cfg, name, "Already done", jira_issue_key="PROJ-100")
        todos = storage.load_todos(cfg, name)
        todos.append(todo)
        storage.save_todos(cfg, name, todos)

        errors = [
            {
                "retry_payload": {
                    "issue": {
                        "key": "PROJ-100",
                        "summary": "Retry task",
                        "priority": {"name": "Medium"},
                        "status": {"name": "To Do"},
                        "labels": [],
                        "description": "",
                        "duedate": None,
                        "assignee": None,
                        "subtasks": [],
                    }
                }
            }
        ]
        token = self._make_retry_token(errors)
        fn = self._get_full_sync_fn()
        result = json.loads(fn(retry_failures=token, project_name=name))
        assert result["status"] == "success"
        assert "already applied" in result["summary"]["message"].lower()


# ── Comments JSON parameter in full sync ──────────────────────────────────────


class TestFullSyncCommentsJson:
    """Tests for the comments_json parameter in proj_jira_full_sync."""

    def _get_full_sync_fn(self):
        from server.tools.jira_sync import _run_jira_full_sync

        return _run_jira_full_sync

    def test_comments_json_passed_through(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """comments_json parameter is parsed and applied to created todos."""
        _cfg, name = cfg_with_project
        issues = [
            _make_jira_issue(
                "PROJ-10",
                "Task with comments",
                parent=_make_epic_parent("PROJ-5", "Test Epic"),
                description="Some description",
            ),
            _make_epic_issue("PROJ-5", "Test Epic"),
        ]
        comments = {
            "PROJ-10": [
                {"id": "c1", "author": "Alice", "created": "2026-04-01", "body": "Review this"},
            ],
        }
        fn = self._get_full_sync_fn()
        result = json.loads(
            fn(
                jira_issues_json=json.dumps(issues),
                project_name=name,
                comments_json=json.dumps(comments),
            )
        )
        assert result["status"] == "success"

    def test_invalid_comments_json_falls_back_to_empty(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Invalid comments_json is silently treated as empty dict."""
        _cfg, name = cfg_with_project
        issues = [
            _make_epic_issue("PROJ-5", "Test Epic"),
            _make_jira_issue(
                "PROJ-10",
                "Task",
                parent=_make_epic_parent("PROJ-5", "Test Epic"),
            ),
        ]
        fn = self._get_full_sync_fn()
        result = json.loads(
            fn(
                jira_issues_json=json.dumps(issues),
                project_name=name,
                comments_json="NOT VALID JSON {{{",
            )
        )
        # Should succeed despite invalid comments_json (falls back to {})
        assert result["status"] == "success"


# ── Multi-epic sync tests ────────────────────────────────────────────────────


class TestMultiEpicSync:
    """Tests for syncing multiple epics in a single full sync call."""

    def test_two_epics_create_separate_projects(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """Two epics with children create two separate projects with correct todos."""
        cfg, _name = cfg_with_project
        issues = [
            _make_epic_issue("EP-1", "Auth Epic"),
            _make_jira_issue("EP-10", "Login", parent=_make_epic_parent("EP-1", "Auth Epic")),
            _make_jira_issue("EP-11", "Logout", parent=_make_epic_parent("EP-1", "Auth Epic")),
            _make_epic_issue("EP-2", "Payment Epic"),
            _make_jira_issue("EP-20", "Checkout", parent=_make_epic_parent("EP-2", "Payment Epic")),
        ]
        data = compute_mapping(issues, cfg)
        # Force create_project=True for new epic projects
        groups_dicts = []
        for g in data.groups:
            d = g.to_dict()
            if not d.get("project_exists"):
                d["create_project"] = True
            groups_dicts.append(d)
        apply_input = JiraApplyInput(groups=groups_dicts)
        result = apply_mapping(apply_input, cfg)
        # Two new epic-based projects should be created
        assert result.counts["projects_created"] == 2
        # 3 child tasks total
        assert result.counts["todos_created"] == 3

    def test_multi_epic_idempotent_resync(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Re-syncing the same multi-epic set does not create duplicates."""
        cfg, _name = cfg_with_project
        issues = [
            _make_epic_issue("EP-1", "Auth Epic"),
            _make_jira_issue("EP-10", "Login", parent=_make_epic_parent("EP-1", "Auth Epic")),
            _make_epic_issue("EP-2", "Payment Epic"),
            _make_jira_issue("EP-20", "Checkout", parent=_make_epic_parent("EP-2", "Payment Epic")),
        ]
        # First sync -- create projects
        data1 = compute_mapping(issues, cfg)
        groups1 = []
        for g in data1.groups:
            d = g.to_dict()
            if not d.get("project_exists"):
                d["create_project"] = True
            groups1.append(d)
        r1 = apply_mapping(JiraApplyInput(groups=groups1), cfg)
        assert r1.counts["projects_created"] == 2

        # Second sync -- projects now exist, compute_mapping should find them
        data2 = compute_mapping(issues, cfg)
        groups2 = [g.to_dict() for g in data2.groups]
        r2 = apply_mapping(JiraApplyInput(groups=groups2), cfg)

        # No new projects or todos on resync
        assert r2.counts["projects_created"] == 0
        assert r2.counts["todos_created"] == 0


# ── Error visibility tests ────────────────────────────────────────────────────


class TestApplyMappingErrorLogging:
    """apply_mapping must log ERROR for project-creation and issue-apply failures."""

    def test_project_creation_failure_logs_error(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a storage write raises during project creation, ERROR is logged."""
        import logging

        cfg, _ = cfg_with_project

        # Patch storage.save_meta to blow up on first call (project creation)
        original_save_meta = storage.save_meta
        call_count = {"n": 0}

        def _failing_save_meta(c: object, m: object) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("disk full")
            return original_save_meta(c, m)  # type: ignore[arg-type]

        monkeypatch.setattr(storage, "save_meta", _failing_save_meta)

        group = {
            "jira_key": "EP-99",
            "suggested_project": "new-project",
            "create_project": True,
            "project_exists": False,
            "is_epic": True,
            "issues": [_make_jira_issue("EP-99", "Epic title")],
        }

        with caplog.at_level(logging.ERROR, logger="server.tools.jira_sync"):
            result = apply_mapping(JiraApplyInput(groups=[group]), cfg)

        assert any(r.levelno == logging.ERROR for r in caplog.records)
        # All issues in the failing group should be marked failed in per_issue
        assert result.per_issue.get("EP-99", "").startswith("failed")

    def test_issue_apply_failure_logs_error(
        self,
        cfg_with_project: tuple[ProjConfig, str],
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When saving todos raises during issue processing, ERROR is logged."""
        import logging

        cfg, project_name = cfg_with_project

        # Project exists already; patch save_todos to fail
        monkeypatch.setattr(
            storage,
            "save_todos",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        issue = _make_jira_issue("PROJ-1", "Do something")
        group = {
            "jira_key": None,
            "suggested_project": project_name,
            "create_project": False,
            "project_exists": True,
            "is_epic": False,
            "issues": [issue],
        }

        with caplog.at_level(logging.ERROR, logger="server.tools.jira_sync"):
            result = apply_mapping(JiraApplyInput(groups=[group]), cfg)

        assert any(r.levelno == logging.ERROR for r in caplog.records)
        assert result.per_issue.get("PROJ-1", "").startswith("failed")
