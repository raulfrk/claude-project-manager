"""Unit tests for confluence_get_page_tree."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import pages as pages_mod


@pytest.fixture()
def tree_tool():
    mcp = FastMCP("test")
    pages_mod.register(mcp)
    return mcp._tool_manager._tools["confluence_get_page_tree"].fn


def test_tree_nests_by_ancestors(tree_tool) -> None:
    client = MagicMock()
    call_count = [0]

    def fake_get(path, params):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": "10", "title": "root", "space": {"key": "DOCS"}, "_links": {}}
        return {
            "results": [
                {"id": "11", "title": "c1", "ancestors": [{"id": "10"}]},
                {"id": "12", "title": "c2", "ancestors": [{"id": "10"}]},
                {"id": "13", "title": "gc", "ancestors": [{"id": "10"}, {"id": "11"}]},
            ],
            "size": 3,
            "_links": {},
        }

    client.get.side_effect = fake_get
    client.config = MagicMock(default_max_results=25)
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = tree_tool(root_page_id="10")

    tree = result["tree"]
    assert tree["page_id"] == "10"
    ids_at_level_1 = sorted(c["page_id"] for c in tree["children"])
    assert ids_at_level_1 == ["11", "12"]
    c1 = next(c for c in tree["children"] if c["page_id"] == "11")
    assert c1["children"][0]["page_id"] == "13"


def test_tree_max_nodes_cap(tree_tool) -> None:
    client = MagicMock()
    call_count = [0]

    def fake_get(path, params):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": "1", "title": "root", "space": {"key": "DOCS"}, "_links": {}}
        return {
            "results": [
                {"id": str(i), "title": f"n{i}", "ancestors": [{"id": "1"}]} for i in range(500)
            ],
            "size": 500,
            "_links": {},
        }

    client.get.side_effect = fake_get
    client.config = MagicMock(default_max_results=25)
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = tree_tool(root_page_id="1", max_nodes=10)

    def count(n):
        return 1 + sum(count(c) for c in n.get("children", []))

    assert count(result["tree"]) <= 11  # root + up to 10
    assert result.get("truncated") is True


def test_tree_enforces_allowed_spaces(tree_tool) -> None:
    from server.lib.errors import SpaceNotAllowedError

    client = MagicMock()
    # First call: /content/10 for root info
    # If the check raises, we never get to descendants
    client.get.return_value = {
        "id": "10",
        "title": "root",
        "space": {"key": "ENG"},
        "_links": {"webui": "/"},
    }
    client.check_space_allowed.side_effect = SpaceNotAllowedError("ENG")
    client.config = MagicMock(allowed_spaces=["DOCS"], default_max_results=25)

    with (
        patch("server.tools.pages.get_client", return_value=client),
        pytest.raises(SpaceNotAllowedError),
    ):
        tree_tool(root_page_id="10")


def test_tree_root_title_populated(tree_tool) -> None:
    client = MagicMock()
    call_count = [0]

    def fake_get(path, params):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": "10", "title": "RootTitle", "space": {"key": "DOCS"}, "_links": {}}
        return {"results": [], "size": 0, "_links": {}}

    client.get.side_effect = fake_get
    client.config = MagicMock(default_max_results=25)
    client.check_space_allowed = MagicMock()

    with patch("server.tools.pages.get_client", return_value=client):
        result = tree_tool(root_page_id="10")

    assert result["tree"]["title"] == "RootTitle"
