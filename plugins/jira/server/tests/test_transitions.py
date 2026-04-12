"""Tests for Jira transition tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.transitions import register


@pytest.fixture()
def transition_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetTransitions:
    def test_fetches_transitions(self, mock_jira_client: MagicMock, transition_tools: dict) -> None:
        data = {"transitions": [{"id": "11", "name": "To Do"}, {"id": "21", "name": "In Progress"}]}
        mock_jira_client.get.return_value = data

        result = transition_tools["jira_get_transitions"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42/transitions")
        assert json.loads(result) == data

    def test_returns_empty_transitions(
        self, mock_jira_client: MagicMock, transition_tools: dict
    ) -> None:
        mock_jira_client.get.return_value = {"transitions": []}

        result = transition_tools["jira_get_transitions"](issue_key="PROJ-99")

        assert json.loads(result) == {"transitions": []}

    def test_api_error_json(self, mock_jira_client: MagicMock, transition_tools: dict) -> None:
        mock_jira_client.get.side_effect = RuntimeError("Jira API error: 500")

        result = transition_tools["jira_get_transitions"](issue_key="PROJ-42")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]


class TestJiraTransitionIssue:
    def test_posts_transition_with_default_fields(
        self, mock_jira_client: MagicMock, transition_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = None

        result = transition_tools["jira_transition_issue"](issue_key="PROJ-42", transition_id="21")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/transitions",
            json_body={"transition": {"id": "21"}, "fields": {}},
        )
        assert json.loads(result) == {"ok": True, "issue_key": "PROJ-42", "transition_id": "21"}

    def test_posts_transition_with_custom_fields(
        self, mock_jira_client: MagicMock, transition_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = None
        fields = {"resolution": {"name": "Done"}}

        result = transition_tools["jira_transition_issue"](
            issue_key="PROJ-42", transition_id="31", fields_json=json.dumps(fields)
        )

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/transitions",
            json_body={"transition": {"id": "31"}, "fields": fields},
        )
        assert json.loads(result)["ok"] is True

    def test_invalid_fields_json_returns_error(
        self, mock_jira_client: MagicMock, transition_tools: dict
    ) -> None:
        result = transition_tools["jira_transition_issue"](
            issue_key="PROJ-42", transition_id="21", fields_json="bad json"
        )

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid fields JSON" in parsed["error"]
        mock_jira_client.post.assert_not_called()

    def test_api_error_json(self, mock_jira_client: MagicMock, transition_tools: dict) -> None:
        mock_jira_client.post.side_effect = RuntimeError("Jira API error 404: not found")

        result = transition_tools["jira_transition_issue"](issue_key="NOPE-1", transition_id="21")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "404" in parsed["error"]
