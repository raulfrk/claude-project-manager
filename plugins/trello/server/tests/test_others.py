"""Tests for members, comments, checklists, and attachments tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

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

        mock_trello_client.put.assert_called_once_with(
            "/actions/a1", params={"text": "Edited"}
        )
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
