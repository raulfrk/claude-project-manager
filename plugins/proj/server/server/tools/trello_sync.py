"""MCP tools for batched Trello sync — diff and apply.

Model: one Trello card per project. Root todos with children become checklists
(name = todo title), their flattened descendants become checklist items.
Root leaf todos go into a "Tasks" catch-all checklist.

Sync uses last-changed-wins: each todo carries a TrelloSyncState snapshot
recording the name/state at last sync time. Changes are detected by comparing
current local state vs snapshot (local changed) and current Trello state vs
snapshot (Trello changed).
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import Todo, TrelloSyncState
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

TASKS_CHECKLIST_NAME = "Tasks"
_UTC = timezone.utc


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


def _ghost_check(title: str, archived: list[Todo], threshold: float = 0.7) -> bool:
    """Return True if title matches an archived todo (exact or fuzzy)."""
    if not archived:
        return False
    lower_title = title.lower()
    titles = [t.title for t in archived]
    if any(t.lower() == lower_title for t in titles):
        return True
    return bool(difflib.get_close_matches(title, titles, n=1, cutoff=threshold))


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class TrelloSyncPlan:
    """Result of comparing Trello card checklists with local todos."""

    pull_create: list[dict[str, object]] = field(default_factory=list)
    pull_update: list[dict[str, object]] = field(default_factory=list)
    pull_complete: list[str] = field(default_factory=list)
    pull_reopen: list[str] = field(default_factory=list)
    pull_create_root: list[dict[str, object]] = field(default_factory=list)
    push_create_checklist: list[dict[str, object]] = field(default_factory=list)
    push_create_item: list[dict[str, object]] = field(default_factory=list)
    push_update_item: list[dict[str, object]] = field(default_factory=list)
    push_complete_item: list[dict[str, object]] = field(default_factory=list)
    push_delete_item: list[dict[str, object]] = field(default_factory=list)
    push_rename_checklist: list[dict[str, object]] = field(default_factory=list)
    conflicts: list[dict[str, object]] = field(default_factory=list)
    card_create: bool = False
    label_create: bool = False
    list_mismatches: list[dict[str, object]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.pull_create, self.pull_update, self.pull_complete,
            self.pull_reopen, self.pull_create_root,
            self.push_create_checklist, self.push_create_item,
            self.push_update_item, self.push_complete_item,
            self.push_delete_item, self.push_rename_checklist,
            self.conflicts, self.list_mismatches,
            self.card_create, self.label_create,
        ])

    def to_dict(self) -> dict[str, object]:
        return {
            "pull_create": self.pull_create,
            "pull_update": self.pull_update,
            "pull_complete": self.pull_complete,
            "pull_reopen": self.pull_reopen,
            "pull_create_root": self.pull_create_root,
            "push_create_checklist": self.push_create_checklist,
            "push_create_item": self.push_create_item,
            "push_update_item": self.push_update_item,
            "push_complete_item": self.push_complete_item,
            "push_delete_item": self.push_delete_item,
            "push_rename_checklist": self.push_rename_checklist,
            "conflicts": self.conflicts,
            "card_create": self.card_create,
            "label_create": self.label_create,
            "list_mismatches": self.list_mismatches,
            "summary": {
                "pull_create_count": len(self.pull_create),
                "pull_update_count": len(self.pull_update),
                "pull_complete_count": len(self.pull_complete),
                "pull_reopen_count": len(self.pull_reopen),
                "pull_create_root_count": len(self.pull_create_root),
                "push_create_checklist_count": len(self.push_create_checklist),
                "push_create_item_count": len(self.push_create_item),
                "push_update_item_count": len(self.push_update_item),
                "push_complete_item_count": len(self.push_complete_item),
                "push_delete_item_count": len(self.push_delete_item),
                "push_rename_checklist_count": len(self.push_rename_checklist),
                "conflict_count": len(self.conflicts),
                "list_mismatch_count": len(self.list_mismatches),
            },
        }


@dataclass
class TrelloApplyInput:
    """Input for applying Trello sync changes locally."""

    created_locally: list[dict[str, Any]] = field(default_factory=list)
    created_root_locally: list[dict[str, Any]] = field(default_factory=list)
    updated_locally: list[dict[str, Any]] = field(default_factory=list)
    completed_locally: list[str] = field(default_factory=list)
    reopened_locally: list[str] = field(default_factory=list)
    link_trello_ids: list[dict[str, str]] = field(default_factory=list)
    link_trello_card_id: str | None = None


# ── Flattening logic ─────────────────────────────────────────────────────────


def _flatten_descendants(
    todo: Todo,
    todo_map: dict[str, Todo],
    prefix: str = "",
) -> list[tuple[str, Todo]]:
    """Recursively flatten a todo's descendants depth-first.

    Returns list of (display_name, todo) tuples. display_name uses the
    dotted ID path format: "2.3.1 \u2014 title" (em dash separator).
    The todo's own ID already encodes the hierarchy (e.g., "1.1.1").
    """
    results: list[tuple[str, Todo]] = []
    for child_id in todo.children:
        child = todo_map.get(child_id)
        if child is None:
            continue
        results.append((f"{child.id} \u2014 {child.title}", child))
        # Recurse into grandchildren
        results.extend(_flatten_descendants(child, todo_map, prefix))
    return results


def build_expected_state(
    todos: list[Todo],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Build the expected Trello checklist state from local todos.

    Returns (checklists, tasks_items) where:
    - checklists: list of dicts with keys: todo_id, name, items (list of item dicts)
    - tasks_items: list of item dicts for the "Tasks" catch-all checklist
    Each item dict has: todo_id, name, checked
    """
    todo_map = {t.id: t for t in todos}
    roots = [t for t in todos if t.parent is None]

    checklists: list[dict[str, object]] = []
    tasks_items: list[dict[str, object]] = []

    for root in roots:
        if root.children:
            # Root with children -> checklist
            items: list[dict[str, object]] = []
            for display_name, desc_todo in _flatten_descendants(root, todo_map):
                items.append({
                    "todo_id": desc_todo.id,
                    "name": display_name,
                    "checked": desc_todo.status in TERMINAL_STATUSES,
                })
            checklists.append({
                "todo_id": root.id,
                "name": root.title,
                "items": items,
            })
        else:
            # Root leaf -> item in "Tasks" checklist
            tasks_items.append({
                "todo_id": root.id,
                "name": root.title,
                "checked": root.status in TERMINAL_STATUSES,
            })

    return checklists, tasks_items


