"""Tests for wiki_lint_broken_links + wiki_lint_broken_section_refs."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


def _write_page_with_body(wiki_dir: Path, category: str, slug: str, body: str, **fm_extras) -> None:
    """Like _write_page but sets body text (needed for inline [[wikilinks]] + section tests)."""
    import yaml

    fm = {
        "title": slug.title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    fm.update(fm_extras)
    path = wiki_dir / "pages" / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{yaml.safe_dump(fm)}---\n{body}")


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
        _write_page_with_body(
            wiki_setup["wiki_dir"], "concepts", "a", "See [[nonexistent]] for more."
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        assert any(b["link"] == "nonexistent" for b in result["broken"])

    async def test_alias_resolves_not_broken(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "hooks-plugin", aliases=["hooks"])
        _write_page_with_body(wiki_setup["wiki_dir"], "concepts", "b", "See [[hooks]] for details.")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_links"))
        # [[hooks]] resolves via alias → not broken
        assert not any(b["link"] == "hooks" for b in result["broken"])


@pytest.mark.asyncio
class TestWikiLintBrokenSectionRefs:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_present(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page_with_body(
            wiki_setup["wiki_dir"],
            "concepts",
            "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page_with_body(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[target#Overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []

    async def test_section_missing(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page_with_body(
            wiki_setup["wiki_dir"],
            "concepts",
            "target",
            "# Target\n\n## Overview\n\nbody",
        )
        _write_page_with_body(
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
        _write_page_with_body(
            wiki_setup["wiki_dir"],
            "concepts",
            "a",
            "See [[ghost#Overview]] for details.",
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_broken_section_refs"))
        assert result["broken"] == []
