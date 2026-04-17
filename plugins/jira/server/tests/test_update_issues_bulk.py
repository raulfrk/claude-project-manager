"""Tests for jira_update_issues_bulk wrapper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools.issues import register


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict:
    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraUpdateIssuesBulk:
    def test_multi_item_updates(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issues_bulk"](
            updates=[
                {"key": "PROJ-1", "resolution": "Done"},
                {"key": "PROJ-2", "summary": "X", "priority": "High"},
            ]
        )
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        calls = mock_jira_client.put.call_args_list
        assert calls[0] == (
            ("/rest/api/2/issue/PROJ-1",),
            {"json_body": {"fields": {"resolution": {"name": "Done"}}}},
        )
        assert calls[1] == (
            ("/rest/api/2/issue/PROJ-2",),
            {"json_body": {"fields": {"summary": "X", "priority": {"name": "High"}}}},
        )

    def test_empty_updates_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issues_bulk"](updates=[])
        parsed = json.loads(result)
        assert parsed == {"error": "updates list is empty"}
        mock_jira_client.put.assert_not_called()

    def test_missing_key_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issues_bulk"](
            updates=[{"key": "PROJ-1", "summary": "S"}, {"summary": "X"}]
        )
        parsed = json.loads(result)
        assert parsed == {"error": "each update requires a non-empty key"}
        mock_jira_client.put.assert_not_called()

    def test_all_items_no_fields_returns_warning(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issues_bulk"](
            updates=[{"key": "PROJ-1"}, {"key": "PROJ-2"}]
        )
        parsed = json.loads(result)
        assert parsed == {"warning": "no fields to update in any item", "count": 2}
        mock_jira_client.put.assert_not_called()

    def test_mixed_empty_and_filled_items(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issues_bulk"](
            updates=[
                {"key": "PROJ-1", "resolution": "Done"},
                {"key": "PROJ-2"},  # filtered
                {"key": "PROJ-3", "summary": "X"},
            ]
        )
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert parsed["skipped_keys"] == ["PROJ-2"]
        assert mock_jira_client.put.call_count == 2