# ── Core logic ───────────────────────────────────────────────────────────────


def compute_diff(
    trello_card_json: str,
    cfg: Any,
    name: str,
) -> TrelloSyncPlan:
    """Compare Trello card checklists with local todos using last-changed-wins.

    For each linked item, the algorithm checks:
    - local_changed: todo.updated > sync_state.last_sync
    - trello_changed: item.name != sync_state.synced_name or item.state != sync_state.synced_state
    - Both changed -> conflict (default: prefer local)
    - Only local changed -> push
    - Only Trello changed -> pull
    - Neither changed -> skip

    First-sync migration: if trello_sync_state is None, fall back to direct
    comparison (backward compat for one cycle), then record snapshot on apply.
    """
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    archived = storage.load_archived_todos(cfg, name)

    plan = TrelloSyncPlan()

    # Check if card needs to be created
    if not meta.trello_card_id:
        plan.card_create = True

    # Parse Trello card state
    try:
        trello_data: dict[str, Any] = json.loads(trello_card_json) if trello_card_json else {}
    except json.JSONDecodeError:
        trello_data = {}

    trello_checklists: list[dict[str, Any]] = trello_data.get("checklists", [])
    valid_card = "checklists" in trello_data

    # Build Trello lookups
    trello_items_by_id: dict[str, dict[str, Any]] = {}  # item_id -> item data
    trello_checklists_by_id: dict[str, dict[str, Any]] = {}  # checklist_id -> checklist data
    for cl in trello_checklists:
        cl_id = str(cl.get("id", ""))
        if cl_id:
            trello_checklists_by_id[cl_id] = cl
        for item in cl.get("checkItems", []):
            item_id = str(item.get("id", ""))
            if item_id:
                item["_checklist_id"] = cl_id
                item["_checklist_name"] = str(cl.get("name", ""))
                trello_items_by_id[item_id] = item

    # Build local lookups
    todo_map = {t.id: t for t in todos}
    local_by_checklist_item_id: dict[str, Todo] = {}
    local_by_checklist_id: dict[str, Todo] = {}

    for todo in todos:
        if todo.trello_checklist_item_id:
            local_by_checklist_item_id[todo.trello_checklist_item_id] = todo
        if todo.trello_checklist_id:
            local_by_checklist_id[todo.trello_checklist_id] = todo

    # Build archive lookup (Bug 1 fix: detect items linked to archived todos)
    archived_by_checklist_item_id: dict[str, Todo] = {}
    archived_by_checklist_id: dict[str, Todo] = {}
    for todo in archived:
        if todo.trello_checklist_item_id:
            archived_by_checklist_item_id[todo.trello_checklist_item_id] = todo
        if todo.trello_checklist_id:
            archived_by_checklist_id[todo.trello_checklist_id] = todo

    # Build expected local state
    expected_checklists, expected_tasks_items = build_expected_state(todos)

    # ── Linked items: last-changed-wins ──────────────────────────────

    ghost_deleted_ids: set[str] = set()

    for item_id, item in trello_items_by_id.items():
        item_name = str(item.get("name", ""))
        item_state = str(item.get("state", "incomplete"))
        is_checked = item_state == "complete"

        if item_id in local_by_checklist_item_id:
            local_todo = local_by_checklist_item_id[item_id]
            local_is_done = local_todo.status in TERMINAL_STATUSES
            expected_name = _find_expected_name(
                local_todo.id, expected_checklists, expected_tasks_items,
            )
            local_display_name = expected_name or local_todo.title
            local_state_str = "complete" if local_is_done else "incomplete"

            ss = local_todo.trello_sync_state

            if ss is None or not ss.last_sync:
                # ── First-sync migration (232.8): no snapshot yet ────
                # Fall back to direct comparison for one cycle
                checklist_id = str(item.get("_checklist_id", ""))
                _first_sync_diff(
                    plan, local_todo, item_name, item_state, is_checked,
                    local_is_done, local_display_name, expected_checklists,
                    expected_tasks_items, checklist_id,
                )
            else:
                # ── Last-changed-wins logic (232.5) ──────────────────
                local_changed = local_todo.updated > ss.last_sync
                trello_changed = (
                    item_name != ss.synced_name or item_state != ss.synced_state
                )

                if local_changed and trello_changed:
                    # Conflict — default: prefer local (most recent update)
                    resolution = "local"
                    plan.conflicts.append({
                        "todo_id": local_todo.id,
                        "local_value": {"name": local_display_name, "state": local_state_str},
                        "trello_value": {"name": item_name, "state": item_state},
                        "resolution": resolution,
                    })
                    # Apply local-wins: push local state
                    _emit_push_for_linked(
                        plan, local_todo, local_display_name, local_state_str,
                        item_name, item_state, item,
                    )
                elif local_changed and not trello_changed:
                    # Only local changed -> push
                    _emit_push_for_linked(
                        plan, local_todo, local_display_name, local_state_str,
                        item_name, item_state, item,
                    )
                elif trello_changed and not local_changed:
                    # Only Trello changed -> pull
                    _emit_pull_for_linked(
                        plan, local_todo, item_name, item_state, is_checked,
                        local_is_done, expected_checklists, expected_tasks_items,
                    )
                # else: neither changed -> skip

        elif item_id in archived_by_checklist_item_id:
            # Bug 1 fix: Item is linked to an archived todo — don't pull as new.
            # If Trello item is still unchecked, push complete to keep in sync.
            if not is_checked:
                plan.push_complete_item.append({
                    "item_id": item_id,
                    "checklist_id": str(item.get("_checklist_id", "")),
                    "state": "complete",
                })
            # If already checked: skip — both sides agree it's done.

        else:
            # New item in Trello not linked locally — create
            actual_title = _strip_id_prefix(item_name)

            # Bug 2 fix: ghost check against archived todos
            if _ghost_check(actual_title, archived):
                # Matches a recently archived todo — don't pull duplicate.
                # Push delete to clean up the Trello side.
                plan.push_delete_item.append({
                    "item_id": item_id,
                    "checklist_id": str(item.get("_checklist_id", "")),
                })
                ghost_deleted_ids.add(item_id)
                continue

            cl_id = str(item.get("_checklist_id", ""))

            # Determine parent: if checklist is linked to a root todo, parent = that root
            parent_id: str | None = None
            parent_checklist_id: str | None = None
            if cl_id and cl_id in local_by_checklist_id:
                parent_todo = local_by_checklist_id[cl_id]
                parent_id = parent_todo.id
            elif cl_id and str(item.get("_checklist_name", "")) != TASKS_CHECKLIST_NAME:
                # Bug 3 fix: item is in a new checklist (will be pull_create_root)
                # Store the checklist ID so apply_changes can resolve the parent
                parent_checklist_id = cl_id

            plan.pull_create.append({
                "title": actual_title,
                "parent": parent_id,
                "parent_checklist_id": parent_checklist_id,
                "trello_checklist_item_id": item_id,
                "checked": is_checked,
            })

    # New checklists not linked locally -> potentially new root todos
    for cl_id, cl in trello_checklists_by_id.items():
        cl_name = str(cl.get("name", ""))
        # Bug 1 fix: also skip checklists linked to archived root todos
        if (
            cl_id not in local_by_checklist_id
            and cl_id not in archived_by_checklist_id
            and cl_name != TASKS_CHECKLIST_NAME
        ):
            plan.pull_create_root.append({
                "title": cl_name,
                "trello_checklist_id": cl_id,
            })

    # ── Closure propagation (Bug 4 fix) ──────────────────────────────
    # Like Todoist sync: if a linked todo's Trello item was deleted, close it.
    stale_links: set[str] = set()
    if valid_card:
        for todo in todos:
            if (
                todo.trello_checklist_item_id
                and todo.trello_checklist_item_id not in trello_items_by_id
                and todo.status not in TERMINAL_STATUSES
            ):
                stale_links.add(todo.trello_checklist_item_id)
                plan.pull_complete.append(todo.id)

    # ── Push phase: Local -> Trello (unlinked items) ─────────────────

    # Push checklists for root todos with children
    for cl_spec in expected_checklists:
        root_id = str(cl_spec["todo_id"])
        root_todo = todo_map.get(root_id)
        if root_todo is None:
            continue

        if not root_todo.trello_checklist_id:
            # New checklist to create
            plan.push_create_checklist.append({
                "todo_id": root_id,
                "name": str(cl_spec["name"]),
            })
        else:
            # Check if name changed
            trello_cl = trello_checklists_by_id.get(root_todo.trello_checklist_id)
            if trello_cl:
                trello_name = str(trello_cl.get("name", ""))
                local_name = str(cl_spec["name"])
                if trello_name != local_name:
                    plan.push_rename_checklist.append({
                        "checklist_id": root_todo.trello_checklist_id,
                        "name": local_name,
                    })

        # Push items within this checklist (only unlinked ones)
        items_spec = cl_spec.get("items", [])
        if isinstance(items_spec, list):
            for item_spec in items_spec:
                item_todo_id = str(item_spec.get("todo_id", ""))  # type: ignore[union-attr]
                item_todo = todo_map.get(item_todo_id)
                if item_todo is None:
                    continue
                # Only push-create for items not yet linked; linked items
                # are handled by the last-changed-wins loop above.
                # Bug 5 fix: skip items with stale links (handled by closure propagation)
                if not item_todo.trello_checklist_item_id:
                    plan.push_create_item.append({
                        "todo_id": item_todo.id,
                        "name": str(item_spec.get("name", "")),  # type: ignore[union-attr]
                        "checklist_id": root_todo.trello_checklist_id,
                        "checked": bool(item_spec.get("checked", False)),  # type: ignore[union-attr]
                    })
                # Stale links (item deleted in Trello) are handled by closure
                # propagation above — no re-creation.

    # Push items for the "Tasks" catch-all checklist
    # Find Tasks checklist: prefer stored ID, fall back to name-based scan
    tasks_cl_id: str | None = None
    stored_tasks_id = meta.trello.trello_tasks_checklist_id
    if stored_tasks_id and stored_tasks_id in trello_checklists_by_id:
        # Stored ID is still valid
        tasks_cl_id = stored_tasks_id
    else:
        # Stored ID missing or stale — fall back to name-based scan
        for cl_id, cl in trello_checklists_by_id.items():
            if str(cl.get("name", "")) == TASKS_CHECKLIST_NAME:
                tasks_cl_id = cl_id
                break
        # Update stored ID if we found it by name (or clear if gone)
        if tasks_cl_id != stored_tasks_id:
            meta.trello.trello_tasks_checklist_id = tasks_cl_id
            storage.save_meta(cfg, meta)

    if expected_tasks_items and not tasks_cl_id:
        # Need to create "Tasks" checklist
        plan.push_create_checklist.append({
            "todo_id": "_tasks",
            "name": TASKS_CHECKLIST_NAME,
        })

    for item_spec in expected_tasks_items:
        item_todo_id = str(item_spec.get("todo_id", ""))
        item_todo = todo_map.get(item_todo_id)
        if item_todo is None:
            continue
        # Only push-create for items not yet linked
        # Bug 5 fix: skip items with stale links (handled by closure propagation)
        if not item_todo.trello_checklist_item_id:
            plan.push_create_item.append({
                "todo_id": item_todo.id,
                "name": str(item_spec.get("name", "")),
                "checklist_id": tasks_cl_id,
                "checked": bool(item_spec.get("checked", False)),
            })
        # Stale links (item deleted in Trello) are handled by closure
        # propagation above — no re-creation.

    # Push delete: items in Trello not linked to any local or archived todo
    # Bug 7 fix: include archived todos' links to prevent deleting their items
    linked_trello_item_ids = {
        t.trello_checklist_item_id for t in todos if t.trello_checklist_item_id
    } | {
        t.trello_checklist_item_id for t in archived if t.trello_checklist_item_id
    }
    for item_id in trello_items_by_id:
        if item_id in ghost_deleted_ids:
            continue  # already queued for deletion by ghost check
        if item_id not in linked_trello_item_ids and item_id not in {
            str(pc.get("trello_checklist_item_id", ""))
            for pc in plan.pull_create
        }:
            plan.push_delete_item.append({
                "item_id": item_id,
                "checklist_id": str(trello_items_by_id[item_id].get("_checklist_id", "")),
            })

    # ── List mismatch detection (228.5) ──────────────────────────────
    # If list_mappings are configured, check whether the card's current list
    # matches the expected list for the project's status.
    if meta.trello_card_id and trello_data:
        from server.lib.models import TrelloListMappings

        proj_lm = meta.trello.list_mappings if meta.trello.list_mappings is not None else cfg.trello.list_mappings
        status_list_map: dict[str, str] = {
            "active": proj_lm.active,
            "paused": proj_lm.pending,
            "blocked": proj_lm.pending,
        }
        expected_list = status_list_map.get(meta.status, "")
        if expected_list:
            current_list = str(trello_data.get("list", {}).get("name", "")) if isinstance(trello_data.get("list"), dict) else ""
            if not current_list:
                current_list = str(trello_data.get("idList", ""))
            if current_list and current_list != expected_list:
                plan.list_mismatches.append({
                    "card_id": meta.trello_card_id,
                    "current_list": current_list,
                    "expected_list": expected_list,
                    "project_status": meta.status,
                })

    return plan


