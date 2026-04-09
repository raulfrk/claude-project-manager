"""Contract tests for Trello list and label endpoints."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig
from tests.contracts.labels import CREATE_LABEL, DELETE_LABEL, GET_LABELS, UPDATE_LABEL
from tests.contracts.lists import CREATE_LIST, GET_LIST, GET_LISTS, UPDATE_LIST

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
    import server.tools.labels as labels_mod
    import server.tools.lists as lists_mod

    for mod in [client_mod, lists_mod, labels_mod]:
        monkeypatch.setattr(mod, "get_client", lambda: client)


@pytest.fixture()
def tools(_patch_client: None) -> dict[str, object]:
    from mcp.server.fastmcp import FastMCP

    from server.tools.labels import register as reg_labels
    from server.tools.lists import register as reg_lists

    app = FastMCP("test")
    reg_lists(app)
    reg_labels(app)
    fns: dict[str, object] = {}
    for name, tool in app._tool_manager._tools.items():
        fns[name] = tool.fn
    return fns


# ---------------------------------------------------------------------------
# List tools
# ---------------------------------------------------------------------------


class TestGetLists:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        lists_data = [
            {"id": "lst1", "name": "To Do"},
            {"id": "lst2", "name": "Done"},
        ]
        route = respx.get(f"{BASE}/boards/{BOARD_ID}/lists").mock(
            return_value=build_success_response(GET_LISTS, lists_data),
        )

        result = tools["get_lists"](BOARD_ID)

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_LISTS, path_params={"boardId": BOARD_ID})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_LISTS)
        assert len(parsed) == 2


class TestGetList:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        list_data = {"id": "lst1", "name": "To Do"}
        route = respx.get(f"{BASE}/lists/lst1").mock(
            return_value=build_success_response(GET_LIST, list_data),
        )

        result = tools["get_list"]("lst1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_LIST, path_params={"listId": "lst1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_LIST)
        assert parsed["id"] == "lst1"


class TestCreateList:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        created = {"id": "lst3", "name": "In Progress"}
        route = respx.post(f"{BASE}/lists").mock(
            return_value=build_success_response(CREATE_LIST, created),
        )

        result = tools["create_list"]("In Progress", BOARD_ID)

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CREATE_LIST)
        url_str = str(request.url)
        assert "name=In+Progress" in url_str or "name=In%20Progress" in url_str
        assert f"idBoard={BOARD_ID}" in url_str
        parsed = json.loads(result)
        assert_response_parses(parsed, CREATE_LIST)


class TestUpdateList:
    @respx.mock
    def test_contract_name(self, tools: dict) -> None:
        updated = {"id": "lst1", "name": "Renamed"}
        route = respx.put(f"{BASE}/lists/lst1").mock(
            return_value=build_success_response(UPDATE_LIST, updated),
        )

        result = tools["update_list"]("lst1", name="Renamed")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_LIST, path_params={"listId": "lst1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, UPDATE_LIST)

    @respx.mock
    def test_contract_closed(self, tools: dict) -> None:
        updated = {"id": "lst1", "name": "Archived", "closed": True}
        route = respx.put(f"{BASE}/lists/lst1").mock(
            return_value=build_success_response(UPDATE_LIST, updated),
        )

        tools["update_list"]("lst1", closed=True)

        request = route.calls[0].request
        url_str = str(request.url)
        assert "closed=True" in url_str or "closed=true" in url_str


# ---------------------------------------------------------------------------
# Label tools
# ---------------------------------------------------------------------------


class TestGetLabels:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        labels_data = [
            {"id": "lbl1", "name": "Bug", "color": "red"},
            {"id": "lbl2", "name": "Feature", "color": "green"},
        ]
        route = respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=build_success_response(GET_LABELS, labels_data),
        )

        result = tools["get_labels"](BOARD_ID)

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_LABELS, path_params={"boardId": BOARD_ID})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_LABELS)
        assert len(parsed) == 2


class TestCreateLabel:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        created = {"id": "lbl3", "name": "Urgent", "color": "orange"}
        route = respx.post(f"{BASE}/labels").mock(
            return_value=build_success_response(CREATE_LABEL, created),
        )

        result = tools["create_label"](BOARD_ID, "Urgent", "orange")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CREATE_LABEL)
        url_str = str(request.url)
        assert "name=Urgent" in url_str
        assert "color=orange" in url_str
        parsed = json.loads(result)
        assert_response_parses(parsed, CREATE_LABEL)


class TestUpdateLabel:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        updated = {"id": "lbl1", "name": "Critical", "color": "red"}
        route = respx.put(f"{BASE}/labels/lbl1").mock(
            return_value=build_success_response(UPDATE_LABEL, updated),
        )

        result = tools["update_label"]("lbl1", name="Critical")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, UPDATE_LABEL, path_params={"labelId": "lbl1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, UPDATE_LABEL)


class TestDeleteLabel:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/labels/lbl1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["delete_label"]("lbl1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, DELETE_LABEL, path_params={"labelId": "lbl1"})
        parsed = json.loads(result)
        assert parsed["deleted"] is True
        assert parsed["label_id"] == "lbl1"
