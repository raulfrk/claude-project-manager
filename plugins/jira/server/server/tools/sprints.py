"""Jira sprint tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import JsonValue, get_client


def register(app: FastMCP) -> None:
    @app.tool(description="List sprints for a Jira board. Optionally filter by state (active, closed, future).")
    def jira_get_sprints(board_id: str, state: str = "") -> str:
        client = get_client()
        params: dict[str, str] | None = {"state": state} if state else None
        data = client.get(f"/rest/agile/1.0/board/{board_id}/sprint", params=params)
        return json.dumps(data)

    @app.tool(description="Move issues to a sprint.")
    def jira_move_to_sprint(sprint_id: str, issue_keys: list[str]) -> str:
        client = get_client()
        issues: list[JsonValue] = list(issue_keys)
        body: dict[str, JsonValue] = {"issues": issues}
        client.post(
            f"/rest/agile/1.0/sprint/{sprint_id}/issue",
            json_body=body,
        )
        return json.dumps({"ok": True, "sprint_id": sprint_id, "issues": issue_keys})
