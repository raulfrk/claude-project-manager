"""Hook-friendly Trello wrapper tools for automated hook dispatch."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from server.lib.client import JsonValue, get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _load_proj_config() -> dict[str, JsonValue]:
    """Load ~/.claude/proj.yaml to read Trello sync config."""
    path = Path("~/.claude/proj.yaml").expanduser()
    if not path.exists():
        return {}
    with path.open() as f:
        data: dict[str, JsonValue] = yaml.safe_load(f) or {}
        return data


def _get_trello_sync_config() -> dict[str, JsonValue]:
    """Extract sync.trello section from proj.yaml."""
    cfg = _load_proj_config()
    sync = cfg.get("sync")
    if not isinstance(sync, dict):
        return {}
    trello = sync.get("trello")
    if not isinstance(trello, dict):
        return {}
    return trello


def _resolve_list_id(board_id: str, list_name: str) -> str:
    """Resolve a list name/ID to a list ID on the given board."""
    client = get_client()
    try:
        raw_lists = client.get(f"/boards/{board_id}/lists")
    except Exception:
        return ""
    board_lists = raw_lists if isinstance(raw_lists, list) else []
    for lst in board_lists:
        if not isinstance(lst, dict):
            continue
        if lst.get("name") == list_name or lst.get("id") == list_name:
            return str(lst.get("id", ""))
    return ""


def register(app: FastMCP) -> None:
    @app.tool(
        description=(
            "Hook-friendly card creation for project init. "
            "Creates a Trello card on the configured default list. "
            "Reads board_id and list from proj.yaml sync.trello config. "
            "Returns {card_id} for feedback writeback."
        ),
    )
    def trello_add_card_hook(name: str) -> str:
        trello_cfg = _get_trello_sync_config()
        board_id = str(trello_cfg.get("default_board_id", ""))
        default_list = str(trello_cfg.get("default_list", "Active"))

        if not board_id:
            return json.dumps(
                {
                    "error": (
                        "No default_board_id configured in sync.trello. "
                        "Run /proj:trello-setup first."
                    ),
                }
            )

        client = get_client()

        # Resolve list_id from list name
        list_id = _resolve_list_id(board_id, default_list)
        if not list_id:
            return json.dumps(
                {
                    "error": f"List '{default_list}' not found on board {board_id}.",
                }
            )

        # Create card
        try:
            card = client.post(
                "/cards",
                params={"idList": list_id, "name": name},
            )
        except Exception as exc:
            return json.dumps(
                {
                    "error": f"Failed to create card: {exc}",
                }
            )

        if not isinstance(card, dict):
            return json.dumps({"error": "Unexpected card response format"})
        card_id = str(card.get("id", ""))

        return json.dumps({"card_id": card_id})

    @app.tool(
        description=(
            "Hook-friendly card creation for a new todo. "
            "Creates a Trello card on the configured tasks list. "
            "Reads board_id and list_mappings from proj.yaml sync.trello config. "
            "Returns {card_id} for feedback writeback."
        ),
    )
    def trello_add_todo_card_hook(
        name: str,
        desc: str | None = None,
        due: str | None = None,
    ) -> str:
        trello_cfg = _get_trello_sync_config()
        board_id = str(trello_cfg.get("default_board_id", ""))

        if not board_id:
            return json.dumps(
                {
                    "error": (
                        "No default_board_id configured in sync.trello. "
                        "Run /proj:trello-setup first."
                    ),
                }
            )

        list_mappings = trello_cfg.get("list_mappings")
        tasks_list = "proj-tasks"
        if isinstance(list_mappings, dict):
            tasks_list = str(list_mappings.get("tasks", tasks_list))

        list_id = _resolve_list_id(board_id, tasks_list)
        if not list_id:
            return json.dumps(
                {
                    "error": f"Tasks list '{tasks_list}' not found on board {board_id}.",
                }
            )

        client = get_client()
        params: dict[str, str] = {"idList": list_id, "name": name}
        if desc:
            params["desc"] = desc
        if due:
            params["due"] = due

        try:
            card = client.post("/cards", params=params)
        except Exception as exc:
            return json.dumps({"error": f"Failed to create card: {exc}"})

        if not isinstance(card, dict):
            return json.dumps({"error": "Unexpected card response format"})

        return json.dumps({"card_id": str(card.get("id", ""))})

    @app.tool(
        description=(
            "Hook-friendly child card creation. "
            "Creates a Trello card on the tasks list and attaches a link "
            "to the parent card. Returns {card_id} for feedback writeback."
        ),
    )
    def trello_add_child_card_hook(
        parent_card_id: str | None,
        name: str,
        desc: str | None = None,
        due: str | None = None,
    ) -> str:
        trello_cfg = _get_trello_sync_config()
        board_id = str(trello_cfg.get("default_board_id", ""))

        if not board_id:
            return json.dumps(
                {
                    "error": (
                        "No default_board_id configured in sync.trello. "
                        "Run /proj:trello-setup first."
                    ),
                }
            )

        list_mappings = trello_cfg.get("list_mappings")
        tasks_list = "proj-tasks"
        if isinstance(list_mappings, dict):
            tasks_list = str(list_mappings.get("tasks", tasks_list))

        list_id = _resolve_list_id(board_id, tasks_list)
        if not list_id:
            return json.dumps(
                {
                    "error": f"Tasks list '{tasks_list}' not found on board {board_id}.",
                }
            )

        client = get_client()
        params: dict[str, str] = {"idList": list_id, "name": name}
        if desc:
            params["desc"] = desc
        if due:
            params["due"] = due

        try:
            card = client.post("/cards", params=params)
        except Exception as exc:
            return json.dumps({"error": f"Failed to create child card: {exc}"})

        if not isinstance(card, dict):
            return json.dumps({"error": "Unexpected card response format"})

        card_id = str(card.get("id", ""))
        card_url = str(card.get("shortUrl", card.get("url", "")))

        # Attach link to parent card if available
        if parent_card_id and card_url:
            with contextlib.suppress(Exception):
                client.post(
                    f"/cards/{parent_card_id}/attachments",
                    params={"url": card_url, "name": name},
                )

        return json.dumps({"card_id": card_id})

    @app.tool(
        description=(
            "Hook-friendly batch child card creation. "
            "Creates multiple Trello cards on the tasks list and attaches "
            "links to the parent card. Items is a list of card name strings. "
            "Returns {children: [{card_id}]} for feedback writeback."
        ),
    )
    def trello_batch_add_child_cards_hook(
        parent_card_id: str | None,
        items: list[str],
    ) -> str:
        trello_cfg = _get_trello_sync_config()
        board_id = str(trello_cfg.get("default_board_id", ""))

        if not board_id:
            return json.dumps(
                {
                    "error": (
                        "No default_board_id configured in sync.trello. "
                        "Run /proj:trello-setup first."
                    ),
                }
            )

        list_mappings = trello_cfg.get("list_mappings")
        tasks_list = "proj-tasks"
        if isinstance(list_mappings, dict):
            tasks_list = str(list_mappings.get("tasks", tasks_list))

        list_id = _resolve_list_id(board_id, tasks_list)
        if not list_id:
            return json.dumps(
                {
                    "error": f"Tasks list '{tasks_list}' not found on board {board_id}.",
                }
            )

        client = get_client()
        children: list[dict[str, str]] = []
        failures: list[dict[str, JsonValue]] = []

        for idx, name in enumerate(items):
            try:
                card = client.post(
                    "/cards",
                    params={"idList": list_id, "name": name},
                )
                if not isinstance(card, dict):
                    failures.append({"index": idx, "name": name, "error": "Unexpected response"})
                    continue
                card_id = str(card.get("id", ""))
                card_url = str(card.get("shortUrl", card.get("url", "")))
                children.append({"card_id": card_id})

                # Attach link to parent card
                if parent_card_id and card_url:
                    with contextlib.suppress(Exception):
                        client.post(
                            f"/cards/{parent_card_id}/attachments",
                            params={"url": card_url, "name": name},
                        )
            except Exception as exc:
                failures.append({"index": idx, "name": name, "error": str(exc)})

        return json.dumps(
            {
                "children": children,
                "failures": failures,
            }
        )

    @app.tool(
        description=(
            "Hook-friendly verification that a todo's Trello card "
            "exists and is in the expected done list after completion."
        ),
    )
    def trello_verify_card_hook(card_id: str) -> str:
        if not card_id:
            return json.dumps(
                {
                    "verified": False,
                    "error": "No card_id provided",
                }
            )

        client = get_client()
        try:
            card = client.get(f"/cards/{card_id}")
        except Exception as exc:
            return json.dumps(
                {
                    "verified": False,
                    "error": f"Failed to fetch card: {exc}",
                }
            )

        if not isinstance(card, dict):
            return json.dumps(
                {
                    "verified": False,
                    "error": "Unexpected card response format",
                }
            )

        # Check the card exists and get its list
        trello_cfg = _get_trello_sync_config()
        list_mappings = trello_cfg.get("list_mappings")
        done_list = "Done"
        if isinstance(list_mappings, dict):
            done_list = str(list_mappings.get("done", done_list))

        card_list_id = str(card.get("idList", ""))
        card_closed = bool(card.get("closed", False))

        # Resolve done list ID
        board_id = str(trello_cfg.get("default_board_id", ""))
        done_list_id = _resolve_list_id(board_id, done_list) if board_id else ""

        in_done_list = card_list_id == done_list_id if done_list_id else False

        return json.dumps(
            {
                "verified": True,
                "card_id": card_id,
                "card_name": str(card.get("name", "")),
                "in_done_list": in_done_list,
                "closed": card_closed,
                "current_list_id": card_list_id,
            }
        )
