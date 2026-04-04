"""Hook-friendly Trello wrapper tools for automated hook dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _load_proj_config() -> dict:
    """Load ~/.claude/proj.yaml to read Trello sync config."""
    path = Path("~/.claude/proj.yaml").expanduser()
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _get_trello_sync_config() -> dict:
    """Extract sync.trello section from proj.yaml."""
    cfg = _load_proj_config()
    return cfg.get("sync", {}).get("trello", {})


def register(app: FastMCP) -> None:
    @app.tool(
        description=(
            "Hook-friendly card+checklist creation for project init. "
            "Creates a Trello card on the configured list and adds a "
            "'Tasks' checklist. Reads board_id and list from proj.yaml "
            "sync.trello config. "
            "Returns {card_id, checklist_id} for feedback writeback."
        ),
    )
    def trello_add_card_hook(name: str) -> str:
        trello_cfg = _get_trello_sync_config()
        board_id = trello_cfg.get("default_board_id", "")
        default_list = trello_cfg.get("default_list", "Active")

        if not board_id:
            return json.dumps({
                "error": (
                    "No default_board_id configured in sync.trello. "
                    "Run /proj:trello-setup first."
                ),
            })

        client = get_client()

        # Resolve list_id from list name
        try:
            board_lists = client.get(f"/boards/{board_id}/lists")
        except Exception as exc:
            return json.dumps({
                "error": f"Failed to fetch board lists: {exc}",
            })

        list_id = ""
        for lst in board_lists:
            if lst.get("name") == default_list or lst.get("id") == default_list:
                list_id = lst["id"]
                break

        if not list_id:
            return json.dumps({
                "error": f"List '{default_list}' not found on board {board_id}.",
            })

        # Create card
        try:
            card = client.post(
                "/cards", params={"idList": list_id, "name": name},
            )
        except Exception as exc:
            return json.dumps({
                "error": f"Failed to create card: {exc}",
            })

        card_id = card.get("id", "")

        # Create "Tasks" checklist on the card
        try:
            checklist = client.post(
                "/checklists",
                params={"idCard": card_id, "name": "Tasks"},
            )
        except Exception as exc:
            # Card was created but checklist failed — return card_id anyway
            return json.dumps({
                "card_id": card_id,
                "checklist_id": "",
                "warning": f"Card created but checklist failed: {exc}",
            })

        checklist_id = checklist.get("id", "")

        return json.dumps({
            "card_id": card_id,
            "checklist_id": checklist_id,
        })

    @app.tool(
        description=(
            "Hook-friendly batch checklist item creation for batch child todo sync. "
            "Creates multiple checklist items on the given checklist. "
            "Creates the checklist first if checklist_id is null and card_id is provided. "
            "Items is a list of item name strings."
        ),
    )
    def trello_batch_add_checklist_items_hook(
        checklist_id: str | None,
        items: list[str],
        card_id: str | None = None,
        checklist_name: str | None = None,
    ) -> str:
        if not checklist_id:
            if not card_id:
                return json.dumps({"error": "card_id is required to create checklist"})
            client = get_client()
            try:
                new_checklist = client.post(
                    "/checklists",
                    params={"idCard": card_id, "name": checklist_name or "Tasks"},
                )
                checklist_id = new_checklist["id"]
            except Exception as exc:
                return json.dumps({
                    "error": f"checklist creation failed: {exc}",
                    "checklist_id": None,
                })
        client = get_client()
        successes: list[dict] = []
        failures: list[dict] = []
        for idx, name in enumerate(items):
            try:
                created = client.post(
                    f"/checklists/{checklist_id}/checkItems",
                    params={"name": name},
                )
                successes.append(created)
            except Exception as exc:
                failures.append({"index": idx, "name": name, "error": str(exc)})
        return json.dumps({
            "checklist_id": checklist_id,
            "successes": successes,
            "failures": failures,
        })

    @app.tool(
        description=(
            "Hook-friendly single checklist item creation. "
            "Creates the checklist first if checklist_id is null and card_id is provided. "
            "Returns {id, checklist_id} for feedback writeback."
        ),
    )
    def trello_add_checklist_item_hook(
        checklist_id: str | None,
        item_name: str,
        card_id: str | None = None,
        checklist_name: str | None = None,
    ) -> str:
        if not checklist_id:
            if not card_id:
                return json.dumps({"error": "card_id is required to create checklist"})
            client = get_client()
            try:
                new_checklist = client.post(
                    "/checklists",
                    params={"idCard": card_id, "name": checklist_name or "Tasks"},
                )
                checklist_id = new_checklist["id"]
            except Exception as exc:
                return json.dumps({
                    "error": f"checklist creation failed: {exc}",
                    "checklist_id": None,
                })
        client = get_client()
        created = client.post(
            f"/checklists/{checklist_id}/checkItems",
            params={"name": item_name},
        )
        return json.dumps({"id": created["id"], "checklist_id": checklist_id})

