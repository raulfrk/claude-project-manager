"""Tests for Jira issue link tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.links import register


@pytest.fixture()
def link_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraLinkIssues:
    def test_posts_issue_link(self, mock_jira_client: MagicMock, link_tools: dict) -> None:
        mock_jira_client.post.return_value = None

        result = link_tools["jira_link_issues"](
            inward_key="PROJ-1", outward_key="PROJ-2", link_type="Blocks"
        )

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issueLink",
            json_body={
                "type": {"name": "Blocks"},
                "inwardIssue": {"key": "PROJ-1"},
                "outwardIssue": {"key": "PROJ-2"},
            },
        )
        parsed = json.loads(result)
        assert parsed == {
            "ok": True,
            "inward_key": "PROJ-1",
            "outward_key": "PROJ-2",
            "link_type": "Blocks",
        }


class TestJiraGetLinkTypes:
    def test_fetches_link_types(self, mock_jira_client: MagicMock, link_tools: dict) -> None:
        data = {"issueLinkTypes": [{"id": "10000", "name": "Blocks"}]}
        mock_jira_client.get.return_value = data

        result = link_tools["jira_get_link_types"]()

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issueLinkType")
        assert json.loads(result) == data
