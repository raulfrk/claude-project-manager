"""Unit tests for confluence_list_comments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import comments as cm_mod


@pytest.fixture()
def tool():
    mcp = FastMCP("test")
    cm_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_comments"].fn


def test_comments_envelope_shape(tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "id": "c1",
                "version": {"when": "2026-04-20T10:00:00Z", "by": {"displayName": "Alice"}},
                "body": {"view": {"value": "<p>nice</p>"}},
                "extensions": {"location": "footer"},
            }
        ],
        "size": 1,
        "_links": {},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.comments.get_client", return_value=client):
        result = tool(page_id="42")

    assert result["count"] == 1
    assert result["results"][0]["id"] == "c1"
    assert result["results"][0]["author"] == "Alice"
    assert "nice" in result["results"][0]["body_md"]
    assert result["results"][0]["location"] == "footer"


def test_comments_location_filter(tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.comments.get_client", return_value=client):
        tool(page_id="42", location="inline")

    params = client.get.call_args.kwargs["params"]
    assert params["location"] == "inline"
