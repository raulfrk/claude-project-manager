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
