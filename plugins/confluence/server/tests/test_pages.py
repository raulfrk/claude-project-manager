"""Unit tests for pages tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import pages as pages_mod


@pytest.fixture()
def get_page_tool():
    mcp = FastMCP("test")
    pages_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_get_page"].fn


def test_get_page_by_id_returns_markdown(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "id": "42",
        "title": "My Page",
        "version": {"number": 3},
        "space": {"key": "DOCS"},
        "body": {"view": {"value": "<h1>Hello</h1>"}},
        "_links": {"webui": "/display/DOCS/My+Page"},
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(page_id="42")

    client.get.assert_called_once()
    path_called = client.get.call_args.args[0]
    assert path_called == "/content/42"
    assert result["page_id"] == "42"
    assert result["title"] == "My Page"
    assert result["space_key"] == "DOCS"
    assert result["version"] == 3
    assert "# Hello" in result["body_md"]


def test_get_page_by_title_and_space(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "id": "99",
                "title": "Target",
                "version": {"number": 1},
                "space": {"key": "DOCS"},
                "body": {"view": {"value": "<p>x</p>"}},
                "_links": {"webui": "/"},
            }
        ]
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(title="Target", space_key="DOCS")

    path_called = client.get.call_args.args[0]
    assert path_called == "/content"
    params = client.get.call_args.kwargs["params"]
    assert params["spaceKey"] == "DOCS"
    assert params["title"] == "Target"
    assert result["page_id"] == "99"


def test_get_page_format_html_returns_html_only(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "id": "1",
        "title": "T",
        "version": {"number": 1},
        "space": {"key": "D"},
        "body": {"view": {"value": "<p>x</p>"}},
        "_links": {"webui": "/"},
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(page_id="1", format="html")

    assert "body_html" in result
    assert "body_md" not in result


def test_get_page_format_both_returns_both(get_page_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "id": "1",
        "title": "T",
        "version": {"number": 1},
        "space": {"key": "D"},
        "body": {"view": {"value": "<p>x</p>"}},
        "_links": {"webui": "/"},
    }
    client.config = MagicMock(allowed_spaces=[])
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = get_page_tool(page_id="1", format="both")

    assert "body_md" in result
    assert "body_html" in result


def test_get_page_requires_id_or_title(get_page_tool) -> None:
    with (
        patch("server.tools.pages.get_client", return_value=MagicMock()),
        pytest.raises(ValueError),
    ):
        get_page_tool()


def test_get_page_title_requires_space(get_page_tool) -> None:
    with (
        patch("server.tools.pages.get_client", return_value=MagicMock()),
        pytest.raises(ValueError),
    ):
        get_page_tool(title="Target")


def test_get_page_enforces_allowed_spaces_by_title(get_page_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    client.check_space_allowed.side_effect = SpaceNotAllowedError("ENG")
    client.config = MagicMock(allowed_spaces=["DOCS"])

    with (
        patch("server.tools.pages.get_client", return_value=client),
        pytest.raises(SpaceNotAllowedError),
    ):
        get_page_tool(title="x", space_key="ENG")


def test_get_page_enforces_allowed_spaces_after_fetch(get_page_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    client.get.return_value = {
        "id": "42",
        "title": "T",
        "version": {"number": 1},
        "space": {"key": "ENG"},
        "body": {"view": {"value": "<p>x</p>"}},
        "_links": {"webui": "/"},
    }

    def _check(key):
        if key == "ENG":
            raise SpaceNotAllowedError("ENG")

    client.check_space_allowed.side_effect = _check
    client.config = MagicMock(allowed_spaces=["DOCS"])

    with (
        patch("server.tools.pages.get_client", return_value=client),
        pytest.raises(SpaceNotAllowedError),
    ):
        get_page_tool(page_id="42")
