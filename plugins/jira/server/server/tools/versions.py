"""Jira version tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import JsonValue, get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Get versions for a Jira project.")
    def jira_get_versions(project_key: str) -> str:
        client = get_client()
        data = client.get(f"/rest/api/2/project/{project_key}/versions")
        return json.dumps(data)

    @app.tool(description="Create a version in a Jira project.")
    def jira_create_version(
        project_key: str,
        name: str,
        description: str = "",
        release_date: str = "",
    ) -> str:
        client = get_client()
        body: dict[str, JsonValue] = {"project": project_key, "name": name}
        if description:
            body["description"] = description
        if release_date:
            body["releaseDate"] = release_date
        data = client.post("/rest/api/2/version", json_body=body)
        return json.dumps(data)
