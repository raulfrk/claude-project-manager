"""Tests for Jira watcher tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.watchers import register


@pytest.fixture()
def watcher_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetWatchers:
    def test_fetches_watchers(
        self, mock_jira_client: MagicMock, watcher_tools: dict
    ) -> None:
        data = {"watchCount": 2, "watchers": [{"name": "alice"}, {"name": "bob"}]}
        mock_jira_client.get.return_value = data

        result = watcher_tools["jira_get_watchers"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42/watchers")
        assert json.loads(result) == data


class TestJiraAddWatcher:
    def test_adds_watcher(
        self, mock_jira_client: MagicMock, watcher_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = None

        result = watcher_tools["jira_add_watcher"](issue_key="PROJ-42", username="alice")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/watchers", json_body="alice"
        )
        assert json.loads(result) == {"ok": True, "issue_key": "PROJ-42", "username": "alice"}


class TestJiraRemoveWatcher:
    def test_removes_watcher(
        self, mock_jira_client: MagicMock, watcher_tools: dict
    ) -> None:
        mock_jira_client.delete.return_value = None

        result = watcher_tools["jira_remove_watcher"](issue_key="PROJ-42", username="alice")

        mock_jira_client.delete.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/watchers", params={"username": "alice"}
        )
        assert json.loads(result) == {"deleted": True, "issue_key": "PROJ-42", "username": "alice"}
