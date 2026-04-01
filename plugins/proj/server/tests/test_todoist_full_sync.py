"""Tests for todoist_full_sync tool (proj_todoist_full_sync)."""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import httpx
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
from server.tools.todoist_full_sync import register as register_full_sync


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


# ── Full-sync tool tests ─────────────────────────────────────────────────────


class TestProjTodoistFullSync:
    """Tests for the proj_todoist_full_sync tool."""

    def _register_and_call(self, **kwargs):
        """Register the tool and call it via the captured function."""
        captured = {}

        class FakeApp:
            def tool(self, **deco_kwargs):
                def decorator(fn):
                    captured["fn"] = fn
                    return fn
                return decorator

        fake = FakeApp()
        register_full_sync(fake)
        return captured["fn"](**kwargs)

    # 1. test_full_success ─────────────────────────────────────────────────────

    def test_full_success(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Diff returns push+pull ops, all execute, returns status: success with correct summary counts."""
        cfg, name = cfg_with_project

        # Create a local unlinked todo (will push_create)
        todo = _make_todo(cfg, name, "Local task")
        storage.save_todos(cfg, name, [todo])

        # Todoist has one new task (will pull_create)
        todoist_tasks = [_make_todoist_task("t1", "Remote task", priority=2)]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            if tool_name == "todoist_add_tasks":
                # Return created tasks with IDs
                return [{"id": f"created_{i}"} for i in range(len(params.get("tasks", [])))]
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert "summary" in result
        assert result["summary"]["pull"]["created"] == 1
        assert result["summary"]["push"]["tasks_created"] == 1

    # 2. test_partial_failure ──────────────────────────────────────────────────

    def test_partial_failure(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One push op fails, others succeed; returns partial_success with retry_token and errors."""
        cfg, name = cfg_with_project

        # Two local unlinked todos — one will succeed, one will fail
        todo1 = _make_todo(cfg, name, "Will succeed")
        todo2 = _make_todo(cfg, name, "Will fail", status="done", todoist_task_id="t_done")
        storage.save_todos(cfg, name, [todo1, todo2])

        # Todoist has the done task still open
        todoist_tasks = [_make_todoist_task("t_done", "Will fail")]

        call_count = {"n": 0}

        def mock_call(tool_name, params):
            call_count["n"] += 1
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            if tool_name == "todoist_add_tasks":
                return [{"id": "created_1"}]
            if tool_name == "todoist_complete_tasks":
                raise ConnectionError("Todoist API timeout")
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "partial_success"
        assert "errors" in result
        assert "retry_token" in result
        assert any(e["operation_type"] == "push_complete" for e in result["errors"])

    # 3. test_retry ────────────────────────────────────────────────────────────

    def test_retry(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retry_failures token re-executes only failed ops (fetch NOT re-called)."""
        failed_ops = [
            {
                "operation_type": "push_complete",
                "error": "timeout",
                "retryable": True,
                "retry_payload": {"ids": ["t_done"]},
            }
        ]
        token = base64.b64encode(json.dumps(failed_ops).encode()).decode()

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(retry_failures=token)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["retried_succeeded"] == 1
        # Only the retry call — no todoist_find_tasks fetch
        assert len(call_log) == 1
        assert call_log[0][0] == "todoist_complete_tasks"

    # 4. test_up_to_date ───────────────────────────────────────────────────────

    def test_up_to_date(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty diff; returns status: success, up_to_date: true without socket calls."""
        cfg, name = cfg_with_project

        # No local todos, Todoist returns empty
        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return []
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["up_to_date"] is True
        # Should have called todoist_find_tasks since project has todoist_project_id
        # but no push/pull operations
        assert all(t[0] == "todoist_find_tasks" for t in call_log)

    # 5. test_needs_confirmation ───────────────────────────────────────────────

    def test_needs_confirmation(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Diff returns potential_links; first call -> needs_confirmation; second with confirmed_links -> success."""
        cfg, name = cfg_with_project

        # Create a local todo with same title as todoist task -> potential_links
        todo = _make_todo(cfg, name, "Implement user authentication")
        storage.save_todos(cfg, name, [todo])

        todoist_tasks = [_make_todoist_task("t1", "Implement user authentication")]

        def mock_call(tool_name, params):
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        # First call: should return needs_confirmation
        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "needs_confirmation"
        assert len(result["potential_links"]) == 1

        # Second call: confirm the link
        confirmed = json.dumps([{"todo_id": todo.id, "todoist_task_id": "t1"}])
        result_str = self._register_and_call(
            project_name=name, confirmed_links=confirmed
        )
        result = json.loads(result_str)

        assert result["status"] == "success"

    # 6. test_socket_unavailable ───────────────────────────────────────────────

    def test_socket_unavailable(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_call_todoist_tool raises httpx.ConnectError; returns status: error."""
        cfg, name = cfg_with_project

        # Need at least local todos or todoist_project_id to trigger socket call
        # (project already has todoist_project_id="abc123")

        def mock_call(tool_name, params):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "error"
        assert "unavailable" in result["error"].lower()

    # 7. test_phase2_child_create ──────────────────────────────────────────────

    def test_phase2_child_create(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """push_create_phase2 children get correct parentId from phase-1 results."""
        cfg, name = cfg_with_project

        parent = _make_todo(cfg, name, "Parent task")
        child = _make_todo(cfg, name, "Child task", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return []
            if tool_name == "todoist_add_tasks":
                tasks = params.get("tasks", [])
                return [{"id": f"todoist_{i}"} for i in range(len(tasks))]
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["push"]["tasks_created"] == 1
        assert result["summary"]["push"]["tasks_created_phase2"] == 1

        # Verify the phase-2 call included parentId from phase-1
        add_calls = [(t, p) for t, p in call_log if t == "todoist_add_tasks"]
        assert len(add_calls) == 2  # phase-1 and phase-2
        phase2_tasks = add_calls[1][1]["tasks"]
        assert phase2_tasks[0]["parentId"] == "todoist_0"

    # 8. test_root_only_suppression ────────────────────────────────────────────

    def test_root_only_suppression(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """root_only config suppresses child push_create."""
        cfg, name = cfg_with_project

        # Set root_only on project
        meta = storage.load_meta(cfg, name)
        meta.todoist = ProjectTodoistConfig(root_only=True)
        storage.save_meta(cfg, meta)

        # Create parent with linked todoist ID, and child also linked
        parent = _make_todo(cfg, name, "Parent", todoist_task_id="tp")
        child = _make_todo(cfg, name, "Child", todoist_task_id="tc", parent=parent.id)
        parent.children.append(child.id)
        storage.save_todos(cfg, name, [parent, child])

        todoist_tasks = [
            _make_todoist_task("tp", "Parent"),
            _make_todoist_task("tc", "Child", parentId="tp"),
        ]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            if tool_name == "todoist_delete":
                return {}
            return {}

        monkeypatch.setattr(
            "server.tools.todoist_full_sync._call_todoist_tool", mock_call
        )

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["push"]["root_only_cleaned"] == 1
        # Verify todoist_delete was called for the child task
        delete_calls = [(t, p) for t, p in call_log if t == "todoist_delete"]
        assert len(delete_calls) == 1
        assert delete_calls[0][1]["id"] == "tc"
