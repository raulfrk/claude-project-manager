"""Tests for Jira user tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.users import register


@pytest.fixture()
def user_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraSearchUsers:
    def test_returns_matching_users(
        self, mock_jira_client: MagicMock, user_tools: dict
    ) -> None:
        users = [{"key": "alice", "displayName": "Alice Smith"}]
        mock_jira_client.get.return_value = users

        result = user_tools["jira_search_users"](query="al")

        mock_jira_client.get.assert_called_once_with(
            "/rest/api/2/user/search",
            params={"username": "al", "maxResults": 50},
        )
        assert json.loads(result) == users

    def test_custom_max_results(
        self, mock_jira_client: MagicMock, user_tools: dict
    ) -> None:
        mock_jira_client.get.return_value = []

        user_tools["jira_search_users"](query="bob", max_results=10)

        params = mock_jira_client.get.call_args[1]["params"]
        assert params["maxResults"] == 10
