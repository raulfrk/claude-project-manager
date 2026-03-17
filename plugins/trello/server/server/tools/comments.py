"""Trello comments tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Get all comments on a card.")
    def get_card_comments(card_id: str) -> str:
        client = get_client()
        comments = client.get(f"/cards/{card_id}/actions", params={"filter": "commentCard"})
        return json.dumps(comments)

    @app.tool(description="Add a comment to a card.")
    def add_comment(card_id: str, text: str) -> str:
        client = get_client()
        comment = client.post(f"/cards/{card_id}/actions/comments", params={"text": text})
        return json.dumps(comment)

    @app.tool(description="Update an existing comment.")
    def update_comment(action_id: str, text: str) -> str:
        client = get_client()
        comment = client.put(f"/actions/{action_id}", params={"text": text})
        return json.dumps(comment)

    @app.tool(description="Delete a comment.")
    def delete_comment(action_id: str) -> str:
        client = get_client()
        client.delete(f"/actions/{action_id}")
        return json.dumps({"deleted": True, "action_id": action_id})
