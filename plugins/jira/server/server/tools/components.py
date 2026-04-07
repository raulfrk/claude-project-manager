"""Jira component tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import JsonValue, get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get components for a Jira project.")
    def jira_get_components(project_key: str) -> str:
        client = get_client()
        data = client.get(f"/rest/api/2/project/{project_key}/components")
        return json.dumps(data)

    @app.tool(description="Create a component in a Jira project.")
    def jira_create_component(project_key: str, name: str, description: str = "") -> str:
        client = get_client()
        body: dict[str, JsonValue] = {"project": project_key, "name": name}
        if description:
            body["description"] = description
        data = client.post("/rest/api/2/component", json_body=body)
        return json.dumps(data)