def _first_sync_diff(
    plan: TrelloSyncPlan,
    local_todo: Todo,
    item_name: str,
    item_state: str,
    is_checked: bool,
    local_is_done: bool,
    local_display_name: str,
    expected_checklists: list[dict[str, object]],
    expected_tasks_items: list[dict[str, object]],
    checklist_id: str = "",
) -> None:
    """First-sync migration: no snapshot yet, use direct comparison (232.8).

    Compares current local vs current Trello directly. Any difference is
    treated as a push (local wins for first sync).
    """
    local_state_str = "complete" if local_is_done else "incomplete"

    # Name difference -> push local name
    if item_name != local_display_name:
        plan.push_update_item.append({
            "item_id": local_todo.trello_checklist_item_id,
            "name": local_display_name,
            "checklist_id": checklist_id,
        })

    # State difference -> push local state
    if local_is_done and not is_checked:
        plan.push_complete_item.append({
            "item_id": local_todo.trello_checklist_item_id,
            "checklist_id": checklist_id,
            "state": "complete",
        })
    elif not local_is_done and is_checked:
        # Trello is checked but local is not — for first sync, pull Trello's state
        plan.pull_complete.append(local_todo.id)


def _emit_push_for_linked(
    plan: TrelloSyncPlan,
    local_todo: Todo,
    local_display_name: str,
    local_state_str: str,
    trello_name: str,
    trello_state: str,
    trello_item: dict[str, Any],
) -> None:
    """Emit push operations for a linked item where local wins."""
    if local_display_name != trello_name:
        plan.push_update_item.append({
            "item_id": local_todo.trello_checklist_item_id,
            "name": local_display_name,
            "checklist_id": str(trello_item.get("_checklist_id", "")),
        })
    if local_state_str != trello_state:
        if local_state_str == "complete":
            plan.push_complete_item.append({
                "item_id": local_todo.trello_checklist_item_id,
                "checklist_id": str(trello_item.get("_checklist_id", "")),
                "state": "complete",
            })


