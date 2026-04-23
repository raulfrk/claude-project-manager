"""Shared test fixtures for Trello MCP server tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from test_contracts.fixtures import patch_get_client_everywhere

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig


@pytest.fixture()
def mock_trello_client(mocker: pytest.MockerFixture) -> MagicMock:
    """Patch get_client() across every tool module to return a shared mock.

    Tool modules are autodiscovered under ``server.tools`` — no hand-maintained
    location list to keep in sync when new tool modules are added.
    """
    mock_client = MagicMock(spec=TrelloClient)
    # Provide a default config with empty whitelist so board tools work in tests
    mock_client._config = TrelloConfig(api_key="test_key", token="test_token", allowed_board_ids=[])
    patch_get_client_everywhere(mocker, return_value=mock_client)
    return mock_client
