"""Zoxide tool implementations."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register zoxide tools with the MCP server."""

    @mcp.tool()
    def zoxide_boost(path: str, times: int = 10) -> str:
        """Boost a path in zoxide's frecency database by calling 'zoxide add' multiple times."""
        try:
            for _ in range(times):
                subprocess.run(
                    ["zoxide", "add", path],
                    check=False,
                    capture_output=True,
                )
        except FileNotFoundError:
            return "zoxide not found, skipping"
        return f"Boosted {path} (x{times})"

    @mcp.tool()
    def zoxide_remove(path: str) -> str:
        """Remove a path from zoxide's frecency database."""
        try:
            subprocess.run(
                ["zoxide", "remove", path],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            return "zoxide not found, skipping"
        return f"Removed {path} from zoxide"

    @mcp.tool()
    def zoxide_query(keyword: str, max_results: int = 5) -> str:
        """Query zoxide's frecency database for paths matching a keyword."""
        try:
            result = subprocess.run(
                ["zoxide", "query", keyword],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return "zoxide not found, skipping"
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "No matches found"
        return "\n".join(lines[:max_results])
