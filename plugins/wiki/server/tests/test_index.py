"""Tests for wiki_index_read + wiki_index_rebuild."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiIndexRebuild:
    async def test_rebuild_empty(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_index_rebuild"))
        assert result["entries_by_category"] == {}
        index_md = wiki_setup["wiki_dir"] / "index.md"
        assert index_md.exists()
        assert "# Wiki Index" in index_md.read_text()

    async def test_rebuild_groups_by_category(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks", tags=["hooks"])
        _write_page(wiki_setup["wiki_dir"], "decisions", "fastmcp", tags=["mcp"])
        _write_page(wiki_setup["wiki_dir"], "references", "api")
        result = json.loads(await call_tool(mcp_app, "wiki_index_rebuild"))
        assert result["entries_by_category"]["concepts"] == 1
        assert result["entries_by_category"]["decisions"] == 1
        assert result["entries_by_category"]["references"] == 1
        content = (wiki_setup["wiki_dir"] / "index.md").read_text()
        assert "## Concepts" in content
        assert "[[hooks]]" in content

    async def test_rebuild_includes_recent(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(
            wiki_setup["wiki_dir"], "concepts", "newest", last_ingested="2026-04-23T12:00:00Z"
        )
        _write_page(
            wiki_setup["wiki_dir"], "concepts", "older", last_ingested="2024-01-01T00:00:00Z"
        )
        await call_tool(mcp_app, "wiki_index_rebuild")
        content = (wiki_setup["wiki_dir"] / "index.md").read_text()
        assert "## Recent" in content
        # Newest first
        recent_section = content.split("## Recent")[1]
        assert recent_section.index("newest") < recent_section.index("older")

    async def test_rebuild_is_idempotent(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        await call_tool(mcp_app, "wiki_index_rebuild")
        first = (wiki_setup["wiki_dir"] / "index.md").read_text()
        await call_tool(mcp_app, "wiki_index_rebuild")
        second = (wiki_setup["wiki_dir"] / "index.md").read_text()
        assert first == second


@pytest.mark.asyncio
class TestWikiIndexRead:
    async def test_read_when_missing(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_index_read"))
        assert result["content"] == ""
        assert result["categories"] == {}
        assert result["recent"] == []

    async def test_read_after_rebuild(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        await call_tool(mcp_app, "wiki_index_rebuild")
        result = json.loads(await call_tool(mcp_app, "wiki_index_read"))
        assert "Wiki Index" in result["content"]
        assert result["categories"].get("concepts") == 1
