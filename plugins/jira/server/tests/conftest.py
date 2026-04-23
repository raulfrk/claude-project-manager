"""Shared test fixtures for Jira MCP server tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from test_contracts.fixtures import patch_get_client_everywhere

from server.lib.client import JiraClient
from server.lib.config import JiraConfig


@pytest.fixture()
def mock_jira_client(mocker: pytest.MockerFixture) -> MagicMock:
    """Patch get_client() across every tool module to return a shared mock.

    Tool modules are autodiscovered under ``server.tools`` — no hand-maintained
    location list to keep in sync when new tool modules are added.
    """
    mock_client = MagicMock(spec=JiraClient)
    # Provide a default config with empty whitelist so project tools work in tests
    mock_client._config = JiraConfig(
        personal_access_token="test_pat",
        base_url="https://jira.example.com",
        allowed_project_keys=[],
    )
    patch_get_client_everywhere(mocker, return_value=mock_client)
    return mock_client
