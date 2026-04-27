"""
proj_trello_full_sync -- full-cycle Trello sync executed within the MCP layer.

Reduces model-side orchestration from ~10 tool calls to 3 by handling:
fetch -> diff -> execute push ops -> apply pull ops -> return summary.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from server.lib import storage
from server.tools.config import require_config, require_project
from server.tools.trello_migration import _needs_migration, migrate_checklist_to_card
from server.tools.trello_sync import (
    TrelloApplyInput,
    TrelloSyncPlan,
    apply_changes,
    compute_diff,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.lib.models import JsonValue, ProjConfig

logger = logging.getLogger(__name__)


def _is_retryable(exc: Exception) -> bool:
    """Return True if the error is transient and the operation can be retried."""
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


def _classify_error(exc: Exception, context: str) -> str:
    """Return a descriptive error message with classification."""
    if isinstance(exc, httpx.TimeoutException):
        logger.warning("Trello timeout (retryable) during %s: %s", context, exc)
        return f"Timeout (retryable): {exc}"
    if isinstance(exc, httpx.ConnectError):
        logger.warning("Trello connection error (retryable) during %s: %s", context, exc)
        return f"Connection error (retryable): {exc}"
    if isinstance(exc, httpx.HTTPStatusError):
        logger.error(
            "Trello HTTP %s (permanent) during %s: %s", exc.response.status_code, context, exc
        )
        return f"HTTP {exc.response.status_code} (permanent): {exc}"
    logger.error("Trello error (permanent) during %s: %s", context, exc)
    return f"Error (permanent): {exc}"


def _as_dict(v: JsonValue) -> dict[str, JsonValue]:
    """Narrow JsonValue to dict, returning empty dict if not a dict."""
    return v if isinstance(v, dict) else {}


def _as_str(v: JsonValue, default: str = "") -> str:
    """Narrow JsonValue to str."""
    return str(v) if v is not None else default


def _as_list(v: JsonValue) -> list[JsonValue]:
    """Narrow JsonValue to list."""
    return v if isinstance(v, list) else []


# -- Inter-plugin call helpers ------------------------------------------------


def _resolve_trello_socket() -> str:
    """Read Trello plugin socket path from registry, fall back to legacy."""

    registry_file = Path.home() / ".claude" / "sockets" / "trello"
    try:
        path = registry_file.read_text().strip()
        if path and Path(path).exists():
            return path
    except (FileNotFoundError, OSError):
        pass
    from hook_transport.socket_path import socket_dir, socket_glob

    sock_root = socket_dir()
    candidates = sorted(
        sock_root.glob(socket_glob("trello")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return str(candidates[0])
    return str(sock_root / "claude-cpm-trello.sock")


def _call_trello_tool(tool_name: str, params: dict[str, JsonValue]) -> JsonValue:
    """Call a Trello MCP tool via inter-plugin Unix domain socket."""
    sock_path = _resolve_trello_socket()
    transport = httpx.HTTPTransport(uds=sock_path)
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            "http://localhost/hook",
            json={"tool": tool_name, "params": params},
        )
        resp.raise_for_status()
        data = resp.json()
        # Check for error response
        if isinstance(data, dict) and not data.get("ok", True):
            raise RuntimeError(f"Trello tool {tool_name} failed: {data.get('error', 'unknown')}")
        # Unwrap {"ok": True, "result": ...} envelope
        if isinstance(data, dict) and "result" in data:
            result = data["result"]
            # Tools return json.dumps(...) strings — parse them
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    return result
            return result
        return data


# -- Push operation builder ---------------------------------------------------


def _resolve_name_to_id(name: str, items: list[dict[str, JsonValue]]) -> str | None:
    for item in items:
        if item.get("name") == name:
            id_val = item.get("id")
            return str(id_val) if isinstance(id_val, str) else None
    return None


def _build_push_ops(plan: TrelloSyncPlan, card_id: str) -> list[dict[str, JsonValue]]:
    """Convert a TrelloSyncPlan into a flat list of push operations.

    Each op is a dict with keys: type, tool, params, and optionally
    checklist_key (for cascading skip on checklist create failure).
    """
    ops: list[dict[str, JsonValue]] = []

    for entry in plan.push_create_checklist:
        ops.append(
            {
                "type": "push_create_checklist",
                "tool": "create_checklist",
                "params": {"card_id": card_id, "name": entry["name"]},
                "todo_id": entry.get("todo_id"),
                "checklist_key": entry.get("todo_id"),
            }
        )

    for entry in plan.push_create_item:
        ops.append(
            {
                "type": "push_create_item",
                "tool": "add_checklist_item",
                "params": {
                    "checklist_id": entry.get("checklist_id", ""),
                    "name": entry["name"],
                },
                "todo_id": entry.get("todo_id"),
                "parent_checklist_todo_id": entry.get("parent_checklist_todo_id"),
            }
        )

    for entry in plan.push_update_item:
        params: dict[str, JsonValue] = {
            "card_id": card_id,
            "checklist_id": entry.get("checklist_id", ""),
            "item_id": entry.get("trello_checklist_item_id", ""),
        }
        if "name" in entry:
            params["name"] = entry["name"]
        ops.append(
            {
                "type": "push_update_item",
                "tool": "update_checklist_item",
                "params": params,
                "todo_id": entry.get("todo_id"),
            }
        )

    for entry in plan.push_complete_item:
        ops.append(
            {
                "type": "push_complete_item",
                "tool": "update_checklist_item",
                "params": {
                    "card_id": card_id,
                    "checklist_id": entry.get("checklist_id", ""),
                    "item_id": entry.get("trello_checklist_item_id", ""),
                    "state": "complete",
                },
                "todo_id": entry.get("todo_id"),
            }
        )

    for entry in plan.push_delete_item:
        ops.append(
            {
                "type": "push_delete_item",
                "tool": "delete_checklist_item",
                "params": {
                    "checklist_id": entry.get("checklist_id", ""),
                    "item_id": entry.get("trello_checklist_item_id", ""),
                },
                "todo_id": entry.get("todo_id"),
            }
        )

    for entry in plan.push_rename_checklist:
        ops.append(
            {
                "type": "push_rename_checklist",
                "tool": "rename_checklist",
                "params": {
                    "checklist_id": entry.get("trello_checklist_id", ""),
                    "name": entry["name"],
                },
                "todo_id": entry.get("todo_id"),
            }
        )

    for entry in plan.push_reopen_item:
        ops.append(
            {
                "type": "push_reopen_item",
                "tool": "update_checklist_item",
                "params": {
                    "card_id": card_id,
                    "checklist_id": entry.get("checklist_id", ""),
                    "item_id": entry.get("trello_checklist_item_id", ""),
                    "state": "incomplete",
                },
                "todo_id": entry.get("todo_id"),
            }
        )

    return ops


# -- Core execution -----------------------------------------------------------


def _execute_push_ops(
    ops: list[dict[str, JsonValue]],
    card_id: str = "",
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]]]:
    """Execute push operations, accumulating errors.

    Returns (succeeded_ops, errors). Handles cascading skip: if a checklist
    create fails, all items targeting that checklist are skipped.
    """
    errors: list[dict[str, JsonValue]] = []
    succeeded: list[dict[str, JsonValue]] = []
    skipped_checklists: set[str] = set()

    # Pre-fetch existing checklists for dedup on create operations
    existing_checklists: list[dict[str, JsonValue]] | None = None
    if card_id and any(op["type"] in ("push_create_checklist", "push_create_item") for op in ops):
        try:
            data = _call_trello_tool("get_card_checklists", {"card_id": card_id})
            raw_checklists = (
                data
                if isinstance(data, list)
                else data.get("checklists", [])
                if isinstance(data, dict)
                else []
            )
            existing_checklists = [
                x
                for x in (raw_checklists if isinstance(raw_checklists, list) else [])
                if isinstance(x, dict)
            ]
        except Exception as exc:
            logger.error(
                "Failed to pre-fetch checklists for dedup (card=%s): %s",
                card_id,
                exc,
                exc_info=True,
            )
            existing_checklists = None  # If fetch fails, skip dedup and proceed normally

    for op in ops:
        op_params = _as_dict(op.get("params"))
        # Cascading skip: if parent checklist creation failed, skip its items
        parent_cl = op.get("parent_checklist_todo_id")
        if parent_cl and parent_cl in skipped_checklists:
            errors.append(
                {
                    "operation_type": op["type"],
                    "error": f"Skipped: parent checklist {parent_cl} failed to create",
                    "retryable": True,
                    "retry_payload": op,
                }
            )
            continue

        # Dedup guard: skip checklist creation if one with same name exists
        if op["type"] == "push_create_checklist" and existing_checklists is not None:
            cl_name = _as_str(op_params.get("name", "")).strip().lower()
            match = next(
                (
                    cl
                    for cl in existing_checklists
                    if isinstance(cl, dict)
                    and _as_str(cl.get("name", "")).strip().lower() == cl_name
                ),
                None,
            )
            if match:
                logger.warning(
                    "Skipping duplicate checklist creation: '%s' already exists on card (id=%s)",
                    _as_str(op_params.get("name", "")),
                    _as_str(match.get("id", "")),
                )
                op["result"] = match
                succeeded.append(op)
                continue

        # Dedup guard: skip checklist item creation if one with same name exists
        if op["type"] == "push_create_item" and existing_checklists is not None:
            checklist_id = _as_str(op_params.get("checklist_id", ""))
            item_name = _as_str(op_params.get("name", "")).strip().lower()
            dedup_match = None
            for cl in existing_checklists:
                if not isinstance(cl, dict) or cl.get("id") != checklist_id:
                    continue
                items = _as_list(cl.get("checkItems", []))
                dedup_match = next(
                    (
                        it
                        for it in items
                        if isinstance(it, dict)
                        and _as_str(it.get("name", "")).strip().lower() == item_name
                    ),
                    None,
                )
                break
            if dedup_match:
                logger.warning(
                    "Skipping duplicate checklist item creation: '%s' already exists (id=%s)",
                    _as_str(op_params.get("name", "")),
                    _as_str(dedup_match.get("id", "")) if isinstance(dedup_match, dict) else "",
                )
                op["result"] = dedup_match
                succeeded.append(op)
                continue

        try:
            tool_name = _as_str(op.get("tool"))
            result = _call_trello_tool(tool_name, op_params)
            op["result"] = result
            succeeded.append(op)
        except Exception as e:
            errors.append(
                {
                    "operation_type": op["type"],
                    "error": str(e),
                    "retryable": True,
                    "retry_payload": op,
                }
            )
            ck = op.get("checklist_key")
            if op["type"] == "push_create_checklist" and isinstance(ck, str):
                skipped_checklists.add(ck)

    return succeeded, errors


def _retry_failed_ops(
    failed_ops: list[dict[str, JsonValue]],
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]]]:
    """Re-attempt only previously failed operations.

    Returns (succeeded, still_failed).
    Performs dedup checks before retrying create operations to avoid duplicates
    when the original create succeeded but the response was lost.
    """
    succeeded: list[dict[str, JsonValue]] = []
    still_failed: list[dict[str, JsonValue]] = []

    # Pre-fetch checklists for dedup on create retries
    _checklist_cache: dict[str, list[dict[str, JsonValue]]] = {}

    def _get_checklists_for_card(cid: str) -> list[dict[str, JsonValue]]:
        if cid not in _checklist_cache:
            try:
                data = _call_trello_tool("get_card_checklists", {"card_id": cid})
                raw = (
                    data
                    if isinstance(data, list)
                    else data.get("checklists", [])
                    if isinstance(data, dict)
                    else []
                )
                _checklist_cache[cid] = [
                    x for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)
                ]
            except Exception as exc:
                logger.error(
                    "Failed to fetch checklists for retry dedup (card=%s): %s",
                    cid,
                    exc,
                    exc_info=True,
                )
                _checklist_cache[cid] = []
        return _checklist_cache[cid]

    for entry in failed_ops:
        payload = _as_dict(entry.get("retry_payload", {}))
        tool = _as_str(payload.get("tool"))
        params = _as_dict(payload.get("params"))
        if not tool or not params:
            still_failed.append(entry)
            continue

        op_type = _as_str(payload.get("type")) or _as_str(entry.get("operation_type", ""))

        # Dedup guard for checklist creation retries
        dedup_match: dict[str, JsonValue] | None = None
        if op_type == "push_create_checklist" and params.get("card_id"):
            checklists = _get_checklists_for_card(_as_str(params["card_id"]))
            cl_name = _as_str(params.get("name", "")).strip().lower()
            dedup_match = next(
                (
                    cl
                    for cl in checklists
                    if isinstance(cl, dict)
                    and _as_str(cl.get("name", "")).strip().lower() == cl_name
                ),
                None,
            )
            if dedup_match:
                logger.warning(
                    "Skipping duplicate checklist creation on retry: '%s' already exists (id=%s)",
                    _as_str(params.get("name", "")),
                    _as_str(dedup_match.get("id", "")),
                )
                payload["result"] = dedup_match
                succeeded.append(payload)
                continue

        # Dedup guard for checklist item creation retries
        dedup_match = None
        if op_type == "push_create_item" and params.get("checklist_id"):
            # Find the card_id from the checklist cache or retry payload
            card_id_for_lookup = _as_str(params.get("card_id", ""))
            if not card_id_for_lookup:
                # Try to find card_id from any cached data
                for cid, cls in _checklist_cache.items():
                    if any(
                        isinstance(cl, dict) and cl.get("id") == params["checklist_id"]
                        for cl in cls
                    ):
                        card_id_for_lookup = cid
                        break
            if card_id_for_lookup:
                checklists = _get_checklists_for_card(card_id_for_lookup)
                dedup_match = None
                for cl in checklists:
                    if not isinstance(cl, dict) or cl.get("id") != params["checklist_id"]:
                        continue
                    item_name = _as_str(params.get("name", "")).strip().lower()
                    check_items = _as_list(cl.get("checkItems", []))
                    dedup_match = next(
                        (
                            it
                            for it in check_items
                            if isinstance(it, dict)
                            and _as_str(it.get("name", "")).strip().lower() == item_name
                        ),
                        None,
                    )
                    if dedup_match:
                        logger.warning(
                            "Skipping duplicate checklist item on"
                            " retry: '%s' already exists (id=%s)",
                            _as_str(params.get("name", "")),
                            _as_str(dedup_match.get("id", ""))
                            if isinstance(dedup_match, dict)
                            else "",
                        )
                        payload["result"] = dedup_match
                        succeeded.append(payload)
                        break
                else:
                    # Checklist not found in cache or no match — proceed with retry
                    pass
                if dedup_match:
                    continue

        try:
            result = _call_trello_tool(tool, params)
            payload["result"] = result
            succeeded.append(payload)
        except Exception as e:
            still_failed.append(
                {
                    "operation_type": _as_str(entry.get("operation_type"))
                    or _as_str(payload.get("type", "unknown")),
                    "error": str(e),
                    "retryable": False,
                    "retry_payload": payload,
                }
            )

    return succeeded, still_failed


def _build_summary(
    plan: TrelloSyncPlan,
    pull_counts: dict[str, int],
    succeeded_push: list[dict[str, JsonValue]],
) -> dict[str, JsonValue]:
    """Build a human-readable summary of what was synced."""
    push_by_type: dict[str, int] = {}
    for op in succeeded_push:
        t = _as_str(op.get("type", "unknown"))
        push_by_type[t] = push_by_type.get(t, 0) + 1

    return {
        "pull": pull_counts,
        "push": {
            "checklists_created": push_by_type.get("push_create_checklist", 0),
            "items_created": push_by_type.get("push_create_item", 0),
            "items_updated": push_by_type.get("push_update_item", 0),
            "items_completed": push_by_type.get("push_complete_item", 0),
            "items_deleted": push_by_type.get("push_delete_item", 0),
            "items_reopened": push_by_type.get("push_reopen_item", 0),
            "checklists_renamed": push_by_type.get("push_rename_checklist", 0),
        },
    }


# -- Single-project sync (extracted for batch reuse) --------------------------


def _sync_single_project(
    cfg: ProjConfig,
    name: str,
) -> dict[str, JsonValue]:
    """Execute a full Trello sync cycle for one project.

    Returns a result dict with status, summary, and optional errors/warnings.
    Extracted from the tool handler so batch mode can reuse it.
    """
    # Load project meta
    meta = storage.load_meta(cfg, name)
    card_id = meta.trello_card_id
    board_id = meta.trello.board_id or cfg.trello.default_board_id

    if not board_id:
        return {
            "status": "error",
            "error": "No Trello board_id configured (per-project or global default).",
        }

    # Auto-migrate from checklist model to card model if needed
    todos = storage.load_todos(cfg, name)
    migration_summary: dict[str, JsonValue] | None = None
    if _needs_migration(todos):
        migration_summary = migrate_checklist_to_card(
            cfg,
            name,
            meta,
            todos,
            call_trello=_call_trello_tool,
        )
        migration_errors = migration_summary.get("errors", [])
        if (
            isinstance(migration_errors, list)
            and migration_errors
            and not migration_summary.get("migrated", 0)
        ):
            return {
                "status": "error",
                "error": f"Trello checklist-to-card migration failed: {migration_errors}",
                "migration": migration_summary,
            }
        meta = storage.load_meta(cfg, name)
        card_id = meta.trello_card_id

    # Fetch board lists + todo cards for compute_diff (card-per-todo model)
    warnings: list[str] = []
    try:
        lists_result = _call_trello_tool("get_lists", {"board_id": board_id})
        lists_data: list[dict[str, JsonValue]] = (
            [x for x in lists_result if isinstance(x, dict)]
            if isinstance(lists_result, list)
            else []
        )
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to fetch Trello lists: {e}",
        }

    # Resolve list IDs by name for tasks + done lists
    proj_lm = (
        meta.trello.list_mappings
        if meta.trello.list_mappings is not None
        else cfg.trello.list_mappings
    )
    list_id_by_name: dict[str, str] = {
        _as_str(lst.get("name", "")).lower(): _as_str(lst.get("id", ""))
        for lst in lists_data
        if isinstance(lst, dict)
    }
    task_list_ids = [
        lid
        for lname, lid in list_id_by_name.items()
        if lname in {proj_lm.tasks.lower(), proj_lm.done.lower()}
    ]

    # Fetch cards from tasks + done lists
    all_cards: list[dict[str, JsonValue]] = []
    for list_id in task_list_ids:
        try:
            cards_result = _call_trello_tool("get_cards_by_list_id", {"list_id": list_id})
            if isinstance(cards_result, list):
                all_cards.extend(c for c in cards_result if isinstance(c, dict))
        except Exception as e:
            warnings.append(f"Failed to fetch cards for list {list_id}: {e}")

    # Fetch project tracking card if linked
    project_card: dict[str, JsonValue] | None = None
    if card_id:
        try:
            project_card = _as_dict(_call_trello_tool("get_card", {"card_id": card_id}))
        except Exception:
            logger.debug("Failed to fetch project tracking card from Trello", exc_info=True)

    trello_card_json = json.dumps(
        {
            "cards": all_cards,
            "lists": lists_data,
            "project_card": project_card or {},
        }
    )

    # Compute diff
    plan = compute_diff(trello_card_json, cfg, name)

    # If project tracking card needs creating, do it first
    if plan.project_card_create and not card_id:
        try:
            default_list = cfg.trello.default_list or "Active"
            target_list_id = None
            for lst in lists_data:
                if _as_str(lst.get("name", "")).lower() == default_list.lower():
                    target_list_id = lst.get("id")
                    break
            if not target_list_id and lists_data:
                target_list_id = lists_data[0].get("id")

            if not target_list_id:
                return {
                    "status": "error",
                    "error": "No lists found on the Trello board.",
                }

            existing_card_id = None
            try:
                existing_cards = _call_trello_tool(
                    "get_cards_by_list_id", {"list_id": target_list_id}
                )
                if isinstance(existing_cards, list):
                    for ec in existing_cards:
                        if (
                            isinstance(ec, dict)
                            and _as_str(ec.get("name", "")).strip().lower() == name.strip().lower()
                        ):
                            existing_card_id = ec.get("id")
                            break
            except Exception:
                logger.debug("Failed to check for existing card on list", exc_info=True)

            if existing_card_id:
                logger.warning(
                    "Skipping duplicate card creation: card '%s' already exists on list (id=%s)",
                    name,
                    existing_card_id,
                )
                card_result: dict[str, JsonValue] = {"id": existing_card_id}
            else:
                card_result = _as_dict(
                    _call_trello_tool(
                        "add_card_to_list",
                        {
                            "list_id": target_list_id,
                            "name": name,
                        },
                    )
                )
            new_card_id = _as_str(card_result.get("id", ""))
            if new_card_id:
                link_data = TrelloApplyInput(link_trello_card_id=new_card_id)
                apply_changes(link_data, cfg, name)
                card_id = new_card_id
                # Re-compute diff with empty cards (new project card, no todos yet)
                trello_card_json = json.dumps(
                    {"cards": [], "lists": lists_data, "project_card": {}}
                )
                plan = compute_diff(trello_card_json, cfg, name)
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to create Trello card: {e}",
            }

    # Check for pull_delete candidates requiring user confirmation
    if plan.pull_delete:
        return {
            "status": "needs_confirmation",
            "requires_confirmation": True,
            "pull_delete_pending": plan.pull_delete,
        }

    # Empty diff -> up to date
    if plan.is_empty():
        return {
            "status": "success",
            "summary": {
                "pull": {
                    "created": 0,
                    "created_root": 0,
                    "updated": 0,
                    "completed": 0,
                    "reopened": 0,
                    "linked": 0,
                },
                "push": {
                    "checklists_created": 0,
                    "items_created": 0,
                    "items_updated": 0,
                    "items_completed": 0,
                    "items_deleted": 0,
                    "items_reopened": 0,
                    "checklists_renamed": 0,
                },
                "up_to_date": True,
            },
        }

    # Apply pull operations locally
    has_pulls = bool(
        plan.pull_create
        or plan.pull_update
        or plan.pull_complete
        or plan.pull_reopen
        or plan.pull_create_root
    )
    if has_pulls:
        pull_data = TrelloApplyInput(
            created_locally=plan.pull_create,
            created_root_locally=plan.pull_create_root,
            updated_locally=plan.pull_update,
            completed_locally=plan.pull_complete,
            reopened_locally=plan.pull_reopen,
        )
        pull_counts = apply_changes(pull_data, cfg, name)
    else:
        pull_counts = {
            "created": 0,
            "created_root": 0,
            "updated": 0,
            "completed": 0,
            "reopened": 0,
            "linked": 0,
        }

    # Execute push operations
    if card_id:
        ops = _build_push_ops(plan, card_id)
        succeeded, errors = _execute_push_ops(ops, card_id=card_id)
    else:
        succeeded, errors = [], []

    # Record TrelloSyncState snapshots after push
    apply_changes(TrelloApplyInput(), cfg, name, push_confirmed=True)

    # Auto-move card to correct list based on list_mismatches
    cards_moved = 0
    seen_card_ids: set[str] = set()
    if board_id and plan.list_mismatches:
        if not lists_data:
            raw = _call_trello_tool("get_lists", {"board_id": board_id})
            lists_data = [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
        lists_data_safe = lists_data if isinstance(lists_data, list) else []
        for mismatch in plan.list_mismatches:
            card_id = str(mismatch["card_id"])
            expected_list = str(mismatch["expected_list"])
            if card_id in seen_card_ids:
                continue
            seen_card_ids.add(card_id)
            list_id = _resolve_name_to_id(expected_list, lists_data_safe)
            if not list_id:
                warnings.append(f"list not found: {expected_list}")
                continue
            try:
                _call_trello_tool("move_card", {"card_id": card_id, "list_id": list_id})
                cards_moved += 1
            except Exception as e:
                errors.append(
                    {
                        "operation_type": "list_mismatch",
                        "error": str(e),
                        "retryable": False,
                        "retry_payload": {"card_id": mismatch["card_id"], "list_id": list_id},
                    }
                )

    # Build response
    summary = _build_summary(plan, pull_counts, succeeded)
    summary["cards_moved"] = cards_moved

    result: dict[str, JsonValue] = {}
    if errors:
        token = base64.b64encode(json.dumps(errors).encode()).decode()
        result = {
            "status": "partial_success",
            "summary": summary,
            "errors": errors,
            "retry_token": token,
        }
    else:
        result = {
            "status": "success",
            "summary": summary,
        }

    if warnings:
        result["warnings"] = warnings
    if migration_summary:
        result["migration"] = migration_summary
    return result


def _is_trello_enabled(cfg: ProjConfig, project_name: str) -> bool:
    """Check if a project has Trello sync enabled.

    Returns True if either the global Trello sync is enabled and the project
    doesn't explicitly disable it, or the project explicitly enables it.
    """
    try:
        meta = storage.load_meta(cfg, project_name)
    except (FileNotFoundError, Exception):
        return False

    # Per-project override takes priority
    if meta.trello.enabled is not None:
        return meta.trello.enabled

    # Fall back to global config
    return cfg.trello.enabled


def _sync_batch(cfg: ProjConfig) -> dict[str, JsonValue]:
    """Sync all Trello-enabled projects sequentially with rate limiting.

    Returns a combined summary: {projects: [{name, status, summary}]}.
    """
    index = storage.load_index(cfg)
    project_results: list[dict[str, JsonValue]] = []

    # Filter for non-archived, Trello-enabled projects
    eligible: list[str] = []
    for pname, entry in index.projects.items():
        if entry.archived:
            continue
        if _is_trello_enabled(cfg, pname):
            eligible.append(pname)

    if not eligible:
        return {
            "status": "success",
            "projects": [],
            "message": "No Trello-enabled projects found.",
        }

    for i, pname in enumerate(eligible):
        try:
            result = _sync_single_project(cfg, pname)
            project_results.append(
                {
                    "name": pname,
                    "status": result.get("status", "unknown"),
                    "summary": result.get("summary", {}),
                }
            )
        except Exception as e:
            logger.warning("Batch sync failed for project %s: %s", pname, e)
            project_results.append(
                {
                    "name": pname,
                    "status": "error",
                    "summary": {"error": str(e)},
                }
            )

        # Rate limiting between projects (skip after the last one)
        if i < len(eligible) - 1:
            time.sleep(1.0)

    # Determine overall status
    statuses = {str(r.get("status", "")) for r in project_results}
    if statuses == {"success"}:
        overall = "success"
    elif "error" in statuses and statuses == {"error"}:
        overall = "error"
    else:
        overall = "partial_success"

    return {
        "status": overall,
        "projects": project_results,
    }


# -- Callable helper (used by proj_sync dispatcher) --------------------------


def _run_trello_full_sync(
    project_name: str | None = None,
    retry_failures: str | None = None,
) -> str:
    """Full Trello sync cycle — callable without MCP registration."""
    # -- Retry mode: re-attempt only failed ops --
    if retry_failures:
        try:
            failed_ops = json.loads(base64.b64decode(retry_failures))
        except (json.JSONDecodeError, Exception) as e:
            return json.dumps({"status": "error", "error": f"Invalid retry_failures: {e}"})

        succeeded, still_failed = _retry_failed_ops(failed_ops)
        if still_failed:
            token = base64.b64encode(json.dumps(still_failed).encode()).decode()
            return json.dumps(
                {
                    "status": "partial_success",
                    "retried_succeeded": len(succeeded),
                    "errors": still_failed,
                    "retry_token": token,
                }
            )
        return json.dumps(
            {
                "status": "success",
                "retried_succeeded": len(succeeded),
                "summary": {"retry": True, "succeeded": len(succeeded)},
            }
        )

    # -- Normal mode: full sync cycle --

    # Check if we have a specific project or active session
    result = require_project(project_name)
    if isinstance(result, str):
        # No active project -- enter batch mode if no explicit name was given
        if project_name is not None:
            # Explicit project name was given but not found
            return json.dumps({"status": "error", "error": result})

        # Batch mode: sync all Trello-enabled projects
        try:
            cfg = require_config()
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

        batch_result = _sync_batch(cfg)
        return json.dumps(batch_result, indent=2)

    cfg, name = result
    single_result = _sync_single_project(cfg, name)
    return json.dumps(single_result)


# -- MCP tool registration ---------------------------------------------------


def register(app: FastMCP) -> None:
    """No-op: proj_trello_full_sync merged into proj_sync (605.6)."""
