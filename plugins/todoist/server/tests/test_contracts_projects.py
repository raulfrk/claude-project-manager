"""Contract tests for Todoist REST v2 project endpoints.

Each test mocks the HTTP transport via respx, calls the tool function,
then validates request shape and response parsing against EndpointContracts.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import pytest
import respx
from contracts.errors import (
    RATE_LIMITED_429,
    SERVER_ERROR_500,
    UNAUTHORIZED_401,
)
from contracts.projects import (
    CREATE_PROJECT,
    LIST_PROJECTS,
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
    """Patch get_client() in tool modules to return our respx-backed client."""
    monkeypatch.setattr("server.tools.projects.get_client", lambda: client)
    return client


def _register_project_tools():
    """Register project tools and return the app."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.projects import register

    app = FastMCP("test")
    register(app)
    return app


def _get_tool(app, name: str):
    return app._tool_manager._tools[name]


# -- todoist_find_projects (GET /api/v1/projects) ---------------------------


class TestFindProjectsContract:
    @respx.mock
    def test_list_projects_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.get(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(LIST_PROJECTS, [_api_project()])
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_find_projects")
        json.loads(tool.fn())

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, LIST_PROJECTS)

    @respx.mock
    def test_list_projects_response_parses(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                LIST_PROJECTS,
                [_api_project(id="p1", name="Alpha"), _api_project(id="p2", name="Beta")],
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_find_projects")
        result = json.loads(tool.fn())

        assert isinstance(result, list)
        assert len(result) == 2

    @respx.mock
    def test_list_projects_with_name_filter(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                LIST_PROJECTS,
                [_api_project(id="p1", name="Alpha"), _api_project(id="p2", name="Beta")],
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_find_projects")
        result = json.loads(tool.fn(name="alpha"))

        # Client-side filtering: only "Alpha" matches
        assert len(result) == 1
        assert result[0]["name"] == "Alpha"

    @respx.mock
    def test_list_projects_empty(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(LIST_PROJECTS, [])
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_find_projects")
        result = json.loads(tool.fn())

        assert result == []


# -- todoist_add_projects (POST /api/v1/projects) ---------------------------


class TestAddProjectsContract:
    @respx.mock
    def test_create_project_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                CREATE_PROJECT, _api_project(id="new1", name="My Project")
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_projects")
        json.loads(tool.fn(name="My Project"))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CREATE_PROJECT)
        body = json.loads(request.content)
        assert body["name"] == "My Project"

    @respx.mock
    def test_create_project_response_parses(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                CREATE_PROJECT, _api_project(id="new1", name="Created")
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_projects")
        result = json.loads(tool.fn(name="Created"))

        assert_response_parses(result, CREATE_PROJECT)

    @respx.mock
    def test_create_project_with_color(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                CREATE_PROJECT, _api_project(id="new1", name="Colored", color="red")
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_projects")
        json.loads(tool.fn(name="Colored", color="red"))

        body = json.loads(route.calls[0].request.content)
        assert body["color"] == "red"

    @respx.mock
    def test_create_project_with_favorite(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                CREATE_PROJECT, _api_project(id="fav1", name="Favorite", is_favorite=True)
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_projects")
        json.loads(tool.fn(name="Favorite", is_favorite=True))

        body = json.loads(route.calls[0].request.content)
        assert body["is_favorite"] is True


# -- todoist_add_project_hook (POST /api/v1/projects) -----------------------


class TestAddProjectHookContract:
    @respx.mock
    def test_hook_create_request_shape(self, mock_client: TodoistClient) -> None:
        route = respx.post(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                CREATE_PROJECT, _api_project(id="hook1", name="Hook Project")
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_project_hook")
        json.loads(tool.fn(name="Hook Project"))

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CREATE_PROJECT)
        body = json.loads(request.content)
        assert body["name"] == "Hook Project"

    @respx.mock
    def test_hook_create_response_shape(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/projects").mock(
            return_value=build_success_response(
                CREATE_PROJECT, _api_project(id="hook1", name="Hook")
            )
        )

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_project_hook")
        result = json.loads(tool.fn(name="Hook"))

        assert len(result["successes"]) == 1
        assert result["failures"] == []

    @respx.mock
    def test_hook_create_error_returns_failure(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/projects").mock(return_value=build_error_response(SERVER_ERROR_500))

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_project_hook")
        result = json.loads(tool.fn(name="Fail"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "500" in result["failures"][0]["error"]


# -- Error contract tests ----------------------------------------------------


class TestProjectErrorContracts:
    @respx.mock
    def test_401_unauthorized(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/projects").mock(return_value=build_error_response(UNAUTHORIZED_401))

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_find_projects")
        with pytest.raises(RuntimeError, match="Invalid API token"):
            tool.fn()

    @respx.mock
    def test_429_rate_limited(self, mock_client: TodoistClient) -> None:
        respx.get(f"{BASE_URL}/projects").mock(return_value=build_error_response(RATE_LIMITED_429))

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_find_projects")
        with pytest.raises(RuntimeError, match="Retry after 30 seconds"):
            tool.fn()

    @respx.mock
    def test_500_on_create(self, mock_client: TodoistClient) -> None:
        respx.post(f"{BASE_URL}/projects").mock(return_value=build_error_response(SERVER_ERROR_500))

        app = _register_project_tools()
        tool = _get_tool(app, "todoist_add_projects")
        with pytest.raises(RuntimeError, match="Todoist API error 500"):
            tool.fn(name="Broken")
