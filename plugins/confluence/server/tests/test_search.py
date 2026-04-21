"""Unit tests for confluence_search tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import search as search_mod


@pytest.fixture()
def search_tool():
    mcp = FastMCP("test")
    search_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_search"].fn


def test_search_wraps_text_in_cql(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [],
        "size": 0,
        "totalSize": 0,
        "_links": {},
    }
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="incident report")

    call_params = client.get.call_args.kwargs["params"]
    assert 'text ~ "incident report"' in call_params["cql"]


def test_search_with_raw_cql_passes_through(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(cql="space = DOCS AND type = page")

    assert client.get.call_args.kwargs["params"]["cql"] == "space = DOCS AND type = page"


def test_search_injects_space_filter_when_space_key_given(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="foo", space_key="DOCS")

    cql = client.get.call_args.kwargs["params"]["cql"]
    assert 'space = "DOCS"' in cql


def test_search_envelope_shape(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {
        "results": [
            {
                "content": {
                    "id": "42",
                    "type": "page",
                    "title": "Incident",
                    "space": {"key": "DOCS"},
                },
                "excerpt": "snippet",
                "url": "/display/DOCS/Incident",
                "lastModified": "2026-04-20T10:00:00Z",
            }
        ],
        "size": 1,
        "totalSize": 10,
        "_links": {"next": "/search?..."},
    }
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        result = search_tool(text="foo", limit=1, start=0)

    assert result["count"] == 1
    assert result["total"] == 10
    assert result["next_start"] == 1
    assert result["results"][0]["page_id"] == "42"
    assert result["results"][0]["space_key"] == "DOCS"


def test_search_enforces_allowed_spaces(search_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    client.check_space_allowed.side_effect = SpaceNotAllowedError("ENG")
    client.config = MagicMock(allowed_spaces=["DOCS"], default_max_results=25)

    with (
        patch("server.tools.search.get_client", return_value=client),
        pytest.raises(SpaceNotAllowedError),
    ):
        search_tool(text="foo", space_key="ENG")


def test_search_escapes_double_quote_in_text(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text='foo" OR type=user OR "bar')

    cql = client.get.call_args.kwargs["params"]["cql"]
    assert 'text ~ "foo\\" OR type=user OR \\"bar"' in cql


def test_search_escapes_backslash_in_text(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="path\\foo")

    cql = client.get.call_args.kwargs["params"]["cql"]
    assert 'text ~ "path\\\\foo"' in cql


def test_search_cql_none_and_text_none_raises(search_tool) -> None:
    with (
        patch("server.tools.search.get_client", return_value=MagicMock()),
        pytest.raises(ValueError, match="Either cql or text"),
    ):
        search_tool()


def test_search_escapes_double_quote_in_space_key(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)
    client.check_space_allowed = MagicMock()

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="foo", space_key='A" OR x="B')

    cql = client.get.call_args.kwargs["params"]["cql"]
    # Raw `"` must not appear unescaped within the space_key value
    assert 'space = "A\\" OR x=\\"B"' in cql


def test_search_escapes_double_quote_in_type(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=[], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="foo", type='page" OR type="blogpost')

    cql = client.get.call_args.kwargs["params"]["cql"]
    assert 'type = "page\\" OR type=\\"blogpost"' in cql


def test_search_allowed_spaces_injection_is_quoted(search_tool) -> None:
    client = MagicMock()
    client.get.return_value = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
    client.config = MagicMock(allowed_spaces=['A"MAL', "B"], default_max_results=25)

    with patch("server.tools.search.get_client", return_value=client):
        search_tool(text="foo")

    cql = client.get.call_args.kwargs["params"]["cql"]
    assert 'space = "A\\"MAL"' in cql
    assert 'space = "B"' in cql
