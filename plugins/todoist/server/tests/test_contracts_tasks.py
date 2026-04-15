"""Contract tests for Todoist API v1 task endpoints.

Each test mocks the HTTP transport via respx, calls the tool function,
then validates request shape and response parsing against EndpointContracts.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from contracts.errors import (
    FORBIDDEN_403,
    NOT_FOUND_404,
    RATE_LIMITED_429,
    SERVER_ERROR_500,
    UNAUTHORIZED_401,
)
from contracts.tasks import (
    CLOSE_TASK,
    CREATE_TASK,
    DELETE_TASK,
    GET_TASK,
    LIST_TASKS,
    REOPEN_TASK,
    UPDATE_TASK,
)
from test_contracts import (
    assert_request_matches_contract,
    assert_response_parses,
    build_error_response,
    build_success_response,
)

from server.lib.client import BASE_URL, TodoistClient
from server.lib.config import TodoistConfig

# -- Test constants ----------------------------------------------------------

API_TOKEN = "test-token-abc123"

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


def _api_task(
    id: str = "123456",
    content: str = "Test task",
    priority: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal Todoist API task response."""
    return {
        "id": id,
        "content": content,
        "description": "",
        "priority": priority,
        "labels": [],
        "due": None,
        "project_id": "proj1",
        "parent_id": None,
        "checked": False,
        "updated_at": "2026-01-01T00:00:00Z",
        **extra,
    }


def _api_project(
    id: str = "proj1",
    name: str = "Test Project",
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal Todoist API project response."""
    return {
        "id": id,
        "name": name,
        "color": "blue",
        "is_favorite": False,
        **extra,
    }


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear proxy env vars that break httpx.Client()."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def client() -> Generator[TodoistClient, None, None]:
    """Create a TodoistClient with a real httpx.Client, mocked by respx."""
    c = TodoistClient(TodoistConfig(api_token=API_TOKEN))
    yield c
    c._http.close()


@pytest.fixture()
def mock_client(monkeypatch: pytest.MonkeyPatch, client: TodoistClient) -> TodoistClient:
    """Patch get_client() in all tool modules to return our respx-backed client."""
    monkeypatch.setattr("server.tools.tasks.get_client", lambda: client)
    monkeypatch.setattr("server.tools.projects.get_client", lambda: client)
    return client


def _register_task_tools():
    """Register task tools and return the app."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.tasks import register

    app = FastMCP("test")
    register(app)
    return app


def _get_tool(app, name: str):
    return app._tool_manager._tools[name]


# -- todoist_find_tasks (GET /api/v1/tasks) ---------------------------------


class TestFindTasksContract:
    @respx.mock
    def test_list_tasks_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.get(f"{BASE_URL}/tasks").mock(
            return_value=build_success_response(LIST_TASKS, [_api_task()])
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        json.loads(tool.fn())

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, LIST_TASKS)

    @respx.mock
    def test_list_tasks_response_parses(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks").mock(
            return_value=build_success_response(
                LIST_TASKS,
                [_api_task(id="t1"), _api_task(id="t2")],
            )
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        result = json.loads(tool.fn())

        assert isinstance(result, list)
        assert len(result) == 2
        for task in result:
            assert_response_parses(task, CREATE_TASK)  # same task schema

    @respx.mock
    def test_list_tasks_with_project_filter(self, mock_client: TodoistClient) -> None:
        route = respx.get(f"{BASE_URL}/tasks", params={"project_id": "proj99"}).mock(
            return_value=build_success_response(LIST_TASKS, [_api_task(project_id="proj99")])
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        result = json.loads(tool.fn(project_id="proj99"))

        assert route.called
        assert len(result) == 1

    @respx.mock
    def test_list_tasks_with_filter_param(self, mock_client: TodoistClient) -> None:
        route = respx.get(f"{BASE_URL}/tasks", params={"filter": "today"}).mock(
            return_value=build_success_response(LIST_TASKS, [])
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        result = json.loads(tool.fn(filter="today"))

        assert route.called
        assert result == []


# -- todoist_add_tasks (POST /api/v1/tasks) ---------------------------------


class TestAddTasksContract:
    @respx.mock
    def test_create_task_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/tasks").mock(
            return_value=build_success_response(
                CREATE_TASK,
                _api_task(id="new1", content="Buy milk"),
            )
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        json.loads(tool.fn(tasks=[{"content": "Buy milk"}]))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CREATE_TASK)
        body = json.loads(request.content)
        assert body["content"] == "Buy milk"

    @respx.mock
    def test_create_task_response_parses(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/tasks").mock(
            return_value=build_success_response(CREATE_TASK, _api_task(id="new1"))
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "Test"}]))

        assert len(result["successes"]) == 1
        assert_response_parses(result["successes"][0], CREATE_TASK)

    @respx.mock
    def test_create_task_with_all_fields(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/tasks").mock(
            return_value=build_success_response(CREATE_TASK, _api_task())
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        tool.fn(
            tasks=[
                {
                    "content": "Full task",
                    "description": "Details",
                    "priority": "high",
                    "labels": ["urgent"],
                    "dueString": "tomorrow",
                    "projectId": "proj1",
                    "parentId": "parent1",
                }
            ]
        )

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["content"] == "Full task"
        assert body["description"] == "Details"
        assert body["priority"] == 2  # high -> p2 -> 2
        assert body["labels"] == ["urgent"]
        assert body["due_string"] == "tomorrow"
        assert body["project_id"] == "proj1"
        assert body["parent_id"] == "parent1"

    @respx.mock
    def test_create_multiple_tasks(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/tasks").mock(
            return_value=build_success_response(CREATE_TASK, _api_task())
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "Task 1"}, {"content": "Task 2"}]))

        assert len(result["successes"]) == 2
        assert result["failures"] == []


