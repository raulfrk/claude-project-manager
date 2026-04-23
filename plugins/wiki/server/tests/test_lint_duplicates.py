"""Tests for wiki_lint_duplicates."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintDuplicates:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        assert result["duplicates"] == []

    async def test_no_duplicates(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        assert result["duplicates"] == []

    async def test_duplicate_slug_different_categories(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        dupes = result["duplicates"]
        assert len(dupes) == 1
        # Each group is [path_a, path_b, ...]
        paths = dupes[0]
        assert len(paths) == 2
        assert all("hooks.md" in p for p in paths)

    async def test_case_insensitive_match(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "Hooks")
        _write_page(wiki_setup["wiki_dir"], "decisions", "hooks")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_duplicates"))
        assert len(result["duplicates"]) == 1
