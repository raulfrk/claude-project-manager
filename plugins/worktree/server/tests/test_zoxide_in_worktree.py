"""Smoke tests: zoxide tools folded into worktree server."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools.zoxide import register


@pytest.fixture()
def app() -> FastMCP:
    """Fresh FastMCP instance with zoxide tools registered."""
    instance = FastMCP("test-worktree")
    register(instance)
    return instance


@pytest.fixture()
def zoxide_tools() -> dict:
    """Registered zoxide tools keyed by name."""
    inst = FastMCP("test-zoxide")
    register(inst)
    return {t.name: t for t in inst._tool_manager.list_tools()}


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


class TestZoxideMissingBinary:
    """Bug #12: zoxide_remove and zoxide_query must error when binary is missing."""

    def test_zoxide_remove_error_json_when_binary_missing(self, zoxide_tools: dict) -> None:
        """zoxide_remove returns JSON error dict (not success) when FileNotFoundError raised."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = zoxide_tools["zoxide_remove"].fn(path="/some/path")
        data = json.loads(result)
        assert "error" in data
        assert "zoxide" in data["error"].lower()

    def test_zoxide_query_error_json_when_binary_missing(self, zoxide_tools: dict) -> None:
        """zoxide_query returns JSON error dict (not empty results) when binary missing."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = zoxide_tools["zoxide_query"].fn(keyword="foo")
        data = json.loads(result)
        assert "error" in data
        assert "zoxide" in data["error"].lower()

    def test_zoxide_boost_reports_failure_when_binary_missing(self, zoxide_tools: dict) -> None:
        """zoxide_boost already handles FileNotFoundError; verify 0 successes + useful message."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = zoxide_tools["zoxide_boost"].fn(path="/some/path", times=3)
        data = json.loads(result)
        assert data["successes"] == 0
        assert "zoxide not found" in data["result"]
