"""Jira label tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Get all labels in the Jira instance.")
    def jira_get_labels(max_results: int = 1000) -> str:
        client = get_client()
        data = client.get(
            "/rest/api/2/label",
            params={"maxResults": max_results},
        )
        return json.dumps(data)
