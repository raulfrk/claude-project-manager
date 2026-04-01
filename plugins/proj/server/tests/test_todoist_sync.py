"""Tests for todoist_sync tools (proj_todoist_diff and proj_todoist_apply)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    ProjectTodoistConfig,
    RepoEntry,
    Todo,
    TodoistSync,
)
from server.tools.todoist_full_sync import (
    ApplyInput,
    SyncPlan,
    _apply_description_sync,
    _ghost_check,
    _todoist_date,
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
    **kwargs: object,
) -> dict[str, object]:
    task: dict[str, object] = {
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
        assert _todoist_date("2026-03-07T12:34:56Z") == "2026-03-07"

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



# ── Standalone function tests ────────────────────────────────────────────────


class TestComputeDiff:
    def test_empty_both_sides(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff([], cfg, name)
        assert plan.is_empty()

    def test_new_todoist_task(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tasks = [_make_todoist_task("t1", "New task", priority=3)]
        plan = compute_diff(tasks, cfg, name)  # type: ignore[arg-type]
        assert len(plan.pull_create) == 1
        assert plan.pull_create[0]["title"] == "New task"

    def test_unlinked_local_pushes(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local only")
        storage.save_todos(cfg, name, [todo])
        plan = compute_diff([], cfg, name)
        assert len(plan.push_create) == 1
        assert plan.push_create[0]["content"] == "Local only"

    def test_push_create_includes_project_id(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """push_create entries include project_id when meta.todoist_project_id is set."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local todo with project")
        storage.save_todos(cfg, name, [todo])
        plan = compute_diff([], cfg, name)
        assert len(plan.push_create) == 1
        assert plan.push_create[0]["project_id"] == "abc123"

    def test_push_create_omits_project_id_when_unset(
        self, cfg_with_project: tuple[ProjConfig, str],
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

    def test_returns_sync_plan_type(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff([], cfg, name)
        assert isinstance(plan, SyncPlan)


class TestPotentialLinks:
    """Tests for potential_links detection (todo 373.5)."""

    def test_matching_titles_detected_as_potential_link(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Unlinked local todo + Todoist task with similar title → potential_links."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Implement user authentication")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Implement user authentication")]
        plan = compute_diff(tasks, cfg, name)  # type: ignore[arg-type]

        assert len(plan.potential_links) == 1
        assert plan.potential_links[0]["local_todo"]["id"] == todo.id
        assert plan.potential_links[0]["todoist_task"]["id"] == "t1"
        assert plan.pull_create == []
        assert plan.push_create == []

    def test_dissimilar_titles_not_linked(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Unlinked local todo + Todoist task with dissimilar title → normal pull/push."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Implement user authentication")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Fix database migration script")]
        plan = compute_diff(tasks, cfg, name)  # type: ignore[arg-type]

        assert plan.potential_links == []
        assert len(plan.pull_create) == 1
        assert len(plan.push_create) == 1


class TestTwoPhasePush:
    """Tests for two-phase push: roots first, then children (todo 374.6)."""

    def test_parent_in_phase1_child_in_phase2(
        self, cfg_with_project: tuple[ProjConfig, str],
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
        data = ApplyInput(created_locally=[{
            "title": "New",
            "todoist_task_id": "t1",
            "tags": [],
        }])
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

    def test_returns_counts_dict(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        data = ApplyInput()
        counts = apply_changes(data, cfg, name)
        assert isinstance(counts, dict)
        assert counts["created"] == 0


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
        assert d["summary"]["push_create_count"] == 1  # type: ignore[index]
        assert d["summary"]["pull_create_count"] == 0  # type: ignore[index]


