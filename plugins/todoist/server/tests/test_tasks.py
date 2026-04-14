"""Tests for Todoist task tools: add, complete, find, update, delete, uncomplete."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from server.lib.client import TodoistClient
from server.tools.tasks import _build_task_payload, _resolve_priority

# -- Fixtures ---------------------------------------------------------------

_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "FTP_PROXY",
    "ftp_proxy",
)


@pytest.fixture(autouse=True)
def _patch_get_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear proxy env vars that break httpx.Client() in the test process."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Return a MagicMock that replaces get_client() in the tasks module."""
    client = MagicMock(spec=TodoistClient)
    monkeypatch.setattr("server.tools.tasks.get_client", lambda: client)
    return client


@pytest.fixture()
def _register_tools():
    """Register the task tools on a throw-away FastMCP app and return the tool funcs."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    from server.tools.tasks import register

    register(app)
    return app


def _api_task(
    id: str = "1",
    content: str = "Task",
    priority: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal Todoist API task response."""
    return {"id": id, "content": content, "priority": priority, **extra}


# -- _resolve_priority -------------------------------------------------------


class TestResolvePriority:
    def test_none_returns_none(self) -> None:
        assert _resolve_priority(None) is None

    def test_int_passthrough(self) -> None:
        assert _resolve_priority(2) == 2

    def test_todoist_string_p1(self) -> None:
        assert _resolve_priority("p1") == 1

    def test_todoist_string_p4(self) -> None:
        assert _resolve_priority("p4") == 4

    def test_local_high(self) -> None:
        assert _resolve_priority("high") == 2

    def test_local_medium(self) -> None:
        assert _resolve_priority("medium") == 3

    def test_local_low(self) -> None:
        assert _resolve_priority("low") == 4

    def test_unknown_string_defaults_to_medium(self) -> None:
        assert _resolve_priority("urgent") == 3

    def test_case_insensitive(self) -> None:
        assert _resolve_priority("P2") == 2
        assert _resolve_priority("HIGH") == 2


# -- _build_task_payload -----------------------------------------------------


class TestBuildTaskPayload:
    def test_content_only(self) -> None:
        assert _build_task_payload({"content": "Buy milk"}) == {"content": "Buy milk"}

    def test_all_fields(self) -> None:
        payload = _build_task_payload(
            {
                "content": "Task",
                "description": "Desc",
                "priority": "high",
                "labels": ["a"],
                "dueString": "tomorrow",
                "projectId": "proj1",
                "parentId": "parent1",
            }
        )
        assert payload == {
            "content": "Task",
            "description": "Desc",
            "priority": 2,
            "labels": ["a"],
            "due_string": "tomorrow",
            "project_id": "proj1",
            "parent_id": "parent1",
        }

    def test_snake_case_aliases(self) -> None:
        payload = _build_task_payload(
            {
                "content": "X",
                "due_string": "next week",
                "project_id": "p1",
                "parent_id": "pp1",
            }
        )
        assert payload["due_string"] == "next week"
        assert payload["project_id"] == "p1"
        assert payload["parent_id"] == "pp1"

    def test_priority_none_excluded(self) -> None:
        payload = _build_task_payload({"content": "Task", "priority": None})
        assert "priority" not in payload

    def test_empty_dict(self) -> None:
        assert _build_task_payload({}) == {}


# -- todoist_add_tasks -------------------------------------------------------


