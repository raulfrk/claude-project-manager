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
from server.tools.todoist_full_sync import (
    ApplyInput,
    _compute_todoist_depth,
    _infer_parent_link_from_children,
    _migrate_parent_links,
    apply_changes,
    compute_diff,
)
from server.tools.todoist_full_sync import (
    register as register_full_sync,
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
        "updated_at": updated_at,
        "is_completed": False,
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

    def test_full_success(self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
        """Diff returns push+pull ops, all execute, returns
        status: success with correct summary counts."""
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

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

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
        """One push op fails, others succeed; returns
        partial_success with retry_token and errors."""
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

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "partial_success"
        assert "errors" in result
        assert "retry_token" in result
        assert any(e["operation_type"] == "push_complete" for e in result["errors"])

    # 3. test_retry ────────────────────────────────────────────────────────────

    def test_retry(self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
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

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = self._register_and_call(retry_failures=token)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["retried_succeeded"] == 1
        # Only the retry call — no todoist_find_tasks fetch
        assert len(call_log) == 1
        assert call_log[0][0] == "todoist_complete_tasks"

    # 4. test_up_to_date ───────────────────────────────────────────────────────

    def test_up_to_date(self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty diff; returns status: success, up_to_date: true without socket calls."""
        _cfg, name = cfg_with_project

        # No local todos, Todoist returns empty
        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return []
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

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
        """Diff returns potential_links; first call ->
        needs_confirmation; second with confirmed_links -> success."""
        cfg, name = cfg_with_project

        # Create a local todo with same title as todoist task -> potential_links
        todo = _make_todo(cfg, name, "Implement user authentication")
        storage.save_todos(cfg, name, [todo])

        todoist_tasks = [_make_todoist_task("t1", "Implement user authentication")]

        def mock_call(tool_name, params):
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        # First call: should return needs_confirmation
        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "needs_confirmation"
        assert len(result["potential_links"]) == 1

        # Second call: confirm the link
        confirmed = json.dumps([{"todo_id": todo.id, "todoist_task_id": "t1"}])
        result_str = self._register_and_call(project_name=name, confirmed_links=confirmed)
        result = json.loads(result_str)

        assert result["status"] == "success"

    # 6. test_socket_unavailable ───────────────────────────────────────────────

    def test_socket_unavailable(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_call_todoist_tool raises httpx.ConnectError; returns status: error."""
        _cfg, name = cfg_with_project

        # Need at least local todos or todoist_project_id to trigger socket call
        # (project already has todoist_project_id="abc123")

        def mock_call(tool_name, params):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

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

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["push"]["tasks_created"] == 1
        assert result["summary"]["push"]["tasks_created_phase2"] == 1

        # Verify the phase-2 call included parentId from phase-1
        add_calls = [(t, p) for t, p in call_log if t == "todoist_add_tasks"]
        assert len(add_calls) == 2  # phase-1 and phase-2
        phase2_tasks = add_calls[1][1]["tasks"]
        assert phase2_tasks[0]["parent_id"] == "todoist_0"

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
            _make_todoist_task("tc", "Child", parent_id="tp"),
        ]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            if tool_name == "todoist_delete":
                return {}
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["push"]["root_only_cleaned"] == 1
        # Verify todoist_delete was called for the child task
        delete_calls = [(t, p) for t, p in call_log if t == "todoist_delete"]
        assert len(delete_calls) == 1
        assert delete_calls[0][1]["id"] == "tc"

    # 9. test_dedup_successful_create_no_dup ───────────────────────────────

    def test_dedup_successful_create_no_dup(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Task created normally; retry is a no-op because dedup finds existing ID."""
        cfg, name = cfg_with_project

        todo = _make_todo(cfg, name, "Dedup task", todoist_task_id="")
        storage.save_todos(cfg, name, [todo])

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                if any(c[0] == "todoist_add_tasks" for c in call_log):
                    # After the first create, return the task as existing
                    return [{"id": "created_1", "content": "Dedup task"}]
                return []
            if tool_name == "todoist_add_tasks":
                return [{"id": "created_1"}]
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        # First call creates the task
        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)
        assert result["status"] == "success"

        # Now simulate a retry where the dedup guard finds the task
        failed_ops = [
            {
                "operation_type": "push_create",
                "error": "timeout",
                "retryable": True,
                "retry_payload": {
                    "content": "Dedup task",
                    "project_id": "abc123",
                    "todo_id": todo.id,
                },
            }
        ]
        token = base64.b64encode(json.dumps(failed_ops).encode()).decode()

        result_str = self._register_and_call(retry_failures=token)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["retried_succeeded"] == 1
        # todoist_find_tasks was called for dedup lookup, NOT todoist_add_tasks again
        retry_calls = [(t, p) for t, p in call_log if t == "todoist_add_tasks"]
        # Only the first create call, no second add_tasks during retry
        assert len(retry_calls) == 1

    # 10. test_dedup_truncated_response_finds_existing ─────────────────────

    def test_dedup_truncated_response_finds_existing(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """todoist_add_tasks returns empty ID;
        _find_existing_todoist_task returns a match; result is success."""
        cfg, name = cfg_with_project

        todo = _make_todo(cfg, name, "Truncated task")
        storage.save_todos(cfg, name, [todo])

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                # If this is a dedup lookup (not the initial fetch), return the task
                if any(c[0] == "todoist_add_tasks" for c in call_log):
                    return [{"id": "recovered_1", "content": "Truncated task"}]
                return []  # initial fetch: no remote tasks
            if tool_name == "todoist_add_tasks":
                # Return empty ID — simulates truncated response
                return [{"id": ""}]
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = self._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        # The task was recovered via dedup lookup, not an error
        assert result["summary"]["push"]["tasks_created"] == 1
        # Verify _find_existing_todoist_task was called (a second todoist_find_tasks call)
        find_calls = [(t, p) for t, p in call_log if t == "todoist_find_tasks"]
        assert len(find_calls) >= 2  # initial fetch + dedup lookup

    # 11. test_dedup_genuine_failure_retries_correctly ─────────────────────

    def test_dedup_genuine_failure_retries_correctly(
        self, cfg_with_project: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Task not found via dedup; retry creates correctly."""
        failed_ops = [
            {
                "operation_type": "push_create",
                "error": "timeout",
                "retryable": True,
                "retry_payload": {
                    "content": "Genuinely new",
                    "project_id": "abc123",
                    "todo_id": "t1",
                },
            }
        ]
        token = base64.b64encode(json.dumps(failed_ops).encode()).decode()

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return []  # dedup finds nothing
            if tool_name == "todoist_add_tasks":
                return [{"id": "new_created_1"}]
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = self._register_and_call(retry_failures=token)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["retried_succeeded"] == 1
        # Dedup lookup called, then add_tasks called because nothing found
        find_calls = [t for t, _ in call_log if t == "todoist_find_tasks"]
        add_calls = [t for t, _ in call_log if t == "todoist_add_tasks"]
        assert len(find_calls) == 1
        assert len(add_calls) == 1


# ── Migration tests (399.3) ──────────────────────────────────────────────────


class TestMigrateParentLinks:
    """Tests for _migrate_parent_links() idempotency and correctness."""

    def _make_local_todo(
        self, todo_id: str, parent: str | None = None, todoist_task_id: str | None = None
    ) -> Todo:
        return Todo(
            id=todo_id,
            title=f"Todo {todo_id}",
            parent=parent,
            todoist_task_id=todoist_task_id,
        )

    def test_migrates_missing_parent_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Child with todoist_task_id, parent with todoist_task_id,
        Todoist task has no parentId -> update called."""
        parent = self._make_local_todo("100", todoist_task_id="tid_parent")
        child = self._make_local_todo("100.1", parent="100", todoist_task_id="tid_child")

        todoist_tasks = [
            {"id": "tid_parent", "parent_id": None},
            {"id": "tid_child", "parent_id": None},  # Missing parent link
        ]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result = _migrate_parent_links([parent, child], todoist_tasks)

        assert result["migrated"] == 1
        assert result["already_correct"] == 0
        assert result["skipped_unlinked"] == 0
        # Verify the update was called with correct parentId
        assert len(call_log) == 1
        assert call_log[0][0] == "todoist_update_tasks"
        tasks_arg = call_log[0][1]["tasks"]
        assert isinstance(tasks_arg, str)  # JSON-encoded
        import json as _json

        updates = _json.loads(tasks_arg)
        assert updates == [{"id": "tid_child", "parent_id": "tid_parent"}]

    def test_already_correct_no_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Child already has correct parentId in Todoist → no update call."""
        parent = self._make_local_todo("100", todoist_task_id="tid_parent")
        child = self._make_local_todo("100.1", parent="100", todoist_task_id="tid_child")

        todoist_tasks = [
            {"id": "tid_parent", "parent_id": None},
            {"id": "tid_child", "parent_id": "tid_parent"},  # Already correct
        ]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result = _migrate_parent_links([parent, child], todoist_tasks)

        assert result["migrated"] == 0
        assert result["already_correct"] == 1
        assert result["skipped_unlinked"] == 0
        assert len(call_log) == 0  # No update call

    def test_skips_unlinked_parent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parent has no todoist_task_id → skipped_unlinked."""
        parent = self._make_local_todo("100", todoist_task_id=None)  # No Todoist link
        child = self._make_local_todo("100.1", parent="100", todoist_task_id="tid_child")

        todoist_tasks = [
            {"id": "tid_child", "parent_id": None},
        ]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result = _migrate_parent_links([parent, child], todoist_tasks)

        assert result["migrated"] == 0
        assert result["already_correct"] == 0
        assert result["skipped_unlinked"] == 1
        assert len(call_log) == 0

    def test_skips_root_todos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Todos without a parent are silently skipped."""
        root = self._make_local_todo("100", todoist_task_id="tid_root")

        todoist_tasks = [{"id": "tid_root", "parent_id": None}]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result = _migrate_parent_links([root], todoist_tasks)

        assert result == {"migrated": 0, "already_correct": 0, "skipped_unlinked": 0}
        assert len(call_log) == 0


# ── Post-execution linkage fix tests (399.2) ─────────────────────────────────


class TestPostExecutionLinkageFix:
    """Tests for the post-execution re-parenting pass after combined_id_map is built."""

    def test_reparents_child_after_parent_created_in_sync(
        self,
        cfg_with_project: tuple,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pre-existing child gets re-parented when parent was just created in the same sync."""
        cfg, name = cfg_with_project

        # Parent todo (unlinked — will be created in this sync)
        parent_todo = _make_todo(cfg, name, "Parent task")
        # Child todo (already linked to Todoist, but Todoist task has no parentId)
        child_todo = _make_todo(
            cfg, name, "Child task", parent=parent_todo.id, todoist_task_id="existing_child_tid"
        )
        storage.save_todos(cfg, name, [parent_todo, child_todo])

        # Todoist state: only the child exists (parent not yet created)
        todoist_tasks = [
            _make_todoist_task("existing_child_tid", "Child task", parent_id=None),
        ]

        call_log = []

        def mock_call(tool_name, params):
            call_log.append((tool_name, params))
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            if tool_name == "todoist_add_tasks":
                # Parent gets created → returns new ID
                return [{"id": "new_parent_tid"}]
            if tool_name == "todoist_update_tasks":
                return {}
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = TestProjTodoistFullSync()._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] in ("success", "partial_success")

        # Verify that an update call was made to set parentId on the child
        update_calls = [(t, p) for t, p in call_log if t == "todoist_update_tasks"]
        reparent_found = False
        for _, params in update_calls:
            tasks = params.get("tasks", [])
            if isinstance(tasks, str):
                tasks = json.loads(tasks)
            for task in tasks:
                if (
                    task.get("id") == "existing_child_tid"
                    and task.get("parent_id") == "new_parent_tid"
                ):
                    reparent_found = True
        assert reparent_found, (
            f"Expected re-parent update for existing_child_tid → new_parent_tid. "
            f"Update calls: {update_calls}"
        )


# ── _infer_parent_link_from_children unit tests ──────────────────────────────


def _make_local_todo(
    todo_id: str, title: str, todoist_id: str | None = None, parent: str | None = None
) -> Todo:
    today = str(date.today())
    t = Todo(id=todo_id, title=title, created=today, updated=today)
    t.todoist_task_id = todoist_id
    t.parent = parent
    return t


def _make_task(task_id: str, content: str, parent_id: str | None = None) -> dict:
    task: dict = {"id": task_id, "content": content, "priority": 4, "labels": [], "description": ""}
    if parent_id:
        task["parent_id"] = parent_id
    return task


class TestInferParentLinkFromChildren:
    def _build_maps(self, todos: list[Todo]) -> tuple[dict, dict]:
        local_by_todoist_id = {t.todoist_task_id: t for t in todos if t.todoist_task_id}
        local_by_id = {t.id: t for t in todos}
        return local_by_todoist_id, local_by_id

    def test_single_child_linked_to_local_parent(self):
        """1 Todoist child linked to a local child whose parent is L-P → returns L-P."""
        parent_todo = _make_local_todo("lp", "Parent", todoist_id="tp-a")
        child_todo = _make_local_todo("lc", "Child", todoist_id="tc", parent="lp")
        todos = [parent_todo, child_todo]
        todoist_by_id = {
            "tp-b": _make_task("tp-b", "Parent"),  # unlinked duplicate
            "tc": _make_task("tc", "Child", parent_id="tp-b"),
        }
        local_by_todoist_id, local_by_id = self._build_maps(todos)

        result = _infer_parent_link_from_children(
            "tp-b", todoist_by_id, local_by_todoist_id, local_by_id
        )
        assert result is not None
        assert result.id == "lp"

    def test_multiple_children_same_parent(self):
        """2 children both linked to children of L-P → returns L-P."""
        parent_todo = _make_local_todo("lp", "Parent", todoist_id="tp-a")
        child1 = _make_local_todo("lc1", "Child 1", todoist_id="tc1", parent="lp")
        child2 = _make_local_todo("lc2", "Child 2", todoist_id="tc2", parent="lp")
        todos = [parent_todo, child1, child2]
        todoist_by_id = {
            "tp-b": _make_task("tp-b", "Parent"),
            "tc1": _make_task("tc1", "Child 1", parent_id="tp-b"),
            "tc2": _make_task("tc2", "Child 2", parent_id="tp-b"),
        }
        local_by_todoist_id, local_by_id = self._build_maps(todos)

        result = _infer_parent_link_from_children(
            "tp-b", todoist_by_id, local_by_todoist_id, local_by_id
        )
        assert result is not None
        assert result.id == "lp"

    def test_children_different_parents_returns_none(self):
        """Children point to different local parents → returns None."""
        parent1 = _make_local_todo("lp1", "Parent 1", todoist_id="tp1")
        parent2 = _make_local_todo("lp2", "Parent 2", todoist_id="tp2")
        child1 = _make_local_todo("lc1", "Child 1", todoist_id="tc1", parent="lp1")
        child2 = _make_local_todo("lc2", "Child 2", todoist_id="tc2", parent="lp2")
        todos = [parent1, parent2, child1, child2]
        todoist_by_id = {
            "tp-b": _make_task("tp-b", "Whatever"),
            "tc1": _make_task("tc1", "Child 1", parent_id="tp-b"),
            "tc2": _make_task("tc2", "Child 2", parent_id="tp-b"),
        }
        local_by_todoist_id, local_by_id = self._build_maps(todos)

        result = _infer_parent_link_from_children(
            "tp-b", todoist_by_id, local_by_todoist_id, local_by_id
        )
        assert result is None

    def test_no_linked_children_returns_none(self):
        """Todoist children exist but none are linked locally → returns None."""
        todoist_by_id = {
            "tp-b": _make_task("tp-b", "Parent"),
            "tc": _make_task("tc", "Child", parent_id="tp-b"),
        }
        # tc is not in local_by_todoist_id
        local_by_todoist_id: dict = {}
        local_by_id: dict = {}

        result = _infer_parent_link_from_children(
            "tp-b", todoist_by_id, local_by_todoist_id, local_by_id
        )
        assert result is None

    def test_no_children_at_all_returns_none(self):
        """Todoist task has no children → returns None immediately."""
        todoist_by_id = {"tp-b": _make_task("tp-b", "Parent")}
        result = _infer_parent_link_from_children("tp-b", todoist_by_id, {}, {})
        assert result is None

    def test_child_no_local_parent_returns_none(self):
        """Linked child has parent=None → no parent to infer → returns None."""
        child_todo = _make_local_todo("lc", "Child", todoist_id="tc", parent=None)
        todos = [child_todo]
        todoist_by_id = {
            "tp-b": _make_task("tp-b", "Parent"),
            "tc": _make_task("tc", "Child", parent_id="tp-b"),
        }
        local_by_todoist_id, local_by_id = self._build_maps(todos)

        result = _infer_parent_link_from_children(
            "tp-b", todoist_by_id, local_by_todoist_id, local_by_id
        )
        assert result is None


class TestComputeDiffChildInference:
    """Integration tests for child-based parent inference in compute_diff."""

    def test_child_inference_prevents_duplicate_pull(self, cfg_with_project: tuple):
        """The exact incident scenario: local parent already linked to task A,
        Todoist task B (same title, children linked to local children of parent)
        → B goes to potential_links, NOT pull_create."""
        cfg, name = cfg_with_project
        today = str(date.today())

        # Local state: parent (linked to task-a), two children (linked to tc1, tc2)
        parent_todo = Todo(id="1", title="sandbox-perms skill", created=today, updated=today)
        parent_todo.todoist_task_id = "task-a"
        child1 = Todo(id="1.1", title="Manual test 1", created=today, updated=today)
        child1.todoist_task_id = "tc1"
        child1.parent = "1"
        child2 = Todo(id="1.2", title="Manual test 2", created=today, updated=today)
        child2.todoist_task_id = "tc2"
        child2.parent = "1"
        storage.save_todos(cfg, name, [parent_todo, child1, child2])

        # Todoist state: task-a (linked), task-b (unlinked duplicate), tc1/tc2 (children of task-b)
        todoist_tasks = [
            _make_task("task-a", "sandbox-perms skill"),
            _make_task("task-b", "sandbox-perms skill"),  # duplicate, unlinked
            _make_task("tc1", "Manual test 1", parent_id="task-b"),
            _make_task("tc2", "Manual test 2", parent_id="task-b"),
        ]

        plan = compute_diff(todoist_tasks, cfg, name)

        # task-b should be in potential_links with score 1.0
        link_ids = [e["todoist_task"]["id"] for e in plan.potential_links]
        assert "task-b" in link_ids, (
            f"Expected task-b in potential_links, got: {plan.potential_links}"
        )

        # task-b must NOT be in pull_create
        pull_create_ids = [e["todoist_task_id"] for e in plan.pull_create]
        assert "task-b" not in pull_create_ids, (
            f"task-b should not be in pull_create: {plan.pull_create}"
        )

        # Score for task-b should be 1.0
        task_b_link = next(e for e in plan.potential_links if e["todoist_task"]["id"] == "task-b")
        assert task_b_link["score"] == 1.0


# ── 448.5: Unit tests for depth, parentId extraction, orphan re-linking ──────


class TestComputeTodoistDepth:
    """Unit tests for _compute_todoist_depth()."""

    def test_root_task_depth_zero(self) -> None:
        """Root task (no parentId) returns depth 0."""
        todoist_by_id = {"t1": {"id": "t1"}}
        assert _compute_todoist_depth("t1", todoist_by_id) == 0

    def test_child_depth_one(self) -> None:
        """Task with one parent returns depth 1."""
        todoist_by_id = {
            "parent": {"id": "parent"},
            "child": {"id": "child", "parent_id": "parent"},
        }
        assert _compute_todoist_depth("child", todoist_by_id) == 1

    def test_grandchild_depth_two(self) -> None:
        """Task two levels deep returns depth 2."""
        todoist_by_id = {
            "root": {"id": "root"},
            "mid": {"id": "mid", "parent_id": "root"},
            "leaf": {"id": "leaf", "parent_id": "mid"},
        }
        assert _compute_todoist_depth("leaf", todoist_by_id) == 2

    def test_circular_ref_breaks_without_infinite_loop(self) -> None:
        """Circular parent_id chain terminates via seen-set guard."""
        todoist_by_id = {
            "a": {"id": "a", "parent_id": "b"},
            "b": {"id": "b", "parent_id": "c"},
            "c": {"id": "c", "parent_id": "a"},
        }
        # Should not hang; result depends on where the cycle is detected
        depth = _compute_todoist_depth("a", todoist_by_id)
        assert depth <= 10  # capped by max-depth guard

    def test_missing_parent_depth_zero(self) -> None:
        """Task whose parent_id points to a non-existent task
        returns depth 1 (walks one hop then stops)."""
        todoist_by_id = {
            "orphan": {"id": "orphan", "parent_id": "ghost"},
        }
        # Walks one hop (orphan → ghost), ghost not in map → stops
        assert _compute_todoist_depth("orphan", todoist_by_id) == 1

    def test_unknown_task_id_depth_zero(self) -> None:
        """Task ID not in the map at all returns depth 0."""
        assert _compute_todoist_depth("nonexistent", {}) == 0

    def test_parent_id_underscore_variant(self) -> None:
        """Handles parent_id (API v1 snake_case format)."""
        todoist_by_id = {
            "root": {"id": "root"},
            "child": {"id": "child", "parent_id": "root"},
        }
        assert _compute_todoist_depth("child", todoist_by_id) == 1


class TestPullCreateParentId:
    """Verify compute_diff output includes todoist_parent_id when parentId is set."""

    def test_pull_create_includes_todoist_parent_id(
        self,
        cfg_with_project: tuple,
    ) -> None:
        """New Todoist task with parent_id populates todoist_parent_id in pull_create."""
        cfg, name = cfg_with_project

        todoist_tasks = [
            _make_todoist_task("tp", "Parent task"),
            {**_make_todoist_task("tc", "Child task"), "parent_id": "tp"},
        ]

        plan = compute_diff(todoist_tasks, cfg, name)

        # Both should be in pull_create
        pull_ids = {str(item["todoist_task_id"]) for item in plan.pull_create}
        assert "tp" in pull_ids
        assert "tc" in pull_ids

        child_item = next(i for i in plan.pull_create if i["todoist_task_id"] == "tc")
        assert child_item["todoist_parent_id"] == "tp"

    def test_pull_create_none_parent_when_absent(
        self,
        cfg_with_project: tuple,
    ) -> None:
        """New Todoist task without parent_id has todoist_parent_id=None."""
        cfg, name = cfg_with_project

        todoist_tasks = [_make_todoist_task("t1", "Solo task")]

        plan = compute_diff(todoist_tasks, cfg, name)

        solo = next(i for i in plan.pull_create if i["todoist_task_id"] == "t1")
        assert solo["todoist_parent_id"] is None


class TestApplyChangesParentChild:
    """Tests for apply_changes parent-child creation ordering and orphan re-linking."""

    def test_parent_and_child_new_parent_created_first(
        self,
        cfg_with_project: tuple,
    ) -> None:
        """When both parent and child are new, parent is created first and child is linked."""
        cfg, name = cfg_with_project

        data = ApplyInput(
            created_locally=[
                {
                    "title": "Parent",
                    "todoist_task_id": "tp",
                    "todoist_parent_id": None,
                    "priority": "medium",
                },
                {
                    "title": "Child",
                    "todoist_task_id": "tc",
                    "todoist_parent_id": "tp",
                    "priority": "medium",
                },
            ],
        )

        result = apply_changes(data, cfg, name)

        assert result["created"] == 2
        todos = storage.load_todos(cfg, name)
        todo_map = {t.title: t for t in todos}

        parent = todo_map["Parent"]
        child = todo_map["Child"]
        assert child.parent == parent.id
        assert child.id in parent.children

    def test_existing_parent_new_child(
        self,
        cfg_with_project: tuple,
    ) -> None:
        """New child links to an existing parent via todoist_parent_id."""
        cfg, name = cfg_with_project

        # Create parent first
        parent_todo = _make_todo(cfg, name, "Existing parent", todoist_task_id="tp")
        storage.save_todos(cfg, name, [parent_todo])

        data = ApplyInput(
            created_locally=[
                {
                    "title": "New child",
                    "todoist_task_id": "tc",
                    "todoist_parent_id": "tp",
                    "priority": "medium",
                },
            ],
        )

        result = apply_changes(data, cfg, name)

        assert result["created"] == 1
        todos = storage.load_todos(cfg, name)
        todo_map = {t.title: t for t in todos}

        child = todo_map["New child"]
        parent = todo_map["Existing parent"]
        assert child.parent == parent.id
        assert child.id in parent.children

    def test_orphan_relinked_after_batch_create(
        self,
        cfg_with_project: tuple,
    ) -> None:
        """Child whose todoist_parent_id points to a parent created in the same batch
        but not resolvable at creation time gets re-linked via the orphan pass.

        This happens when the parent lacks a todoist_task_id in the pull_create items
        (e.g. manually added), so the depth sort can't order them and todoist_to_local
        doesn't know about the parent when the child is processed.

        We simulate this by having the parent created without a todoist_task_id,
        then adding it to todoist_to_local after creation (via link_todoist_ids).
        Actually, the orphan path resolves after ALL creates, so we can test by having
        the child reference a todoist ID that only appears on a separately-created parent.
        """
        cfg, name = cfg_with_project

        # Pre-create the parent with a todoist_task_id so it's in todoist_to_local
        parent_todo = _make_todo(cfg, name, "Late parent", todoist_task_id="tp")
        storage.save_todos(cfg, name, [parent_todo])

        # Child references tp as todoist_parent_id, but since the parent is already
        # in storage (not in created_locally), depth sort has no effect.
        # However, todoist_to_local is built from existing todos, so the parent IS found.
        # To truly test orphan re-link, we need a case where todoist_to_local doesn't
        # have the parent at child-creation time but has it after all creates.

        # Use two items: child references "tp_new" which is the todoist ID of the
        # second item. The second item has no todoist_task_id set initially in
        # the synthetic map because it uses a different key format.
        data = ApplyInput(
            created_locally=[
                {
                    "title": "Orphan child",
                    "todoist_task_id": "tc",
                    "todoist_parent_id": "tp_new",
                    "priority": "medium",
                },
                {
                    "title": "New parent",
                    "todoist_task_id": "tp_new",
                    "todoist_parent_id": None,
                    "priority": "medium",
                },
            ],
        )

        apply_changes(data, cfg, name)

        todos = storage.load_todos(cfg, name)
        todo_map = {t.title: t for t in todos}

        child = todo_map["Orphan child"]
        parent = todo_map["New parent"]

        # With depth-based sorting, parent (depth 0) is created before child (depth 1),
        # so the child finds its parent at creation time — no orphan pass needed.
        assert child.parent == parent.id
        assert child.id in parent.children

    def test_empty_todoist_parent_id_stays_root(
        self,
        cfg_with_project: tuple,
    ) -> None:
        """Item with empty todoist_parent_id stays at root level."""
        cfg, name = cfg_with_project

        data = ApplyInput(
            created_locally=[
                {
                    "title": "Root task",
                    "todoist_task_id": "t1",
                    "todoist_parent_id": "",
                    "priority": "medium",
                },
            ],
        )

        result = apply_changes(data, cfg, name)

        assert result["created"] == 1
        todos = storage.load_todos(cfg, name)
        root = next(t for t in todos if t.title == "Root task")
        assert root.parent is None


# ── 448.6: Integration tests for full sync round-trip with nested tasks ──────


class TestFullSyncParentChild:
    """Integration tests for full sync round-trip with nested tasks."""

    def test_three_level_nesting(
        self,
        cfg_with_project: tuple,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Three-level nesting — grandchild → child → parent chain is correct."""
        cfg, name = cfg_with_project

        todoist_tasks = [
            _make_todoist_task("t1", "Root"),
            {**_make_todoist_task("t2", "Mid"), "parent_id": "t1"},
            {**_make_todoist_task("t3", "Leaf"), "parent_id": "t2"},
        ]

        def mock_call(tool_name, params):
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = TestProjTodoistFullSync()._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["pull"]["created"] == 3

        todos = storage.load_todos(cfg, name)
        todo_map = {t.title: t for t in todos}
        root = todo_map["Root"]
        mid = todo_map["Mid"]
        leaf = todo_map["Leaf"]

        assert mid.parent == root.id
        assert leaf.parent == mid.id
        assert mid.id in root.children
        assert leaf.id in mid.children

    def test_external_parent_child_stays_root(
        self,
        cfg_with_project: tuple,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Child's parent_id points to a task not in the fetched list — child stays root."""
        cfg, name = cfg_with_project

        # Only the child is in the task list; "external_parent" is not
        todoist_tasks = [
            {**_make_todoist_task("tc", "Orphan child"), "parent_id": "external_parent"},
        ]

        def mock_call(tool_name, params):
            if tool_name == "todoist_find_tasks":
                return todoist_tasks
            return {}

        monkeypatch.setattr("server.tools.todoist_full_sync._call_todoist_tool", mock_call)

        result_str = TestProjTodoistFullSync()._register_and_call(project_name=name)
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["summary"]["pull"]["created"] == 1

        todos = storage.load_todos(cfg, name)
        child = next(t for t in todos if t.title == "Orphan child")
        assert child.parent is None
