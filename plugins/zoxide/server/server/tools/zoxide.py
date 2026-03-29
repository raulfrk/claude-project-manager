"""Zoxide tool implementations."""

from __future__ import annotations

import json
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
            return json.dumps({"result": "zoxide not found, skipping"})
        return json.dumps({"result": f"Boosted {path} (x{times})", "path": path, "times": times})

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
            return json.dumps({"result": "zoxide not found, skipping"})
        return json.dumps({"result": f"Removed {path} from zoxide", "path": path})

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
            return json.dumps({"result": [], "paths": [], "count": 0})
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return json.dumps({"result": [], "paths": [], "count": 0})
        results_list = lines[:max_results]
        return json.dumps({"result": results_list, "paths": results_list, "count": len(results_list)})
