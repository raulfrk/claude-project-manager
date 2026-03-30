"""
proj_trello_full_sync -- full-cycle Trello sync executed within the MCP layer.

Reduces model-side orchestration from ~10 tool calls to 3 by handling:
fetch -> diff -> execute push ops -> apply pull ops -> return summary.
"""

from __future__ import annotations

import json
import logging
import time
import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from server.lib import storage
from server.tools.config import require_project
from server.tools.trello_sync import (
    TrelloApplyInput,
    TrelloSyncPlan,
    apply_changes,
    compute_diff,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# -- Inter-plugin call helpers ------------------------------------------------


def _resolve_trello_socket() -> str:
    """Read Trello plugin socket path from registry, fall back to legacy."""
    registry_file = Path.home() / ".claude" / "sockets" / "trello"
    try:
        path = registry_file.read_text().strip()
        if path:
            return path
    except (FileNotFoundError, OSError):
        pass
    return "/tmp/claude-hooks-trello.sock"


def _call_trello_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Call a Trello MCP tool via inter-plugin Unix domain socket."""
    sock_path = _resolve_trello_socket()
    transport = httpx.HTTPTransport(uds=sock_path)
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            "http://localhost/call",
            json={"tool": tool_name, "params": params},
        )
        resp.raise_for_status()
        return resp.json()


# -- Push operation builder ---------------------------------------------------


def _build_push_ops(plan: TrelloSyncPlan, card_id: str) -> list[dict[str, Any]]:
    """Convert a TrelloSyncPlan into a flat list of push operations.

    Each op is a dict with keys: type, tool, params, and optionally
    checklist_key (for cascading skip on checklist create failure).
    """
    ops: list[dict[str, Any]] = []

    for entry in plan.push_create_checklist:
        ops.append({
            "type": "push_create_checklist",
            "tool": "create_checklist",
            "params": {"cardId": card_id, "name": entry["name"]},
            "todo_id": entry.get("todo_id"),
            "checklist_key": entry.get("todo_id"),
        })

    for entry in plan.push_create_item:
        ops.append({
            "type": "push_create_item",
            "tool": "add_checklist_item",
            "params": {
                "checklistId": entry.get("checklist_id", ""),
                "name": entry["name"],
            },
            "todo_id": entry.get("todo_id"),
            "parent_checklist_todo_id": entry.get("parent_checklist_todo_id"),
        })

    for entry in plan.push_update_item:
        params: dict[str, Any] = {
            "cardId": card_id,
            "checklistId": entry.get("checklist_id", ""),
            "checkItemId": entry.get("trello_checklist_item_id", ""),
        }
        if "name" in entry:
            params["name"] = entry["name"]
        ops.append({
            "type": "push_update_item",
            "tool": "update_checklist_item",
            "params": params,
            "todo_id": entry.get("todo_id"),
        })

    for entry in plan.push_complete_item:
        ops.append({
            "type": "push_complete_item",
            "tool": "update_checklist_item",
            "params": {
                "cardId": card_id,
                "checklistId": entry.get("checklist_id", ""),
                "checkItemId": entry.get("trello_checklist_item_id", ""),
                "state": "complete",
            },
            "todo_id": entry.get("todo_id"),
        })

    for entry in plan.push_delete_item:
        ops.append({
            "type": "push_delete_item",
            "tool": "delete_checklist_item",
            "params": {
                "checklistId": entry.get("checklist_id", ""),
                "checkItemId": entry.get("trello_checklist_item_id", ""),
            },
            "todo_id": entry.get("todo_id"),
        })

    for entry in plan.push_rename_checklist:
        ops.append({
            "type": "push_rename_checklist",
            "tool": "rename_checklist",
            "params": {
                "checklistId": entry.get("trello_checklist_id", ""),
                "name": entry["name"],
            },
            "todo_id": entry.get("todo_id"),
        })

    return ops


# -- Core execution -----------------------------------------------------------


def _execute_push_ops(
    ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute push operations, accumulating errors.

    Returns (succeeded_ops, errors). Handles cascading skip: if a checklist
    create fails, all items targeting that checklist are skipped.
    """
    errors: list[dict[str, Any]] = []
    succeeded: list[dict[str, Any]] = []
    skipped_checklists: set[str] = set()

    for op in ops:
        # Cascading skip: if parent checklist creation failed, skip its items
        parent_cl = op.get("parent_checklist_todo_id")
        if parent_cl and parent_cl in skipped_checklists:
            errors.append({
                "operation_type": op["type"],
                "error": f"Skipped: parent checklist {parent_cl} failed to create",
                "retryable": True,
                "retry_payload": op,
            })
            continue

        try:
            result = _call_trello_tool(op["tool"], op["params"])
            op["result"] = result
            succeeded.append(op)
        except Exception as e:
            errors.append({
                "operation_type": op["type"],
                "error": str(e),
                "retryable": True,
                "retry_payload": op,
            })
            if op["type"] == "push_create_checklist" and op.get("checklist_key"):
                skipped_checklists.add(op["checklist_key"])

    return succeeded, errors


def _retry_failed_ops(
    failed_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-attempt only previously failed operations.

    Returns (succeeded, still_failed).
    """
    succeeded: list[dict[str, Any]] = []
    still_failed: list[dict[str, Any]] = []

    for entry in failed_ops:
        payload = entry.get("retry_payload", {})
        tool = payload.get("tool")
        params = payload.get("params")
        if not tool or not params:
            still_failed.append(entry)
            continue
        try:
            result = _call_trello_tool(tool, params)
            payload["result"] = result
            succeeded.append(payload)
        except Exception as e:
            still_failed.append({
                "operation_type": entry.get("operation_type", payload.get("type", "unknown")),
                "error": str(e),
                "retryable": False,
                "retry_payload": payload,
            })

    return succeeded, still_failed


def _build_summary(
    plan: TrelloSyncPlan,
    pull_counts: dict[str, int],
    succeeded_push: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a human-readable summary of what was synced."""
    push_by_type: dict[str, int] = {}
    for op in succeeded_push:
        t = op.get("type", "unknown")
        push_by_type[t] = push_by_type.get(t, 0) + 1

    return {
        "pull": pull_counts,
        "push": {
            "checklists_created": push_by_type.get("push_create_checklist", 0),
            "items_created": push_by_type.get("push_create_item", 0),
            "items_updated": push_by_type.get("push_update_item", 0),
            "items_completed": push_by_type.get("push_complete_item", 0),
            "items_deleted": push_by_type.get("push_delete_item", 0),
            "checklists_renamed": push_by_type.get("push_rename_checklist", 0),
        },
    }


# -- MCP tool registration ---------------------------------------------------


def register(app: FastMCP) -> None:
    """Register proj_trello_full_sync tool."""

    @app.tool(
        description=(
            "Execute a full Trello sync cycle for the active project: "
            "fetch card state -> diff -> execute push ops -> apply pull ops -> return summary. "
            "Reduces the sync flow from ~10 tool calls to 1. "
            "On success: {\"status\": \"success\", \"summary\": {...}}. "
            "On partial failure: {\"status\": \"partial_success\", \"errors\": [...], \"retry_token\": \"...\"}. "
            "If pull_delete candidates exist: {\"status\": \"needs_confirmation\", \"pull_delete_pending\": [...]}. "
            "Pass retry_failures (base64-encoded JSON) to re-attempt only previously failed ops."
        )
    )
    def proj_trello_full_sync(
        project_name: str | None = None,
        retry_failures: str | None = None,
    ) -> str:
        # -- Retry mode: re-attempt only failed ops --
        if retry_failures:
            try:
                failed_ops = json.loads(base64.b64decode(retry_failures))
            except (json.JSONDecodeError, Exception) as e:
                return json.dumps({"status": "error", "error": f"Invalid retry_failures: {e}"})

            succeeded, still_failed = _retry_failed_ops(failed_ops)
            if still_failed:
                token = base64.b64encode(json.dumps(still_failed).encode()).decode()
                return json.dumps({
                    "status": "partial_success",
                    "retried_succeeded": len(succeeded),
                    "errors": still_failed,
                    "retry_token": token,
                })
            return json.dumps({
                "status": "success",
                "retried_succeeded": len(succeeded),
                "summary": {"retry": True, "succeeded": len(succeeded)},
            })

        # -- Normal mode: full sync cycle --

        # 1. Load config + resolve project
        result = require_project(project_name)
        if isinstance(result, str):
            return json.dumps({"status": "error", "error": result})
        cfg, name = result

        # 2. Load project meta
        meta = storage.load_meta(cfg, name)
        card_id = meta.trello_card_id
        board_id = meta.trello.board_id or cfg.trello.default_board_id

        if not board_id:
            return json.dumps({
                "status": "error",
                "error": "No Trello board_id configured (per-project or global default).",
            })

        # 3. Fetch card state (or create card if needed)
        if card_id:
            try:
                card_data = _call_trello_tool("get_card_checklists", {"cardId": card_id})
                trello_card_json = json.dumps({"checklists": card_data if isinstance(card_data, list) else card_data.get("checklists", [])})
            except Exception as e:
                return json.dumps({
                    "status": "error",
                    "error": f"Failed to fetch card checklists: {e}",
                })
        else:
            trello_card_json = json.dumps({"checklists": []})

        # 4. Compute diff
        plan = compute_diff(trello_card_json, cfg, name)

        # 5. If card needs creating, do it first
        if plan.card_create and not card_id:
            try:
                # Resolve target list
                lists_data = _call_trello_tool("get_lists", {"boardId": board_id})
                default_list = cfg.trello.default_list or "Active"
                target_list_id = None
                if isinstance(lists_data, list):
                    for lst in lists_data:
                        if lst.get("name", "").lower() == default_list.lower():
                            target_list_id = lst["id"]
                            break
                    if not target_list_id and lists_data:
                        target_list_id = lists_data[0]["id"]

                if not target_list_id:
                    return json.dumps({
                        "status": "error",
                        "error": "No lists found on the Trello board.",
                    })

                card_result = _call_trello_tool("add_card_to_list", {
                    "listId": target_list_id,
                    "name": name,
                })
                new_card_id = card_result.get("id", "") if isinstance(card_result, dict) else ""
                if new_card_id:
                    # Link the card locally
                    link_data = TrelloApplyInput(link_trello_card_id=new_card_id)
                    apply_changes(link_data, cfg, name)
                    card_id = new_card_id
                    # Re-fetch meta and recompute diff with empty card
                    trello_card_json = json.dumps({"checklists": []})
                    plan = compute_diff(trello_card_json, cfg, name)
            except Exception as e:
                return json.dumps({
                    "status": "error",
                    "error": f"Failed to create Trello card: {e}",
                })

        # 6. Check for pull_delete candidates requiring user confirmation
        if plan.pull_delete:
            return json.dumps({
                "status": "needs_confirmation",
                "requires_confirmation": True,
                "pull_delete_pending": plan.pull_delete,
            })

        # 7. Empty diff -> up to date
        if plan.is_empty():
            return json.dumps({
                "status": "success",
                "summary": {
                    "pull": {"created": 0, "created_root": 0, "updated": 0, "completed": 0, "reopened": 0, "linked": 0},
                    "push": {"checklists_created": 0, "items_created": 0, "items_updated": 0, "items_completed": 0, "items_deleted": 0, "checklists_renamed": 0},
                    "up_to_date": True,
                },
            })

        # 8. Apply pull operations locally
        has_pulls = bool(
            plan.pull_create or plan.pull_update or plan.pull_complete
            or plan.pull_reopen or plan.pull_create_root
        )
        if has_pulls:
            pull_data = TrelloApplyInput(
                created_locally=plan.pull_create,  # type: ignore[arg-type]
                created_root_locally=plan.pull_create_root,  # type: ignore[arg-type]
                updated_locally=plan.pull_update,  # type: ignore[arg-type]
                completed_locally=plan.pull_complete,
                reopened_locally=plan.pull_reopen,
            )
            pull_counts = apply_changes(pull_data, cfg, name)
        else:
            pull_counts = {
                "created": 0, "created_root": 0, "updated": 0,
                "completed": 0, "reopened": 0, "linked": 0,
            }

        # 9. Execute push operations
        if card_id:
            ops = _build_push_ops(plan, card_id)
            succeeded, errors = _execute_push_ops(ops)
        else:
            succeeded, errors = [], []

        # 10. Build response
        summary = _build_summary(plan, pull_counts, succeeded)

        if errors:
            token = base64.b64encode(json.dumps(errors).encode()).decode()
            return json.dumps({
                "status": "partial_success",
                "summary": summary,
                "errors": errors,
                "retry_token": token,
            })

        return json.dumps({
            "status": "success",
            "summary": summary,
        })
