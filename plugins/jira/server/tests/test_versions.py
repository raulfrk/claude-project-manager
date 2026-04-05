"""Tests for Jira version tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.versions import register


@pytest.fixture()
def version_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraGetVersions:
    def test_fetches_versions(
        self, mock_jira_client: MagicMock, version_tools: dict
    ) -> None:
        data = [{"id": "1", "name": "1.0"}, {"id": "2", "name": "2.0"}]
        mock_jira_client.get.return_value = data

        result = version_tools["jira_get_versions"](project_key="PROJ")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/project/PROJ/versions")
        assert json.loads(result) == data


class TestJiraCreateVersion:
    def test_creates_version_with_required_fields(
        self, mock_jira_client: MagicMock, version_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {"id": "3", "name": "3.0"}

        result = version_tools["jira_create_version"](project_key="PROJ", name="3.0")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/version",
            json_body={"project": "PROJ", "name": "3.0"},
        )
        assert json.loads(result) == {"id": "3", "name": "3.0"}

    def test_creates_version_with_optional_fields(
        self, mock_jira_client: MagicMock, version_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {"id": "4", "name": "4.0"}

        version_tools["jira_create_version"](
            project_key="PROJ", name="4.0", description="Major release", release_date="2026-06-01"
        )

        call_body = mock_jira_client.post.call_args[1]["json_body"]
        assert call_body["description"] == "Major release"
        assert call_body["releaseDate"] == "2026-06-01"
