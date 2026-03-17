"""Tests for Trello list tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.lists import register


@pytest.fixture()
def list_tools(mock_trello_client: MagicMock) -> dict[str, callable]:
    """Register list tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    tools: dict[str, callable] = {}
    for name, tool in app._tool_manager._tools.items():
        tools[name] = tool.fn
    return tools


class TestGetLists:
    def test_returns_lists(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        lists_data = [
            {"id": "l1", "name": "To Do"},
            {"id": "l2", "name": "Done"},
        ]
        mock_trello_client.get.return_value = lists_data

        result = list_tools["get_lists"]("board1")

        mock_trello_client.get.assert_called_once_with("/boards/board1/lists")
        assert json.loads(result) == lists_data

    def test_returns_empty_list(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        mock_trello_client.get.return_value = []
        result = list_tools["get_lists"]("board1")
        assert json.loads(result) == []


class TestGetList:
    def test_returns_single_list(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        list_data = {"id": "l1", "name": "To Do", "closed": False}
        mock_trello_client.get.return_value = list_data

        result = list_tools["get_list"]("l1")

        mock_trello_client.get.assert_called_once_with("/lists/l1")
        assert json.loads(result) == list_data


class TestCreateList:
    def test_creates_list(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        created = {"id": "l3", "name": "In Progress", "idBoard": "board1"}
        mock_trello_client.post.return_value = created

        result = list_tools["create_list"]("In Progress", "board1")

        mock_trello_client.post.assert_called_once_with(
            "/lists", params={"name": "In Progress", "idBoard": "board1"}
        )
        assert json.loads(result) == created


class TestUpdateList:
    def test_updates_name(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        updated = {"id": "l1", "name": "Renamed"}
        mock_trello_client.put.return_value = updated

        result = list_tools["update_list"]("l1", name="Renamed")

        mock_trello_client.put.assert_called_once_with(
            "/lists/l1", params={"name": "Renamed"}
        )
        assert json.loads(result) == updated

    def test_updates_closed(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "l1", "closed": True}
        result = list_tools["update_list"]("l1", closed=True)
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"]["closed"] is True
        assert json.loads(result)["closed"] is True

    def test_updates_both(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "l1"}
        list_tools["update_list"]("l1", name="N", closed=False)
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {"name": "N", "closed": False}

    def test_none_params_omitted(
        self, mock_trello_client: MagicMock, list_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "l1"}
        list_tools["update_list"]("l1")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {}
