"""Tests for wiki_link_resolve."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


@pytest.mark.asyncio
class TestWikiLinkResolve:
    async def test_resolve_by_slug(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks-architecture")
        result = json.loads(
            await call_tool(mcp_app, "wiki_link_resolve", link="hooks-architecture")
        )
        assert result["resolved"].endswith("hooks-architecture.md")
        assert result["section_found"] is None
        assert result["candidates"] == []

    async def test_resolve_missing(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="nope"))
        assert result["resolved"] is None

    async def test_resolve_case_insensitive(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="HOOKS"))
        assert result["resolved"] is not None

    async def test_resolve_by_alias(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "hooks-plugin-architecture",
            aliases=["hooks-architecture"],
        )
        result = json.loads(
            await call_tool(mcp_app, "wiki_link_resolve", link="hooks-architecture")
        )
        assert result["resolved"].endswith("hooks-plugin-architecture.md")

    async def test_resolve_section_present(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\ntitle: Hooks\ntags: []\nlinks_to: []\nscope: []\n"
            "sources: []\nlast_ingested: '2026-04-23'\n---\n"
            "# Hooks\n\n## Overview\n\ndetails\n\n## Dispatch\n\nmore"
        )
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="hooks#Dispatch"))
        assert result["resolved"].endswith("hooks.md")
        assert result["section_found"] is True

    async def test_resolve_section_missing(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="hooks#Nonexistent"))
        assert result["resolved"].endswith("hooks.md")
        assert result["section_found"] is False

    async def test_resolve_collisions(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="hooks"))
        # First match wins (sorted) + candidates list populated
        assert result["resolved"] is not None
        assert len(result["candidates"]) >= 1

    async def test_resolve_with_display_alias(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """[[slug|display alias]] — `|alias` portion is for rendering only,
        must be stripped before slug lookup."""
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_link_resolve", link="hooks|Hook System"))
        assert result["resolved"].endswith("hooks.md"), result
        assert result["section_found"] is None

    async def test_resolve_with_section_and_display_alias(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """[[slug#section|display alias]] — both `#section` + `|alias` parsed."""
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\ntitle: Hooks\ntags: []\nlinks_to: []\nscope: []\n"
            "sources: []\nlast_ingested: '2026-04-23'\n---\n"
            "# Hooks\n\n## Dispatch\n\nbody"
        )
        result = json.loads(
            await call_tool(mcp_app, "wiki_link_resolve", link="hooks#Dispatch|Dispatch flow")
        )
        assert result["resolved"].endswith("hooks.md")
        assert result["section_found"] is True
