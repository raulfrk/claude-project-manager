"""Tests for wiki_page_delete."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiPageDelete:
    async def test_delete_existing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "target")
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "target.md"
        assert path.exists()

        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="target", category="concepts")
        )
        assert result["deleted"] is True
        assert not path.exists()

    async def test_delete_missing_returns_error(self, mcp_app: FastMCP) -> None:
        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="nope", category="concepts")
        )
        assert "error" in result
        assert "not_found" in result["error"]

    async def test_delete_updates_backlinks(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "target")
        _write_page(wiki_setup["wiki_dir"], "concepts", "referrer", links_to=["target"])

        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="target", category="concepts")
        )
        assert result["deleted"] is True
        assert "referrer" in result["backlinks_updated"]

        referrer_path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "referrer.md"
        import yaml

        raw = referrer_path.read_text()
        fm_text = raw.split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert "target" not in fm.get("links_to", [])

    async def test_delete_no_backlinks_reports_empty(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "lonely")
        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="lonely", category="concepts")
        )
        assert result["deleted"] is True
        assert result["backlinks_updated"] == []
