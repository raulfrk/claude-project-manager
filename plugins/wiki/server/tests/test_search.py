"""Tests for wiki_search_bm25 + wiki_search_index_refresh."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


@pytest.mark.asyncio
class TestWikiSearchBM25:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="anything"))
        assert result["hits"] == []

    async def test_basic_keyword_search(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks", "Hooks dispatch via router.")
        _write_page(wiki_setup["wiki_dir"], "concepts", "cache", "Cache uses LRU eviction.")
        _write_page(wiki_setup["wiki_dir"], "concepts", "filler", "unrelated filler page.")
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="router"))
        assert len(result["hits"]) >= 1
        assert result["hits"][0]["slug"] == "hooks"

    async def test_limit_respected(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        for i in range(5):
            _write_page(wiki_setup["wiki_dir"], "concepts", f"p{i}", f"content-word p{i}")
        # Need at least one differentiating page for BM25 to produce non-zero scores
        _write_page(wiki_setup["wiki_dir"], "concepts", "other", "totally different topic here")
        result = json.loads(
            await call_tool(mcp_app, "wiki_search_bm25", query="content-word", limit=2)
        )
        assert len(result["hits"]) <= 2

    async def test_filter_by_category(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks-c", "router hooks here")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks-d", "router decisions about hooks")
        _write_page(wiki_setup["wiki_dir"], "concepts", "unrelated", "nothing relevant here")
        result = json.loads(
            await call_tool(mcp_app, "wiki_search_bm25", query="hooks", category="concepts")
        )
        slugs = [h["slug"] for h in result["hits"]]
        assert "hooks-c" in slugs
        assert "hooks-d" not in slugs

    async def test_filter_by_tags(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "shared-token body", tags=["x"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "shared-token body", tags=["y"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "c", "other stuff", tags=["z"])
        result = json.loads(
            await call_tool(mcp_app, "wiki_search_bm25", query="shared-token", tags=["x"])
        )
        slugs = [h["slug"] for h in result["hits"]]
        assert slugs == ["a"]

    async def test_filter_by_scope(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "scope-token", scope=["project:cpm"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "scope-token", scope=["global"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "c", "other", scope=["global"])
        result = json.loads(
            await call_tool(
                mcp_app, "wiki_search_bm25", query="scope-token", scope_filter="project:cpm"
            )
        )
        assert [h["slug"] for h in result["hits"]] == ["a"]

    async def test_snippet_populated(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(
            wiki_setup["wiki_dir"], "concepts", "hooks", "Hooks plugin architecture is centralized."
        )
        _write_page(wiki_setup["wiki_dir"], "concepts", "other", "nothing relevant here at all")
        _write_page(wiki_setup["wiki_dir"], "concepts", "filler", "filler content")
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="centralized"))
        assert len(result["hits"]) == 1
        assert "centralized" in result["hits"][0]["snippet"].lower()

    async def test_rebuilds_on_staleness(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # First search builds + caches index
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "alpha beta")
        _write_page(wiki_setup["wiki_dir"], "concepts", "filler", "totally different content")
        await call_tool(mcp_app, "wiki_search_bm25", query="alpha")
        # Add a new page; search should auto-rebuild and find it
        import time

        time.sleep(0.01)
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "beta gamma")
        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="gamma"))
        assert any(h["slug"] == "b" for h in result["hits"])

    async def test_flat_layout_minimal_profile_returns_hits(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """Minimal-profile wiki w/ flat pages/ layout must still return BM25 hits."""
        import yaml

        # Switch to minimal profile (empty categories, flat pages/)
        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        cfg_path.write_text(yaml.safe_dump({"schema_version": 1, "profile": "minimal"}))

        # Write 3 flat pages (no category dir)
        pages_dir = wiki_setup["wiki_dir"] / "pages"
        for slug, body in [
            ("hooks", "Hooks dispatch via router."),
            ("cache", "Cache uses LRU."),
            ("filler", "unrelated"),
        ]:
            fm = yaml.safe_dump(
                {
                    "title": slug.title(),
                    "tags": [],
                    "links_to": [],
                    "scope": ["global"],
                    "sources": [],
                    "last_ingested": "2026-04-23T10:00:00Z",
                }
            )
            (pages_dir / f"{slug}.md").write_text(f"---\n{fm}---\n{body}")

        result = json.loads(await call_tool(mcp_app, "wiki_search_bm25", query="router"))
        slugs = [h["slug"] for h in result["hits"]]
        assert "hooks" in slugs, f"Expected 'hooks' in minimal-profile hits, got: {slugs}"


@pytest.mark.asyncio
class TestWikiSearchIndexRefresh:
    async def test_refresh_empty(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_search_index_refresh"))
        assert result["pages_indexed"] == 0
        assert result["elapsed_ms"] >= 0

    async def test_refresh_rebuilds_index(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "content a")
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "content b")
        result = json.loads(await call_tool(mcp_app, "wiki_search_index_refresh"))
        assert result["pages_indexed"] == 2
        assert result["elapsed_ms"] >= 0
