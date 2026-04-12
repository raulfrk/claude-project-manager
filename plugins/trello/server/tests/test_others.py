"""Tests for members, comments, checklists, and attachments tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from server.tools.attachments import register as register_attachments
from server.tools.checklists import register as register_checklists
from server.tools.comments import register as register_comments
from server.tools.members import register as register_members


def _collect_tools(register_fn: callable, mock_client: MagicMock) -> dict[str, callable]:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register_fn(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


# ========== Members ==========


class TestGetBoardMembers:
    def test_returns_members(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_members, mock_trello_client)
        members_data = [{"id": "m1", "fullName": "Alice"}, {"id": "m2", "fullName": "Bob"}]
        mock_trello_client.get.return_value = members_data

        result = tools["get_board_members"]("board1")

        mock_trello_client.get.assert_called_once_with("/boards/board1/members")
        assert json.loads(result) == members_data

    def test_returns_empty(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_members, mock_trello_client)
        mock_trello_client.get.return_value = []
        result = tools["get_board_members"]("board1")
        assert json.loads(result) == []


class TestAddCardMember:
    def test_adds_member(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_members, mock_trello_client)
        mock_trello_client.post.return_value = ["m1", "m2"]

        result = tools["add_card_member"]("c1", "m2")

        mock_trello_client.post.assert_called_once_with(
            "/cards/c1/idMembers", params={"value": "m2"}
        )
        assert json.loads(result) == ["m1", "m2"]


class TestRemoveCardMember:
    def test_removes_member(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_members, mock_trello_client)
        mock_trello_client.delete.return_value = None

        result = tools["remove_card_member"]("c1", "m2")

        mock_trello_client.delete.assert_called_once_with("/cards/c1/idMembers/m2")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["card_id"] == "c1"
        assert parsed["member_id"] == "m2"


# ========== Comments ==========


class TestGetCardComments:
    def test_returns_comments(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_comments, mock_trello_client)
        comments_data = [{"id": "a1", "data": {"text": "Hello"}}]
        mock_trello_client.get.return_value = comments_data

        result = tools["get_card_comments"]("c1")

        mock_trello_client.get.assert_called_once_with(
            "/cards/c1/actions", params={"filter": "commentCard"}
        )
        assert json.loads(result) == comments_data


class TestAddComment:
    def test_adds_comment(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_comments, mock_trello_client)
        comment = {"id": "a2", "data": {"text": "New comment"}}
        mock_trello_client.post.return_value = comment

        result = tools["add_comment"]("c1", "New comment")

        mock_trello_client.post.assert_called_once_with(
            "/cards/c1/actions/comments", params={"text": "New comment"}
        )
        assert json.loads(result) == comment


class TestUpdateComment:
    def test_updates_comment(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_comments, mock_trello_client)
        updated = {"id": "a1", "data": {"text": "Edited"}}
        mock_trello_client.put.return_value = updated

        result = tools["update_comment"]("a1", "Edited")

        mock_trello_client.put.assert_called_once_with("/actions/a1", params={"text": "Edited"})
        assert json.loads(result) == updated


class TestDeleteComment:
    def test_deletes_comment(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_comments, mock_trello_client)
        mock_trello_client.delete.return_value = None

        result = tools["delete_comment"]("a1")

        mock_trello_client.delete.assert_called_once_with("/actions/a1")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["action_id"] == "a1"


# ========== Checklists ==========


class TestGetCardChecklists:
    def test_returns_checklists(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        data = [{"id": "cl1", "name": "Tasks", "checkItems": []}]
        mock_trello_client.get.return_value = data

        result = tools["get_card_checklists"]("c1")

        mock_trello_client.get.assert_called_once_with("/cards/c1/checklists")
        assert json.loads(result) == data


class TestCreateChecklist:
    def test_creates_checklist(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        created = {"id": "cl2", "name": "QA Steps"}
        mock_trello_client.post.return_value = created

        result = tools["create_checklist"]("c1", "QA Steps")

        mock_trello_client.post.assert_called_once_with(
            "/checklists", params={"idCard": "c1", "name": "QA Steps"}
        )
        assert json.loads(result) == created


class TestAddChecklistItem:
    def test_adds_item(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        item = {"id": "ci1", "name": "Step 1", "state": "incomplete"}
        mock_trello_client.post.return_value = item

        result = tools["add_checklist_item"]("cl1", "Step 1")

        mock_trello_client.post.assert_called_once_with(
            "/checklists/cl1/checkItems", params={"name": "Step 1"}
        )
        assert json.loads(result) == item


class TestUpdateChecklistItem:
    def test_marks_complete(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        updated = {"id": "ci1", "state": "complete"}
        mock_trello_client.put.return_value = updated

        result = tools["update_checklist_item"]("c1", "cl1", "ci1", "complete")

        mock_trello_client.put.assert_called_once_with(
            "/cards/c1/checklist/cl1/checkItem/ci1",
            params={"state": "complete"},
        )
        assert json.loads(result) == updated

    def test_marks_incomplete(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        updated = {"id": "ci1", "state": "incomplete"}
        mock_trello_client.put.return_value = updated

        result = tools["update_checklist_item"]("c1", "cl1", "ci1", "incomplete")

        _, kwargs = mock_trello_client.put.call_args
        assert kwargs["params"]["state"] == "incomplete"
        assert json.loads(result)["state"] == "incomplete"


class TestDeleteChecklist:
    def test_deletes_checklist(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.delete.return_value = None

        result = tools["delete_checklist"]("cl1")

        mock_trello_client.delete.assert_called_once_with("/checklists/cl1")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["checklist_id"] == "cl1"


class TestDeleteChecklistNotFound:
    def test_404_returns_warning(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        from server.lib.client import TrelloAPIError

        mock_trello_client.delete.side_effect = TrelloAPIError(404, "not found")

        result = tools["delete_checklist"]("cl_gone")

        parsed = json.loads(result)
        assert "warning" in parsed
        assert parsed["checklist_id"] == "cl_gone"


class TestRenameChecklistItem:
    def test_renames_item(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        updated = {"id": "ci1", "name": "New Name"}
        mock_trello_client.put.return_value = updated

        result = tools["rename_checklist_item"]("c1", "cl1", "ci1", "New Name")

        mock_trello_client.put.assert_called_once_with(
            "/cards/c1/checkItem/ci1", params={"name": "New Name"}
        )
        assert json.loads(result) == updated


class TestDeleteChecklistItem:
    def test_deletes_item(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.delete.return_value = None

        result = tools["delete_checklist_item"]("c1", "cl1", "ci1")

        mock_trello_client.delete.assert_called_once_with("/cards/c1/checkItem/ci1")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["card_id"] == "c1"
        assert parsed["item_id"] == "ci1"


class TestRenameChecklist:
    def test_renames_checklist(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        updated = {"id": "cl1", "name": "Renamed"}
        mock_trello_client.put.return_value = updated

        result = tools["rename_checklist"]("cl1", "Renamed")

        mock_trello_client.put.assert_called_once_with(
            "/checklists/cl1", params={"name": "Renamed"}
        )
        assert json.loads(result) == updated


# ========== Batch Checklist Tools ==========


class TestBatchAddChecklistItems:
    def test_creates_multiple_items(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.side_effect = [
            {"id": "ci1", "name": "Item A", "state": "incomplete"},
            {"id": "ci2", "name": "Item B", "state": "complete"},
        ]

        result = tools["batch_add_checklist_items"](
            "cl1",
            [{"name": "Item A"}, {"name": "Item B", "checked": True}],
        )

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0
        assert parsed["successes"][0]["id"] == "ci1"
        assert parsed["successes"][1]["id"] == "ci2"

        # Verify checked param was passed for second item
        calls = mock_trello_client.post.call_args_list
        assert calls[0][0][0] == "/checklists/cl1/checkItems"
        assert calls[0][1]["params"] == {"name": "Item A"}
        assert calls[1][1]["params"] == {"name": "Item B", "checked": "true"}

    def test_missing_name_recorded_as_failure(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.return_value = {"id": "ci1", "name": "Good"}

        result = tools["batch_add_checklist_items"](
            "cl1",
            [{"name": ""}, {"name": "Good"}],
        )

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert parsed["failures"][0]["index"] == 0
        assert "Missing" in parsed["failures"][0]["error"]
        assert len(parsed["successes"]) == 1

    def test_api_error_captured_as_failure(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.post.side_effect = [
            RuntimeError("Trello API error 429: rate limited"),
            {"id": "ci2", "name": "Second"},
        ]

        result = tools["batch_add_checklist_items"](
            "cl1",
            [{"name": "First"}, {"name": "Second"}],
        )

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "429" in parsed["failures"][0]["error"]
        assert len(parsed["successes"]) == 1

    def test_empty_items_list(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)

        result = tools["batch_add_checklist_items"]("cl1", [])

        parsed = json.loads(result)
        assert parsed["successes"] == []
        assert parsed["failures"] == []


class TestBatchUpdateChecklistItems:
    def test_updates_multiple_items(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.put.side_effect = [
            {"id": "ci1", "name": "Renamed", "state": "incomplete"},
            {"id": "ci2", "state": "complete"},
        ]

        result = tools["batch_update_checklist_items"](
            "c1",
            [
                {"checklist_id": "cl1", "item_id": "ci1", "name": "Renamed"},
                {"checklist_id": "cl1", "item_id": "ci2", "state": "complete"},
            ],
        )

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0

        calls = mock_trello_client.put.call_args_list
        assert calls[0][0][0] == "/cards/c1/checklist/cl1/checkItem/ci1"
        assert calls[0][1]["params"] == {"name": "Renamed"}
        assert calls[1][0][0] == "/cards/c1/checklist/cl1/checkItem/ci2"
        assert calls[1][1]["params"] == {"state": "complete"}

    def test_missing_ids_recorded_as_failure(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)

        result = tools["batch_update_checklist_items"](
            "c1",
            [{"checklist_id": "", "item_id": "ci1", "state": "complete"}],
        )

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "Missing" in parsed["failures"][0]["error"]

    def test_no_fields_to_update(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)

        result = tools["batch_update_checklist_items"](
            "c1",
            [{"checklist_id": "cl1", "item_id": "ci1"}],
        )

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "No fields" in parsed["failures"][0]["error"]

    def test_api_error_captured_as_failure(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_checklists, mock_trello_client)
        mock_trello_client.put.side_effect = RuntimeError("API error")

        result = tools["batch_update_checklist_items"](
            "c1",
            [{"checklist_id": "cl1", "item_id": "ci1", "state": "complete"}],
        )

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert len(parsed["successes"]) == 0


# ========== Attachments ==========


class TestGetCardAttachments:
    def test_returns_attachments(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        data = [{"id": "att1", "name": "file.pdf", "url": "https://example.com/file.pdf"}]
        mock_trello_client.get.return_value = data

        result = tools["get_card_attachments"]("c1")

        mock_trello_client.get.assert_called_once_with("/cards/c1/attachments")
        assert json.loads(result) == data

    def test_returns_empty(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        mock_trello_client.get.return_value = []
        result = tools["get_card_attachments"]("c1")
        assert json.loads(result) == []


class TestAddAttachment:
    def test_adds_attachment_with_url(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        attached = {"id": "att2", "url": "https://example.com/doc.pdf"}
        mock_trello_client.post.return_value = attached

        result = tools["add_attachment"]("c1", url="https://example.com/doc.pdf")

        mock_trello_client.post.assert_called_once_with(
            "/cards/c1/attachments", params={"url": "https://example.com/doc.pdf"}
        )
        assert json.loads(result) == attached

    def test_adds_attachment_with_name(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        mock_trello_client.post.return_value = {"id": "att2"}
        tools["add_attachment"]("c1", url="https://x.com/f", name="My File")
        _, kwargs = mock_trello_client.post.call_args
        assert kwargs["params"]["name"] == "My File"
        assert kwargs["params"]["url"] == "https://x.com/f"

    def test_empty_url_omitted(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        mock_trello_client.post.return_value = {"id": "att2"}
        tools["add_attachment"]("c1")
        _, kwargs = mock_trello_client.post.call_args
        assert "url" not in kwargs["params"]
        assert "name" not in kwargs["params"]


class TestDeleteAttachment:
    def test_deletes_attachment(self, mock_trello_client: MagicMock) -> None:
        tools = _collect_tools(register_attachments, mock_trello_client)
        mock_trello_client.delete.return_value = None

        result = tools["delete_attachment"]("c1", "att1")

        mock_trello_client.delete.assert_called_once_with("/cards/c1/attachments/att1")
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["card_id"] == "c1"
        assert parsed["attachment_id"] == "att1"
