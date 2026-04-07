"""Trello members tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="Get all members of a board.")
    def get_board_members(board_id: str) -> str:
        client = get_client()
        members = client.get(f"/boards/{board_id}/members")
        return json.dumps(members)

    @app.tool(description="Add a member to a card.")
    def add_card_member(card_id: str, member_id: str) -> str:
        client = get_client()
        result = client.post(f"/cards/{card_id}/idMembers", params={"value": member_id})
        return json.dumps(result)

    @app.tool(description="Remove a member from a card.")
    def remove_card_member(card_id: str, member_id: str) -> str:
        client = get_client()
        client.delete(f"/cards/{card_id}/idMembers/{member_id}")
        return json.dumps({"deleted": True, "card_id": card_id, "member_id": member_id})
