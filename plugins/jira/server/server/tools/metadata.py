"""Jira metadata tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="List all issue types available in the Jira instance.")
    def jira_get_issue_types() -> str:
        client = get_client()
        data = client.get("/rest/api/2/issuetype")
        return json.dumps(data)

    @app.tool(description="List all fields (system and custom) in the Jira instance.")
    def jira_get_fields() -> str:
        client = get_client()
        data = client.get("/rest/api/2/field")
        return json.dumps(data)

    @app.tool(description="List all priorities configured in the Jira instance.")
    def jira_get_priorities() -> str:
        client = get_client()
        data = client.get("/rest/api/2/priority")
        return json.dumps(data)

    @app.tool(description="List all statuses configured in the Jira instance.")
    def jira_get_statuses() -> str:
        client = get_client()
        data = client.get("/rest/api/2/status")
        return json.dumps(data)
