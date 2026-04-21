"""Unit tests for confluence_list_spaces."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import spaces as spaces_mod


@pytest.fixture()
def list_spaces_tool():
    mcp = FastMCP("test")
    spaces_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_spaces"].fn


def test_list_spaces_envelope_shape(list_spaces_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "key": "DOCS",
                "name": "Docs",
                "type": "global",
                "_links": {"webui": "/display/DOCS"},
            }
        ],
        "size": 1,
        "_links": {"next": "/space?..."},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.spaces.get_client", return_value=client):
        result = list_spaces_tool()

    assert result["count"] == 1
    assert result["results"][0]["key"] == "DOCS"
    assert result["next_start"] == 25


def test_list_spaces_passes_type_filter(list_spaces_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.spaces.get_client", return_value=client):
        list_spaces_tool(type="personal")

    params = client.get.call_args.kwargs["params"]
    assert params["type"] == "personal"


def test_list_spaces_no_next_link_returns_null_cursor(list_spaces_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.spaces.get_client", return_value=client):
        result = list_spaces_tool()

    assert result["next_start"] is None