def _emit_pull_for_linked(
    plan: TrelloSyncPlan,
    local_todo: Todo,
    item_name: str,
    item_state: str,
    is_checked: bool,
    local_is_done: bool,
    expected_checklists: list[dict[str, object]],
    expected_tasks_items: list[dict[str, object]],
) -> None:
    """Emit pull operations for a linked item where Trello wins."""
    # Name change
    expected_name = _find_expected_name(
        local_todo.id, expected_checklists, expected_tasks_items,
    )
    if item_name != local_todo.title:
        if expected_name is None or item_name != expected_name:
            actual_title = _strip_id_prefix(item_name)
            plan.pull_update.append({
                "todo_id": local_todo.id,
                "title": actual_title,
            })

    # State change
    if is_checked and not local_is_done:
        plan.pull_complete.append(local_todo.id)
    elif not is_checked and local_is_done:
        plan.pull_reopen.append(local_todo.id)


def _find_expected_name(
    todo_id: str,
    checklists: list[dict[str, object]],
    tasks_items: list[dict[str, object]],
) -> str | None:
    """Find the expected display name for a todo in the expected state."""
    for cl in checklists:
        items = cl.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and str(item.get("todo_id", "")) == todo_id:
                    return str(item.get("name", ""))
    for item in tasks_items:
        if isinstance(item, dict) and str(item.get("todo_id", "")) == todo_id:
            return str(item.get("name", ""))
    return None


