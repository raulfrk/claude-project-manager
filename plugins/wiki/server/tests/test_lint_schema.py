"""Tests for wiki_lint_schema."""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import _write_page, call_tool


@pytest.mark.asyncio
class TestWikiLintSchema:
    async def test_empty_wiki(self, mcp_app: FastMCP) -> None:
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        assert result["violations"] == []

    async def test_fully_valid_page_no_violations(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        assert result["violations"] == []

    async def test_missing_required_fields_flagged(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Create wiki/config.yaml with required_frontmatter
        import yaml

        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "required_frontmatter": [
                        "title",
                        "tags",
                        "links_to",
                        "scope",
                        "sources",
                        "last_ingested",
                    ]
                }
            )
        )

        # Hand-write a page with only title + tags (missing links_to, scope, sources, last_ingested)
        path = wiki_setup["wiki_dir"] / "pages" / "concepts" / "bad.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: Bad\ntags: []\n---\nbody")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        violations = result["violations"]
        # At least one violation for the bad page (missing required fields)
        bad_violations = [v for v in violations if v["page"] == "bad"]
        assert len(bad_violations) >= 1
        missing = set(bad_violations[0]["missing_fields"])
        assert {"links_to", "scope", "sources", "last_ingested"}.issubset(missing)

    async def test_malformed_last_ingested_flagged(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        _write_page(wiki_setup["wiki_dir"], "concepts", "a", last_ingested="not-a-date")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        violations = result["violations"]
        assert len(violations) == 1
        assert "last_ingested" in violations[0].get("invalid_fields", [])

    async def test_config_override_required_fields(
        self, mcp_app: FastMCP, wiki_setup: dict[str, Path]
    ) -> None:
        # Override required_frontmatter in wiki/config.yaml to be stricter
        import yaml

        cfg_path = wiki_setup["wiki_dir"] / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text())
        data["required_frontmatter"] = [
            "title",
            "tags",
            "links_to",
            "scope",
            "sources",
            "last_ingested",
            "verified_at",
        ]
        cfg_path.write_text(yaml.safe_dump(data))
        _write_page(wiki_setup["wiki_dir"], "concepts", "a")
        result = json.loads(await call_tool(mcp_app, "wiki_lint_schema"))
        assert any("verified_at" in v["missing_fields"] for v in result["violations"])
