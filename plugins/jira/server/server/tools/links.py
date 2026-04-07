"""Jira issue link tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Link two Jira issues together with the given link type.")
    def jira_link_issues(inward_key: str, outward_key: str, link_type: str) -> str:
        client = get_client()
        client.post(
            "/rest/api/2/issueLink",
            json_body={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward_key},
                "outwardIssue": {"key": outward_key},
            },
        )
        return json.dumps(
            {
                "ok": True,
                "inward_key": inward_key,
                "outward_key": outward_key,
                "link_type": link_type,
            }
        )

    @app.tool(description="Get all available issue link types.")
    def jira_get_link_types() -> str:
        client = get_client()
        data = client.get("/rest/api/2/issueLinkType")
        return json.dumps(data)
