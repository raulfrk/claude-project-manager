"""Jira label tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get all labels in the Jira instance.")
    def jira_get_labels(max_results: int = 1000) -> str:
        client = get_client()
        try:
            data = client.get(
                "/rest/api/2/label",
                params={"maxResults": max_results},
            )
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
