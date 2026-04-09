"""Tests for Trello board tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.boards import register


@pytest.fixture()
def board_tools(mock_trello_client: MagicMock) -> dict[str, callable]:
    """Register board tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    # Extract the tool functions from the registered tools
    tools: dict[str, callable] = {}
    for name, tool in app._tool_manager._tools.items():
        tools[name] = tool.fn
    return tools


class TestListBoards:
    def test_returns_boards(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        boards_data = [{"id": "b1", "name": "Project"}, {"id": "b2", "name": "Personal"}]
        mock_trello_client.get.return_value = boards_data

        result = board_tools["list_boards"]()

        mock_trello_client.get.assert_called_once_with("/members/me/boards")
        assert json.loads(result) == boards_data

    def test_returns_empty_list(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        mock_trello_client.get.return_value = []
        result = board_tools["list_boards"]()
        assert json.loads(result) == []


class TestListBoardsWhitelistFiltering:
    def test_filters_to_allowed_boards(
        self,
        mock_trello_client: MagicMock,
        board_tools: dict,
    ) -> None:
        mock_trello_client._config.allowed_board_ids = ["b1"]
        mock_trello_client.get.return_value = [
            {"id": "b1", "name": "Allowed"},
            {"id": "b2", "name": "Blocked"},
        ]

        result = board_tools["list_boards"]()

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "b1"

    def test_empty_whitelist_returns_nothing(
        self,
        mock_trello_client: MagicMock,
        board_tools: dict,
    ) -> None:
        mock_trello_client._config.allowed_board_ids = ["b99"]
        mock_trello_client.get.return_value = [
            {"id": "b1", "name": "Board"},
        ]

        result = board_tools["list_boards"]()

        parsed = json.loads(result)
        assert parsed == []


class TestGetBoard:
    def test_returns_single_board(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        board_data = {"id": "b1", "name": "Project", "desc": "A board"}
        mock_trello_client.get.return_value = board_data

        result = board_tools["get_board"]("b1")

        mock_trello_client.get.assert_called_once_with("/boards/b1")
        assert json.loads(result) == board_data


class TestUpdateBoard:
    def test_updates_name(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        updated = {"id": "b1", "name": "Renamed"}
        mock_trello_client.put.return_value = updated

        result = board_tools["update_board"]("b1", name="Renamed")

        mock_trello_client.put.assert_called_once_with("/boards/b1", params={"name": "Renamed"})
        assert json.loads(result) == updated

    def test_updates_desc(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        mock_trello_client.put.return_value = {"id": "b1", "desc": "New desc"}
        result = board_tools["update_board"]("b1", desc="New desc")
        mock_trello_client.put.assert_called_once_with("/boards/b1", params={"desc": "New desc"})
        assert json.loads(result)["desc"] == "New desc"

    def test_updates_both(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        mock_trello_client.put.return_value = {"id": "b1"}
        board_tools["update_board"]("b1", name="N", desc="D")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {"name": "N", "desc": "D"}

    def test_omits_none_params(self, mock_trello_client: MagicMock, board_tools: dict) -> None:
        mock_trello_client.put.return_value = {"id": "b1"}
        board_tools["update_board"]("b1")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {}
