"""Tests for Jira comment tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.comments import register


@pytest.fixture()
def comment_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraAddComment:
    def test_posts_comment(self, mock_jira_client: MagicMock, comment_tools: dict) -> None:
        mock_jira_client.post.return_value = {"id": "100", "body": "Hello"}

        result = comment_tools["jira_add_comment"](issue_key="PROJ-1", body="Hello")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/PROJ-1/comment", json_body={"body": "Hello"}
        )
        assert json.loads(result) == {"id": "100", "body": "Hello"}

    def test_api_error_propagates(self, mock_jira_client: MagicMock, comment_tools: dict) -> None:
        mock_jira_client.post.side_effect = RuntimeError("Jira API error 403: forbidden")

        with pytest.raises(RuntimeError, match="403"):
            comment_tools["jira_add_comment"](issue_key="PROJ-1", body="Hello")


class TestJiraUpdateComment:
    def test_puts_updated_body(self, mock_jira_client: MagicMock, comment_tools: dict) -> None:
        mock_jira_client.put.return_value = {"id": "100", "body": "Updated"}

        result = comment_tools["jira_update_comment"](
            issue_key="PROJ-1", comment_id="100", body="Updated"
        )

        mock_jira_client.put.assert_called_once_with(
            "/rest/api/2/issue/PROJ-1/comment/100", json_body={"body": "Updated"}
        )
        assert json.loads(result) == {"id": "100", "body": "Updated"}

    def test_api_error_propagates(self, mock_jira_client: MagicMock, comment_tools: dict) -> None:
        mock_jira_client.put.side_effect = RuntimeError("Jira API error 404: not found")

        with pytest.raises(RuntimeError, match="404"):
            comment_tools["jira_update_comment"](
                issue_key="PROJ-1", comment_id="999", body="Updated"
            )


class TestJiraDeleteComment:
    def test_deletes_and_returns_confirmation(
        self, mock_jira_client: MagicMock, comment_tools: dict
    ) -> None:
        mock_jira_client.delete.return_value = None

        result = comment_tools["jira_delete_comment"](issue_key="PROJ-1", comment_id="100")

        mock_jira_client.delete.assert_called_once_with("/rest/api/2/issue/PROJ-1/comment/100")
        assert json.loads(result) == {
            "deleted": True,
            "issue_key": "PROJ-1",
            "comment_id": "100",
        }

    def test_api_error_propagates(self, mock_jira_client: MagicMock, comment_tools: dict) -> None:
        mock_jira_client.delete.side_effect = RuntimeError("Jira API error 404: not found")

        with pytest.raises(RuntimeError, match="404"):
            comment_tools["jira_delete_comment"](issue_key="PROJ-1", comment_id="999")
