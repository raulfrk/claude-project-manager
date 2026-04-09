"""Contract tests for Trello board and member endpoints."""

from __future__ import annotations

import json

import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig
from tests.contracts.boards import GET_BOARD, GET_BOARD_MEMBERS, LIST_BOARDS, UPDATE_BOARD

BASE = "https://api.trello.com/1"
TEST_KEY = "test_key"
TEST_TOKEN = "test_token"
BOARD_ID = "board1"


@pytest.fixture()
def config() -> TrelloConfig:
    return TrelloConfig(
        api_key=TEST_KEY,
        token=TEST_TOKEN,
        allowed_board_ids=[BOARD_ID],
    )


@pytest.fixture()
def client(config: TrelloConfig, monkeypatch: pytest.MonkeyPatch) -> TrelloClient:
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    return TrelloClient(config)


@pytest.fixture()
def _patch_client(client: TrelloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.lib.client as client_mod
    import server.tools.boards as boards_mod
    import server.tools.members as members_mod

    for mod in [client_mod, boards_mod, members_mod]:
        monkeypatch.setattr(mod, "get_client", lambda: client)


@pytest.fixture()
def tools(_patch_client: None) -> dict[str, object]:
    from mcp.server.fastmcp import FastMCP

    from server.tools.boards import register as reg_boards
    from server.tools.members import register as reg_members

    app = FastMCP("test")
    reg_boards(app)
    reg_members(app)
    fns: dict[str, object] = {}
    for name, tool in app._tool_manager._tools.items():
        fns[name] = tool.fn
    return fns


class TestListBoards:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        boards_data = [
            {"id": BOARD_ID, "name": "Project"},
            {"id": "board2", "name": "Other"},
        ]
        route = respx.get(f"{BASE}/members/me/boards").mock(
            return_value=build_success_response(LIST_BOARDS, boards_data),
        )

        result = tools["list_boards"]()

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, LIST_BOARDS)
        assert "key=test_key" in str(request.url)
        assert "token=test_token" in str(request.url)
        parsed = json.loads(result)
        # Filtered to allowed_board_ids
        assert len(parsed) == 1
        assert parsed[0]["id"] == BOARD_ID

    @respx.mock
    def test_auth_params_present(self, tools: dict) -> None:
        route = respx.get(f"{BASE}/members/me/boards").mock(
            return_value=build_success_response(LIST_BOARDS, []),
        )

        tools["list_boards"]()

        url_str = str(route.calls[0].request.url)
        assert f"key={TEST_KEY}" in url_str
        assert f"token={TEST_TOKEN}" in url_str


class TestGetBoard:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        board_data = {"id": BOARD_ID, "name": "Project", "desc": "A board"}
        route = respx.get(f"{BASE}/boards/{BOARD_ID}").mock(
            return_value=build_success_response(GET_BOARD, board_data),
        )

        result = tools["get_board"](BOARD_ID)

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_BOARD, path_params={"boardId": BOARD_ID})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_BOARD)
        assert parsed["id"] == BOARD_ID


class TestUpdateBoard:
    @respx.mock
    def test_contract_name(self, tools: dict) -> None:
        updated = {"id": BOARD_ID, "name": "Renamed"}
        route = respx.put(f"{BASE}/boards/{BOARD_ID}").mock(
            return_value=build_success_response(UPDATE_BOARD, updated),
        )

        result = tools["update_board"](BOARD_ID, name="Renamed")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_BOARD, path_params={"boardId": BOARD_ID})
        assert "name=Renamed" in str(request.url)
        parsed = json.loads(result)
        assert_response_parses(parsed, UPDATE_BOARD)

    @respx.mock
    def test_contract_desc(self, tools: dict) -> None:
        updated = {"id": BOARD_ID, "name": "Board", "desc": "New desc"}
        route = respx.put(f"{BASE}/boards/{BOARD_ID}").mock(
            return_value=build_success_response(UPDATE_BOARD, updated),
        )

        tools["update_board"](BOARD_ID, desc="New desc")

        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_BOARD, path_params={"boardId": BOARD_ID})


class TestGetBoardMembers:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        members_data = [
            {"id": "m1", "fullName": "Alice"},
            {"id": "m2", "fullName": "Bob"},
        ]
        route = respx.get(f"{BASE}/boards/{BOARD_ID}/members").mock(
            return_value=build_success_response(GET_BOARD_MEMBERS, members_data),
        )

        result = tools["get_board_members"](BOARD_ID)

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request, GET_BOARD_MEMBERS, path_params={"boardId": BOARD_ID}
        )
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_BOARD_MEMBERS)
        assert len(parsed) == 2
