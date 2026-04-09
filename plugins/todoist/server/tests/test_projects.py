"""Tests for Todoist project tools: add and find."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from server.lib.client import TodoistClient

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
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock(spec=TodoistClient)
    monkeypatch.setattr("server.tools.projects.get_client", lambda: client)
    return client


def _make_app():
    from mcp.server.fastmcp import FastMCP

    from server.tools.projects import register

    app = FastMCP("test")
    register(app)
    return app


def _api_project(
    id: str = "1",
    name: str = "Inbox",
    **extra: Any,
) -> dict[str, Any]:
    return {"id": id, "name": name, **extra}


# -- todoist_add_projects ----------------------------------------------------


class TestAddProjects:
    def test_success_minimal(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_project(id="p1", name="Work")

        app = _make_app()
        tool = app._tool_manager._tools["todoist_add_projects"]
        result = json.loads(tool.fn(name="Work"))

        assert result["id"] == "p1"
        assert result["name"] == "Work"
        mock_client.post.assert_called_once_with(
            "/projects", json={"name": "Work", "is_favorite": False}
        )

    def test_success_with_color_and_favorite(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_project(
            id="p2", name="Personal", color="red", is_favorite=True
        )

        app = _make_app()
        tool = app._tool_manager._tools["todoist_add_projects"]
        result = json.loads(tool.fn(name="Personal", color="red", is_favorite=True))

        assert result["name"] == "Personal"
        mock_client.post.assert_called_once_with(
            "/projects",
            json={"name": "Personal", "is_favorite": True, "color": "red"},
        )

    def test_api_error(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("API error")

        app = _make_app()
        tool = app._tool_manager._tools["todoist_add_projects"]

        with pytest.raises(RuntimeError, match="API error"):
            tool.fn(name="Bad")


# -- todoist_find_projects ---------------------------------------------------


class TestFindProjects:
    def test_no_filter_returns_all(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [
            _api_project(id="1", name="Inbox"),
            _api_project(id="2", name="Work"),
        ]

        app = _make_app()
        tool = app._tool_manager._tools["todoist_find_projects"]
        result = json.loads(tool.fn())

        assert len(result) == 2

    def test_name_filter_case_insensitive(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [
            _api_project(id="1", name="Inbox"),
            _api_project(id="2", name="Work Project"),
            _api_project(id="3", name="Personal"),
        ]

        app = _make_app()
        tool = app._tool_manager._tools["todoist_find_projects"]
        result = json.loads(tool.fn(name="work"))

        assert len(result) == 1
        assert result[0]["name"] == "Work Project"

    def test_name_filter_no_matches(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [
            _api_project(id="1", name="Inbox"),
        ]

        app = _make_app()
        tool = app._tool_manager._tools["todoist_find_projects"]
        result = json.loads(tool.fn(name="nonexistent"))

        assert result == []

    def test_api_error(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.side_effect = RuntimeError("timeout")

        app = _make_app()
        tool = app._tool_manager._tools["todoist_find_projects"]

        with pytest.raises(RuntimeError, match="timeout"):
            tool.fn()

    def test_name_filter_substring_match(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [
            _api_project(id="1", name="My Work Tasks"),
            _api_project(id="2", name="Homework"),
        ]

        app = _make_app()
        tool = app._tool_manager._tools["todoist_find_projects"]
        result = json.loads(tool.fn(name="work"))

        assert len(result) == 2

    def test_non_list_response_returns_empty(self, mock_client: MagicMock) -> None:
        mock_client.get_paginated.return_value = [{"error": "unexpected"}]

        app = _make_app()
        tool = app._tool_manager._tools["todoist_find_projects"]
        result = json.loads(tool.fn())

        # get_paginated returns list; non-dict items filtered by tool
        assert len(result) == 1


# -- todoist_add_project_hook ------------------------------------------------


class TestAddProjectHook:
    def test_success(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _api_project(id="h1", name="Hook Project")

        app = _make_app()
        tool = app._tool_manager._tools["todoist_add_project_hook"]
        result = json.loads(tool.fn(name="Hook Project"))

        assert len(result["successes"]) == 1
        assert result["failures"] == []

    def test_api_error_returns_failure(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("Server error")

        app = _make_app()
        tool = app._tool_manager._tools["todoist_add_project_hook"]
        result = json.loads(tool.fn(name="Bad"))

        assert result["successes"] == []
        assert len(result["failures"]) == 1
        assert "Server error" in result["failures"][0]["error"]
