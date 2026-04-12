"""Jira watcher tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get watchers for a Jira issue.")
    def jira_get_watchers(issue_key: str) -> str:
        client = get_client()
        try:
            data = client.get(f"/rest/api/2/issue/{issue_key}/watchers")
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Add a watcher to a Jira issue.")
    def jira_add_watcher(issue_key: str, username: str) -> str:
        client = get_client()
        try:
            client.post(
                f"/rest/api/2/issue/{issue_key}/watchers",
                json_body=username,
            )
            return json.dumps({"ok": True, "issue_key": issue_key, "username": username})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Remove a watcher from a Jira issue.")
    def jira_remove_watcher(issue_key: str, username: str) -> str:
        client = get_client()
        try:
            client.delete(
                f"/rest/api/2/issue/{issue_key}/watchers",
                params={"username": username},
            )
            return json.dumps({"deleted": True, "issue_key": issue_key, "username": username})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
