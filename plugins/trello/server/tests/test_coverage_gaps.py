"""Tests filling coverage gaps identified by the test audit.

Covers:
- trello_verify_checklist_item (0 coverage -> full coverage)
- delete_checklist non-404 re-raise
- batch_update_checklist_items empty list
- batch_create_cards: all items fail validation
- batch_add_checklist_items: item with no 'name' key at all
- list_boards non-list/non-dict responses
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.boards import register as register_boards
from server.tools.cards import register as register_cards
from server.tools.checklists import register as register_checklists


def _collect_tools(register_fn: callable, mock_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register_fn(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


# ========== trello_verify_checklist_item (0 -> full coverage) ==========


class TestVerifyChecklistItem:
    def test_item_found_complete(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {
                "id": "cl1",
                "checkItems": [
                    {"id": "ci1", "state": "complete", "name": "Task A"},
                    {"id": "ci2", "state": "incomplete", "name": "Task B"},
                ],
            }
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is True
        assert result["item_id"] == "ci1"
        assert result["state"] == "complete"
        assert result["name"] == "Task A"

    def test_item_found_incomplete(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {
                "id": "cl1",
                "checkItems": [
                    {"id": "ci2", "state": "incomplete", "name": "Task B"},
                ],
            }
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci2"))

        assert result["verified"] is True
        assert result["state"] == "incomplete"
        assert result["name"] == "Task B"

    def test_item_not_found(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {
                "id": "cl1",
                "checkItems": [
                    {"id": "ci1", "state": "complete", "name": "Task A"},
                ],
            }
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci_missing"))

        assert result["verified"] is False
        assert result["item_id"] == "ci_missing"
        assert result["state"] == "unknown"
        assert result["name"] == ""

    def test_empty_checklists(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = []

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is False

    def test_non_list_response(self, mock_trello_client: MagicMock) -> None:
        """When checklists endpoint returns non-list, treat as empty."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = {"error": "unexpected"}

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is False

    def test_non_dict_checklist_skipped(self, mock_trello_client: MagicMock) -> None:
        """Non-dict items in checklists list are skipped."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            "not-a-dict",
            {"id": "cl1", "checkItems": [{"id": "ci1", "state": "complete", "name": "A"}]},
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is True
        assert result["item_id"] == "ci1"

    def test_non_list_check_items_skipped(self, mock_trello_client: MagicMock) -> None:
        """Checklist with non-list checkItems is skipped."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {"id": "cl1", "checkItems": "not-a-list"},
            {"id": "cl2", "checkItems": [{"id": "ci1", "state": "incomplete", "name": "B"}]},
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is True
        assert result["name"] == "B"

    def test_non_dict_check_item_skipped(self, mock_trello_client: MagicMock) -> None:
        """Non-dict items in checkItems are skipped."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {
                "id": "cl1",
                "checkItems": [
                    "not-a-dict",
                    {"id": "ci1", "state": "complete", "name": "C"},
                ],
            },
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is True

    def test_missing_state_defaults_to_incomplete(self, mock_trello_client: MagicMock) -> None:
        """Item without 'state' key defaults to 'incomplete'."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {"id": "cl1", "checkItems": [{"id": "ci1", "name": "No state"}]},
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is True
        assert result["state"] == "incomplete"

    def test_missing_name_defaults_to_empty(self, mock_trello_client: MagicMock) -> None:
        """Item without 'name' key defaults to empty string."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.get.return_value = [
            {"id": "cl1", "checkItems": [{"id": "ci1", "state": "complete"}]},
        ]

        result = json.loads(tools["trello_verify_checklist_item"]("c1", "ci1"))

        assert result["verified"] is True
        assert result["name"] == ""


# ========== delete_checklist: non-404 re-raise ==========


class TestDeleteChecklistNon404:
    def test_non_404_exception_reraises(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.delete.side_effect = RuntimeError("Trello API error 500: server error")

        with pytest.raises(RuntimeError, match="500"):
            tools["delete_checklist"]("cl1")


# ========== batch_update_checklist_items: empty list ==========


class TestBatchUpdateChecklistItemsEmpty:
    def test_empty_updates_list(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)

        result = json.loads(tools["batch_update_checklist_items"]("c1", []))

        assert result["successes"] == []
        assert result["failures"] == []


# ========== batch_add_checklist_items: missing 'name' key entirely ==========


class TestBatchAddChecklistItemsMissingNameKey:
    def test_no_name_key_recorded_as_failure(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.return_value = {"id": "ci1", "name": "Good"}

        result = json.loads(
            tools["batch_add_checklist_items"](
                "cl1",
                [{"checked": True}, {"name": "Good"}],
            )
        )

        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 0
        assert len(result["successes"]) == 1


# ========== batch_create_cards: all items fail validation ==========


class TestBatchCreateCardsAllFail:
    def test_all_cards_missing_required_fields(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_cards, mock_trello_client)

        result = json.loads(
            tools["batch_create_cards"](
                [
                    {"name": "No list"},
                    {"list_id": "list1"},
                    {},
                ]
            )
        )

        assert len(result["successes"]) == 0
        assert len(result["failures"]) == 3


# ========== list_boards edge cases ==========


class TestListBoardsEdgeCases:
    def test_non_list_response_returns_empty(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_boards, mock_trello_client)
        mock_trello_client.get.return_value = {"error": "unexpected"}

        result = json.loads(tools["list_boards"]())
        assert result == []

    def test_non_dict_items_filtered_with_whitelist(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_boards, mock_trello_client)
        mock_trello_client._config.allowed_board_ids = ["b1"]
        mock_trello_client.get.return_value = [
            "not-a-dict",
            {"id": "b1", "name": "Good"},
            42,
        ]

        result = json.loads(tools["list_boards"]())
        assert len(result) == 1
        assert result[0]["id"] == "b1"
