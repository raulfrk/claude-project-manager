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
from server.tools.todoist_sync import (
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


# ── Diff tool tests ──────────────────────────────────────────────────────────


class TestTodoistDiff:
    def test_empty_both_sides(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json="[]", project_name=name))  # type: ignore[operator]
        assert result["summary"]["pull_create_count"] == 0
        assert result["summary"]["push_create_count"] == 0

    def test_new_todoist_task_creates_pull(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tasks = [_make_todoist_task("t1", "New from Todoist", priority=3)]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["summary"]["pull_create_count"] == 1
        assert result["pull_create"][0]["title"] == "New from Todoist"
        assert result["pull_create"][0]["priority"] == "medium"
        assert result["pull_create"][0]["todoist_task_id"] == "t1"

    def test_ghost_detection(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        # Add an archived todo
        archived_todo = Todo(id="99", title="Old task", status="done")
        storage.save_archived_todos(cfg, name, [archived_todo])

        tasks = [_make_todoist_task("t1", "Old task")]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["summary"]["ghost_close_count"] == 1
        assert result["ghost_close"] == ["t1"]
        assert result["summary"]["pull_create_count"] == 0

    def test_todoist_newer_updates_local(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Old title", todoist_task_id="t1", updated="2020-01-01")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Updated title", priority=2, updated_at="2099-01-01T00:00:00Z")]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["summary"]["pull_update_count"] == 1
        assert result["pull_update"][0]["title"] == "Updated title"
        assert result["pull_update"][0]["priority"] == "high"

    def test_local_newer_pushes_update(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local title", todoist_task_id="t1", updated="2099-12-31")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Todoist title", updated_at="2020-01-01T00:00:00Z")]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["summary"]["push_update_count"] == 1
        assert result["push_update"][0]["content"] == "Local title"

    def test_unlinked_local_todo_pushes_create(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "New local todo")
        storage.save_todos(cfg, name, [todo])

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json="[]", project_name=name))  # type: ignore[operator]
        assert result["summary"]["push_create_count"] == 1
        assert result["push_create"][0]["content"] == "New local todo"

    def test_missing_from_todoist_completes_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Was in Todoist", todoist_task_id="t_gone")
        storage.save_todos(cfg, name, [todo])

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json="[]", project_name=name))  # type: ignore[operator]
        assert result["summary"]["pull_complete_count"] == 1
        assert result["pull_complete"] == [todo.id]

    def test_local_done_todoist_open_pushes_complete(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Done locally", todoist_task_id="t1", status="done", updated="2020-01-01")
        storage.save_todos(cfg, name, [todo])

        tasks = [_make_todoist_task("t1", "Done locally", updated_at="2020-01-01T00:00:00Z")]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["summary"]["push_complete_count"] == 1
        assert result["push_complete"] == ["t1"]

    def test_invalid_json_returns_error(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = diff(todoist_tasks_json="not json", project_name=name)  # type: ignore[operator]
        assert "Invalid JSON" in result

    def test_due_date_pulled_from_todoist(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        tasks = [_make_todoist_task("t1", "Task with due", due={"date": "2026-06-15", "string": "Jun 15"})]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["pull_create"][0]["due_date"] == "2026-06-15"

    def test_root_only_cleanup(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        # Set root_only on project
        meta = storage.load_meta(cfg, name)
        meta.todoist = ProjectTodoistConfig(root_only=True)
        storage.save_meta(cfg, meta)

        # Local child todo linked to Todoist
        parent = _make_todo(cfg, name, "Parent", todoist_task_id="tp")
        child = _make_todo(cfg, name, "Child", todoist_task_id="tc", parent=parent.id)
        storage.save_todos(cfg, name, [parent, child])

        tasks = [
            _make_todoist_task("tp", "Parent"),
            _make_todoist_task("tc", "Child", parentId="tp"),
        ]

        from server.tools.todoist_sync import register
        from unittest.mock import MagicMock
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        diff = tools["proj_todoist_diff"]
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), project_name=name))  # type: ignore[operator]
        assert result["summary"]["root_only_cleanup_count"] == 1
        assert result["root_only_cleanup"][0]["todoist_task_id"] == "tc"


# ── Apply tool tests ─────────────────────────────────────────────────────────


class TestTodoistApply:
    def _get_apply_fn(self):  # noqa: ANN202
        from unittest.mock import MagicMock

        from server.tools.todoist_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools["proj_todoist_apply"]

    def test_create_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [{
                "title": "From Todoist",
                "priority": "high",
                "tags": ["sync"],
                "notes": "desc",
                "due_date": "2026-06-15",
                "todoist_task_id": "t1",
                "todoist_description_synced": "desc",
            }],
            "updated_locally": [],
            "completed_locally": [],
            "link_todoist_ids": [],
            "cleared_todoist_ids": [],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["created"] == 1

        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].title == "From Todoist"
        assert todos[0].todoist_task_id == "t1"
        assert todos[0].priority == "high"
        assert todos[0].due_date == "2026-06-15"
        assert todos[0].todoist_description_synced == "desc"

    def test_update_locally(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Old title", todoist_task_id="t1")
        storage.save_todos(cfg, name, [todo])

        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [],
            "updated_locally": [{
                "todo_id": todo.id,
                "title": "New title",
                "priority": "high",
                "tags": ["updated"],
                "notes": "new notes",
                "todoist_description_synced": "new notes",
            }],
            "completed_locally": [],
            "link_todoist_ids": [],
            "cleared_todoist_ids": [],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["updated"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].title == "New title"
        assert todos[0].priority == "high"

    def test_complete_locally_leaf(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "To complete", todoist_task_id="t1")
        storage.save_todos(cfg, name, [todo])

        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [],
            "updated_locally": [],
            "completed_locally": [todo.id],
            "link_todoist_ids": [],
            "cleared_todoist_ids": [],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["completed"] == 1

        # Leaf todo should be archived
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0
        archived = storage.load_archived_todos(cfg, name)
        assert len(archived) == 1
        assert archived[0].status == "done"

    def test_link_todoist_ids(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Pushed to Todoist")
        storage.save_todos(cfg, name, [todo])

        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [],
            "updated_locally": [],
            "completed_locally": [],
            "link_todoist_ids": [{"todo_id": todo.id, "todoist_task_id": "new_t_id"}],
            "cleared_todoist_ids": [],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["linked"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].todoist_task_id == "new_t_id"

    def test_clear_todoist_ids(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Child", todoist_task_id="tc")
        storage.save_todos(cfg, name, [todo])

        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [],
            "updated_locally": [],
            "completed_locally": [],
            "link_todoist_ids": [],
            "cleared_todoist_ids": [todo.id],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["cleared"] == 1

        todos = storage.load_todos(cfg, name)
        assert todos[0].todoist_task_id is None

    def test_invalid_json_returns_error(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        apply_fn = self._get_apply_fn()
        result = apply_fn(apply_json="not json", project_name=name)  # type: ignore[operator]
        assert "Invalid JSON" in result

    def test_combined_operations(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Test creating, updating, linking, and completing in one call."""
        cfg, name = cfg_with_project
        existing = _make_todo(cfg, name, "Existing", todoist_task_id="t_existing")
        to_link = _make_todo(cfg, name, "To link")
        to_complete = _make_todo(cfg, name, "To complete")
        storage.save_todos(cfg, name, [existing, to_link, to_complete])

        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [{"title": "Brand new", "todoist_task_id": "t_new"}],
            "updated_locally": [{"todo_id": existing.id, "title": "Updated existing"}],
            "completed_locally": [to_complete.id],
            "link_todoist_ids": [{"todo_id": to_link.id, "todoist_task_id": "t_linked"}],
            "cleared_todoist_ids": [],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["created"] == 1
        assert result["counts"]["updated"] == 1
        assert result["counts"]["completed"] == 1
        assert result["counts"]["linked"] == 1

    def test_complete_child_stays_active(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        """Child todo marked done stays in active list (archives with parent)."""
        cfg, name = cfg_with_project
        parent = _make_todo(cfg, name, "Parent")
        child = _make_todo(cfg, name, "Child", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        apply_fn = self._get_apply_fn()
        data = {
            "created_locally": [],
            "updated_locally": [],
            "completed_locally": [child.id],
            "link_todoist_ids": [],
            "cleared_todoist_ids": [],
        }
        result = json.loads(apply_fn(apply_json=json.dumps(data), project_name=name))  # type: ignore[operator]
        assert result["counts"]["completed"] == 1

        # Child with parent is NOT archived, just marked done
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 2
        child_todo = next(t for t in todos if t.id == child.id)
        assert child_todo.status == "done"


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

    def test_returns_sync_plan_type(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        plan = compute_diff([], cfg, name)
        assert isinstance(plan, SyncPlan)


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


# ── Auto-apply tests ─────────────────────────────────────────────────────────


class TestAutoApply:
    def _get_diff_fn(self):  # noqa: ANN202
        from unittest.mock import MagicMock

        from server.tools.todoist_sync import register
        app = MagicMock()
        tools: dict[str, object] = {}
        app.tool = lambda **kw: lambda fn: tools.update({fn.__name__: fn}) or fn
        register(app)
        return tools["proj_todoist_diff"]

    def test_auto_apply_false_returns_plan_only(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json="[]", auto_apply=False, project_name=name))  # type: ignore[operator]
        # Old format: plan at top level with summary
        assert "summary" in result
        assert "auto_applied" not in result

    def test_auto_apply_true_returns_project_info(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json="[]", auto_apply=True, project_name=name))  # type: ignore[operator]
        assert "project_info" in result
        assert result["project_info"]["todoist_project_id"] == "abc123"
        assert "auto_applied" in result

    def test_auto_apply_empty_no_side_effects(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json="[]", auto_apply=True, project_name=name))  # type: ignore[operator]
        assert result["auto_applied"]["created"] == 0
        assert result["plan"]["summary"]["pull_create_count"] == 0
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 0

    def test_auto_apply_creates_pulled_todos(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        tasks = [_make_todoist_task("t1", "From Todoist", priority=2)]
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), auto_apply=True, project_name=name))  # type: ignore[operator]
        assert result["auto_applied"]["created"] == 1
        # Verify local todo was actually created
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].title == "From Todoist"
        assert todos[0].todoist_task_id == "t1"

    def test_auto_apply_completes_pulled_todos(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        # Local todo linked to Todoist, but Todoist task is gone
        todo = _make_todo(cfg, name, "Was in Todoist", todoist_task_id="t_gone")
        storage.save_todos(cfg, name, [todo])
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json="[]", auto_apply=True, project_name=name))  # type: ignore[operator]
        assert result["auto_applied"]["completed"] == 1

    def test_auto_apply_preserves_push_operations(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Push operations should NOT be applied locally — they go to Todoist."""
        cfg, name = cfg_with_project
        todo = _make_todo(cfg, name, "Local only")
        storage.save_todos(cfg, name, [todo])
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json="[]", auto_apply=True, project_name=name))  # type: ignore[operator]
        # Push create should be in the plan for the LLM to execute
        assert result["plan"]["summary"]["push_create_count"] == 1
        # But no auto-apply of push operations
        assert result["auto_applied"]["linked"] == 0

    def test_auto_apply_mixed_pull_and_push(
        self, cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        # Local unlinked todo (push) + new Todoist task (pull)
        todo = _make_todo(cfg, name, "Local todo")
        storage.save_todos(cfg, name, [todo])
        tasks = [_make_todoist_task("t1", "Todoist todo")]
        diff = self._get_diff_fn()
        result = json.loads(diff(todoist_tasks_json=json.dumps(tasks), auto_apply=True, project_name=name))  # type: ignore[operator]
        # Pull was auto-applied
        assert result["auto_applied"]["created"] == 1
        # Push is still in the plan
        assert result["plan"]["summary"]["push_create_count"] == 1
        # Local state has both: the original + the pulled one
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 2
