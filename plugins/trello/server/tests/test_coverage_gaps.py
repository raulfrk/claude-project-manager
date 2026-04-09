"""Tests filling coverage gaps identified by the test audit.

Covers:
- trello_verify_checklist_item (0 coverage -> full coverage)
- delete_checklist non-404 re-raise
- Hook tool edge cases (non-dict responses, API errors, missing config)
- trello_verify_card_hook error paths
- batch_update_checklist_items empty list
- list_boards non-list/non-dict responses
- _resolve_list_id edge cases
- batch_create_cards: all items fail validation
- batch_add_checklist_items: item with no 'name' key at all
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.boards import register as register_boards
from server.tools.cards import register as register_cards
from server.tools.checklists import register as register_checklists
from server.tools.hooks import register as register_hooks


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


# ========== Hook tool edge cases ==========


class TestAddCardHookNonDictResponse:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_hooks(app)
        return app._tool_manager._tools["trello_add_card_hook"].fn

    def test_non_dict_card_response(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1", "default_list": "Active"},
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "Active"}]
        mock_trello_client.post.return_value = "not-a-dict"

        tool = self._get_tool()
        result = json.loads(tool(name="project"))
        assert "error" in result
        assert "Unexpected" in result["error"]


class TestAddTodoCardHookEdgeCases:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_hooks(app)
        return app._tool_manager._tools["trello_add_todo_card_hook"].fn

    def test_api_error_returns_error(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.side_effect = RuntimeError("API error 500")

        tool = self._get_tool()
        result = json.loads(tool(name="task"))
        assert "error" in result
        assert "500" in result["error"]

    def test_non_dict_card_response(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.return_value = "not-a-dict"

        tool = self._get_tool()
        result = json.loads(tool(name="task"))
        assert "error" in result
        assert "Unexpected" in result["error"]

    def test_default_tasks_list_when_no_mappings(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """When list_mappings is absent, defaults to 'proj-tasks'."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1"},
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.return_value = {"id": "card-1"}

        tool = self._get_tool()
        result = json.loads(tool(name="task"))
        assert result["card_id"] == "card-1"


class TestAddChildCardHookEdgeCases:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_hooks(app)
        return app._tool_manager._tools["trello_add_child_card_hook"].fn

    def test_api_error_returns_error(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.side_effect = RuntimeError("API error 429")

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", name="child"))
        assert "error" in result
        assert "429" in result["error"]

    def test_non_dict_card_response(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.return_value = "not-a-dict"

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", name="child"))
        assert "error" in result
        assert "Unexpected" in result["error"]

    def test_tasks_list_not_found(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "Other"}]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", name="child"))
        assert "error" in result
        assert "proj-tasks" in result["error"]

    def test_card_without_short_url_uses_url(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """When shortUrl is missing, falls back to 'url' key."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.side_effect = [
            {"id": "child-card", "url": "https://trello.com/c/long"},
            {"id": "attach-1"},
        ]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", name="child"))
        assert result["card_id"] == "child-card"
        # Verify attachment used the url fallback
        mock_trello_client.post.assert_any_call(
            "/cards/parent-1/attachments",
            params={"url": "https://trello.com/c/long", "name": "child"},
        )

    def test_attachment_failure_suppressed(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """Attachment errors are suppressed via contextlib.suppress."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.side_effect = [
            {"id": "child-card", "shortUrl": "https://trello.com/c/abc"},
            RuntimeError("Attachment API error"),  # attachment fails
        ]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", name="child"))
        # Card creation still succeeds despite attachment failure
        assert result["card_id"] == "child-card"


class TestBatchAddChildCardsHookEdgeCases:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_hooks(app)
        return app._tool_manager._tools["trello_batch_add_child_cards_hook"].fn

    def test_tasks_list_not_found(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "Other"}]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", items=["a"]))
        assert "error" in result
        assert "proj-tasks" in result["error"]

    def test_non_dict_card_response_recorded_as_failure(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.return_value = "not-a-dict"

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", items=["a"]))
        assert len(result["children"]) == 0
        assert len(result["failures"]) == 1
        assert "Unexpected" in result["failures"][0]["error"]

    def test_creates_cards_without_parent(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """When parent_card_id is None, no attachments are created."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.side_effect = [
            {"id": "card-a", "shortUrl": "https://trello.com/c/a"},
            {"id": "card-b", "shortUrl": "https://trello.com/c/b"},
        ]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id=None, items=["a", "b"]))
        assert len(result["children"]) == 2
        # Only 2 post calls (card creation), no attachment calls
        assert mock_trello_client.post.call_count == 2

    def test_empty_items_list(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="p1", items=[]))
        assert result["children"] == []
        assert result["failures"] == []

    def test_attachment_failure_suppressed(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """Attachment errors are suppressed for each card."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"tasks": "proj-tasks"},
            },
        )
        mock_trello_client.get.return_value = [{"id": "list-1", "name": "proj-tasks"}]
        mock_trello_client.post.side_effect = [
            {"id": "card-a", "shortUrl": "https://trello.com/c/a"},
            RuntimeError("attachment fail"),  # attachment for a fails
        ]

        tool = self._get_tool()
        result = json.loads(tool(parent_card_id="parent-1", items=["a"]))
        assert len(result["children"]) == 1
        assert result["children"][0]["card_id"] == "card-a"
        assert len(result["failures"]) == 0


