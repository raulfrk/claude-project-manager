"""Tests for wiki_scope_detect."""

import json
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiScopeDetect:
    async def test_proj_absent(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        """proj.yaml doesn't exist → scope='global', proj_present=False."""
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is False

    async def test_proj_present_no_active(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        """proj.yaml exists but no active project → scope='global', proj_present=True."""
        proj_yaml_path.write_text(yaml.safe_dump({}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_proj_present_with_valid_data(
        self, mcp_app: FastMCP, proj_yaml_path: Path
    ) -> None:
        """proj.yaml exists w/ config data → scope='global', proj_present=True.

        Note: active project is session-scoped only (not persisted to proj.yaml),
        so even valid proj.yaml always returns global scope.
        """
        proj_yaml_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "tracking_dir": "~/projects/tracking",
                    "git_integration": True,
                }
            )
        )
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_malformed_proj_yaml(self, mcp_app: FastMCP, proj_yaml_path: Path) -> None:
        """Malformed proj.yaml → treat as global, but proj_present=True."""
        proj_yaml_path.write_text("not: valid: yaml: :")
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True
