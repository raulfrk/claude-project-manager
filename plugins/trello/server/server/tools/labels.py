"""Trello labels tools."""
from __future__ import annotations
import json
from mcp.server.fastmcp import FastMCP
from server.lib.client import get_client

def register(app: FastMCP) -> None:
    @app.tool(description="Get all labels for a board.")
    def get_labels(board_id: str) -> str:
        client = get_client()
        labels = client.get(f"/boards/{board_id}/labels")
        return json.dumps(labels)

    @app.tool(description="Create a new label on a board.")
    def create_label(board_id: str, name: str, color: str) -> str:
        client = get_client()
        params = {"name": name, "color": color, "idBoard": board_id}
        label = client.post("/labels", params=params)
        return json.dumps(label)

    @app.tool(description="Update a label's name or color.")
    def update_label(label_id: str, name: str | None = None, color: str | None = None) -> str:
        client = get_client()
        params: dict[str, str] = {}
        if name is not None:
            params["name"] = name
        if color is not None:
            params["color"] = color
        label = client.put(f"/labels/{label_id}", params=params)
        return json.dumps(label)

    @app.tool(description="Delete a label permanently.")
    def delete_label(label_id: str) -> str:
        client = get_client()
        client.delete(f"/labels/{label_id}")
        return json.dumps({"deleted": True, "label_id": label_id})

    @app.tool(description="Add or remove a label on a card.")
    def toggle_card_label(card_id: str, label_id: str, action: str) -> str:
        client = get_client()
        if action == "add":
            result = client.post(f"/cards/{card_id}/idLabels", params={"value": label_id})
            return json.dumps(result)
        elif action == "remove":
            client.delete(f"/cards/{card_id}/idLabels/{label_id}")
            return json.dumps({"removed": True, "card_id": card_id, "label_id": label_id})
        else:
            return json.dumps({"error": f"Invalid action '{action}'. Use 'add' or 'remove'."})