# ========== trello_verify_card_hook edge cases ==========


class TestVerifyCardHookEdgeCases:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_hooks(app)
        return app._tool_manager._tools["trello_verify_card_hook"].fn

    def test_api_error_fetching_card(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        tool = self._get_tool()
        mock_trello_client.get.side_effect = RuntimeError("API error 500")

        result = json.loads(tool(card_id="card-1"))
        assert result["verified"] is False
        assert "500" in result["error"]

    def test_non_dict_card_response(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        tool = self._get_tool()
        mock_trello_client.get.return_value = "not-a-dict"

        result = json.loads(tool(card_id="card-1"))
        assert result["verified"] is False
        assert "Unexpected" in result["error"]

    def test_no_board_id_in_config(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        """When no board_id in config, in_done_list is False."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={},
        )
        mock_trello_client.get.return_value = {
            "id": "card-1",
            "name": "Task",
            "idList": "list-1",
            "closed": False,
        }

        tool = self._get_tool()
        result = json.loads(tool(card_id="card-1"))
        assert result["verified"] is True
        assert result["in_done_list"] is False

    def test_card_not_in_done_list(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={
                "default_board_id": "board-1",
                "list_mappings": {"done": "Done"},
            },
        )
        mock_trello_client.get.side_effect = [
            {"id": "card-1", "name": "Task", "idList": "other-list", "closed": False},
            [{"id": "done-list", "name": "Done"}],
        ]

        tool = self._get_tool()
        result = json.loads(tool(card_id="card-1"))
        assert result["verified"] is True
        assert result["in_done_list"] is False
        assert result["current_list_id"] == "other-list"

    def test_card_closed(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1"},
        )
        mock_trello_client.get.side_effect = [
            {"id": "card-1", "name": "Task", "idList": "list-1", "closed": True},
            [{"id": "done-list", "name": "Done"}],
        ]

        tool = self._get_tool()
        result = json.loads(tool(card_id="card-1"))
        assert result["verified"] is True
        assert result["closed"] is True


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


# ========== _resolve_list_id edge cases (tested via hooks) ==========


class TestResolveListIdEdgeCases:
    def _get_tool(self) -> callable:
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("test")
        register_hooks(app)
        return app._tool_manager._tools["trello_add_card_hook"].fn

    def test_board_lists_api_error(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        """When board lists API call fails, list resolves to empty string."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1", "default_list": "Active"},
        )
        mock_trello_client.get.side_effect = RuntimeError("API error")

        tool = self._get_tool()
        result = json.loads(tool(name="project"))
        assert "error" in result
        assert "Active" in result["error"]

    def test_non_list_board_response(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """When board lists returns non-list, list resolves to empty string."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1", "default_list": "Active"},
        )
        mock_trello_client.get.return_value = {"error": "bad response"}

        tool = self._get_tool()
        result = json.loads(tool(name="project"))
        assert "error" in result
        assert "Active" in result["error"]

    def test_non_dict_list_items_skipped(
        self, mock_trello_client: MagicMock, mocker: MagicMock
    ) -> None:
        """Non-dict items in board lists are skipped during resolution."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1", "default_list": "Active"},
        )
        mock_trello_client.get.return_value = [
            "not-a-dict",
            {"id": "list-1", "name": "Active"},
        ]
        mock_trello_client.post.return_value = {"id": "card-1"}

        tool = self._get_tool()
        result = json.loads(tool(name="project"))
        assert result["card_id"] == "card-1"

    def test_resolve_by_id_not_name(self, mock_trello_client: MagicMock, mocker: MagicMock) -> None:
        """List can be resolved by ID instead of name."""
        mocker.patch(
            "server.tools.hooks._get_trello_sync_config",
            return_value={"default_board_id": "board-1", "default_list": "list-direct-id"},
        )
        mock_trello_client.get.return_value = [
            {"id": "list-direct-id", "name": "Some Other Name"},
        ]
        mock_trello_client.post.return_value = {"id": "card-1"}

        tool = self._get_tool()
        result = json.loads(tool(name="project"))
        assert result["card_id"] == "card-1"
