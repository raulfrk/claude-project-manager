"""Unit tests for zoxide MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools.zoxide import register


@pytest.fixture()
def tools():
    """Register zoxide tools on a FastMCP instance and return callable tool functions."""
    mcp = FastMCP("test-zoxide")
    register(mcp)
    # Extract the registered tool functions by name
    funcs = {}
    for name, tool in mcp._tool_manager._tools.items():
        funcs[name] = tool.fn
    return funcs


@pytest.fixture()
def zoxide_boost(tools):
    return tools["zoxide_boost"]


@pytest.fixture()
def zoxide_remove(tools):
    return tools["zoxide_remove"]


@pytest.fixture()
def zoxide_query(tools):
    return tools["zoxide_query"]


# --- zoxide_boost tests ---


class TestZoxideBoost:
    @patch("server.tools.zoxide.subprocess.run")
    def test_default_times(self, mock_run, zoxide_boost):
        result = zoxide_boost("/some/path")

        assert mock_run.call_count == 10
        for c in mock_run.call_args_list:
            assert c == call(["zoxide", "add", "/some/path"], check=False, capture_output=True)
        assert result == "Boosted /some/path (x10)"

    @patch("server.tools.zoxide.subprocess.run")
    def test_custom_times(self, mock_run, zoxide_boost):
        result = zoxide_boost("/custom/path", times=3)

        assert mock_run.call_count == 3
        for c in mock_run.call_args_list:
            assert c == call(["zoxide", "add", "/custom/path"], check=False, capture_output=True)
        assert result == "Boosted /custom/path (x3)"

    @patch("server.tools.zoxide.subprocess.run")
    def test_zero_times(self, mock_run, zoxide_boost):
        result = zoxide_boost("/some/path", times=0)

        assert mock_run.call_count == 0
        assert result == "Boosted /some/path (x0)"

    @patch("server.tools.zoxide.subprocess.run", side_effect=FileNotFoundError)
    def test_zoxide_not_found(self, mock_run, zoxide_boost):
        result = zoxide_boost("/some/path")

        assert result == "zoxide not found, skipping"
        assert mock_run.call_count == 1  # fails on first call, stops immediately


# --- zoxide_remove tests ---


class TestZoxideRemove:
    @patch("server.tools.zoxide.subprocess.run")
    def test_remove_success(self, mock_run, zoxide_remove):
        result = zoxide_remove("/old/path")

        mock_run.assert_called_once_with(
            ["zoxide", "remove", "/old/path"], check=False, capture_output=True
        )
        assert result == "Removed /old/path from zoxide"

    @patch("server.tools.zoxide.subprocess.run", side_effect=FileNotFoundError)
    def test_zoxide_not_found(self, mock_run, zoxide_remove):
        result = zoxide_remove("/old/path")

        assert result == "zoxide not found, skipping"
        assert mock_run.call_count == 1


# --- zoxide_query tests ---


class TestZoxideQuery:
    @patch("server.tools.zoxide.subprocess.run")
    def test_parses_multiline_output(self, mock_run, zoxide_query):
        mock_run.return_value = MagicMock(
            stdout="/home/user/projects\n/home/user/docs\n/home/user/code\n"
        )

        result = zoxide_query("home")

        mock_run.assert_called_once_with(
            ["zoxide", "query", "home"], capture_output=True, text=True, check=False
        )
        assert result == "/home/user/projects\n/home/user/docs\n/home/user/code"

    @patch("server.tools.zoxide.subprocess.run")
    def test_empty_output(self, mock_run, zoxide_query):
        mock_run.return_value = MagicMock(stdout="")

        result = zoxide_query("nonexistent")

        assert result == "No matches found"

    @patch("server.tools.zoxide.subprocess.run")
    def test_whitespace_only_output(self, mock_run, zoxide_query):
        mock_run.return_value = MagicMock(stdout="  \n  \n  ")

        result = zoxide_query("something")

        assert result == "No matches found"

    @patch("server.tools.zoxide.subprocess.run", side_effect=FileNotFoundError)
    def test_zoxide_not_found(self, mock_run, zoxide_query):
        result = zoxide_query("home")

        assert result == "zoxide not found, skipping"
        assert mock_run.call_count == 1

    @patch("server.tools.zoxide.subprocess.run")
    def test_max_results_limits_output(self, mock_run, zoxide_query):
        mock_run.return_value = MagicMock(
            stdout="/path/1\n/path/2\n/path/3\n/path/4\n/path/5\n/path/6\n/path/7\n"
        )

        result = zoxide_query("path", max_results=3)

        assert result == "/path/1\n/path/2\n/path/3"

    @patch("server.tools.zoxide.subprocess.run")
    def test_default_max_results(self, mock_run, zoxide_query):
        mock_run.return_value = MagicMock(
            stdout="\n".join(f"/path/{i}" for i in range(10)) + "\n"
        )

        result = zoxide_query("path")

        lines = result.split("\n")
        assert len(lines) == 5  # default max_results=5

    @patch("server.tools.zoxide.subprocess.run")
    def test_strips_whitespace_from_lines(self, mock_run, zoxide_query):
        mock_run.return_value = MagicMock(stdout="  /home/user/projects  \n  /home/user/docs  \n")

        result = zoxide_query("home")

        assert result == "/home/user/projects\n/home/user/docs"
