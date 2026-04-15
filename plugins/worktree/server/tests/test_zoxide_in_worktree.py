"""Smoke tests: zoxide tools folded into worktree server."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools.zoxide import register


@pytest.fixture()
def app() -> FastMCP:
    """Fresh FastMCP instance with zoxide tools registered."""
    instance = FastMCP("test-worktree")
    register(instance)
    return instance


class TestZoxideToolsRegistered:
    """zoxide tools must appear in worktree server after fold."""

    def test_zoxide_boost_registered(self, app: FastMCP) -> None:
        names = [t.name for t in app._tool_manager.list_tools()]
        assert "zoxide_boost" in names

    def test_zoxide_query_registered(self, app: FastMCP) -> None:
        names = [t.name for t in app._tool_manager.list_tools()]
        assert "zoxide_query" in names

    def test_zoxide_remove_registered(self, app: FastMCP) -> None:
        names = [t.name for t in app._tool_manager.list_tools()]
        assert "zoxide_remove" in names
