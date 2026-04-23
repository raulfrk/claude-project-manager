"""Tests for wiki_lint_category_violations."""

import json
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool
from tests.test_page_list import _write_page


@pytest.mark.asyncio
class TestWikiLintCategoryViolations:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []

    async def test_profile_matches_all(self, mcp_app: FastMCP, wiki_setup: dict[str, Path]) -> None:
        # software profile has decisions, concepts, etc.
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        _write_page(wiki_setup["wiki_dir"], "decisions", "b")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []

    async def test_off_profile_category(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # "random" is not in software profile (concepts/decisions/references/pitfalls/entities)
        _write_page(wiki_setup["wiki_dir"], "random", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        violations = result["violations"]
        assert len(violations) == 1
        assert violations[0]["page"] == "a"
        assert violations[0]["found_category"] == "random"
        # configured list contains the 5 software-profile categories
        assert "concepts" in violations[0]["configured"]

    async def test_flat_page_non_minimal_profile_is_violation(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Flat page (no category dir) under non-minimal profile → violation
        # found_category should be None (uncategorized marker)
        _write_page(wiki_setup["wiki_dir"], None, "flat")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        violations = result["violations"]
        assert len(violations) == 1
        assert violations[0]["page"] == "flat"
        assert violations[0]["found_category"] in (None, "uncategorized")
        assert "concepts" in violations[0]["configured"]

    async def test_minimal_profile_no_violations(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Switch to minimal profile: empty categories → no violations possible
        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        cfg_path.write_text(yaml.safe_dump({"schema_version": 1, "profile": "minimal"}))
        _write_page(wiki_setup["wiki_dir"], "anything", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []

    async def test_missing_profile_config_no_violations(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Delete profile config → lint can't enforce; returns []
        (wiki_setup["wiki_dir"] / "config.yaml").unlink()
        _write_page(wiki_setup["wiki_dir"], "random", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_category_violations"))
        assert result["violations"] == []
