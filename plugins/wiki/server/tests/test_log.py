"""Tests for wiki_log_append + wiki_log_read."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiLogAppend:
    async def test_append_creates_log_md(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_log_append",
                action="ingest",
                title="file:/tmp/x.md",
                body="2 pages updated",
            )
        )
        assert "entry" in result
        log_md = wiki_setup["wiki_dir"] / "log.md"
        assert log_md.exists()
        content = log_md.read_text()
        assert "## [" in content
        assert "ingest" in content
        assert "file:/tmp/x.md" in content
        assert "2 pages updated" in content

    async def test_entry_format_karpathy_prefix(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="full", body="")
        content = (wiki_setup["wiki_dir"] / "log.md").read_text()
        # Must match: ## [YYYY-MM-DD] <action> | <title>
        import re

        pattern = r"^## \[\d{4}-\d{2}-\d{2}\] lint \| full$"
        assert re.search(pattern, content, re.MULTILINE)

    async def test_append_preserves_prior_entries(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="first")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="second")
        content = (wiki_setup["wiki_dir"] / "log.md").read_text()
        assert content.index("first") < content.index("second")

    async def test_body_optional(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        result = json.loads(
            await call_tool(mcp_app, "wiki_log_append", action="note", title="observation")
        )
        assert "error" not in result


@pytest.mark.asyncio
class TestWikiLogRead:
    async def test_read_empty(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_log_read"))
        assert result["entries"] == []

    async def test_read_returns_parsed_entries(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="t1", body="b1")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="t2")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read"))
        entries = result["entries"]
        assert len(entries) == 2
        assert entries[0]["action"] == "ingest"
        assert entries[0]["title"] == "t1"
        assert entries[0]["body"] == "b1"
        assert entries[1]["action"] == "lint"

    async def test_read_action_filter(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="a")
        await call_tool(mcp_app, "wiki_log_append", action="lint", title="b")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read", action_filter="ingest"))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["action"] == "ingest"

    async def test_read_limit(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        for i in range(5):
            await call_tool(mcp_app, "wiki_log_append", action="note", title=f"n{i}")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read", limit=2))
        # Limit returns most-recent N
        assert len(result["entries"]) == 2
        assert result["entries"][-1]["title"] == "n4"

    async def test_read_since_date(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        # Seed log with an older entry
        log_md = wiki_setup["wiki_dir"] / "log.md"
        log_md.write_text("## [2024-01-01] ingest | old\nold body\n\n")
        await call_tool(mcp_app, "wiki_log_append", action="ingest", title="new")
        result = json.loads(await call_tool(mcp_app, "wiki_log_read", since="2026-01-01"))
        titles = [e["title"] for e in result["entries"]]
        assert "new" in titles
        assert "old" not in titles
