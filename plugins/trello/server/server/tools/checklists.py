"""Trello checklists tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import JsonValue, TrelloAPIError, get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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
        try:
            client.delete(f"/checklists/{checklist_id}")
        except TrelloAPIError as exc:
            if exc.status_code == 404:
                return json.dumps(
                    {
                        "warning": "checklist not found or already deleted",
                        "checklist_id": checklist_id,
                    }
                )
            raise
        return json.dumps({"deleted": True, "checklist_id": checklist_id})

    @app.tool(description="Rename a checklist item.")
    def rename_checklist_item(card_id: str, checklist_id: str, item_id: str, name: str) -> str:
        client = get_client()
        item = client.put(f"/cards/{card_id}/checkItem/{item_id}", params={"name": name})
        return json.dumps(item)

    @app.tool(description="Delete a checklist item.")
    def delete_checklist_item(card_id: str, checklist_id: str, item_id: str) -> str:
        client = get_client()
        client.delete(f"/cards/{card_id}/checkItem/{item_id}")
        return json.dumps({"deleted": True, "card_id": card_id, "item_id": item_id})

    @app.tool(description="Rename a checklist.")
    def rename_checklist(checklist_id: str, name: str) -> str:
        client = get_client()
        checklist = client.put(f"/checklists/{checklist_id}", params={"name": name})
        return json.dumps(checklist)

    @app.tool(
        description=(
            "Add multiple items to a checklist in one call. "
            "Each item dict has 'name' (required) and 'checked' (optional bool, default false). "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def batch_add_checklist_items(checklist_id: str, items: list[dict[str, str | bool]]) -> str:
        client = get_client()
        successes: list[JsonValue] = []
        failures: list[dict[str, JsonValue]] = []
        for idx, item in enumerate(items):
            try:
                name = str(item.get("name", ""))
                if not name:
                    failures.append({"index": idx, "error": "Missing 'name' field"})
                    continue
                params: dict[str, str] = {"name": name}
                if item.get("checked"):
                    params["checked"] = "true"
                created = client.post(f"/checklists/{checklist_id}/checkItems", params=params)
                successes.append(created)
            except Exception as exc:
                failures.append(
                    {"index": idx, "name": str(item.get("name", "")), "error": str(exc)}
                )
        return json.dumps({"successes": successes, "failures": failures})

    @app.tool(
        description=(
            "Verify a checklist item's current state on a card. "
            "Returns the item's verified status, state, and name."
        ),
    )
    def trello_verify_checklist_item(card_id: str, item_id: str) -> str:
        client = get_client()
        raw_checklists = client.get(f"/cards/{card_id}/checklists")
        checklists = raw_checklists if isinstance(raw_checklists, list) else []
        for checklist in checklists:
            if not isinstance(checklist, dict):
                continue
            check_items = checklist.get("checkItems", [])
            if not isinstance(check_items, list):
                continue
            for item in check_items:
                if not isinstance(item, dict):
                    continue
                if item.get("id") == item_id:
                    return json.dumps(
                        {
                            "verified": True,
                            "item_id": item_id,
                            "state": item.get("state", "incomplete"),
                            "name": item.get("name", ""),
                        }
                    )
        return json.dumps(
            {
                "verified": False,
                "item_id": item_id,
                "state": "unknown",
                "name": "",
            }
        )

    @app.tool(
        description=(
            "Update multiple checklist items in one call. "
            "Each update dict has 'checklist_id', 'item_id' (both required), "
            "and optional 'name' and 'state' ('complete' or 'incomplete'). "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def batch_update_checklist_items(card_id: str, updates: list[dict[str, str]]) -> str:
        client = get_client()
        successes: list[JsonValue] = []
        failures: list[dict[str, JsonValue]] = []
        for idx, update in enumerate(updates):
            it_id = ""
            try:
                cl_id = update.get("checklist_id", "")
                it_id = update.get("item_id", "")
                if not cl_id or not it_id:
                    failures.append(
                        {
                            "index": idx,
                            "error": "Missing 'checklist_id' or 'item_id'",
                        }
                    )
                    continue
                params: dict[str, str] = {}
                if "name" in update:
                    params["name"] = update["name"]
                if "state" in update:
                    params["state"] = update["state"]
                if not params:
                    failures.append({"index": idx, "error": "No fields to update"})
                    continue
                result = client.put(
                    f"/cards/{card_id}/checklist/{cl_id}/checkItem/{it_id}",
                    params=params,
                )
                successes.append(result)
            except Exception as exc:
                failures.append({"index": idx, "item_id": it_id, "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})
