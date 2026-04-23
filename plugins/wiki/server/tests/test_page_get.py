"""Tests for wiki_page_get."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiPageGet:
    async def test_get_existing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\ntitle: Hooks\ntags: [a]\nlinks_to: []\nscope: [global]\n"
            "sources: []\nlast_ingested: '2026-04-23'\n---\nBody text."
        )
        result = json.loads(
            await call_tool(mcp_app, "wiki_page_get", slug="hooks", category="concepts")
        )
        assert result["frontmatter"]["title"] == "Hooks"
        assert result["body"] == "Body text."
        assert result["path"].endswith("hooks.md")

    async def test_get_missing_returns_error(self, mcp_app: FastMCP) -> None:
        result = json.loads(
            await call_tool(mcp_app, "wiki_page_get", slug="nope", category="concepts")
        )
        assert result["error"] == "not_found"

    async def test_get_without_category_flat_layout(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "flat.md"
        page.write_text(
            "---\ntitle: Flat\ntags: []\nlinks_to: []\nscope: []\nsources: []\n"
            "last_ingested: '2026-04-23'\n---\nflat body"
        )
        raw = await call_tool(mcp_app, "wiki_page_get", slug="flat", category=None)
        result = json.loads(raw)
        assert result["frontmatter"]["title"] == "Flat"

    async def test_malformed_frontmatter_returns_error(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        page = wiki_setup["wiki_dir"] / "pages" / "concepts" / "broken.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("---\ntitle: : :\n---\nbody")
        result = json.loads(
            await call_tool(mcp_app, "wiki_page_get", slug="broken", category="concepts")
        )
        assert "error" in result
        assert "frontmatter" in result["error"].lower()