# -- todoist_update_tasks (POST /api/v1/tasks/{id}) -------------------------


class TestUpdateTasksContract:
    @respx.mock
    def test_update_task_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/tasks/t1").mock(
            return_value=build_success_response(UPDATE_TASK, _api_task(id="t1", content="Updated"))
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_update_tasks")
        json.loads(tool.fn(tasks=[{"id": "t1", "content": "Updated"}]))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_TASK, path_params={"task_id": "t1"})

    @respx.mock
    def test_update_task_response_parses(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/tasks/t1").mock(
            return_value=build_success_response(UPDATE_TASK, _api_task(id="t1", content="Updated"))
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_update_tasks")
        result = json.loads(tool.fn(tasks=[{"id": "t1", "content": "Updated"}]))

        assert len(result["successes"]) == 1
        assert_response_parses(result["successes"][0], UPDATE_TASK)


# -- todoist_complete_tasks (POST /api/v1/tasks/{id}/close) -----------------


class TestCompleteTasksContract:
    @respx.mock
    def test_close_task_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/tasks/t1/close").mock(return_value=httpx.Response(204))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_complete_tasks")
        json.loads(tool.fn(ids=["t1"]))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CLOSE_TASK, path_params={"task_id": "t1"})

    @respx.mock
    def test_close_multiple_tasks(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/tasks/t1/close").mock(return_value=httpx.Response(204))
        respx.post(f"{BASE_URL}/tasks/t2/close").mock(return_value=httpx.Response(204))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_complete_tasks")
        result = json.loads(tool.fn(ids=["t1", "t2"]))

        assert len(result["successes"]) == 2
        assert result["failures"] == []


# -- todoist_uncomplete_tasks (POST /api/v1/tasks/{id}/reopen) --------------


class TestUncompleteTasksContract:
    @respx.mock
    def test_reopen_task_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/tasks/t1/reopen").mock(return_value=httpx.Response(204))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_uncomplete_tasks")
        json.loads(tool.fn(ids=["t1"]))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, REOPEN_TASK, path_params={"task_id": "t1"})

    @respx.mock
    def test_reopen_multiple_tasks(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/tasks/t1/reopen").mock(return_value=httpx.Response(204))
        respx.post(f"{BASE_URL}/tasks/t2/reopen").mock(return_value=httpx.Response(204))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_uncomplete_tasks")
        result = json.loads(tool.fn(ids=["t1", "t2"]))

        assert len(result["successes"]) == 2
        assert result["failures"] == []


# -- todoist_delete (DELETE /api/v1/tasks/{id}) -----------------------------


class TestDeleteTaskContract:
    @respx.mock
    def test_delete_task_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.delete(f"{BASE_URL}/tasks/t1").mock(return_value=httpx.Response(204))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_delete")
        json.loads(tool.fn(id="t1"))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, DELETE_TASK, path_params={"task_id": "t1"})

    @respx.mock
    def test_delete_task_response_shape(self, mock_client: TodoistClient) -> None:
        respx.delete(f"{BASE_URL}/tasks/t1").mock(return_value=httpx.Response(204))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_delete")
        result = json.loads(tool.fn(id="t1"))

        assert result == {"deleted": True, "id": "t1"}


# -- todoist_verify_complete (GET /api/v1/tasks/{id}) -----------------------


class TestVerifyCompleteContract:
    @respx.mock
    def test_verify_complete_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.get(f"{BASE_URL}/tasks/t1").mock(
            return_value=build_success_response(GET_TASK, _api_task(id="t1", checked=True))
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_verify_complete")
        json.loads(tool.fn(todoist_task_id="t1"))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_TASK, path_params={"task_id": "t1"})

    @respx.mock
    def test_verify_complete_completed_task(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks/t1").mock(
            return_value=build_success_response(GET_TASK, _api_task(id="t1", checked=True))
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_verify_complete")
        result = json.loads(tool.fn(todoist_task_id="t1"))

        assert result["verified"] is True
        assert result["status"] == "completed"

    @respx.mock
    def test_verify_complete_open_task(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks/t1").mock(
            return_value=build_success_response(GET_TASK, _api_task(id="t1", checked=False))
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_verify_complete")
        result = json.loads(tool.fn(todoist_task_id="t1"))

        assert result["verified"] is False
        assert result["status"] == "open"


# -- Error contract tests ----------------------------------------------------


class TestTaskErrorContracts:
    @respx.mock
    def test_401_unauthorized(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(UNAUTHORIZED_401))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        # find_tasks returns [] on non-list response, but client raises on 401
        with pytest.raises(RuntimeError, match="Invalid API token"):
            tool.fn()

    @respx.mock
    def test_403_forbidden(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(FORBIDDEN_403))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        with pytest.raises(RuntimeError, match="Todoist API error 403"):
            tool.fn()

    @respx.mock
    def test_404_not_found(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks/nonexistent").mock(
            return_value=build_error_response(NOT_FOUND_404)
        )

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_verify_complete")
        result = json.loads(tool.fn(todoist_task_id="nonexistent"))

        # verify_complete catches exceptions and returns error status
        assert result["verified"] is False
        assert result["status"] == "error"

    @respx.mock
    def test_429_rate_limited(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(RATE_LIMITED_429))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        with pytest.raises(RuntimeError, match="Retry after 30 seconds"):
            tool.fn()

    @respx.mock
    def test_500_server_error(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/tasks").mock(return_value=build_error_response(SERVER_ERROR_500))

        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "Fail"}]))

        # add_tasks catches exceptions per-task
        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "500" in result["failures"][0]["error"]