def _strip_id_prefix(name: str) -> str:
    """Strip ID prefix from a checklist item name.

    Handles both old format ('1.1: title', '1.1: 1.1.1: title')
    and new format ('1.1 \u2014 title', '1.1.1 \u2014 title').
    """
    # New format: "2.3.1 \u2014 title"
    m = re.match(r"^[\d.]+\s*\u2014\s*", name)
    if m:
        return name[m.end():]
    # Old format: one or more "ID: " prefixes (IDs contain digits and dots)
    return re.sub(r"^(?:\d[\d.]*:\s*)+", "", name)


# ── Apply logic ──────────────────────────────────────────────────────────────


def apply_changes(
    data: TrelloApplyInput,
    cfg: Any,
    name: str,
) -> dict[str, int]:
    """Apply Trello sync changes to local todos atomically. Returns counts dict."""
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    todo_map = {t.id: t for t in todos}
    now = _now()

    counts = {
        "created": 0,
        "created_root": 0,
        "updated": 0,
        "completed": 0,
        "reopened": 0,
        "linked": 0,
    }

    # 1. Create new root todos (from pull_create_root -- new checklists)
    for item in data.created_root_locally:
        todo = Todo(
            id=next_todo_id(meta),
            title=str(item.get("title", "")),
            created=now,
            updated=now,
            trello_checklist_id=str(item["trello_checklist_id"]) if item.get("trello_checklist_id") else None,
        )
        todos.append(todo)
        todo_map[todo.id] = todo
        counts["created_root"] += 1

    # Build lookup: trello_checklist_id -> todo_id (for resolving new checklist parents)
    checklist_id_to_todo: dict[str, str] = {}
    for todo in todos:
        if todo.trello_checklist_id:
            checklist_id_to_todo[todo.trello_checklist_id] = todo.id

    # 2. Create new child todos (from pull_create -- new checklist items)
    for item in data.created_locally:
        parent_id = str(item["parent"]) if item.get("parent") else None
        # Bug 3 fix: resolve parent from parent_checklist_id if parent is None
        if not parent_id and item.get("parent_checklist_id"):
            parent_id = checklist_id_to_todo.get(str(item["parent_checklist_id"]))
        parent_todo = todo_map.get(parent_id) if parent_id else None
        todo = Todo(
            id=next_todo_id(meta, parent=parent_todo),
            title=str(item.get("title", "")),
            created=now,
            updated=now,
            parent=parent_id,
            trello_checklist_item_id=str(item["trello_checklist_item_id"]) if item.get("trello_checklist_item_id") else None,
            status=TodoStatus.DONE if item.get("checked") else "pending",
        )
        if parent_todo:
            parent_todo.children.append(todo.id)
            parent_todo.updated = now
        todos.append(todo)
        todo_map[todo.id] = todo
        counts["created"] += 1

    # 3. Update existing todos
    for item in data.updated_locally:
        todo_id = str(item.get("todo_id", ""))
        todo = todo_map.get(todo_id)
        if not todo:
            continue
        if "title" in item and item["title"] is not None:
            todo.title = str(item["title"])
        todo.updated = now
        counts["updated"] += 1

    # 4. Link Trello IDs (after push operations return Trello IDs)
    for item in data.link_trello_ids:
        todo_id = str(item.get("todo_id", ""))
        # Handle _tasks sentinel: store checklist ID on meta instead of a todo
        if todo_id == "_tasks" and "trello_checklist_id" in item:
            meta.trello.trello_tasks_checklist_id = str(item["trello_checklist_id"]) if item.get("trello_checklist_id") else None
            counts["linked"] += 1
            continue
        todo = todo_map.get(todo_id)
        if not todo:
            continue
        if "trello_checklist_id" in item:
            todo.trello_checklist_id = str(item["trello_checklist_id"]) if item.get("trello_checklist_id") else None
        if "trello_checklist_item_id" in item:
            todo.trello_checklist_item_id = str(item["trello_checklist_item_id"]) if item.get("trello_checklist_item_id") else None
        todo.updated = now
        counts["linked"] += 1

    # 5. Link card ID on project meta
    if data.link_trello_card_id:
        meta.trello_card_id = data.link_trello_card_id

    # 6. Complete todos
    to_archive: list[Todo] = []
    for raw_todo_id in data.completed_locally:
        todo = todo_map.get(str(raw_todo_id))
        if not todo or todo.status in TERMINAL_STATUSES:
            continue
        todo.status = TodoStatus.DONE
        todo.updated = now
        counts["completed"] += 1
        # Leaf todos (no parent, no children) get archived
        if not todo.parent and not todo.children:
            to_archive.append(todo)
            for t in todos:
                if todo.id in t.blocks:
                    t.blocks.remove(todo.id)
                    t.updated = now
                if todo.id in t.blocked_by:
                    t.blocked_by.remove(todo.id)
                    t.updated = now

    # 7. Reopen todos
    for raw_todo_id in data.reopened_locally:
        todo = todo_map.get(str(raw_todo_id))
        if not todo or todo.status not in TERMINAL_STATUSES:
            continue
        todo.status = "pending"
        todo.updated = now
        counts["reopened"] += 1

    # 8. Record trello_sync_state on all synced todos (232.7)
    sync_now = _now()
    expected_checklists, expected_tasks_items = build_expected_state(todos)
    for todo in todos:
        if todo.trello_checklist_item_id or todo.trello_checklist_id:
            expected_name = _find_expected_name(
                todo.id, expected_checklists, expected_tasks_items,
            )
            display_name = expected_name or todo.title
            state_str = "complete" if todo.status in TERMINAL_STATUSES else "incomplete"
            todo.trello_sync_state = TrelloSyncState(
                last_sync=sync_now,
                synced_name=display_name,
                synced_state=state_str,
            )

    # Save atomically
    storage.save_meta(cfg, meta)
    if to_archive:
        remaining = [t for t in todos if t not in to_archive]
        storage.archive_and_remove_todos(cfg, name, remaining, to_archive)
    else:
        storage.save_todos(cfg, name, todos)

    return counts


