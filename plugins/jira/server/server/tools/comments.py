"""Jira comment tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Add a comment to a Jira issue.")
    def jira_add_comment(issue_key: str, body: str) -> str:
        client = get_client()
        data = client.post(
            f"/rest/api/2/issue/{issue_key}/comment",
            json_body={"body": body},
        )
        return json.dumps(data)

    @app.tool(description="Update an existing comment on a Jira issue.")
    def jira_update_comment(issue_key: str, comment_id: str, body: str) -> str:
        client = get_client()
        data = client.put(
            f"/rest/api/2/issue/{issue_key}/comment/{comment_id}",
            json_body={"body": body},
        )
        return json.dumps(data)

    @app.tool(description="Delete a comment from a Jira issue.")
    def jira_delete_comment(issue_key: str, comment_id: str) -> str:
        client = get_client()
        client.delete(f"/rest/api/2/issue/{issue_key}/comment/{comment_id}")
        return json.dumps(
            {"deleted": True, "issue_key": issue_key, "comment_id": comment_id}
        )
