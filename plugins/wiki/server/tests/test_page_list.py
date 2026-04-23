"""Tests for wiki_page_list."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


@pytest.mark.asyncio
class TestWikiPageList:
    async def test_list_empty(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_page_list"))
        assert result["pages"] == []

    async def test_list_all(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", tags=["x"])
        _write_page(wiki_setup["wiki_dir"], "decisions", "b", tags=["y"])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list"))
        slugs = sorted(p["slug"] for p in result["pages"])
        assert slugs == ["a", "b"]

    async def test_filter_by_category(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", category="concepts"))
        assert len(result["pages"]) == 1
        assert result["pages"][0]["slug"] == "a"

    async def test_filter_by_tags(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", tags=["hooks"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", tags=["other"])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", tags=["hooks"]))
        assert [p["slug"] for p in result["pages"]] == ["a"]

    async def test_filter_by_scope(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", scope=["project:cpm"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", scope=["global"])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", scope_filter="project:cpm"))
        assert [p["slug"] for p in result["pages"]] == ["a"]

    async def test_filter_by_linked_to(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["router"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", links_to=[])
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", linked_to="router"))
        assert [p["slug"] for p in result["pages"]] == ["a"]

    async def test_filter_by_linked_from(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", links_to=[])
        # "linked_from=a" → pages that a points at → ["b"]
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", linked_from="a"))
        assert [p["slug"] for p in result["pages"]] == ["b"]

    async def test_limit(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        for i in range(5):
            _write_page(wiki_setup["wiki_dir"], "concepts", f"p{i}")
        result = json.loads(await call_tool(mcp_app, "wiki_page_list", limit=2))
        assert len(result["pages"]) == 2
        assert result["truncated"] is True
