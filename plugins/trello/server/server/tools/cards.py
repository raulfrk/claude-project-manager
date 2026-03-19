"""Trello cards tools."""
from __future__ import annotations
import json
from mcp.server.fastmcp import FastMCP
from server.lib.client import get_client

def register(app: FastMCP) -> None:
    @app.tool(description="Get all cards on a list.")
    def get_cards_by_list_id(list_id: str) -> str:
        client = get_client()
        cards = client.get(f"/lists/{list_id}/cards")
        return json.dumps(cards)

    @app.tool(description="Get a single card by ID.")
    def get_card(card_id: str) -> str:
        client = get_client()
        card = client.get(f"/cards/{card_id}")
        return json.dumps(card)

    @app.tool(description="Add a new card to a list.")
    def add_card_to_list(list_id: str, name: str, desc: str = "", due: str | None = None) -> str:
        client = get_client()
        params: dict[str, str] = {"idList": list_id, "name": name}
        if desc:
            params["desc"] = desc
        if due is not None:
            params["due"] = due
        card = client.post("/cards", params=params)
        return json.dumps(card)

    @app.tool(description="Update a card's name, description, due date, or closed status.")
    def update_card_details(
        card_id: str,
        name: str | None = None,
        desc: str | None = None,
        due: str | None = None,
        closed: bool | None = None,
    ) -> str:
        client = get_client()
        params: dict[str, str | bool] = {}
        if name is not None:
            params["name"] = name
        if desc is not None:
            params["desc"] = desc
        if due is not None:
            params["due"] = due
        if closed is not None:
            params["closed"] = closed
        card = client.put(f"/cards/{card_id}", params=params)
        return json.dumps(card)

    @app.tool(description="Move a card to a different list.")
    def move_card(card_id: str, list_id: str) -> str:
        client = get_client()
        card = client.put(f"/cards/{card_id}", params={"idList": list_id})
        return json.dumps(card)

    @app.tool(description="Archive a card.")
    def archive_card(card_id: str) -> str:
        client = get_client()
        card = client.put(f"/cards/{card_id}", params={"closed": True})
        return json.dumps(card)

    @app.tool(description="Delete a card permanently.")
    def delete_card(card_id: str) -> str:
        client = get_client()
        client.delete(f"/cards/{card_id}")
        return json.dumps({"deleted": True, "card_id": card_id})

    @app.tool(
        description=(
            "Create multiple cards in one call. "
            "Each card dict has 'list_id' and 'name' (required), "
            "plus optional 'desc' and 'due'. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def batch_create_cards(cards: list[dict[str, str]]) -> str:
        client = get_client()
        successes: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        for idx, card in enumerate(cards):
            try:
                list_id = card.get("list_id", "")
                name = card.get("name", "")
                if not list_id or not name:
                    failures.append({
                        "index": idx,
                        "error": "Missing 'list_id' or 'name'",
                    })
                    continue
                params: dict[str, str] = {"idList": list_id, "name": name}
                desc = card.get("desc", "")
                if desc:
                    params["desc"] = desc
                due = card.get("due")
                if due is not None:
                    params["due"] = due
                created = client.post("/cards", params=params)
                successes.append(created)
            except Exception as exc:  # noqa: BLE001
                failures.append({"index": idx, "name": card.get("name", ""), "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})
