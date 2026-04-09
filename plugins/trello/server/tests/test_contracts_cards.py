"""Contract tests for Trello card, comment, attachment, and member endpoints."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig
from tests.contracts.cards import (
    ADD_ATTACHMENT,
    ADD_CARD,
    ADD_CARD_LABEL,
    ADD_CARD_MEMBER,
    ADD_COMMENT,
    DELETE_ATTACHMENT,
    DELETE_CARD,
    GET_CARD,
    GET_CARD_ATTACHMENTS,
    GET_CARD_COMMENTS,
    GET_CARDS_BY_LIST,
    REMOVE_CARD_LABEL,
    REMOVE_CARD_MEMBER,
    UPDATE_CARD,
)

BASE = "https://api.trello.com/1"
TEST_KEY = "test_key"
TEST_TOKEN = "test_token"


@pytest.fixture()
def config() -> TrelloConfig:
    return TrelloConfig(api_key=TEST_KEY, token=TEST_TOKEN, allowed_board_ids=[])


@pytest.fixture()
def client(config: TrelloConfig, monkeypatch: pytest.MonkeyPatch) -> TrelloClient:
    # Clear proxy env vars so httpx.Client doesn't try to use SOCKS
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    return TrelloClient(config)


@pytest.fixture()
def _patch_client(client: TrelloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch get_client() in all tool modules to return our test client."""
    import server.lib.client as client_mod
    import server.tools.attachments as attachments_mod
    import server.tools.cards as cards_mod
    import server.tools.comments as comments_mod
    import server.tools.labels as labels_mod
    import server.tools.members as members_mod

    for mod in [client_mod, cards_mod, comments_mod, attachments_mod, members_mod, labels_mod]:
        monkeypatch.setattr(mod, "get_client", lambda: client)


