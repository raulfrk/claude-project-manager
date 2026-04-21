"""Unit tests for confluence_list_attachments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import attachments as att_mod


@pytest.fixture()
def tool():
    mcp = FastMCP("test")
    att_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_list_attachments"].fn


def test_attachments_envelope_shape(tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "id": "a1",
                "title": "diagram.png",
                "extensions": {"mediaType": "image/png", "fileSize": 12345},
                "_links": {"download": "/download/a1"},
            }
        ],
        "size": 1,
        "_links": {},
    }
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.attachments.get_client", return_value=client):
        result = tool(page_id="42")

    assert result["count"] == 1
    assert result["results"][0]["id"] == "a1"
    assert result["results"][0]["media_type"] == "image/png"
    assert result["results"][0]["file_size"] == 12345
    assert result["results"][0]["download_url"] == "/download/a1"


def test_attachments_media_type_filter(tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "_links": {}}
    client.config = MagicMock(default_max_results=25)

    with patch("server.tools.attachments.get_client", return_value=client):
        tool(page_id="42", media_type="image/png")

    params = client.get.call_args.kwargs["params"]
    assert params["mediaType"] == "image/png"
