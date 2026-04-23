"""Tests for wiki_lint_stale."""

import json
from datetime import UTC
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintStale:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        assert result["stale"] == []

    async def test_fresh_pages_not_stale(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        from datetime import datetime

        recent = datetime.now(UTC).isoformat()
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested=recent)
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        assert result["stale"] == []

    async def test_old_page_flagged(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        _write_page(
            wiki_setup["wiki_dir"], "concepts", "ancient", last_ingested="2020-01-01T00:00:00Z"
        )
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        slugs = [p["slug"] for p in result["stale"]]
        assert "ancient" in slugs

    async def test_days_param_override(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        # Page 10 days old; default threshold 90 → not stale; with days=5 → stale
        from datetime import datetime, timedelta

        ten_days_ago = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested=ten_days_ago)

        r_default = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        assert r_default["stale"] == []

        r_strict = json.loads(await call_tool(mcp_app, "wiki_lint_stale", days=5))
        assert any(p["slug"] == "a" for p in r_strict["stale"])

    async def test_malformed_date_excluded(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested="not-a-date")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_stale"))
        # Unparseable dates are not flagged as stale — reported under schema lint instead
        assert result["stale"] == []
