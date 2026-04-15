"""Tests filling coverage gaps identified by the test audit.

Covers:
- trello_verify_checklist_item (0 coverage -> full coverage)
- delete_checklist non-404 re-raise
- batch_update_checklist_items empty list
- batch_create_cards: all items fail validation
- batch_add_checklist_items: item with no 'name' key at all
- list_boards non-list/non-dict responses
- batch op narrowed exception handling (RuntimeError, httpx.HTTPError, propagation)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
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


# ========== update_checklist_item (batch mode): empty list ==========


class TestUpdateChecklistItemBatchEmpty:
    def test_empty_updates_list(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)

        result = json.loads(tools["update_checklist_item"]("c1", updates=[]))

        assert result["successes"] == []
        assert result["failures"] == []


# ========== add_checklist_item (batch mode): missing 'name' key entirely ==========


class TestAddChecklistItemBatchMissingNameKey:
    def test_no_name_key_recorded_as_failure(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.return_value = {"id": "ci1", "name": "Good"}

        result = json.loads(
            tools["add_checklist_item"](
                "cl1",
                items=[{"checked": True}, {"name": "Good"}],
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


# ========== add_checklist_item (batch mode): exception paths ==========


class TestAddChecklistItemBatchExceptionPaths:
    def test_runtime_error_captured_in_failures(self, mock_trello_client: MagicMock) -> None:
        """RuntimeError mid-batch is captured; subsequent items still process."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.side_effect = [
            RuntimeError("Trello API error 400: bad request"),
            {"id": "ci2", "name": "Item 2"},
        ]

        result = json.loads(
            tools["add_checklist_item"](
                "cl1",
                items=[{"name": "Item 1"}, {"name": "Item 2"}],
            )
        )

        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 0
        assert "400" in result["failures"][0]["error"]
        assert len(result["successes"]) == 1

    def test_httpx_error_captured_in_failures(self, mock_trello_client: MagicMock) -> None:
        """httpx.HTTPError is captured in failures."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.side_effect = httpx.ConnectError("connection refused")

        result = json.loads(tools["add_checklist_item"]("cl1", items=[{"name": "Item 1"}]))

        assert len(result["failures"]) == 1
        assert "connection refused" in result["failures"][0]["error"]


# ========== update_checklist_item (batch mode): exception paths ==========


class TestUpdateChecklistItemBatchExceptionPaths:
    def test_runtime_error_captured_in_failures(self, mock_trello_client: MagicMock) -> None:
        """RuntimeError mid-batch is captured; subsequent items still process."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.put.side_effect = [
            RuntimeError("Trello API error 404: not found"),
            {"id": "ci2", "state": "complete"},
        ]

        result = json.loads(
            tools["update_checklist_item"](
                "c1",
                updates=[
                    {"checklist_id": "cl1", "item_id": "ci1", "state": "complete"},
                    {"checklist_id": "cl1", "item_id": "ci2", "state": "complete"},
                ],
            )
        )

        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 0
        assert "404" in result["failures"][0]["error"]
        assert len(result["successes"]) == 1

    def test_httpx_error_captured_in_failures(self, mock_trello_client: MagicMock) -> None:
        """httpx.HTTPError is captured in failures."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.put.side_effect = httpx.TimeoutException("request timed out")

        result = json.loads(
            tools["update_checklist_item"](
                "c1",
                updates=[{"checklist_id": "cl1", "item_id": "ci1", "state": "complete"}],
            )
        )

        assert len(result["failures"]) == 1
        assert "timed out" in result["failures"][0]["error"]


# ========== trello_batch_archive_cards: httpx.HTTPError path ==========


class TestBatchArchiveCardsHttpError:
    def test_httpx_error_captured_in_failed(self, mock_trello_client: MagicMock) -> None:
        """httpx.HTTPError is captured in failed list."""
        tools = _collect_tools(register_cards, mock_trello_client)
        mock_trello_client.put.side_effect = httpx.ConnectError("connection refused")

        result = json.loads(tools["trello_batch_archive_cards"](["card1"]))

        assert len(result["failed"]) == 1
        assert result["failed"][0]["card_id"] == "card1"
        assert "connection refused" in result["failed"][0]["error"]
        assert result["archived"] == []


# ========== batch_create_cards: httpx.HTTPError path ==========


class TestBatchCreateCardsHttpError:
    def test_httpx_error_captured_in_failures(self, mock_trello_client: MagicMock) -> None:
        """httpx.HTTPError is captured in failures."""
        tools = _collect_tools(register_cards, mock_trello_client)
        mock_trello_client.post.side_effect = httpx.ReadError("read error")

        result = json.loads(tools["batch_create_cards"]([{"list_id": "l1", "name": "Card 1"}]))

        assert len(result["failures"]) == 1
        assert result["failures"][0]["index"] == 0
        assert "read error" in result["failures"][0]["error"]
        assert result["successes"] == []


# ========== Programming errors propagate (not caught) ==========


class TestBatchOpProgrammingErrorPropagates:
    def test_type_error_propagates_from_batch_archive(self, mock_trello_client: MagicMock) -> None:
        """TypeError from client is NOT caught — it propagates."""
        tools = _collect_tools(register_cards, mock_trello_client)
        mock_trello_client.put.side_effect = TypeError("unexpected type")

        with pytest.raises(TypeError, match="unexpected type"):
            tools["trello_batch_archive_cards"](["card1"])

    def test_value_error_propagates_from_batch_create(self, mock_trello_client: MagicMock) -> None:
        """ValueError from client is NOT caught — it propagates."""
        tools = _collect_tools(register_cards, mock_trello_client)
        mock_trello_client.post.side_effect = ValueError("bad value")

        with pytest.raises(ValueError, match="bad value"):
            tools["batch_create_cards"]([{"list_id": "l1", "name": "Card 1"}])

    def test_key_error_propagates_from_add_checklist_item_batch(
        self, mock_trello_client: MagicMock
    ) -> None:
        """KeyError from client is NOT caught — it propagates."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.side_effect = KeyError("missing key")

        with pytest.raises(KeyError, match="missing key"):
            tools["add_checklist_item"]("cl1", items=[{"name": "Item 1"}])

    def test_attribute_error_propagates_from_update_checklist_item_batch(
        self, mock_trello_client: MagicMock
    ) -> None:
        """AttributeError from client is NOT caught — it propagates."""
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.put.side_effect = AttributeError("no such attr")

        with pytest.raises(AttributeError, match="no such attr"):
            tools["update_checklist_item"](
                "c1",
                updates=[{"checklist_id": "cl1", "item_id": "ci1", "state": "complete"}],
            )
