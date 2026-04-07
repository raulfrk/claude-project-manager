"""Tests for the trello_init tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

import server.lib.client as client_mod
import server.lib.config as config_mod
from server.tools.init import register


@pytest.fixture()
def init_tools() -> dict[str, callable]:
    """Register init tools on a mock FastMCP and collect them."""
    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestTrelloInitSuccess:
    def test_happy_path_writes_config(self, init_tools: dict, tmp_path: Path) -> None:
        config_path = tmp_path / "trello.yaml"
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"username": "alice"}

        # Clear caches before test
        config_mod._cached_config = MagicMock()
        client_mod._cached_client = MagicMock()

        with (
            patch("server.tools.init.httpx.get", return_value=mock_resp) as mock_get,
            patch("server.tools.init.Path.expanduser", return_value=config_path),
        ):
            result = init_tools["trello_init"](
                api_key="mykey",
                token="mytoken",
                default_board_id="b1",
                allowed_board_ids=["b1", "b2"],
                rate_limit_per_10s=50,
            )

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["username"] == "alice"

        # Verify httpx.get was called with correct params
        mock_get.assert_called_once_with(
            "https://api.trello.com/1/members/me",
            params={"key": "mykey", "token": "mytoken"},
            timeout=30,
        )

        # Verify config was written
        import yaml

        with config_path.open() as f:
            written = yaml.safe_load(f)
        assert written["api_key"] == "mykey"
        assert written["token"] == "mytoken"
        assert written["default_board_id"] == "b1"
        assert written["allowed_board_ids"] == ["b1", "b2"]
        assert written["rate_limit_per_10s"] == 50

        # Verify caches were cleared
        assert config_mod._cached_config is None
        assert client_mod._cached_client is None


class TestTrelloInitFailure:
    def test_invalid_credentials_returns_error(self, init_tools: dict) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.text = "invalid token"

        with patch("server.tools.init.httpx.get", return_value=mock_resp):
            result = init_tools["trello_init"](api_key="bad", token="bad")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "401" in parsed["error"]


class TestTrelloInitCacheClearing:
    def test_clears_cached_config_and_client(self, init_tools: dict, tmp_path: Path) -> None:
        config_path = tmp_path / "trello.yaml"
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"username": "bob"}

        config_mod._cached_config = MagicMock()
        client_mod._cached_client = MagicMock()

        with (
            patch("server.tools.init.httpx.get", return_value=mock_resp),
            patch("server.tools.init.Path.expanduser", return_value=config_path),
        ):
            init_tools["trello_init"](api_key="k", token="t")

        assert config_mod._cached_config is None
        assert client_mod._cached_client is None
