"""Tests for wiki_page_write."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool

BASE_FRONTMATTER: dict = {
    "title": "Hooks architecture",
    "tags": ["hooks", "plugin"],
    "links_to": [],
    "scope": ["project:cpm"],
    "sources": [],
    "last_ingested": "2026-04-23T10:00:00Z",
}


@pytest.mark.asyncio
class TestWikiPageWrite:
    async def test_create_new_page(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="hooks-architecture",
                category="concepts",
                frontmatter=BASE_FRONTMATTER,
                body="# Hooks\n\nContent.",
                mode="create",
            )
        )
        assert result["created"] is True
        assert result["updated"] is False
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks-architecture.md"
        assert path.exists()
        assert "title: Hooks architecture" in path.read_text()

    async def test_create_on_existing_returns_error(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: X\n---\nold")

        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="hooks",
                category="concepts",
                frontmatter=BASE_FRONTMATTER,
                body="new",
                mode="create",
            )
        )
        assert "error" in result
        assert "exists" in result["error"].lower()
        assert path.read_text().endswith("old")

    async def test_update_existing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: Old\n---\nold body")

        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="hooks",
                category="concepts",
                frontmatter=BASE_FRONTMATTER,
                body="new body",
                mode="update",
            )
        )
        assert result["updated"] is True
        assert "new body" in path.read_text()

    async def test_update_missing_returns_error(self, mcp_app: FastMCP) -> None:
        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="nope",
                category="concepts",
                frontmatter=BASE_FRONTMATTER,
                body="",
                mode="update",
            )
        )
        assert "error" in result
        assert "not_found" in result["error"] or "does not exist" in result["error"].lower()

    async def test_upsert_creates_then_updates(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "hooks.md"
        r1 = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="hooks",
                category="concepts",
                frontmatter=BASE_FRONTMATTER,
                body="first",
                mode="upsert",
            )
        )
        assert r1["created"] is True

        r2 = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="hooks",
                category="concepts",
                frontmatter={**BASE_FRONTMATTER, "title": "Updated"},
                body="second",
                mode="upsert",
            )
        )
        assert r2["updated"] is True
        assert "second" in path.read_text()

    async def test_upsert_noop_on_identical_content(self, mcp_app: FastMCP) -> None:
        args = {
            "slug": "hooks",
            "category": "concepts",
            "frontmatter": BASE_FRONTMATTER,
            "body": "same",
            "mode": "upsert",
        }
        await call_tool(mcp_app, "wiki_page_write", **args)
        r2 = json.loads(await call_tool(mcp_app, "wiki_page_write", **args))
        # Identical payload → no-op
        assert r2.get("noop") is True

    async def test_missing_required_frontmatter_fails(self, mcp_app: FastMCP) -> None:
        incomplete: dict = {"title": "X"}  # missing tags, links_to, scope, sources, last_ingested
        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="hooks",
                category="concepts",
                frontmatter=incomplete,
                body="",
                mode="create",
            )
        )
        assert "error" in result
        assert "missing" in result["error"].lower()

    async def test_category_not_in_profile_warns_but_writes(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # software profile has 5 fixed categories; "random" is not one
        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_page_write",
                slug="odd",
                category="random",
                frontmatter=BASE_FRONTMATTER,
                body="x",
                mode="create",
            )
        )
        assert result["created"] is True
        assert result.get("warning")
        assert "category" in result["warning"].lower()
