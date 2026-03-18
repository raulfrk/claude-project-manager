"""Tests for the jira_init tool."""

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


class TestJiraInitSuccess:
    def test_happy_path_writes_config(self, init_tools: dict, tmp_path: Path) -> None:
        config_path = tmp_path / "jira.yaml"
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "displayName": "Alice Smith",
            "emailAddress": "alice@example.com",
        }

        # Pre-set caches to verify they get cleared
        config_mod._cached_config = MagicMock()
        client_mod._cached_client = MagicMock()

        with patch("server.tools.init.httpx.get", return_value=mock_resp) as mock_get, \
             patch("server.tools.init.Path.expanduser", return_value=config_path):
            result = init_tools["jira_init"](
                personal_access_token="my_pat",
                base_url="https://jira.example.com/",
                allowed_project_keys=["PROJ", "DEV"],
                default_user="alice",
                rate_limit_per_10s=50,
            )

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["displayName"] == "Alice Smith"
        assert parsed["emailAddress"] == "alice@example.com"

        # Verify httpx.get was called with correct URL and headers
        mock_get.assert_called_once_with(
            "https://jira.example.com/rest/api/2/myself",
            headers={"Authorization": "Bearer my_pat"},
            timeout=30,
        )

        # Verify config was written (base_url should be stripped of trailing slash)
        import yaml

        with config_path.open() as f:
            written = yaml.safe_load(f)
        assert written["personal_access_token"] == "my_pat"
        assert written["base_url"] == "https://jira.example.com"
        assert written["allowed_project_keys"] == ["PROJ", "DEV"]
        assert written["default_user"] == "alice"
        assert written["rate_limit_per_10s"] == 50

        # Verify caches were cleared
        assert config_mod._cached_config is None
        assert client_mod._cached_client is None


class TestJiraInitFailure:
    def test_invalid_credentials_returns_error(self, init_tools: dict) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        with patch("server.tools.init.httpx.get", return_value=mock_resp):
            result = init_tools["jira_init"](
                personal_access_token="bad_pat",
                base_url="https://jira.example.com",
            )

        parsed = json.loads(result)
        assert "error" in parsed
        assert "401" in parsed["error"]


class TestJiraInitCacheClearing:
    def test_clears_cached_config_and_client(self, init_tools: dict, tmp_path: Path) -> None:
        config_path = tmp_path / "jira.yaml"
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"displayName": "Bob", "emailAddress": "bob@example.com"}

        config_mod._cached_config = MagicMock()
        client_mod._cached_client = MagicMock()

        with patch("server.tools.init.httpx.get", return_value=mock_resp), \
             patch("server.tools.init.Path.expanduser", return_value=config_path):
            init_tools["jira_init"](personal_access_token="pat", base_url="https://jira.example.com")

        assert config_mod._cached_config is None
        assert client_mod._cached_client is None
