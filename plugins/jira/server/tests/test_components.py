"""Tests for Jira component tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.components import register


@pytest.fixture()
def component_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetComponents:
    def test_fetches_components(
        self, mock_jira_client: MagicMock, component_tools: dict
    ) -> None:
        data = [{"id": "1", "name": "Backend"}, {"id": "2", "name": "Frontend"}]
        mock_jira_client.get.return_value = data

        result = component_tools["jira_get_components"](project_key="PROJ")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/project/PROJ/components")
        assert json.loads(result) == data


class TestJiraCreateComponent:
    def test_creates_component_without_description(
        self, mock_jira_client: MagicMock, component_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {"id": "3", "name": "API"}

        result = component_tools["jira_create_component"](project_key="PROJ", name="API")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/component",
            json_body={"project": "PROJ", "name": "API"},
        )
        assert json.loads(result) == {"id": "3", "name": "API"}

    def test_creates_component_with_description(
        self, mock_jira_client: MagicMock, component_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {"id": "4", "name": "Auth", "description": "Auth module"}

        result = component_tools["jira_create_component"](
            project_key="PROJ", name="Auth", description="Auth module"
        )

        call_body = mock_jira_client.post.call_args[1]["json_body"]
        assert call_body["description"] == "Auth module"
