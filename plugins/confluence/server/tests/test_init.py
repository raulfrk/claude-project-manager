"""Tests for confluence_init tool."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from server.tools import init as init_mod


@pytest.fixture()
def init_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg_path = tmp_path / "confluence.yaml"
    monkeypatch.setenv("CONFLUENCE_CONFIG", str(cfg_path))

    mcp = FastMCP("test")
    init_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_init"].fn, cfg_path


def test_init_writes_cloud_yaml(init_tool) -> None:
    tool, cfg_path = init_tool
    result = tool(
        deployment="cloud",
        base_url="https://acme.atlassian.net",
        email="u@example.com",
        api_token="tok",
        allowed_spaces=["DOCS", "ENG"],
    )

    assert cfg_path.exists()
    data = yaml.safe_load(cfg_path.read_text())
    assert data["deployment"] == "cloud"
    assert data["base_url"] == "https://acme.atlassian.net"
    assert data["email"] == "u@example.com"
    assert data["api_token"] == "tok"
    assert data["allowed_spaces"] == ["DOCS", "ENG"]
    assert "status" in result
    assert result["config_path"] == str(cfg_path)


def test_init_writes_server_yaml(init_tool) -> None:
    tool, cfg_path = init_tool
    tool(
        deployment="server",
        base_url="https://conf.example.com",
        personal_access_token="pat",
    )

    data = yaml.safe_load(cfg_path.read_text())
    assert data["deployment"] == "server"
    assert data["personal_access_token"] == "pat"
    assert data.get("email") is None


def test_init_resets_cached_client(init_tool) -> None:
    import server.lib.client as client_mod

    # Seed a sentinel object
    sentinel = object()
    client_mod._cached_client = sentinel  # type: ignore[assignment]

    tool, _cfg_path = init_tool
    tool(
        deployment="server",
        base_url="https://c.example.com",
        personal_access_token="pat",
    )

    assert client_mod._cached_client is None
