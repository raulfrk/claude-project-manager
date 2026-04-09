"""Dedicated error response contract tests for Todoist REST v2.

Tests each error code (401, 403, 404, 429, 500) against multiple endpoints
(GET /rest/v2/tasks and POST /rest/v2/tasks) for broader coverage than the
inline error tests in test_contracts_tasks.py.
"""

from __future__ import annotations

import json
from collections.abc import Generator

import pytest
import respx
from contracts.errors import (
    FORBIDDEN_403,
    NOT_FOUND_404,
    RATE_LIMITED_429,
    SERVER_ERROR_500,
    UNAUTHORIZED_401,
)
from test_contracts import build_error_response

from server.lib.client import BASE_URL, TodoistClient
from server.lib.config import TodoistConfig

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
    from mcp.server.fastmcp import FastMCP

    from server.tools.tasks import register

    app = FastMCP("test")
    register(app)
    return app


def _get_tool(app, name: str):
    return app._tool_manager._tools[name]


# ---------------------------------------------------------------------------
# 401 Unauthorized — multiple endpoints
# ---------------------------------------------------------------------------


class TestUnauthorized401:
    @respx.mock
    def test_get_tasks_401(self, mock_client: TodoistClient) -> None:
        """GET /rest/v2/tasks returns 401."""
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(UNAUTHORIZED_401))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        with pytest.raises(RuntimeError, match="Invalid API token"):
            tool.fn()

    @respx.mock
    def test_post_tasks_401(self, mock_client: TodoistClient) -> None:
        """POST /rest/v2/tasks returns 401."""
        respx.post(f"{BASE_URL}/tasks").mock(return_value=build_error_response(UNAUTHORIZED_401))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        # add_tasks catches per-task RuntimeError and returns in failures
        result = json.loads(tool.fn(tasks=[{"content": "Test"}]))
        assert result["successes"] == []
        assert len(result["failures"]) == 1
        err = result["failures"][0]["error"]
        assert "401" in err or "Invalid API token" in err


# ---------------------------------------------------------------------------
# 403 Forbidden — multiple endpoints
# ---------------------------------------------------------------------------


class TestForbidden403:
    @respx.mock
    def test_get_tasks_403(self, mock_client: TodoistClient) -> None:
        """GET /rest/v2/tasks returns 403."""
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(FORBIDDEN_403))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        with pytest.raises(RuntimeError, match="Todoist API error 403"):
            tool.fn()

    @respx.mock
    def test_post_tasks_403(self, mock_client: TodoistClient) -> None:
        """POST /rest/v2/tasks returns 403."""
        respx.post(f"{BASE_URL}/tasks").mock(return_value=build_error_response(FORBIDDEN_403))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "Test"}]))
        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "403" in result["failures"][0]["error"]


# ---------------------------------------------------------------------------
# 404 Not Found — multiple endpoints
# ---------------------------------------------------------------------------


class TestNotFound404:
    @respx.mock
    def test_get_task_404(self, mock_client: TodoistClient) -> None:
        """GET /rest/v2/tasks/{id} returns 404 (via verify_complete)."""
        respx.get(f"{BASE_URL}/tasks/nonexistent").mock(
            return_value=build_error_response(NOT_FOUND_404)
        )
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_verify_complete")
        result = json.loads(tool.fn(todoist_task_id="nonexistent"))
        assert result["verified"] is False
        assert result["status"] == "error"

    @respx.mock
    def test_post_tasks_404(self, mock_client: TodoistClient) -> None:
        """POST /rest/v2/tasks returns 404."""
        respx.post(f"{BASE_URL}/tasks").mock(return_value=build_error_response(NOT_FOUND_404))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "Test"}]))
        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "404" in result["failures"][0]["error"]


# ---------------------------------------------------------------------------
# 429 Rate Limited — multiple endpoints
# ---------------------------------------------------------------------------


class TestRateLimited429:
    @respx.mock
    def test_get_tasks_429(self, mock_client: TodoistClient) -> None:
        """GET /rest/v2/tasks returns 429 with Retry-After header."""
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(RATE_LIMITED_429))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        with pytest.raises(RuntimeError, match="Retry after 30 seconds"):
            tool.fn()

    @respx.mock
    def test_post_tasks_429(self, mock_client: TodoistClient) -> None:
        """POST /rest/v2/tasks returns 429 with Retry-After header."""
        respx.post(f"{BASE_URL}/tasks").mock(return_value=build_error_response(RATE_LIMITED_429))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        # add_tasks catches per-task RuntimeError; 429 includes rate limit info
        result = json.loads(tool.fn(tasks=[{"content": "Test"}]))
        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "Retry after 30 seconds" in result["failures"][0]["error"]


# ---------------------------------------------------------------------------
# 500 Server Error — multiple endpoints
# ---------------------------------------------------------------------------


class TestServerError500:
    @respx.mock
    def test_get_tasks_500(self, mock_client: TodoistClient) -> None:
        """GET /rest/v2/tasks returns 500."""
        respx.get(f"{BASE_URL}/tasks").mock(return_value=build_error_response(SERVER_ERROR_500))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_find_tasks")
        with pytest.raises(RuntimeError, match="Todoist API error 500"):
            tool.fn()

    @respx.mock
    def test_post_tasks_500(self, mock_client: TodoistClient) -> None:
        """POST /rest/v2/tasks returns 500."""
        respx.post(f"{BASE_URL}/tasks").mock(return_value=build_error_response(SERVER_ERROR_500))
        app = _register_task_tools()
        tool = _get_tool(app, "todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "Fail"}]))
        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "500" in result["failures"][0]["error"]
