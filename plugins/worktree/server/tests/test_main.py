"""Tests for server.main module setup and entrypoint."""

from __future__ import annotations

from unittest.mock import patch

from mcp.server.fastmcp import FastMCP


class TestModuleSetup:
    """Verify module-level objects are configured correctly."""

    def test_mcp_is_fastmcp_instance(self) -> None:
        from server.main import mcp

        assert isinstance(mcp, FastMCP)

    def test_mcp_named_worktree(self) -> None:
        from server.main import mcp

        assert mcp.name == "worktree"


class TestMain:
    """Verify main() calls run_dual with the correct arguments."""

    def test_main_calls_run_dual_with_correct_args(self) -> None:
        from server.main import main, mcp

        with patch("server.main.run_dual") as mock_run_dual:
            main()
            mock_run_dual.assert_called_once_with(mcp, "worktree", default_port=19103)

    def test_port_matches_documented_assignment(self) -> None:
        """The hardcoded port 19103 must match the canonical port map.

        Canonical source: plugins/router/server/server/lib/discovery.py
        and plugins/router/server/server/tools/fire.py (_DEFAULT_SERVER_PORTS).
        """
        from server.main import main

        with patch("server.main.run_dual") as mock_run_dual:
            main()
            _, kwargs = mock_run_dual.call_args
            # If called positionally, fall back to args
            if "default_port" in kwargs:
                port = kwargs["default_port"]
            else:
                port = mock_run_dual.call_args.args[2]
            assert port == 19103, (
                f"Port {port} does not match canonical assignment 19103 for worktree"
            )
