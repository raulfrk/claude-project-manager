"""Tests for Jira sprint tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.sprints import register


@pytest.fixture()
def sprint_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetSprints:
    def test_returns_sprints_without_state_filter(
        self, mock_jira_client: MagicMock, sprint_tools: dict
    ) -> None:
        data = {"values": [{"id": 1, "name": "Sprint 1", "state": "active"}]}
        mock_jira_client.get.return_value = data

        result = sprint_tools["jira_get_sprints"](board_id="10")

        mock_jira_client.get.assert_called_once_with(
            "/rest/agile/1.0/board/10/sprint", params=None
        )
        assert json.loads(result) == data

    def test_passes_state_filter(
        self, mock_jira_client: MagicMock, sprint_tools: dict
    ) -> None:
        data = {"values": [{"id": 1, "name": "Sprint 1", "state": "active"}]}
        mock_jira_client.get.return_value = data

        result = sprint_tools["jira_get_sprints"](board_id="10", state="active")

        mock_jira_client.get.assert_called_once_with(
            "/rest/agile/1.0/board/10/sprint", params={"state": "active"}
        )
        assert json.loads(result) == data


class TestJiraMoveToSprint:
    def test_moves_issues_to_sprint(
        self, mock_jira_client: MagicMock, sprint_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {}

        result = sprint_tools["jira_move_to_sprint"](
            sprint_id="5", issue_keys=["PROJ-1", "PROJ-2"]
        )

        mock_jira_client.post.assert_called_once_with(
            "/rest/agile/1.0/sprint/5/issue",
            json_body={"issues": ["PROJ-1", "PROJ-2"]},
        )
        parsed = json.loads(result)
        assert parsed == {"ok": True, "sprint_id": "5", "issues": ["PROJ-1", "PROJ-2"]}
