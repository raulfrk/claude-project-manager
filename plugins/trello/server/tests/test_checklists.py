"""Unit tests for checklist tool error handling."""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from server.lib.client import TrelloAPIError
from server.tools.checklists import register


@pytest.fixture()
def checklist_tools(mock_trello_client):
    """Register checklist tools on a test FastMCP and return tool functions."""
    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestDeleteChecklistErrorHandling:
    def test_404_returns_warning(self, checklist_tools, mock_trello_client) -> None:
        mock_trello_client.delete.side_effect = TrelloAPIError(404, "not found")

        result = checklist_tools["delete_checklist"]("cl1")

        parsed = json.loads(result)
        assert parsed["warning"] == "checklist not found or already deleted"
        assert parsed["checklist_id"] == "cl1"

    def test_non_404_error_reraised(self, checklist_tools, mock_trello_client) -> None:
        mock_trello_client.delete.side_effect = TrelloAPIError(500, "server error")

        with pytest.raises(TrelloAPIError) as exc_info:
            checklist_tools["delete_checklist"]("cl1")
        assert exc_info.value.status_code == 500

    def test_success_returns_deleted(self, checklist_tools, mock_trello_client) -> None:
        mock_trello_client.delete.return_value = {}

        result = checklist_tools["delete_checklist"]("cl1")

        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["checklist_id"] == "cl1"