class TestAddTasks:
    def test_success_single(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="99", content="New task")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "New task"}]))

        assert len(result["successes"]) == 1
        assert result["successes"][0]["id"] == "99"
        assert result["failures"] == []

    def test_missing_content(self, mock_client: MagicMock) -> None:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"description": "no content field"}]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "Missing 'content'" in result["failures"][0]["error"]

    def test_partial_failure(self, mock_client: MagicMock) -> None:
        """First task succeeds, second fails."""
        mock_client.post.side_effect = [
            _api_task(id="10", content="Good"),
            RuntimeError("API error"),
        ]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(
            tool.fn(
                tasks=[
                    {"content": "Good"},
                    {"content": "Bad"},
                ]
            )
        )

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 1

    def test_empty_list(self, mock_client: MagicMock) -> None:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[]))

        assert result == {"successes": [], "failures": []}

    def test_all_fail(self, mock_client: MagicMock) -> None:
        """All tasks fail — result is still valid JSON."""
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(
            tool.fn(
                tasks=[
                    {"description": "no content"},
                    {"description": "also no content"},
                ]
            )
        )

        assert result["successes"] == []
        assert len(result["failures"]) == 2

    def test_parent_index_resolution(self, mock_client: MagicMock) -> None:
        """_parent_index resolves grandchild parentId from previously created task."""
        call_count = 0

        def _mock_post(path: str, json: Any = None) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            # Return sequential IDs: todoist-1, todoist-2, todoist-3
            return _api_task(id=f"todoist-{call_count}", content=json.get("content", ""))

        mock_client.post.side_effect = _mock_post

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]

        # Simulate what todo_batch_add_children now produces:
        # idx 0: Child A (direct child, parentId known)
        # idx 1: Grandchild A1 (_parent_index=0, parentId resolved at creation)
        # idx 2: Child B (direct child, parentId known)
        tasks = [
            {
                "content": "Child A",
                "projectId": "proj-1",
                "parentId": "root-todoist-id",
                "_parent_index": -1,
                "_local_id": "1.1",
            },
            {
                "content": "Grandchild A1",
                "projectId": "proj-1",
                "_parent_index": 0,
                "_local_id": "1.1.1",
            },
            {
                "content": "Child B",
                "projectId": "proj-1",
                "parentId": "root-todoist-id",
                "_parent_index": -1,
                "_local_id": "1.2",
            },
        ]
        result = json.loads(tool.fn(tasks=tasks))

        assert len(result["successes"]) == 3
        assert result["failures"] == []

        # Verify the API calls: Child A gets root parent, Grandchild gets Child A's ID
        calls = mock_client.post.call_args_list
        assert calls[0].kwargs["json"]["parent_id"] == "root-todoist-id"
        assert calls[1].kwargs["json"]["parent_id"] == "todoist-1"  # resolved from idx 0
        assert calls[2].kwargs["json"]["parent_id"] == "root-todoist-id"

        # _parent_index and _local_id should NOT appear in payloads
        for call in calls:
            assert "_parent_index" not in call.kwargs["json"]
            assert "_local_id" not in call.kwargs["json"]

    def test_parent_index_failed_parent_skips_child(self, mock_client: MagicMock) -> None:
        """If a parent task fails, its grandchild (referencing it) also fails."""
        mock_client.post.side_effect = RuntimeError("API error")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]

        tasks = [
            {"content": "Child A", "projectId": "p1", "parentId": "root", "_parent_index": -1},
            {"content": "Grandchild A1", "projectId": "p1", "_parent_index": 0},
        ]
        result = json.loads(tool.fn(tasks=tasks))

        assert result["successes"] == []
        assert len(result["failures"]) == 2
        # First fails from API error, second fails because parent wasn't created
        assert "Parent at index 0 was not created" in result["failures"][1]["error"]


# -- todoist_complete_tasks --------------------------------------------------


class TestCompleteTasks:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.close_task.return_value = {"ok": True}

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["t1", "t2"]))

        assert len(result["successes"]) == 2
        assert result["failures"] == []
        assert mock_client.close_task.call_count == 2

    def test_failure(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = RuntimeError("not found")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["bad-id"]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "not found" in result["failures"][0]["error"]

    def test_partial_failure(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = [
            {"ok": True},
            RuntimeError("gone"),
        ]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["ok-id", "bad-id"]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1

    def test_empty_ids(self, mock_client: MagicMock) -> None:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=[]))

        assert result == {"successes": [], "failures": []}


# -- todoist_find_tasks ------------------------------------------------------