@pytest.fixture()
def tools(_patch_client: None) -> dict[str, object]:
    """Register card/comment/attachment/member/label tools and collect them."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.attachments import register as reg_attach
    from server.tools.cards import register as reg_cards
    from server.tools.comments import register as reg_comments
    from server.tools.labels import register as reg_labels
    from server.tools.members import register as reg_members

    app = FastMCP("test")
    reg_cards(app)
    reg_comments(app)
    reg_attach(app)
    reg_members(app)
    reg_labels(app)
    fns: dict[str, object] = {}
    for name, tool in app._tool_manager._tools.items():
        fns[name] = tool.fn
    return fns


# ---------------------------------------------------------------------------
# Card tools
# ---------------------------------------------------------------------------


class TestGetCardsByListId:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        cards_data = [{"id": "c1", "name": "Card 1"}, {"id": "c2", "name": "Card 2"}]
        route = respx.get(f"{BASE}/lists/list1/cards").mock(
            return_value=build_success_response(GET_CARDS_BY_LIST, cards_data),
        )

        result = tools["get_cards_by_list_id"]("list1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_CARDS_BY_LIST, path_params={"listId": "list1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_CARDS_BY_LIST)
        assert len(parsed) == 2


class TestGetCard:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        card_data = {"id": "c1", "name": "My Card", "desc": "Details"}
        route = respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_success_response(GET_CARD, card_data),
        )

        result = tools["get_card"]("c1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_CARD, path_params={"cardId": "c1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_CARD)
        assert parsed["id"] == "c1"


class TestAddCardToList:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        created = {"id": "c3", "name": "New Card", "idList": "list1"}
        route = respx.post(f"{BASE}/cards").mock(
            return_value=build_success_response(ADD_CARD, created),
        )

        result = tools["add_card_to_list"]("list1", "New Card")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, ADD_CARD)
        assert "key=test_key" in str(request.url)
        assert "token=test_token" in str(request.url)
        parsed = json.loads(result)
        assert_response_parses(parsed, ADD_CARD)
        assert parsed["id"] == "c3"

    @respx.mock
    def test_with_desc_and_due(self, tools: dict) -> None:
        created = {"id": "c3", "name": "Card", "idList": "list1"}
        route = respx.post(f"{BASE}/cards").mock(
            return_value=build_success_response(ADD_CARD, created),
        )

        tools["add_card_to_list"]("list1", "Card", desc="D", due="2026-04-01")

        request = route.calls[0].request
        url_str = str(request.url)
        assert "desc=D" in url_str
        assert "due=2026-04-01" in url_str


class TestUpdateCardDetails:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        updated = {"id": "c1", "name": "Updated"}
        route = respx.put(f"{BASE}/cards/c1").mock(
            return_value=build_success_response(UPDATE_CARD, updated),
        )

        result = tools["update_card_details"]("c1", name="Updated")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_CARD, path_params={"cardId": "c1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, UPDATE_CARD)
        assert parsed["name"] == "Updated"


class TestMoveCard:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        moved = {"id": "c1", "name": "Card", "idList": "list2"}
        route = respx.put(f"{BASE}/cards/c1").mock(
            return_value=build_success_response(UPDATE_CARD, moved),
        )

        tools["move_card"]("c1", "list2")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_CARD, path_params={"cardId": "c1"})
        assert "idList=list2" in str(request.url)


class TestArchiveCard:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        archived = {"id": "c1", "name": "Card", "closed": True}
        route = respx.put(f"{BASE}/cards/c1").mock(
            return_value=build_success_response(UPDATE_CARD, archived),
        )

        tools["archive_card"]("c1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_CARD, path_params={"cardId": "c1"})
        assert "closed=True" in str(request.url) or "closed=true" in str(request.url)


class TestDeleteCard:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/cards/c1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["delete_card"]("c1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, DELETE_CARD, path_params={"cardId": "c1"})
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["card_id"] == "c1"


class TestBatchCreateCards:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.post(f"{BASE}/cards").mock(
            side_effect=[
                build_success_response(ADD_CARD, {"id": "c10", "name": "A", "idList": "l1"}),
                build_success_response(ADD_CARD, {"id": "c11", "name": "B", "idList": "l2"}),
            ],
        )

        result = tools["batch_create_cards"](
            [
                {"list_id": "l1", "name": "A"},
                {"list_id": "l2", "name": "B"},
            ]
        )

        assert route.call_count == 2
        for call in route.calls:
            assert_request_matches_contract(call.request, ADD_CARD)
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0


# ---------------------------------------------------------------------------
# Comment tools
# ---------------------------------------------------------------------------


class TestGetCardComments:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        comments_data = [{"id": "a1", "type": "commentCard", "data": {}}]
        route = respx.get(f"{BASE}/cards/c1/actions").mock(
            return_value=build_success_response(GET_CARD_COMMENTS, comments_data),
        )

        result = tools["get_card_comments"]("c1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_CARD_COMMENTS, path_params={"cardId": "c1"})
        assert "filter=commentCard" in str(request.url)
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_CARD_COMMENTS)


class TestAddComment:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        comment = {"id": "a2", "data": {"text": "Hello"}}
        route = respx.post(f"{BASE}/cards/c1/actions/comments").mock(
            return_value=build_success_response(ADD_COMMENT, comment),
        )

        result = tools["add_comment"]("c1", "Hello")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, ADD_COMMENT, path_params={"cardId": "c1"})
        assert "text=Hello" in str(request.url)
        parsed = json.loads(result)
        assert_response_parses(parsed, ADD_COMMENT)


class TestUpdateComment:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        updated = {"id": "a1", "data": {"text": "Updated"}}
        route = respx.put(f"{BASE}/actions/a1").mock(
            return_value=httpx.Response(200, json=updated),
        )

        tools["update_comment"]("a1", "Updated")

        assert route.called
        request = route.calls[0].request
        assert request.method == "PUT"
        assert "text=Updated" in str(request.url)


class TestDeleteComment:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/actions/a1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["delete_comment"]("a1")

        assert route.called
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["action_id"] == "a1"


# ---------------------------------------------------------------------------
# Attachment tools
# ---------------------------------------------------------------------------


class TestGetCardAttachments:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        data = [{"id": "att1", "name": "file.pdf", "url": "https://example.com/file.pdf"}]
        route = respx.get(f"{BASE}/cards/c1/attachments").mock(
            return_value=build_success_response(GET_CARD_ATTACHMENTS, data),
        )

        result = tools["get_card_attachments"]("c1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_CARD_ATTACHMENTS, path_params={"cardId": "c1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_CARD_ATTACHMENTS)


class TestAddAttachment:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        attachment = {"id": "att2", "name": "link", "url": "https://example.com"}
        route = respx.post(f"{BASE}/cards/c1/attachments").mock(
            return_value=build_success_response(ADD_ATTACHMENT, attachment),
        )

        result = tools["add_attachment"]("c1", url="https://example.com", name="link")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, ADD_ATTACHMENT, path_params={"cardId": "c1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, ADD_ATTACHMENT)


class TestDeleteAttachment:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/cards/c1/attachments/att1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["delete_attachment"]("c1", "att1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            DELETE_ATTACHMENT,
            path_params={"cardId": "c1", "attachmentId": "att1"},
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True


# ---------------------------------------------------------------------------
# Member tools
# ---------------------------------------------------------------------------


class TestGetBoardMembers:
    """Covered in test_contracts_boards.py."""


class TestAddCardMember:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.post(f"{BASE}/cards/c1/idMembers").mock(
            return_value=httpx.Response(200, json=[{"id": "m1"}]),
        )

        tools["add_card_member"]("c1", "m1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, ADD_CARD_MEMBER, path_params={"cardId": "c1"})
        assert "value=m1" in str(request.url)


class TestRemoveCardMember:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/cards/c1/idMembers/m1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["remove_card_member"]("c1", "m1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            REMOVE_CARD_MEMBER,
            path_params={"cardId": "c1", "memberId": "m1"},
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True


# ---------------------------------------------------------------------------
# Label toggle (on card)
# ---------------------------------------------------------------------------


class TestToggleCardLabelAdd:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.post(f"{BASE}/cards/c1/idLabels").mock(
            return_value=httpx.Response(200, json=[{"id": "lbl1"}]),
        )

        tools["toggle_card_label"]("c1", "lbl1", "add")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, ADD_CARD_LABEL, path_params={"cardId": "c1"})
        assert "value=lbl1" in str(request.url)


class TestToggleCardLabelRemove:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/cards/c1/idLabels/lbl1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["toggle_card_label"]("c1", "lbl1", "remove")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            REMOVE_CARD_LABEL,
            path_params={"cardId": "c1", "labelId": "lbl1"},
        )
        parsed = json.loads(result)
        assert parsed["removed"] is True
