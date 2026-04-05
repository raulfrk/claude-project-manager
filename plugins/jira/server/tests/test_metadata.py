"""Tests for Jira metadata tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.metadata import register


@pytest.fixture()
def metadata_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetIssueTypes:
    def test_fetches_issue_types(
        self, mock_jira_client: MagicMock, metadata_tools: dict
    ) -> None:
        data = [{"id": "1", "name": "Bug"}, {"id": "2", "name": "Task"}]
        mock_jira_client.get.return_value = data

        result = metadata_tools["jira_get_issue_types"]()

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issuetype")
        assert json.loads(result) == data


class TestJiraGetFields:
    def test_fetches_fields(
        self, mock_jira_client: MagicMock, metadata_tools: dict
    ) -> None:
        data = [{"id": "summary", "name": "Summary"}, {"id": "customfield_10001", "name": "Sprint"}]
        mock_jira_client.get.return_value = data

        result = metadata_tools["jira_get_fields"]()

        mock_jira_client.get.assert_called_once_with("/rest/api/2/field")
        assert json.loads(result) == data


class TestJiraGetPriorities:
    def test_fetches_priorities(
        self, mock_jira_client: MagicMock, metadata_tools: dict
    ) -> None:
        data = [{"id": "1", "name": "Highest"}, {"id": "2", "name": "High"}]
        mock_jira_client.get.return_value = data

        result = metadata_tools["jira_get_priorities"]()

        mock_jira_client.get.assert_called_once_with("/rest/api/2/priority")
        assert json.loads(result) == data


class TestJiraGetStatuses:
    def test_fetches_statuses(
        self, mock_jira_client: MagicMock, metadata_tools: dict
    ) -> None:
        data = [{"id": "1", "name": "Open"}, {"id": "3", "name": "In Progress"}]
        mock_jira_client.get.return_value = data

        result = metadata_tools["jira_get_statuses"]()

        mock_jira_client.get.assert_called_once_with("/rest/api/2/status")
        assert json.loads(result) == data
