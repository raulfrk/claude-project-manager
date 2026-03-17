"""Trello checklists tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Get all checklists on a card.")
    def get_card_checklists(card_id: str) -> str:
        client = get_client()
        checklists = client.get(f"/cards/{card_id}/checklists")
        return json.dumps(checklists)

    @app.tool(description="Create a new checklist on a card.")
    def create_checklist(card_id: str, name: str) -> str:
        client = get_client()
        checklist = client.post("/checklists", params={"idCard": card_id, "name": name})
        return json.dumps(checklist)

    @app.tool(description="Add an item to a checklist.")
    def add_checklist_item(checklist_id: str, name: str) -> str:
        client = get_client()
        item = client.post(f"/checklists/{checklist_id}/checkItems", params={"name": name})
        return json.dumps(item)

    @app.tool(description="Update a checklist item's state (complete or incomplete).")
    def update_checklist_item(card_id: str, checklist_id: str, item_id: str, state: str) -> str:
        client = get_client()
        item = client.put(
            f"/cards/{card_id}/checklist/{checklist_id}/checkItem/{item_id}",
            params={"state": state},
        )
        return json.dumps(item)

    @app.tool(description="Delete a checklist.")
    def delete_checklist(checklist_id: str) -> str:
        client = get_client()
        client.delete(f"/checklists/{checklist_id}")
        return json.dumps({"deleted": True, "checklist_id": checklist_id})
