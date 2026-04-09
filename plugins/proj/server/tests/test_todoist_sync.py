"""Tests for todoist_sync tools (proj_todoist_diff and proj_todoist_apply)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    JsonValue,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
    Todo,
    TodoistSync,
)
from server.tools.todoist_full_sync import (
    ApplyInput,
    SyncPlan,
    _apply_description_sync,
    _content_differs,
    _ghost_check,
    _parse_todoist_due,
    _parse_todoist_labels,
    _parse_todoist_priority,
    _todoist_date,
    _ts_newer,
    apply_changes,
    compute_diff,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        todoist=TodoistSync(enabled=True),
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
        todoist_project_id="abc123",
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


def _make_todoist_task(
    task_id: str,
    content: str,
    priority: int = 4,
    updated_at: str = "2099-01-01T00:00:00Z",
    **kwargs: JsonValue,
) -> dict[str, JsonValue]:
    task: dict[str, JsonValue] = {
        "id": task_id,
        "content": content,
        "priority": priority,
        "description": "",
        "labels": [],
        "updatedAt": updated_at,
        "isCompleted": False,
    }
    task.update(kwargs)
    return task


# ── Unit tests for helpers ────────────────────────────────────────────────────


class TestHelpers:
    def test_todoist_date_full_datetime(self) -> None:
        assert _todoist_date("2026-03-07T12:34:56Z") == "2026-03-07T12:34:56"

    def test_todoist_date_empty(self) -> None:
        assert _todoist_date("") == ""

    def test_ghost_check_exact_match(self) -> None:
        archived = [Todo(id="1", title="Fix the bug")]
        assert _ghost_check("Fix the bug", archived) is True

    def test_ghost_check_case_insensitive(self) -> None:
        archived = [Todo(id="1", title="Fix the BUG")]
        assert _ghost_check("fix the bug", archived) is True

    def test_ghost_check_no_match(self) -> None:
        archived = [Todo(id="1", title="Completely different")]
        assert _ghost_check("Fix the bug", archived) is False

    def test_ghost_check_empty_archive(self) -> None:
        assert _ghost_check("anything", []) is False

    def test_ghost_check_fuzzy_match(self) -> None:
        archived = [Todo(id="1", title="Fix the bug in auth")]
        assert _ghost_check("Fix the bug in authentication", archived) is True

    def test_description_sync_unchanged(self) -> None:
        notes, synced = _apply_description_sync("existing notes", "old desc", "old desc")
        assert notes == "existing notes"
        assert synced == "old desc"

    def test_description_sync_new_to_empty(self) -> None:
        notes, synced = _apply_description_sync("", "", "new desc")
        assert notes == "new desc"
        assert synced == "new desc"

    def test_description_sync_append(self) -> None:
        notes, synced = _apply_description_sync("existing notes", "old desc", "new desc")
        assert notes == "existing notes\n\n---\nnew desc"
        assert synced == "new desc"

    def test_todoist_date_offset_format(self) -> None:
        assert _todoist_date("2026-03-07T12:00:00+00:00") == "2026-03-07T12:00:00"

    def test_ts_newer_true(self) -> None:
        assert _ts_newer("2026-03-08T00:00:00", "2026-03-07T00:00:00") is True

    def test_ts_newer_false(self) -> None:
        assert _ts_newer("2026-03-07T00:00:00", "2026-03-08T00:00:00") is False

    def test_ts_newer_fallback_on_bad_input(self) -> None:
        assert _ts_newer("zzz", "aaa") is True  # string comparison fallback

    @pytest.mark.parametrize(
        ("raw_priority", "expected"),
        [
            (4, "low"),
            (3, "medium"),
            (2, "high"),
            (1, "high"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
        ],
    )
    def test_parse_todoist_priority(self, raw_priority: object, expected: str) -> None:
        assert _parse_todoist_priority({"priority": raw_priority}) == expected

    def test_parse_todoist_priority_p_string(self) -> None:
        assert _parse_todoist_priority({"priority": "p3"}) == "medium"

    def test_parse_todoist_priority_missing(self) -> None:
        assert _parse_todoist_priority({}) == "low"

    def test_parse_todoist_labels(self) -> None:
        assert _parse_todoist_labels({"labels": ["bug", "urgent"]}) == ["bug", "urgent"]

    def test_parse_todoist_labels_missing(self) -> None:
        assert _parse_todoist_labels({}) == []

    def test_parse_todoist_due_present(self) -> None:
        assert _parse_todoist_due({"due": {"date": "2026-06-15"}}) == "2026-06-15"

    def test_parse_todoist_due_missing(self) -> None:
        assert _parse_todoist_due({}) is None

    def test_content_differs_identical(self) -> None:
        todo = Todo(id="1", title="Task", priority="low", tags=[], due_date=None)
        task = _make_todoist_task("t1", "Task", priority=4, labels=[], due=None)
        assert _content_differs(todo, task) is False

    def test_content_differs_title_changed(self) -> None:
        todo = Todo(id="1", title="Old title", priority="low")
        task = _make_todoist_task("t1", "New title", priority=4)
        assert _content_differs(todo, task) is True

    def test_content_differs_priority_changed(self) -> None:
        todo = Todo(id="1", title="Task", priority="high")
        task = _make_todoist_task("t1", "Task", priority=4)  # priority 4 → "low"
        assert _content_differs(todo, task) is True


# ── Standalone function tests ────────────────────────────────────────────────


class TestComputeDiff:
    def test_empty_both_sides(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff([], cfg, name)
        assert plan.is_empty()

    def test_new_todoist_task(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tasks = [_make_todoist_task("t1", "New task", priority=3)]
        plan = compute_diff(tasks, cfg, name)
        assert len(plan.pull_create) == 1
        assert plan.pull_create[0]["title"] == "New task"

    def test_unlinked_local_pushes(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local only")
        storage.save_todos(cfg, name, [todo])
        plan = compute_diff([], cfg, name)
        assert len(plan.push_create) == 1
        assert plan.push_create[0]["content"] == "Local only"

    def test_push_create_includes_project_id(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        """push_create entries include project_id when meta.todoist_project_id is set."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local todo with project")
        storage.save_todos(cfg, name, [todo])
        plan = compute_diff([], cfg, name)
        assert len(plan.push_create) == 1
        assert plan.push_create[0]["project_id"] == "abc123"

    def test_push_create_omits_project_id_when_unset(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """push_create entries omit project_id when meta.todoist_project_id is empty."""
        cfg, name = cfg_with_project
        # Clear todoist_project_id on the meta
        meta = storage.load_meta(cfg, name)
        meta.todoist_project_id = ""
        storage.save_meta(cfg, meta)

        todo = _make_todo(cfg, name, "Local todo no project")
        storage.save_todos(cfg, name, [todo])
        plan = compute_diff([], cfg, name)
        assert len(plan.push_create) == 1
        assert "project_id" not in plan.push_create[0]


class TestPotentialLinks:
    """Tests for potential_links detection (todo 373.5)."""

    def test_matching_titles_detected_as_potential_link(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Unlinked local todo + Todoist task with similar title → potential_links."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Implement user authentication")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Implement user authentication")]
        plan = compute_diff(tasks, cfg, name)

        assert len(plan.potential_links) == 1
        assert plan.potential_links[0]["local_todo"]["id"] == todo.id
        assert plan.potential_links[0]["todoist_task"]["id"] == "t1"
        assert plan.pull_create == []
        assert plan.push_create == []

    def test_dissimilar_titles_not_linked(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Unlinked local todo + Todoist task with dissimilar title → normal pull/push."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Implement user authentication")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Fix database migration script")]
        plan = compute_diff(tasks, cfg, name)

        assert plan.potential_links == []
        assert len(plan.pull_create) == 1
        assert len(plan.push_create) == 1


class TestTwoPhasePush:
    """Tests for two-phase push: roots first, then children (todo 374.6)."""

    def test_parent_in_phase1_child_in_phase2(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Unlinked parent → push_create; unlinked child → push_create_phase2."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent task")
        child = _make_todo(cfg, name, "Child task", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        plan = compute_diff([], cfg, name)

        # Parent should be in phase 1 (push_create) with no parentId
        assert len(plan.push_create) == 1
        assert plan.push_create[0]["content"] == "Parent task"
        assert "parentId" not in plan.push_create[0]

        # Child should be in phase 2 with _parent_local_id set
        assert len(plan.push_create_phase2) == 1
        assert plan.push_create_phase2[0]["content"] == "Child task"
        assert plan.push_create_phase2[0]["_parent_local_id"] == parent.id
        assert "parentId" not in plan.push_create_phase2[0]


class TestApplyChanges:
    def test_create_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = ApplyInput(
            created_locally=[
                {
                    "title": "New",
                    "todoist_task_id": "t1",
                    "tags": [],
                }
            ]
        )
        counts = apply_changes(data, cfg, name)
        assert counts["created"] == 1
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].title == "New"

    def test_link_ids(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Unlinked")
        storage.save_todos(cfg, name, [todo])
        data = ApplyInput(link_todoist_ids=[{"todo_id": todo.id, "todoist_task_id": "t99"}])
        counts = apply_changes(data, cfg, name)
        assert counts["linked"] == 1
        todos = storage.load_todos(cfg, name)
        assert todos[0].todoist_task_id == "t99"


class TestSyncPlan:
    def test_is_empty_true(self) -> None:
        plan = SyncPlan()
        assert plan.is_empty()

    def test_is_empty_false_pull(self) -> None:
        plan = SyncPlan(pull_create=[{"title": "x"}])
        assert not plan.is_empty()

    def test_to_dict_has_summary(self) -> None:
        plan = SyncPlan(push_create=[{"content": "x"}])
        d = plan.to_dict()
        summary = d["summary"]
        assert isinstance(summary, dict)
        assert summary["push_create_count"] == 1
        assert summary["pull_create_count"] == 0
