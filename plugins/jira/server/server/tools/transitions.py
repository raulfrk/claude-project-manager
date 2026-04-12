"""Jira transition tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get available transitions for a Jira issue.")
    def jira_get_transitions(issue_key: str) -> str:
        client = get_client()
        try:
            data = client.get(f"/rest/api/2/issue/{issue_key}/transitions")
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(
        description=(
            "Transition a Jira issue to a new status. "
            "fields_json is an optional JSON string of fields to set during the transition."
        ),
    )
    def jira_transition_issue(issue_key: str, transition_id: str, fields_json: str = "{}") -> str:
        client = get_client()
        try:
            fields = json.loads(fields_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid fields JSON: {exc}"})

        try:
            client.post(
                f"/rest/api/2/issue/{issue_key}/transitions",
                json_body={"transition": {"id": transition_id}, "fields": fields},
            )
            return json.dumps({"ok": True, "issue_key": issue_key, "transition_id": transition_id})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
