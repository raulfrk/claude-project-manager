"""Dedicated error response contract tests for Trello API.

Tests each error code (401, 403, 404, 429, 500) against multiple endpoints
(GET /1/cards/{id} and POST /1/cards) for broader coverage than the
inline error tests in test_contracts_cards.py.
"""

from __future__ import annotations

import pytest
import respx
from test_contracts.builders import build_error_response

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig
from tests.contracts.errors import FORBIDDEN, NOT_FOUND, RATE_LIMITED, SERVER_ERROR, UNAUTHORIZED

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
    """Patch get_client() in all tool modules to return our test client."""
    import server.lib.client as client_mod
    import server.tools.cards as cards_mod

    for mod in [client_mod, cards_mod]:
        monkeypatch.setattr(mod, "get_client", lambda: client)


@pytest.fixture()
def tools(_patch_client: None) -> dict[str, object]:
    """Register card tools and collect them."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.cards import register as reg_cards

    app = FastMCP("test")
    reg_cards(app)
    fns: dict[str, object] = {}
    for name, tool in app._tool_manager._tools.items():
        fns[name] = tool.fn
    return fns


# ---------------------------------------------------------------------------
# 401 Unauthorized — multiple endpoints
# ---------------------------------------------------------------------------


class TestUnauthorized401:
    @respx.mock
    def test_get_card_401(self, tools: dict) -> None:
        """GET /1/cards/{id} returns 401."""
        respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_error_response(UNAUTHORIZED),
        )
        with pytest.raises(RuntimeError, match="401"):
            tools["get_card"]("c1")

    @respx.mock
    def test_post_card_401(self, tools: dict) -> None:
        """POST /1/cards returns 401."""
        respx.post(f"{BASE}/cards").mock(
            return_value=build_error_response(UNAUTHORIZED),
        )
        with pytest.raises(RuntimeError, match="401"):
            tools["add_card_to_list"]("list1", "Test Card")


# ---------------------------------------------------------------------------
# 403 Forbidden — multiple endpoints
# ---------------------------------------------------------------------------


class TestForbidden403:
    @respx.mock
    def test_get_card_403(self, tools: dict) -> None:
        """GET /1/cards/{id} returns 403."""
        respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_error_response(FORBIDDEN),
        )
        with pytest.raises(RuntimeError, match="403"):
            tools["get_card"]("c1")

    @respx.mock
    def test_post_card_403(self, tools: dict) -> None:
        """POST /1/cards returns 403."""
        respx.post(f"{BASE}/cards").mock(
            return_value=build_error_response(FORBIDDEN),
        )
        with pytest.raises(RuntimeError, match="403"):
            tools["add_card_to_list"]("list1", "Test Card")


# ---------------------------------------------------------------------------
# 404 Not Found — multiple endpoints
# ---------------------------------------------------------------------------


class TestNotFound404:
    @respx.mock
    def test_get_card_404(self, tools: dict) -> None:
        """GET /1/cards/{id} returns 404."""
        respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_error_response(NOT_FOUND),
        )
        with pytest.raises(RuntimeError, match="404"):
            tools["get_card"]("c1")

    @respx.mock
    def test_post_card_404(self, tools: dict) -> None:
        """POST /1/cards returns 404."""
        respx.post(f"{BASE}/cards").mock(
            return_value=build_error_response(NOT_FOUND),
        )
        with pytest.raises(RuntimeError, match="404"):
            tools["add_card_to_list"]("list1", "Test Card")


# ---------------------------------------------------------------------------
# 429 Rate Limited — multiple endpoints
# ---------------------------------------------------------------------------


class TestRateLimited429:
    @respx.mock
    def test_get_card_429(self, tools: dict) -> None:
        """GET /1/cards/{id} returns 429 with Retry-After header."""
        respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_error_response(RATE_LIMITED),
        )
        with pytest.raises(RuntimeError, match="429"):
            tools["get_card"]("c1")

    @respx.mock
    def test_post_card_429(self, tools: dict) -> None:
        """POST /1/cards returns 429 with Retry-After header."""
        respx.post(f"{BASE}/cards").mock(
            return_value=build_error_response(RATE_LIMITED),
        )
        with pytest.raises(RuntimeError, match="429"):
            tools["add_card_to_list"]("list1", "Test Card")

    @respx.mock
    def test_429_message_includes_rate_limit_info(self, tools: dict) -> None:
        """429 error message should include rate limit details."""
        respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_error_response(RATE_LIMITED),
        )
        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            tools["get_card"]("c1")


# ---------------------------------------------------------------------------
# 500 Server Error — multiple endpoints
# ---------------------------------------------------------------------------


class TestServerError500:
    @respx.mock
    def test_get_card_500(self, tools: dict) -> None:
        """GET /1/cards/{id} returns 500."""
        respx.get(f"{BASE}/cards/c1").mock(
            return_value=build_error_response(SERVER_ERROR),
        )
        with pytest.raises(RuntimeError, match="500"):
            tools["get_card"]("c1")

    @respx.mock
    def test_post_card_500(self, tools: dict) -> None:
        """POST /1/cards returns 500."""
        respx.post(f"{BASE}/cards").mock(
            return_value=build_error_response(SERVER_ERROR),
        )
        with pytest.raises(RuntimeError, match="500"):
            tools["add_card_to_list"]("list1", "Test Card")
