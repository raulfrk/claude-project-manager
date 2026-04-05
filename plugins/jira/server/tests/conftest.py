"""Shared test fixtures for Jira MCP server tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.lib.client import JiraClient
from server.lib.config import JiraConfig

# All modules that import get_client and need to be patched.
_GET_CLIENT_LOCATIONS = [
    "server.lib.client.get_client",
    "server.tools.attachments.get_client",
    "server.tools.comments.get_client",
    "server.tools.components.get_client",
    "server.tools.issues.get_client",
    "server.tools.labels.get_client",
    "server.tools.links.get_client",
    "server.tools.metadata.get_client",
    "server.tools.projects.get_client",
    "server.tools.sprints.get_client",
    "server.tools.transitions.get_client",
    "server.tools.users.get_client",
    "server.tools.versions.get_client",
    "server.tools.watchers.get_client",
    "server.tools.worklogs.get_client",
]


@pytest.fixture()
def mock_jira_client(mocker: pytest.MockerFixture) -> MagicMock:
    """Patch get_client() everywhere to return a shared mock JiraClient."""
    mock_client = MagicMock(spec=JiraClient)
    # Provide a default config with empty whitelist so project tools work in tests
    mock_client._config = JiraConfig(
        personal_access_token="test_pat",
        base_url="https://jira.example.com",
        allowed_project_keys=[],
    )
    for loc in _GET_CLIENT_LOCATIONS:
        mocker.patch(loc, return_value=mock_client)
    return mock_client
