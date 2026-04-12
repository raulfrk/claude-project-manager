"""Jira worklog tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import JsonValue, get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get worklogs for a Jira issue.")
    def jira_get_worklogs(issue_key: str) -> str:
        client = get_client()
        try:
            data = client.get(f"/rest/api/2/issue/{issue_key}/worklog")
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Add a worklog entry to a Jira issue.")
    def jira_add_worklog(issue_key: str, time_spent: str, comment: str = "") -> str:
        client = get_client()
        body: dict[str, JsonValue] = {"timeSpent": time_spent}
        if comment:
            body["comment"] = comment
        try:
            data = client.post(
                f"/rest/api/2/issue/{issue_key}/worklog",
                json_body=body,
            )
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Delete a worklog entry from a Jira issue.")
    def jira_delete_worklog(issue_key: str, worklog_id: str) -> str:
        client = get_client()
        try:
            client.delete(f"/rest/api/2/issue/{issue_key}/worklog/{worklog_id}")
            return json.dumps({"deleted": True, "issue_key": issue_key, "worklog_id": worklog_id})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
