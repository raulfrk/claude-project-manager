"""Tests for Jira issue tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.lib.config import JiraConfig
from server.tools.issues import register


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    """Register issue tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraSearch:
    def test_passes_jql_and_params(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        search_result = {"issues": [{"key": "PROJ-1"}], "total": 1}
        mock_jira_client.get.return_value = search_result

        result = issue_tools["jira_search"](jql="project = PROJ", max_results=10, start_at=5)

        mock_jira_client.get.assert_called_once_with(
            "/rest/api/2/search",
            params={
                "jql": "project = PROJ",
                "maxResults": 10,
                "startAt": 5,
                "fields": "summary,description,priority,assignee,labels,duedate,status,issuetype,parent,subtasks",
            },
        )
        assert json.loads(result) == search_result

    def test_uses_default_params(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_search"](jql="status = Open")

        _, kwargs = mock_jira_client.get.call_args
        assert kwargs["params"]["maxResults"] == 50
        assert kwargs["params"]["startAt"] == 0


class TestJiraGetIssue:
    def test_fetches_issue_by_key(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        issue_data = {"key": "PROJ-42", "fields": {"summary": "Fix bug"}}
        mock_jira_client.get.return_value = issue_data

        result = issue_tools["jira_get_issue"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42")
        assert json.loads(result) == issue_data


class TestJiraGetIssueComments:
    def test_fetches_comments_by_issue_key(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        comments_data = {"comments": [{"body": "Looks good"}], "total": 1}
        mock_jira_client.get.return_value = comments_data

        result = issue_tools["jira_get_issue_comments"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42/comment")
        assert json.loads(result) == comments_data


class TestJiraGetEpicIssues:
    def test_searches_with_parent_jql(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        epic_result = {"issues": [{"key": "PROJ-10"}], "total": 1}
        mock_jira_client.get.return_value = epic_result

        result = issue_tools["jira_get_epic_issues"](epic_key="PROJ-5", max_results=25)

        call_args = mock_jira_client.get.call_args
        assert call_args[0][0] == "/rest/api/2/search"
        params = call_args[1]["params"]
        assert "parent = PROJ-5" in params["jql"]
        assert params["maxResults"] == 25
        assert json.loads(result) == epic_result

    def test_default_max_results(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_epic_issues"](epic_key="PROJ-5")

        params = mock_jira_client.get.call_args[1]["params"]
        assert params["maxResults"] == 50


class TestJiraGetUserIssues:
    def test_uses_explicit_username_and_project_keys(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=["OTHER"],
            default_user="default_user",
        )
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_user_issues"](
            username="alice", project_keys=["PROJ", "DEV"], max_results=10
        )

        params = mock_jira_client.get.call_args[1]["params"]
        jql = params["jql"]
        assert "assignee = alice" in jql
        assert "project in (PROJ, DEV)" in jql
        assert "status not in (Done, Closed, Resolved)" in jql
        assert params["maxResults"] == 10

    def test_falls_back_to_config_defaults(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=["PROJ", "DEV"],
            default_user="config_user",
        )
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_user_issues"]()

        params = mock_jira_client.get.call_args[1]["params"]
        jql = params["jql"]
        assert "assignee = config_user" in jql
        assert "project in (PROJ, DEV)" in jql

    def test_no_username_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            default_user="",
        )

        result = issue_tools["jira_get_user_issues"]()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "No username" in parsed["error"]

    def test_no_project_keys_omits_project_clause(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=[],
            default_user="alice",
        )
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_user_issues"](username="alice")

        params = mock_jira_client.get.call_args[1]["params"]
        jql = params["jql"]
        assert "project in" not in jql
