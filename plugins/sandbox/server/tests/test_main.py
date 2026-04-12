"""Tests for sandbox main.py entrypoint."""

from __future__ import annotations

from unittest.mock import patch

from mcp.server.fastmcp import FastMCP


class TestMain:
    def test_mcp_instance_is_fastmcp_named_sandbox(self) -> None:
        from server.main import mcp

        assert isinstance(mcp, FastMCP)
        assert mcp.name == "sandbox"

    def test_main_calls_run_dual_with_correct_args(self) -> None:
        from server.main import main, mcp

        with patch("server.main.run_dual") as mock_run_dual:
            main()
            mock_run_dual.assert_called_once_with(mcp, "sandbox", default_port=19101)

    def test_port_19101_matches_sandbox_assignment(self) -> None:
        """Regression guard: sandbox port must be 19101 per CLAUDE.md port table."""
        from server.main import main

        with patch("server.main.run_dual") as mock_run_dual:
            main()
            _, kwargs = mock_run_dual.call_args
            # Also accept positional: run_dual(mcp, "sandbox", default_port=19101)
            if "default_port" in kwargs:
                assert kwargs["default_port"] == 19101
            else:
                assert mock_run_dual.call_args[0][2] == 19101

    def test_settings_tools_registered_on_mcp(self) -> None:
        from server.main import mcp

        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        # Verify at least some expected sandbox tools are registered
        assert "sandbox_list" in tool_names
        assert "sandbox_check" in tool_names
        assert "sandbox_add_write_path" in tool_names
