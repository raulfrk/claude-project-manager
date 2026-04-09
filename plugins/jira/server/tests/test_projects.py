"""Tests for Jira project tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.lib.config import JiraConfig
from server.tools.projects import register


@pytest.fixture()
def project_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    """Register project tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraListProjects:
    def test_non_list_api_response_returns_empty(
        self, mock_jira_client: MagicMock, project_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=["PROJ"],
        )
        mock_jira_client.get.return_value = {"error": "unexpected"}

        result = project_tools["jira_list_projects"]()

        parsed = json.loads(result)
        assert parsed == []

    def test_returns_filtered_projects(
        self, mock_jira_client: MagicMock, project_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=["PROJ", "DEV"],
        )
        all_projects = [
            {"key": "PROJ", "name": "Project"},
            {"key": "DEV", "name": "Development"},
            {"key": "SECRET", "name": "Secret"},
        ]
        mock_jira_client.get.return_value = all_projects

        result = project_tools["jira_list_projects"]()

        mock_jira_client.get.assert_called_once_with("/rest/api/2/project")
        parsed = json.loads(result)
        assert len(parsed) == 2
        keys = {p["key"] for p in parsed}
        assert keys == {"PROJ", "DEV"}

    def test_empty_whitelist_returns_error(
        self, mock_jira_client: MagicMock, project_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=[],
        )
        mock_jira_client.get.return_value = [{"key": "PROJ", "name": "Project"}]

        result = project_tools["jira_list_projects"]()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "whitelist" in parsed["error"].lower()


class TestJiraGetProject:
    def test_returns_project_data(self, mock_jira_client: MagicMock, project_tools: dict) -> None:
        project_data = {"key": "PROJ", "name": "Project", "lead": {"displayName": "Alice"}}
        mock_jira_client.get.return_value = project_data

        result = project_tools["jira_get_project"](project_key="PROJ")

        mock_jira_client.check_project_access.assert_called_once_with("PROJ")
        mock_jira_client.get.assert_called_once_with("/rest/api/2/project/PROJ")
        assert json.loads(result) == project_data

    def test_whitelist_check_blocks_access(
        self, mock_jira_client: MagicMock, project_tools: dict
    ) -> None:
        mock_jira_client.check_project_access.side_effect = RuntimeError(
            "Project 'SECRET' not in whitelist."
        )

        with pytest.raises(RuntimeError, match="not in whitelist"):
            project_tools["jira_get_project"](project_key="SECRET")
