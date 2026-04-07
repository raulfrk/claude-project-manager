"""Tests for Jira label tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.labels import register


@pytest.fixture()
def label_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetLabels:
    def test_fetches_labels_with_default_max(
        self, mock_jira_client: MagicMock, label_tools: dict
    ) -> None:
        data = {"values": ["bug", "feature", "docs"], "total": 3}
        mock_jira_client.get.return_value = data

        result = label_tools["jira_get_labels"]()

        mock_jira_client.get.assert_called_once_with(
            "/rest/api/2/label", params={"maxResults": 1000}
        )
        assert json.loads(result) == data

    def test_custom_max_results(self, mock_jira_client: MagicMock, label_tools: dict) -> None:
        mock_jira_client.get.return_value = {"values": [], "total": 0}

        label_tools["jira_get_labels"](max_results=10)

        params = mock_jira_client.get.call_args[1]["params"]
        assert params["maxResults"] == 10
