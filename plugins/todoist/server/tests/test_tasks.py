"""Tests for Todoist task tools: add, complete, find, update, delete, uncomplete."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from server.lib.client import TodoistClient
from server.lib.config import TodoistConfig
from server.tools.tasks import _build_task_payload, _resolve_priority


# -- Fixtures ---------------------------------------------------------------

_PROXY_VARS = (
    "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy",
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

    def test_unknown_string_defaults_to_1(self) -> None:
        assert _resolve_priority("urgent") == 1

    def test_case_insensitive(self) -> None:
        assert _resolve_priority("P2") == 2
        assert _resolve_priority("HIGH") == 2


# -- _build_task_payload -----------------------------------------------------


class TestBuildTaskPayload:
    def test_content_only(self) -> None:
        assert _build_task_payload({"content": "Buy milk"}) == {"content": "Buy milk"}

    def test_all_fields(self) -> None:
        payload = _build_task_payload({
            "content": "Task",
            "description": "Desc",
            "priority": "high",
            "labels": ["a"],
            "dueString": "tomorrow",
            "projectId": "proj1",
            "parentId": "parent1",
        })
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
        payload = _build_task_payload({
            "content": "X",
            "due_string": "next week",
            "project_id": "p1",
            "parent_id": "pp1",
        })
        assert payload["due_string"] == "next week"
        assert payload["project_id"] == "p1"
        assert payload["parent_id"] == "pp1"

    def test_empty_dict(self) -> None:
        assert _build_task_payload({}) == {}


# -- todoist_add_tasks -------------------------------------------------------


class TestAddTasks:
    def test_success_single(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="99", content="New task")

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[{"content": "New task"}]))

        assert len(result["successes"]) == 1
        assert result["successes"][0]["id"] == "99"
        assert result["failures"] == []

    def test_missing_content(self, mock_client: MagicMock) -> None:
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

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

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[
            {"content": "Good"},
            {"content": "Bad"},
        ]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 1

    def test_empty_list(self, mock_client: MagicMock) -> None:
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[]))

        assert result == {"successes": [], "failures": []}

    def test_all_fail(self, mock_client: MagicMock) -> None:
        """All tasks fail — result is still valid JSON."""
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_add_tasks"]
        result = json.loads(tool.fn(tasks=[
            {"description": "no content"},
            {"description": "also no content"},
        ]))

        assert result["successes"] == []
        assert len(result["failures"]) == 2


# -- todoist_complete_tasks --------------------------------------------------


class TestCompleteTasks:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.close_task.return_value = {"ok": True}

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["t1", "t2"]))

        assert len(result["successes"]) == 2
        assert result["failures"] == []
        assert mock_client.close_task.call_count == 2

    def test_failure(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = RuntimeError("not found")

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

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

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=["ok-id", "bad-id"]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1

    def test_empty_ids(self, mock_client: MagicMock) -> None:
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_complete_tasks"]
        result = json.loads(tool.fn(ids=[]))

        assert result == {"successes": [], "failures": []}


# -- todoist_find_tasks ------------------------------------------------------


class TestFindTasks:
    def test_success_no_filter(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = [
            _api_task(id="1", content="A"),
            _api_task(id="2", content="B"),
        ]

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn())

        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_with_project_id(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = [_api_task(id="5")]

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn(project_id="proj1"))

        mock_client.get.assert_called_once_with("/tasks", params={"project_id": "proj1"})
        assert len(result) == 1

    def test_with_filter(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = []

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn(filter="today"))

        mock_client.get.assert_called_once_with("/tasks", params={"filter": "today"})
        assert result == []

    def test_non_list_response_returns_empty(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"error": "unexpected"}

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        result = json.loads(tool.fn())

        assert result == []

    def test_no_params_passes_none(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = []

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_find_tasks"]
        tool.fn()

        mock_client.get.assert_called_once_with("/tasks", params=None)


# -- todoist_update_tasks ----------------------------------------------------


class TestUpdateTasks:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_task(id="1", content="Updated")

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[{"id": "1", "content": "Updated"}]))

        assert len(result["successes"]) == 1
        assert result["successes"][0]["content"] == "Updated"

    def test_missing_id(self, mock_client: MagicMock) -> None:
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

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

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[
            {"id": "1", "content": "Good"},
            {"id": "2", "content": "Bad"},
        ]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1

    def test_empty_list(self, mock_client: MagicMock) -> None:
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_update_tasks"]
        result = json.loads(tool.fn(tasks=[]))

        assert result == {"successes": [], "failures": []}

    def test_api_error(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("Server error")

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

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

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_delete"]
        result = json.loads(tool.fn(id="42"))

        assert result == {"deleted": True, "id": "42"}
        mock_client.delete.assert_called_once_with("/tasks/42")

    def test_error(self, mock_client: MagicMock) -> None:
        mock_client.delete.side_effect = RuntimeError("not found")

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_delete"]

        with pytest.raises(RuntimeError, match="not found"):
            tool.fn(id="999")


# -- todoist_uncomplete_tasks ------------------------------------------------


class TestUncompleteTasks:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.return_value = {"ok": True}

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["t1"]))

        assert len(result["successes"]) == 1
        assert result["failures"] == []

    def test_failure(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.side_effect = RuntimeError("fail")

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

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

        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=["ok", "fail"]))

        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1

    def test_empty_ids(self, mock_client: MagicMock) -> None:
        from server.tools.tasks import register
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_uncomplete_tasks"]
        result = json.loads(tool.fn(ids=[]))

        assert result == {"successes": [], "failures": []}
