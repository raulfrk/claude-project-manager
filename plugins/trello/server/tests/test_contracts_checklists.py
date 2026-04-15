"""Contract tests for Trello checklist endpoints."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig
from tests.contracts.cards import GET_CARD_CHECKLISTS
from tests.contracts.checklists import (
    ADD_CHECKLIST_ITEM,
    CREATE_CHECKLIST,
    DELETE_CHECKLIST,
    DELETE_CHECKLIST_ITEM,
    RENAME_CHECKLIST,
    RENAME_CHECKLIST_ITEM,
    UPDATE_CHECKLIST_ITEM,
)

BASE = "https://api.trello.com/1"
TEST_KEY = "test_key"
TEST_TOKEN = "test_token"


@pytest.fixture()
def config() -> TrelloConfig:
    return TrelloConfig(api_key=TEST_KEY, token=TEST_TOKEN, allowed_board_ids=[])


@pytest.fixture()
def client(config: TrelloConfig, monkeypatch: pytest.MonkeyPatch) -> TrelloClient:
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    return TrelloClient(config)


@pytest.fixture()
def _patch_client(client: TrelloClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.lib.client as client_mod
    import server.tools.checklists as checklists_mod

    for mod in [client_mod, checklists_mod]:
        monkeypatch.setattr(mod, "get_client", lambda: client)


@pytest.fixture()
def tools(_patch_client: None) -> dict[str, object]:
    from mcp.server.fastmcp import FastMCP

    from server.tools.checklists import register as reg_checklists

    app = FastMCP("test")
    reg_checklists(app)
    fns: dict[str, object] = {}
    for name, tool in app._tool_manager._tools.items():
        fns[name] = tool.fn
    return fns


class TestGetCardChecklists:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        checklists_data = [
            {"id": "cl1", "name": "Checklist 1", "checkItems": []},
            {"id": "cl2", "name": "Checklist 2", "checkItems": []},
        ]
        route = respx.get(f"{BASE}/cards/c1/checklists").mock(
            return_value=build_success_response(GET_CARD_CHECKLISTS, checklists_data),
        )

        result = tools["get_card_checklists"]("c1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, GET_CARD_CHECKLISTS, path_params={"cardId": "c1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, GET_CARD_CHECKLISTS)
        assert len(parsed) == 2


class TestCreateChecklist:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        created = {"id": "cl3", "name": "New Checklist"}
        route = respx.post(f"{BASE}/checklists").mock(
            return_value=build_success_response(CREATE_CHECKLIST, created),
        )

        result = tools["create_checklist"]("c1", "New Checklist")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(request, CREATE_CHECKLIST)
        url_str = str(request.url)
        assert "idCard=c1" in url_str
        assert "name=New" in url_str
        parsed = json.loads(result)
        assert_response_parses(parsed, CREATE_CHECKLIST)


class TestAddChecklistItem:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        item = {"id": "ci1", "name": "Task 1", "state": "incomplete"}
        route = respx.post(f"{BASE}/checklists/cl1/checkItems").mock(
            return_value=build_success_response(ADD_CHECKLIST_ITEM, item),
        )

        result = tools["add_checklist_item"]("cl1", "Task 1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request, ADD_CHECKLIST_ITEM, path_params={"checklistId": "cl1"}
        )
        parsed = json.loads(result)
        assert_response_parses(parsed, ADD_CHECKLIST_ITEM)


class TestUpdateChecklistItem:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        updated = {"id": "ci1", "state": "complete", "name": "Task 1"}
        route = respx.put(f"{BASE}/cards/c1/checklist/cl1/checkItem/ci1").mock(
            return_value=build_success_response(UPDATE_CHECKLIST_ITEM, updated),
        )

        result = tools["update_checklist_item"]("c1", "cl1", "ci1", "complete")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            UPDATE_CHECKLIST_ITEM,
            path_params={"cardId": "c1", "checklistId": "cl1", "itemId": "ci1"},
        )
        assert "state=complete" in str(request.url)
        parsed = json.loads(result)
        assert_response_parses(parsed, UPDATE_CHECKLIST_ITEM)


class TestDeleteChecklist:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/checklists/cl1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["delete_checklist"]("cl1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request, DELETE_CHECKLIST, path_params={"checklistId": "cl1"}
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True

    @respx.mock
    def test_404_returns_warning(self, tools: dict) -> None:
        """When checklist is already gone, delete returns a warning instead of raising."""
        respx.delete(f"{BASE}/checklists/cl1").mock(
            return_value=httpx.Response(404, json={"error": "not found"}),
        )

        result = tools["delete_checklist"]("cl1")

        parsed = json.loads(result)
        assert "warning" in parsed


class TestRenameChecklistItem:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        renamed = {"id": "ci1", "name": "Renamed Task"}
        route = respx.put(f"{BASE}/cards/c1/checkItem/ci1").mock(
            return_value=build_success_response(RENAME_CHECKLIST_ITEM, renamed),
        )

        result = tools["rename_checklist_item"]("c1", "cl1", "ci1", "Renamed Task")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            RENAME_CHECKLIST_ITEM,
            path_params={"cardId": "c1", "itemId": "ci1"},
        )
        parsed = json.loads(result)
        assert_response_parses(parsed, RENAME_CHECKLIST_ITEM)
        assert parsed["name"] == "Renamed Task"


class TestDeleteChecklistItem:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.delete(f"{BASE}/cards/c1/checkItem/ci1").mock(
            return_value=httpx.Response(200, json={}),
        )

        result = tools["delete_checklist_item"]("c1", "cl1", "ci1")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            DELETE_CHECKLIST_ITEM,
            path_params={"cardId": "c1", "itemId": "ci1"},
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True


class TestRenameChecklist:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        renamed = {"id": "cl1", "name": "Renamed Checklist"}
        route = respx.put(f"{BASE}/checklists/cl1").mock(
            return_value=build_success_response(RENAME_CHECKLIST, renamed),
        )

        result = tools["rename_checklist"]("cl1", "Renamed Checklist")

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request, RENAME_CHECKLIST, path_params={"checklistId": "cl1"}
        )
        parsed = json.loads(result)
        assert_response_parses(parsed, RENAME_CHECKLIST)


class TestAddChecklistItemBatchMode:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.post(f"{BASE}/checklists/cl1/checkItems").mock(
            side_effect=[
                build_success_response(
                    ADD_CHECKLIST_ITEM, {"id": "ci1", "name": "A", "state": "incomplete"}
                ),
                build_success_response(
                    ADD_CHECKLIST_ITEM, {"id": "ci2", "name": "B", "state": "incomplete"}
                ),
            ],
        )

        result = tools["add_checklist_item"](
            "cl1",
            items=[{"name": "A"}, {"name": "B"}],
        )

        assert route.call_count == 2
        for call in route.calls:
            assert_request_matches_contract(
                call.request, ADD_CHECKLIST_ITEM, path_params={"checklistId": "cl1"}
            )
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0

    @respx.mock
    def test_with_checked_flag(self, tools: dict) -> None:
        route = respx.post(f"{BASE}/checklists/cl1/checkItems").mock(
            return_value=build_success_response(
                ADD_CHECKLIST_ITEM, {"id": "ci1", "name": "Done", "state": "complete"}
            ),
        )

        tools["add_checklist_item"]("cl1", items=[{"name": "Done", "checked": True}])

        url_str = str(route.calls[0].request.url)
        assert "checked=true" in url_str


class TestVerifyChecklistItem:
    @respx.mock
    def test_found(self, tools: dict) -> None:
        checklists_data = [
            {
                "id": "cl1",
                "name": "CL",
                "checkItems": [
                    {"id": "ci1", "state": "complete", "name": "Task 1"},
                    {"id": "ci2", "state": "incomplete", "name": "Task 2"},
                ],
            },
        ]
        route = respx.get(f"{BASE}/cards/c1/checklists").mock(
            return_value=build_success_response(GET_CARD_CHECKLISTS, checklists_data),
        )

        result = tools["trello_verify_checklist_item"]("c1", "ci1")

        assert route.called
        parsed = json.loads(result)
        assert parsed["verified"] is True
        assert parsed["state"] == "complete"
        assert parsed["name"] == "Task 1"

    @respx.mock
    def test_not_found(self, tools: dict) -> None:
        respx.get(f"{BASE}/cards/c1/checklists").mock(
            return_value=build_success_response(GET_CARD_CHECKLISTS, []),
        )

        result = tools["trello_verify_checklist_item"]("c1", "ci_missing")

        parsed = json.loads(result)
        assert parsed["verified"] is False
        assert parsed["state"] == "unknown"


class TestUpdateChecklistItemBatchMode:
    @respx.mock
    def test_contract(self, tools: dict) -> None:
        route = respx.put(f"{BASE}/cards/c1/checklist/cl1/checkItem/ci1").mock(
            return_value=build_success_response(
                UPDATE_CHECKLIST_ITEM, {"id": "ci1", "state": "complete"}
            ),
        )

        result = tools["update_checklist_item"](
            "c1",
            updates=[{"checklist_id": "cl1", "item_id": "ci1", "state": "complete"}],
        )

        assert route.called
        request = route.calls[0].request
        assert_request_matches_contract(
            request,
            UPDATE_CHECKLIST_ITEM,
            path_params={"cardId": "c1", "checklistId": "cl1", "itemId": "ci1"},
        )
        parsed = json.loads(result)
        assert len(parsed["successes"]) == 1
