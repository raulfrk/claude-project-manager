"""Tests for wiki_page_delete."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


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

    async def test_delete_with_slug_collision_preserves_backlinks(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """Bug 751 regression: when two pages share a stem across categories,
        deleting one must NOT strip the slug from other pages' links_to.

        Setup: two pages with stem "hooks" in different categories
        (concepts/hooks.md + decisions/hooks.md). A third page
        topics/integrations.md links to slug "hooks". Deleting
        concepts/hooks.md leaves decisions/hooks.md intact, so the slug
        "hooks" still resolves and integrations.md's links_to must remain
        unchanged.
        """
        wiki_dir = wiki_setup["wiki_dir"]
        _write_page(wiki_dir, "concepts", "hooks")
        _write_page(wiki_dir, "decisions", "hooks")
        _write_page(wiki_dir, "topics", "integrations", links_to=["hooks"])

        result = json.loads(
            await call_tool(mcp_app, "wiki_page_delete", slug="hooks", category="concepts")
        )
        assert result["deleted"] is True
        assert result["backlinks_updated"] == []  # no prune — same-slug page survives

        # Surviving same-slug page intact.
        assert (wiki_dir / "pages" / "decisions" / "hooks.md").exists()

        # links_to on the referring page unchanged.
        from server.lib import frontmatter as fm_mod

        referrer_text = (wiki_dir / "pages" / "topics" / "integrations.md").read_text()
        fm, _body = fm_mod.parse(referrer_text)
        assert fm.get("links_to") == ["hooks"]
