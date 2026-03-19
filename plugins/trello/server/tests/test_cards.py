"""Tests for Trello card tools (critical for trello-sync)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.cards import register


@pytest.fixture()
def card_tools(mock_trello_client: MagicMock) -> dict[str, callable]:
    """Register card tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    tools: dict[str, callable] = {}
    for name, tool in app._tool_manager._tools.items():
        tools[name] = tool.fn
    return tools


class TestGetCardsByListId:
    def test_returns_cards(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        cards_data = [
            {"id": "c1", "name": "Card 1"},
            {"id": "c2", "name": "Card 2"},
        ]
        mock_trello_client.get.return_value = cards_data

        result = card_tools["get_cards_by_list_id"]("list1")

        mock_trello_client.get.assert_called_once_with("/lists/list1/cards")
        assert json.loads(result) == cards_data

    def test_returns_empty_list(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.get.return_value = []
        result = card_tools["get_cards_by_list_id"]("list1")
        assert json.loads(result) == []


class TestGetCard:
    def test_returns_card(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        card_data = {"id": "c1", "name": "My Card", "desc": "Details"}
        mock_trello_client.get.return_value = card_data

        result = card_tools["get_card"]("c1")

        mock_trello_client.get.assert_called_once_with("/cards/c1")
        assert json.loads(result) == card_data


class TestAddCardToList:
    def test_adds_card_minimal(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        created = {"id": "c3", "name": "New Card", "idList": "list1"}
        mock_trello_client.post.return_value = created

        result = card_tools["add_card_to_list"]("list1", "New Card")

        mock_trello_client.post.assert_called_once_with(
            "/cards", params={"idList": "list1", "name": "New Card"}
        )
        assert json.loads(result) == created

    def test_adds_card_with_desc(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c3"}
        card_tools["add_card_to_list"]("list1", "Card", desc="A description")
        _, kwargs = mock_trello_client.post.call_args
        assert kwargs["params"]["desc"] == "A description"

    def test_adds_card_with_due(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c3"}
        card_tools["add_card_to_list"]("list1", "Card", due="2026-04-01")
        _, kwargs = mock_trello_client.post.call_args
        assert kwargs["params"]["due"] == "2026-04-01"

    def test_adds_card_with_all_fields(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c3"}
        card_tools["add_card_to_list"]("list1", "Card", desc="D", due="2026-04-01")
        _, kwargs = mock_trello_client.post.call_args
        assert kwargs["params"] == {
            "idList": "list1",
            "name": "Card",
            "desc": "D",
            "due": "2026-04-01",
        }

    def test_empty_desc_omitted(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c3"}
        card_tools["add_card_to_list"]("list1", "Card", desc="")
        _, kwargs = mock_trello_client.post.call_args
        assert "desc" not in kwargs["params"]

    def test_none_due_omitted(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c3"}
        card_tools["add_card_to_list"]("list1", "Card")
        _, kwargs = mock_trello_client.post.call_args
        assert "due" not in kwargs["params"]


class TestUpdateCardDetails:
    def test_updates_name(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        updated = {"id": "c1", "name": "Updated"}
        mock_trello_client.put.return_value = updated

        result = card_tools["update_card_details"]("c1", name="Updated")

        mock_trello_client.put.assert_called_once_with(
            "/cards/c1", params={"name": "Updated"}
        )
        assert json.loads(result) == updated

    def test_updates_desc(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "c1"}
        card_tools["update_card_details"]("c1", desc="New desc")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"]["desc"] == "New desc"

    def test_updates_due(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "c1"}
        card_tools["update_card_details"]("c1", due="2026-12-31")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"]["due"] == "2026-12-31"

    def test_updates_closed(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "c1", "closed": True}
        result = card_tools["update_card_details"]("c1", closed=True)
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"]["closed"] is True
        assert json.loads(result)["closed"] is True

    def test_updates_all_fields(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "c1"}
        card_tools["update_card_details"](
            "c1", name="N", desc="D", due="2026-01-01", closed=False
        )
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {
            "name": "N",
            "desc": "D",
            "due": "2026-01-01",
            "closed": False,
        }

    def test_none_fields_omitted(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.put.return_value = {"id": "c1"}
        card_tools["update_card_details"]("c1")
        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"] == {}


class TestMoveCard:
    def test_moves_card(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        moved = {"id": "c1", "idList": "list2"}
        mock_trello_client.put.return_value = moved

        result = card_tools["move_card"]("c1", "list2")

        mock_trello_client.put.assert_called_once_with(
            "/cards/c1", params={"idList": "list2"}
        )
        assert json.loads(result) == moved


class TestArchiveCard:
    def test_archives_card(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        archived = {"id": "c1", "closed": True}
        mock_trello_client.put.return_value = archived

        result = card_tools["archive_card"]("c1")

        mock_trello_client.put.assert_called_once_with(
            "/cards/c1", params={"closed": True}
        )
        assert json.loads(result) == archived


class TestDeleteCard:
    def test_deletes_card(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.delete.return_value = None

        result = card_tools["delete_card"]("c1")

        mock_trello_client.delete.assert_called_once_with("/cards/c1")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["card_id"] == "c1"


class TestBatchCreateCards:
    def test_creates_multiple_cards(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.side_effect = [
            {"id": "c10", "name": "Card A", "idList": "list1"},
            {"id": "c11", "name": "Card B", "idList": "list2"},
        ]

        result = card_tools["batch_create_cards"]([
            {"list_id": "list1", "name": "Card A"},
            {"list_id": "list2", "name": "Card B", "desc": "Description B"},
        ])

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0
        assert parsed["successes"][0]["id"] == "c10"
        assert parsed["successes"][1]["id"] == "c11"

        calls = mock_trello_client.post.call_args_list
        assert calls[0] == (("/cards",), {"params": {"idList": "list1", "name": "Card A"}})
        assert calls[1] == (
            ("/cards",),
            {"params": {"idList": "list2", "name": "Card B", "desc": "Description B"}},
        )

    def test_with_due_date(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c10"}

        result = card_tools["batch_create_cards"]([
            {"list_id": "list1", "name": "Card A", "due": "2026-04-01"},
        ])

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 1
        _, kwargs = mock_trello_client.post.call_args
        assert kwargs["params"]["due"] == "2026-04-01"

    def test_missing_list_id_recorded_as_failure(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c10"}

        result = card_tools["batch_create_cards"]([
            {"name": "No List"},
            {"list_id": "list1", "name": "Good Card"},
        ])

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert parsed["failures"][0]["index"] == 0
        assert "Missing" in parsed["failures"][0]["error"]
        assert len(parsed["successes"]) == 1

    def test_missing_name_recorded_as_failure(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        result = card_tools["batch_create_cards"]([
            {"list_id": "list1"},
        ])

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "Missing" in parsed["failures"][0]["error"]

    def test_api_error_captured_as_failure(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.side_effect = [
            RuntimeError("Trello API error 500"),
            {"id": "c11", "name": "Card B"},
        ]

        result = card_tools["batch_create_cards"]([
            {"list_id": "list1", "name": "Fails"},
            {"list_id": "list1", "name": "Card B"},
        ])

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "500" in parsed["failures"][0]["error"]
        assert len(parsed["successes"]) == 1

    def test_empty_cards_list(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        result = card_tools["batch_create_cards"]([])

        parsed = json.loads(result)
        assert parsed["successes"] == []
        assert parsed["failures"] == []

    def test_empty_desc_omitted(
        self, mock_trello_client: MagicMock, card_tools: dict
    ) -> None:
        mock_trello_client.post.return_value = {"id": "c10"}

        card_tools["batch_create_cards"]([
            {"list_id": "list1", "name": "Card A", "desc": ""},
        ])

        _, kwargs = mock_trello_client.post.call_args
        assert "desc" not in kwargs["params"]
