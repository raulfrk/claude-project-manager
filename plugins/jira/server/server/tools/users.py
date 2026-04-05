"""Jira user tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Search for Jira users by username or display name.")
    def jira_search_users(query: str, max_results: int = 50) -> str:
        client = get_client()
        data = client.get(
            "/rest/api/2/user/search",
            params={"username": query, "maxResults": max_results},
        )
        return json.dumps(data)
