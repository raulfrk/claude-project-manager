"""Tests for Jira worklog tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.worklogs import register


@pytest.fixture()
def worklog_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetWorklogs:
    def test_fetches_worklogs(self, mock_jira_client: MagicMock, worklog_tools: dict) -> None:
        data = {"worklogs": [{"id": "1", "timeSpent": "2h"}], "total": 1}
        mock_jira_client.get.return_value = data

        result = worklog_tools["jira_get_worklogs"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42/worklog")
        assert json.loads(result) == data

    def test_api_error_json(self, mock_jira_client: MagicMock, worklog_tools: dict) -> None:
        mock_jira_client.get.side_effect = RuntimeError("Jira API error: 500")

        result = worklog_tools["jira_get_worklogs"](issue_key="PROJ-42")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]


class TestJiraAddWorklog:
    def test_adds_worklog_without_comment(
        self, mock_jira_client: MagicMock, worklog_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {"id": "100", "timeSpent": "2h"}

        result = worklog_tools["jira_add_worklog"](issue_key="PROJ-42", time_spent="2h")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/worklog",
            json_body={"timeSpent": "2h"},
        )
        assert json.loads(result)["timeSpent"] == "2h"

    def test_adds_worklog_with_comment(
        self, mock_jira_client: MagicMock, worklog_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {
            "id": "101",
            "timeSpent": "1h",
            "comment": "Code review",
        }

        result = worklog_tools["jira_add_worklog"](
            issue_key="PROJ-42", time_spent="1h", comment="Code review"
        )

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/worklog",
            json_body={"timeSpent": "1h", "comment": "Code review"},
        )
        assert json.loads(result)["comment"] == "Code review"

    def test_api_error_json(self, mock_jira_client: MagicMock, worklog_tools: dict) -> None:
        mock_jira_client.post.side_effect = RuntimeError("Jira API error: 500")

        result = worklog_tools["jira_add_worklog"](issue_key="PROJ-42", time_spent="2h")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]


class TestJiraDeleteWorklog:
    def test_deletes_worklog(self, mock_jira_client: MagicMock, worklog_tools: dict) -> None:
        mock_jira_client.delete.return_value = None

        result = worklog_tools["jira_delete_worklog"](issue_key="PROJ-42", worklog_id="100")

        mock_jira_client.delete.assert_called_once_with("/rest/api/2/issue/PROJ-42/worklog/100")
        assert json.loads(result) == {"deleted": True, "issue_key": "PROJ-42", "worklog_id": "100"}

    def test_api_error_json(self, mock_jira_client: MagicMock, worklog_tools: dict) -> None:
        mock_jira_client.delete.side_effect = RuntimeError("Jira API error: 500")

        result = worklog_tools["jira_delete_worklog"](issue_key="PROJ-42", worklog_id="100")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]
