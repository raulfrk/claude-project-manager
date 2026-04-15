"""Trello attachments tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get all attachments on a card.")
    def get_card_attachments(card_id: str) -> str:
        client = get_client()
        attachments = client.get(f"/cards/{card_id}/attachments")
        return json.dumps(attachments)

    @app.tool(description="Add an attachment to a card. url is required.")
    def add_attachment(card_id: str, url: str = "", name: str = "") -> str:
        if not url:
            return json.dumps({"error": "url is required"})
        client = get_client()
        params: dict[str, str] = {"url": url}
        if name:
            params["name"] = name
        attachment = client.post(f"/cards/{card_id}/attachments", params=params)
        return json.dumps(attachment)

    @app.tool(description="Delete an attachment from a card.")
    def delete_attachment(card_id: str, attachment_id: str) -> str:
        client = get_client()
        client.delete(f"/cards/{card_id}/attachments/{attachment_id}")
        return json.dumps({"deleted": True, "card_id": card_id, "attachment_id": attachment_id})