class TestFindTasks:
    def test_success_no_filter(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [
            _api_task(id="1", content="A"),
            _api_task(id="2", content="B"),
        ]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn())

        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_with_project_id(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [_api_task(id="5")]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn(project_id="proj1"))

        mock_client.get_paginated.assert_called_once_with(
            "/tasks", params={"project_id": "proj1"}, limit=None
        )
        assert len(result) == 1

    def test_with_filter(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = []

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn(filter="today"))

        mock_client.get_paginated.assert_called_once_with(
            "/tasks", params={"filter": "today"}, limit=None
        )
        assert result == []

    def test_non_list_response_returns_empty(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [{"error": "unexpected"}]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn())

        # get_paginated returns a list; non-dict items are filtered by the tool
        assert len(result) == 1

    def test_no_params_passes_empty(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = []

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        tool.fn()

        mock_client.get_paginated.assert_called_once_with("/tasks", params={}, limit=None)


# -- todoist_update_tasks ----------------------------------------------------


class TestUpdateTasks:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="1", content="Updated")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[{"id": "1", "content": "Updated"}]))

        assert len(result["successes"]) == 1
        assert result["successes"][0]["content"] == "Updated"

    def test_missing_id(self, mock_client: MagicMock) -> None:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "no id"}]))

        assert result["successes"] == []
        assert "Missing 'id'" in result["failures"][0]["error"]

    def test_partial_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = [
            _api_task(id="1", content="Good"),
            RuntimeError("bad update"),
        ]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(
            tool.fn(
                tasks=[
                    {"id": "1", "content": "Good"},
                    {"id": "2", "content": "Bad"},
                ]
            )
        )

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1

    def test_empty_list(self, mock_client: MagicMock) -> None:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[]))

        assert result == {"successes": [], "failures": []}

    def test_api_error(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("Server error")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[{"id": "1", "content": "X"}]))

        assert result["successes"] == []
        assert "Server error" in result["failures"][0]["error"]


# -- todoist_delete ----------------------------------------------------------


class TestDeleteTask:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.delete.return_value = {"ok": True}

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_delete"]
        result = json.loads(tool.fn(id="42"))

        assert result == {"deleted": True, "id": "42"}
        mock_client.delete.assert_called_once_with("/tasks/42")

    def test_error(self, mock_client: MagicMock) -> None:
        mock_client.delete.side_effect = RuntimeError("not found")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_delete"]

        with pytest.raises(RuntimeError, match="not found"):
            tool.fn(id="999")


# -- todoist_uncomplete_tasks ------------------------------------------------


class TestUncompleteTasks:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.return_value = {"ok": True}

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["t1"]))

        assert len(result["successes"]) == 1
        assert result["failures"] == []

    def test_failure(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.side_effect = RuntimeError("fail")

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["bad"]))

        assert result["successes"] == []
        assert len(result["failures"]) == 1

    def test_partial_failure(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.side_effect = [
            {"ok": True},
            RuntimeError("nope"),
        ]

        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["ok", "fail"]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1

    def test_empty_ids(self, mock_client: MagicMock) -> None:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=[]))

        assert result == {"successes": [], "failures": []}


# -- todoist_add_child_task_hook -----------------------------------------------


