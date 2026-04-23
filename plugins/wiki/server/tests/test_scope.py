"""Tests for wiki_scope_detect."""

import json
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestWikiScopeDetect:
    async def test_proj_absent(self, mcp_app: FastMCP, proj_paths: dict[str, Path]) -> None:
        """proj.yaml doesn't exist → global, proj_present=False."""
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is False

    async def test_proj_present_no_session(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """proj.yaml exists, no session file → global, proj_present=True."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_session_file_resolves_project_scope(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """Session file has `active: my-proj` → scope=project:my-proj."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": "my-proj"}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:my-proj"
        assert result["proj_present"] is True

    async def test_session_file_without_proj_yaml_still_works(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """If session file exists but proj.yaml doesn't, still detect scope."""
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": "lonely-proj"}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:lonely-proj"
        assert result["proj_present"] is False

    async def test_malformed_proj_yaml(self, mcp_app: FastMCP, proj_paths: dict[str, Path]) -> None:
        """Malformed proj.yaml: treat as global but proj_present=True."""
        proj_paths["proj_yaml"].write_text("not: valid: yaml: :")
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_malformed_session_file_falls_back_to_global(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text("not: : : valid")
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
        assert result["proj_present"] is True

    async def test_session_file_empty_active_field(
        self, mcp_app: FastMCP, proj_paths: dict[str, Path]
    ) -> None:
        """active: null or active: '' → treat as no active project."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": None}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"