# ── MCP tool registration ────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register Trello sync tools."""

    @app.tool(
        description=(
            "Compare Trello card checklists with local todos and produce a sync plan. "
            "Takes Trello card state as JSON (checklists array with items). Returns a "
            "JSON sync plan with batched operations for both sides. Uses last-changed-wins "
            "logic with conflict detection. "
            "When auto_apply=True, pull operations (pull_create, pull_update, "
            "pull_complete, pull_reopen, pull_create_root) are applied locally "
            "immediately and the response includes project_info so the caller "
            "can execute push operations via Trello MCP tools. "
            "Set summary_only=True to return only summary counts, not full plan arrays."
        )
    )
    def proj_trello_diff(
        trello_card_json: str,
        auto_apply: bool = False,
        summary_only: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, proj_name = result

        plan = compute_diff(trello_card_json, cfg, proj_name)

        if not auto_apply:
            plan_dict = plan.to_dict()
            if summary_only:
                return json.dumps({"summary": plan_dict["summary"]}, indent=2)
            return json.dumps(plan_dict, indent=2)

        # auto_apply mode: apply pull operations server-side
        meta = storage.load_meta(cfg, proj_name)
        plan_dict = plan.to_dict()
        response: dict[str, object] = {
            "plan": {"summary": plan_dict["summary"]} if summary_only else plan_dict,
            "project_info": {
                "mcp_server": "trello",
                "board_id": meta.trello.board_id or cfg.trello.default_board_id,
                "trello_card_id": meta.trello_card_id or "",
                "default_list": cfg.trello.default_list,
            },
        }

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
            counts = apply_changes(pull_data, cfg, proj_name)
            response["auto_applied"] = counts
        else:
            response["auto_applied"] = {
                "created": 0, "created_root": 0, "updated": 0,
                "completed": 0, "reopened": 0, "linked": 0,
            }

        return json.dumps(response, indent=2)

    @app.tool(
        description=(
            "Apply Trello sync results to local todos in bulk. Takes a JSON "
            "object with: created_locally, created_root_locally, updated_locally, "
            "completed_locally, reopened_locally, link_trello_ids, "
            "link_trello_card_id. All changes are applied atomically. "
            "Records trello_sync_state on each synced todo after apply."
        )
    )
    def proj_trello_apply(
        apply_json: str,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, proj_name = result

        try:
            raw: dict[str, Any] = json.loads(apply_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        data = TrelloApplyInput(
            created_locally=raw.get("created_locally", []),
            created_root_locally=raw.get("created_root_locally", []),
            updated_locally=raw.get("updated_locally", []),
            completed_locally=raw.get("completed_locally", []),
            reopened_locally=raw.get("reopened_locally", []),
            link_trello_ids=raw.get("link_trello_ids", []),
            link_trello_card_id=raw.get("link_trello_card_id"),
        )
        counts = apply_changes(data, cfg, proj_name)
        return json.dumps({"status": "ok", "counts": counts})
