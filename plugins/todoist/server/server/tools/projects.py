"""Todoist project tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.lib.models import JsonObject, JsonValue


def register(app: FastMCP) -> None:
    @app.tool(description="Create a Todoist project.")
    def todoist_add_projects(
        name: str,
        color: str | None = None,
        is_favorite: bool = False,
    ) -> str:
        body: JsonObject = {"name": name, "is_favorite": is_favorite}
        if color is not None:
            body["color"] = color
        client = get_client()
        project = client.post("/projects", json=body)
        return json.dumps(project)

    @app.tool(
        description=(
            "Hook-friendly single project creation. Accepts flat params: "
            "name (required). Calls the Todoist API directly."
        ),
    )
    def todoist_add_project_hook(name: str) -> str:
        client = get_client()
        try:
            result = client.post("/projects", json={"name": name})
            return json.dumps({"successes": [result], "failures": []})
        except Exception as exc:
            return json.dumps({"successes": [], "failures": [{"name": name, "error": str(exc)}]})

    @app.tool(description="Find Todoist projects, optionally filtering by name.")
    def todoist_find_projects(name: str | None = None, limit: int | None = None) -> str:
        client = get_client()
        raw_projects = client.get_paginated("/projects", limit=limit)
        projects: list[JsonValue] = [p for p in raw_projects if isinstance(p, dict)]
        if name is not None:
            lower = name.lower()
            projects = [
                p
                for p in projects
                if isinstance(p, dict) and lower in str(p.get("name", "")).lower()
            ]
        return json.dumps(projects)
