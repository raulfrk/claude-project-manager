"""Tests for wiki_lint_broken_links + wiki_lint_broken_section_refs."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


@pytest.mark.asyncio
class TestWikiLintBrokenLinks:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert result["broken"] == []

    async def test_no_broken_links(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert result["broken"] == []

    async def test_frontmatter_links_to_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["ghost"])
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        broken = result["broken"]
        assert len(broken) == 1
        assert broken[0]["from"] == "a"
        assert broken[0]["link"] == "ghost"

    async def test_inline_wikilink_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "See [[nonexistent]] for more.")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert any(b["link"] == "nonexistent" for b in result["broken"])

    async def test_alias_resolves_not_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks-plugin", aliases=["hooks"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b", "See [[hooks]] for details.")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        # [[hooks]] resolves via alias → not broken
        assert not any(b["link"] == "hooks" for b in result["broken"])

    async def test_inline_wikilink_with_display_alias_strips_alias(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """Bug fix: ``[[page|display alias]]`` previously linted as broken
        because ``_collect_link_targets`` returned the raw match
        ``page|display alias``, which then failed slug lookup. After the fix,
        the alias is stripped → resolver looks up ``page`` only.
        """
        _write_page(wiki_setup["wiki_dir"], "concepts", "target")
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[target|the target page]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        # Alias-stripped target resolves → not broken.
        assert result["broken"] == []

    async def test_inline_wikilink_with_alias_pointing_to_missing_page_still_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """When the page is missing, ``[[ghost|nice name]]`` is still broken,
        but the reported ``link`` field is the alias-stripped slug ``ghost``,
        not the raw ``ghost|nice name``.
        """
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", "See [[ghost|nice name]] for details.")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        broken = [b for b in result["broken"] if b["from"] == "a"]
        assert len(broken) == 1
        assert broken[0]["link"] == "ghost"


@pytest.mark.asyncio
class TestWikiLintBrokenSectionRefs:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_present(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[target#Overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_missing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[target#Missing]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        broken = result["broken"]
        assert len(broken) == 1
        assert broken[0]["from"] == "a"
        assert broken[0]["link"] == "target#Missing"
        assert broken[0]["resolved_page"].endswith("target.md")

    async def test_page_missing_excluded(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # When the page itself is missing, broken_links catches it — not broken_section_refs
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[ghost#Overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_ref_with_display_alias_strips_alias(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        """Bug fix: ``[[page#section|display alias]]`` previously linted as a
        broken section ref because ``_collect_link_targets`` returned the raw
        match ``page#section|display alias``, which split into
        section=``section|display alias``, never matching the heading. After
        the fix, the alias is stripped before split → section lookup uses
        ``section`` only.
        """
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[target#Overview|the overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        # Alias-stripped section resolves → not broken.
        assert result["broken"] == []
