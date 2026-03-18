"""Jira project read tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="List Jira projects visible to the configured user, filtered by whitelist.")
    def jira_list_projects() -> str:
        client = get_client()
        cfg = client._config
        all_projects = client.get("/rest/api/2/project")
        if cfg.allowed_project_keys:
            allowed = set(cfg.allowed_project_keys)
            all_projects = [p for p in all_projects if p.get("key") in allowed]
        else:
            return json.dumps({
                "error": "No projects in whitelist. Run jira_init to configure allowed project keys.",
            })
        return json.dumps(all_projects)

    @app.tool(description="Get details for a single Jira project by key.")
    def jira_get_project(project_key: str) -> str:
        client = get_client()
        client.check_project_access(project_key)
        data = client.get(f"/rest/api/2/project/{project_key}")
        return json.dumps(data)