class TestAddChildTaskHook:
    def _get_tool(self, mock_client: MagicMock) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["todoist_add_child_task_hook"]

    def test_happy_path(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="child1", content="Sub-task", priority=2)
        tool = self._get_tool(mock_client)
        result = json.loads(
            tool.fn(
                content="Sub-task",
                priority="high",
                labels=["dev"],
                projectId="proj1",
                parentId="parent1",
            )
        )

        assert len(result["successes"]) == 1
        assert result["successes"][0]["id"] == "child1"
        assert result["failures"] == []
        mock_client.post.assert_called_once()

    def test_null_parent_id_returns_warning(self, mock_client: MagicMock) -> None:
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(content="Task", projectId="proj1", parentId=None))

        assert "warning" in result
        assert "skipping" in result["warning"].lower()
        mock_client.post.assert_not_called()

    def test_null_project_id_returns_warning(self, mock_client: MagicMock) -> None:
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(content="Task", projectId=None, parentId="parent1"))

        assert "warning" in result
        assert "skipping" in result["warning"].lower()
        mock_client.post.assert_not_called()

    def test_empty_content_returns_failure(self, mock_client: MagicMock) -> None:
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(content="", projectId="proj1", parentId="parent1"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "Missing 'content'" in result["failures"][0]["error"]

    def test_api_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("API timeout")
        tool = self._get_tool(mock_client)
        result = json.loads(
            tool.fn(
                content="Task",
                projectId="proj1",
                parentId="parent1",
            )
        )

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "API timeout" in result["failures"][0]["error"]
        assert result["failures"][0]["content"] == "Task"


# -- todoist_complete_task_hook ------------------------------------------------


class TestCompleteTaskHook:
    def _get_tool(self, mock_client: MagicMock) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["todoist_complete_task_hook"]

    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.close_task.return_value = {"ok": True}
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(id="t1"))

        assert result["successes"] == [{"id": "t1"}]
        assert result["failures"] == []
        mock_client.close_task.assert_called_once_with("t1")

    def test_api_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = RuntimeError("gone")
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(id="bad"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["id"] == "bad"
        assert "gone" in result["failures"][0]["error"]


# -- todoist_update_task_hook --------------------------------------------------


class TestUpdateTaskHook:
    def _get_tool(self, mock_client: MagicMock) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["todoist_update_task_hook"]

    def test_success_content_only(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="u1", content="New title")
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(id="u1", content="New title"))

        assert len(result["successes"]) == 1
        assert result["successes"][0]["content"] == "New title"
        assert result["failures"] == []

    def test_all_optional_fields(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="u2", content="Full")
        tool = self._get_tool(mock_client)
        result = json.loads(
            tool.fn(
                id="u2",
                content="Full",
                priority="high",
                labels=["dev"],
                description="Desc",
                dueString="tomorrow",
            )
        )

        assert len(result["successes"]) == 1
        assert result["failures"] == []
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs["json"]
        assert body["priority"] == 2
        assert body["labels"] == ["dev"]
        assert body["description"] == "Desc"
        assert body["due_string"] == "tomorrow"

    def test_api_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("Server error")
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(id="bad", content="X"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["id"] == "bad"

    def test_no_optional_fields(self, mock_client: MagicMock) -> None:
        """Only id is provided, no optional fields — payload should be minimal."""
        mock_client.post.return_value = _api_task(id="u3", content="Unchanged")
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(id="u3"))

        assert len(result["successes"]) == 1
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs["json"]
        # Only id-derived path, no content/priority/etc in body
        assert "content" not in body
        assert "priority" not in body


# -- todoist_verify_complete ---------------------------------------------------


class TestVerifyComplete:
    def _get_tool(self, mock_client: MagicMock) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools["todoist_verify_complete"]

    def test_completed_task(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"id": "v1", "checked": True}
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(todoist_task_id="v1"))

        assert result["verified"] is True
        assert result["status"] == "completed"
        assert result["task_id"] == "v1"

    def test_open_task(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"id": "v2", "checked": False}
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(todoist_task_id="v2"))

        assert result["verified"] is False
        assert result["status"] == "open"

    def test_api_error_returns_error_status(self, mock_client: MagicMock) -> None:
        mock_client.get.side_effect = RuntimeError("not found")
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(todoist_task_id="bad"))

        assert result["verified"] is False
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_non_dict_response(self, mock_client: MagicMock) -> None:
        """API returns a non-dict (e.g. list) — should treat as not completed."""
        mock_client.get.return_value = [{"id": "v3"}]
        tool = self._get_tool(mock_client)
        result = json.loads(tool.fn(todoist_task_id="v3"))

        assert result["verified"] is False
        assert result["status"] == "open"
