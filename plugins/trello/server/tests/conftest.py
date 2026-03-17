"""Shared test fixtures for Trello MCP server tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.lib.client import TrelloClient

# All modules that import get_client and need to be patched.
_GET_CLIENT_LOCATIONS = [
    "server.lib.client.get_client",
    "server.tools.boards.get_client",
    "server.tools.cards.get_client",
    "server.tools.lists.get_client",
    "server.tools.labels.get_client",
    "server.tools.members.get_client",
    "server.tools.comments.get_client",
    "server.tools.checklists.get_client",
    "server.tools.attachments.get_client",
]


@pytest.fixture()
def mock_trello_client(mocker: pytest.MockerFixture) -> MagicMock:
    """Patch get_client() everywhere to return a shared mock TrelloClient."""
    mock_client = MagicMock(spec=TrelloClient)
    for loc in _GET_CLIENT_LOCATIONS:
        mocker.patch(loc, return_value=mock_client)
    return mock_client
