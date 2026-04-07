"""Tests for Trello label tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.labels import register


@pytest.fixture()
def label_tools(mock_trello_client: MagicMock) -> dict[str, callable]:
    """Register label tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    tools: dict[str, callable] = {}
    for name, tool in app._tool_manager._tools.items():
        tools[name] = tool.fn
    return tools


class TestGetLabels:
    def test_returns_labels(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        labels_data = [
            {"id": "lb1", "name": "Bug", "color": "red"},
            {"id": "lb2", "name": "Feature", "color": "green"},
        ]
        mock_trello_client.get.return_value = labels_data

        result = label_tools["get_labels"]("board1")

        mock_trello_client.get.assert_called_once_with("/boards/board1/labels")
        assert json.loads(result) == labels_data

    def test_returns_empty_list(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.get.return_value = []
        result = label_tools["get_labels"]("board1")
        assert json.loads(result) == []


class TestCreateLabel:
    def test_creates_label(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        created = {"id": "lb3", "name": "Urgent", "color": "red"}
        mock_trello_client.post.return_value = created

        result = label_tools["create_label"]("board1", "Urgent", "red")

        mock_trello_client.post.assert_called_once_with(
            "/labels",
            params={"name": "Urgent", "color": "red", "idBoard": "board1"},
        )
        assert json.loads(result) == created


class TestUpdateLabel:
    def test_updates_name(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        updated = {"id": "lb1", "name": "Critical"}
        mock_trello_client.put.return_value = updated

        result = label_tools["update_label"]("lb1", name="Critical")

        mock_trello_client.put.assert_called_once_with("/labels/lb1", params={"name": "Critical"})
        assert json.loads(result) == updated

    def test_updates_color(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.put.return_value = {"id": "lb1", "color": "blue"}
        result = label_tools["update_label"]("lb1", color="blue")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {"color": "blue"}
        assert json.loads(result)["color"] == "blue"

    def test_updates_both(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.put.return_value = {"id": "lb1"}
        label_tools["update_label"]("lb1", name="N", color="green")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {"name": "N", "color": "green"}

    def test_none_params_omitted(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.put.return_value = {"id": "lb1"}
        label_tools["update_label"]("lb1")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {}


class TestDeleteLabel:
    def test_deletes_label(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.delete.return_value = None

        result = label_tools["delete_label"]("lb1")

        mock_trello_client.delete.assert_called_once_with("/labels/lb1")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["label_id"] == "lb1"


class TestToggleCardLabel:
    def test_add_label_to_card(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.post.return_value = ["lb1", "lb2"]

        result = label_tools["toggle_card_label"]("c1", "lb2", "add")

        mock_trello_client.post.assert_called_once_with(
            "/cards/c1/idLabels", params={"value": "lb2"}
        )
        assert json.loads(result) == ["lb1", "lb2"]

    def test_remove_label_from_card(self, mock_trello_client: MagicMock, label_tools: dict) -> None:
        mock_trello_client.delete.return_value = None

        result = label_tools["toggle_card_label"]("c1", "lb1", "remove")

        mock_trello_client.delete.assert_called_once_with("/cards/c1/idLabels/lb1")
        parsed = json.loads(result)
        assert parsed["removed"] is True
        assert parsed["card_id"] == "c1"
        assert parsed["label_id"] == "lb1"

    def test_invalid_action_returns_error(
        self, mock_trello_client: MagicMock, label_tools: dict
    ) -> None:
        result = label_tools["toggle_card_label"]("c1", "lb1", "toggle")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid action" in parsed["error"]
