"""Jira attachment tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Add an attachment to a Jira issue.")
    def jira_add_attachment(issue_key: str, file_path: str) -> str:
        client = get_client()
        try:
            data = client.post_multipart(
                f"/rest/api/2/issue/{issue_key}/attachments",
                file_path=file_path,
            )
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="List attachments on a Jira issue.")
    def jira_list_attachments(issue_key: str) -> str:
        client = get_client()
        try:
            data = client.get(
                f"/rest/api/2/issue/{issue_key}",
                params={"fields": "attachment"},
            )
            if not isinstance(data, dict):
                return json.dumps([])
            fields = data.get("fields", {})
            if not isinstance(fields, dict):
                return json.dumps([])
            return json.dumps(fields.get("attachment", []))
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Delete a Jira attachment by ID.")
    def jira_delete_attachment(attachment_id: str) -> str:
        client = get_client()
        try:
            client.delete(f"/rest/api/2/attachment/{attachment_id}")
            return json.dumps({"deleted": True, "attachment_id": attachment_id})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
