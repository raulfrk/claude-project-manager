"""MCP tool for re-running hook auto-discovery on demand."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.discovery import run_discovery

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def hooks_sync() -> str:
    """Re-run hook auto-discovery and return a summary of changes."""
    summary = run_discovery()
    return json.dumps({"result": summary})


def register(app: FastMCP) -> None:
    """Register the hooks_sync tool with the MCP application."""

    @app.tool(
        description=(
            "Re-run hook auto-discovery: scans sibling plugins for default-hooks.yaml, "
            "registers new hooks, updates drifted auto hooks, and populates server URLs. "
            "Returns a summary of changes."
        )
    )
    def router_sync_tool() -> str:
        return hooks_sync()
