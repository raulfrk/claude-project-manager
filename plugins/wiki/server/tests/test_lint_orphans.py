"""Tests for wiki_lint_orphans."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintOrphans:
    async def test_empty_wiki_no_orphans(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        assert result["orphans"] == []

    async def test_single_page_is_orphan(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "alone")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        # With default orphan_min_page_count=3, a single-page wiki doesn't report orphans.
        assert result["orphans"] == []

    async def test_orphan_detected_above_threshold(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Write 3 pages: 2 linked together, 1 orphan
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b")
        _write_page(wiki_setup["wiki_dir"], "concepts", "alone")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        slugs = sorted(p["slug"] for p in result["orphans"])
        assert slugs == ["alone"]

    async def test_page_with_only_inbound_not_orphan(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", links_to=["b"])
        _write_page(wiki_setup["wiki_dir"], "concepts", "b")  # no outlinks, has inlink from a
        _write_page(wiki_setup["wiki_dir"], "concepts", "c")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        slugs = [p["slug"] for p in result["orphans"]]
        assert "b" not in slugs
        assert "c" in slugs

    async def test_threshold_configurable_via_config_yaml(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Lower orphan threshold to 1 via wiki/config.yaml
        import yaml

        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
        if data is None:
            data = {}
        data.setdefault("lint", {})["orphan_min_page_count"] = 1
        cfg_path.write_text(yaml.safe_dump(data))

        _write_page(wiki_setup["wiki_dir"], "concepts", "alone")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_orphans"))
        assert len(result["orphans"]) == 1
