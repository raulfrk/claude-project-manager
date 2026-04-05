"""Tests for Jira attachment tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.attachments import register


@pytest.fixture()
def attachment_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraAddAttachment:
    def test_posts_multipart(
        self, mock_jira_client: MagicMock, attachment_tools: dict
    ) -> None:
        mock_jira_client.post_multipart.return_value = [{"id": "10001", "filename": "report.pdf"}]

        result = attachment_tools["jira_add_attachment"](
            issue_key="PROJ-42", file_path="/tmp/report.pdf"
        )

        mock_jira_client.post_multipart.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42/attachments",
            file_path="/tmp/report.pdf",
        )
        assert json.loads(result) == [{"id": "10001", "filename": "report.pdf"}]


class TestJiraListAttachments:
    def test_returns_attachment_list(
        self, mock_jira_client: MagicMock, attachment_tools: dict
    ) -> None:
        attachments = [{"id": "10001", "filename": "report.pdf"}]
        mock_jira_client.get.return_value = {"fields": {"attachment": attachments}}

        result = attachment_tools["jira_list_attachments"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with(
            "/rest/api/2/issue/PROJ-42", params={"fields": "attachment"}
        )
        assert json.loads(result) == attachments

    def test_returns_empty_when_no_attachments(
        self, mock_jira_client: MagicMock, attachment_tools: dict
    ) -> None:
        mock_jira_client.get.return_value = {"fields": {}}

        result = attachment_tools["jira_list_attachments"](issue_key="PROJ-42")

        assert json.loads(result) == []


class TestJiraDeleteAttachment:
    def test_deletes_attachment(
        self, mock_jira_client: MagicMock, attachment_tools: dict
    ) -> None:
        mock_jira_client.delete.return_value = None

        result = attachment_tools["jira_delete_attachment"](attachment_id="10001")

        mock_jira_client.delete.assert_called_once_with("/rest/api/2/attachment/10001")
        assert json.loads(result) == {"deleted": True, "attachment_id": "10001"}
