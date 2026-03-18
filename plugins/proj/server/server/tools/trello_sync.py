"""MCP tools for batched Trello sync — diff and apply.

Model: one Trello card per project. Root todos with children become checklists
(name = todo title), their flattened descendants become checklist items.
Root leaf todos go into a "Tasks" catch-all checklist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import Todo
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

TASKS_CHECKLIST_NAME = "Tasks"


def _today() -> str:
    return str(date.today())


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
    card_create: bool = False
    label_create: bool = False

    def is_empty(self) -> bool:
        return not any([
            self.pull_create, self.pull_update, self.pull_complete,
            self.pull_reopen, self.pull_create_root,
            self.push_create_checklist, self.push_create_item,
            self.push_update_item, self.push_complete_item,
            self.push_delete_item, self.push_rename_checklist,
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
            "card_create": self.card_create,
            "label_create": self.label_create,
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

    Returns list of (display_name, todo) tuples. display_name is the todo's
    title prefixed with its ancestor ID path for disambiguation.
    """
    results: list[tuple[str, Todo]] = []
    for child_id in todo.children:
        child = todo_map.get(child_id)
        if child is None:
            continue
        child_prefix = f"{prefix}{child.id}: " if prefix else f"{child.id}: "
        results.append((f"{child_prefix}{child.title}", child))
        # Recurse into grandchildren
        results.extend(_flatten_descendants(child, todo_map, child_prefix))
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
    """Compare Trello card checklists with local todos. Returns a TrelloSyncPlan."""
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)

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

    # Build expected local state
    expected_checklists, expected_tasks_items = build_expected_state(todos)

    # ── Pull phase: Trello -> Local ──────────────────────────────────

    for item_id, item in trello_items_by_id.items():
        item_name = str(item.get("name", ""))
        item_state = str(item.get("state", "incomplete"))
        is_checked = item_state == "complete"

        if item_id in local_by_checklist_item_id:
            local_todo = local_by_checklist_item_id[item_id]
            local_is_done = local_todo.status in TERMINAL_STATUSES

            # Check for name mismatch (pull update)
            # For items with ID prefix, compare the full display name
            if item_name != local_todo.title:
                # Check if this is a prefixed name by looking at expected state
                expected_name = _find_expected_name(local_todo.id, expected_checklists, expected_tasks_items)
                if expected_name is None or item_name != expected_name:
                    # Trello has a different name — pull update
                    # Strip ID prefix if present to get the actual title
                    actual_title = _strip_id_prefix(item_name)
                    plan.pull_update.append({
                        "todo_id": local_todo.id,
                        "title": actual_title,
                    })

            # Check completion state
            if is_checked and not local_is_done:
                plan.pull_complete.append(local_todo.id)
            elif not is_checked and local_is_done:
                plan.pull_reopen.append(local_todo.id)
        else:
            # New item in Trello not linked locally — create
            actual_title = _strip_id_prefix(item_name)
            cl_id = str(item.get("_checklist_id", ""))
            cl_name = str(item.get("_checklist_name", ""))

            # Determine parent: if checklist is linked to a root todo, parent = that root
            parent_id: str | None = None
            if cl_id and cl_id in local_by_checklist_id:
                parent_todo = local_by_checklist_id[cl_id]
                parent_id = parent_todo.id

            plan.pull_create.append({
                "title": actual_title,
                "parent": parent_id,
                "trello_checklist_item_id": item_id,
                "checked": is_checked,
            })

    # New checklists not linked locally -> potentially new root todos
    for cl_id, cl in trello_checklists_by_id.items():
        cl_name = str(cl.get("name", ""))
        if cl_id not in local_by_checklist_id and cl_name != TASKS_CHECKLIST_NAME:
            plan.pull_create_root.append({
                "title": cl_name,
                "trello_checklist_id": cl_id,
            })

    # ── Push phase: Local -> Trello ──────────────────────────────────

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

        # Push items within this checklist
        items_spec = cl_spec.get("items", [])
        if isinstance(items_spec, list):
            for item_spec in items_spec:
                item_todo_id = str(item_spec.get("todo_id", ""))  # type: ignore[union-attr]
                item_todo = todo_map.get(item_todo_id)
                if item_todo is None:
                    continue
                _push_item_diff(
                    plan, item_todo, item_spec, trello_items_by_id,  # type: ignore[arg-type]
                    root_todo.trello_checklist_id,
                )

    # Push items for the "Tasks" catch-all checklist
    # Find if "Tasks" checklist exists in Trello
    tasks_cl_id: str | None = None
    for cl_id, cl in trello_checklists_by_id.items():
        if str(cl.get("name", "")) == TASKS_CHECKLIST_NAME:
            tasks_cl_id = cl_id
            break

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
        _push_item_diff(plan, item_todo, item_spec, trello_items_by_id, tasks_cl_id)

    # Push delete: local items that were deleted but still exist in Trello
    linked_trello_item_ids = {
        t.trello_checklist_item_id for t in todos if t.trello_checklist_item_id
    }
    for item_id in trello_items_by_id:
        if item_id not in linked_trello_item_ids and item_id not in {
            str(pc.get("trello_checklist_item_id", ""))
            for pc in plan.pull_create
        }:
            # Item exists in Trello but not linked locally and not being pulled
            # This means it was deleted locally — push delete
            plan.push_delete_item.append({
                "item_id": item_id,
                "checklist_id": str(trello_items_by_id[item_id].get("_checklist_id", "")),
            })

    return plan


def _push_item_diff(
    plan: TrelloSyncPlan,
    item_todo: Todo,
    item_spec: dict[str, object],
    trello_items_by_id: dict[str, dict[str, Any]],
    checklist_id: str | None,
) -> None:
    """Add push operations for a single checklist item."""
    expected_name = str(item_spec.get("name", ""))
    expected_checked = bool(item_spec.get("checked", False))

    if not item_todo.trello_checklist_item_id:
        # New item to create
        plan.push_create_item.append({
            "todo_id": item_todo.id,
            "name": expected_name,
            "checklist_id": checklist_id,
            "checked": expected_checked,
        })
        return

    trello_item = trello_items_by_id.get(item_todo.trello_checklist_item_id)
    if trello_item is None:
        # Item was deleted in Trello, re-create it
        plan.push_create_item.append({
            "todo_id": item_todo.id,
            "name": expected_name,
            "checklist_id": checklist_id,
            "checked": expected_checked,
        })
        return

    # Check name mismatch
    trello_name = str(trello_item.get("name", ""))
    if trello_name != expected_name:
        plan.push_update_item.append({
            "item_id": item_todo.trello_checklist_item_id,
            "name": expected_name,
            "checklist_id": str(trello_item.get("_checklist_id", "")),
        })

    # Check completion state
    trello_checked = str(trello_item.get("state", "incomplete")) == "complete"
    if expected_checked and not trello_checked:
        plan.push_complete_item.append({
            "item_id": item_todo.trello_checklist_item_id,
            "checklist_id": str(trello_item.get("_checklist_id", "")),
            "state": "complete",
        })


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
    """Strip ID prefix like '1.1: ' from a checklist item name.

    Items are stored as 'ID: title' or 'parentID: childID: title'. This
    strips all leading 'X: ' or 'X.Y: ' segments to recover the actual title.
    """
    # Pattern: one or more "ID: " prefixes (IDs contain digits and dots)
    import re
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
    today = _today()

    counts = {
        "created": 0,
        "created_root": 0,
        "updated": 0,
        "completed": 0,
        "reopened": 0,
        "linked": 0,
    }

    # 1. Create new root todos (from pull_create_root — new checklists)
    for item in data.created_root_locally:
        todo = Todo(
            id=next_todo_id(meta),
            title=str(item.get("title", "")),
            created=today,
            updated=today,
            trello_checklist_id=str(item["trello_checklist_id"]) if item.get("trello_checklist_id") else None,
        )
        todos.append(todo)
        todo_map[todo.id] = todo
        counts["created_root"] += 1

    # 2. Create new child todos (from pull_create — new checklist items)
    for item in data.created_locally:
        parent_id = str(item["parent"]) if item.get("parent") else None
        parent_todo = todo_map.get(parent_id) if parent_id else None
        todo = Todo(
            id=next_todo_id(meta, parent=parent_todo),
            title=str(item.get("title", "")),
            created=today,
            updated=today,
            parent=parent_id,
            trello_checklist_item_id=str(item["trello_checklist_item_id"]) if item.get("trello_checklist_item_id") else None,
            status=TodoStatus.DONE if item.get("checked") else "pending",
        )
        if parent_todo:
            parent_todo.children.append(todo.id)
            parent_todo.updated = today
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
        todo.updated = today
        counts["updated"] += 1

    # 4. Link Trello IDs (after push operations return Trello IDs)
    for item in data.link_trello_ids:
        todo_id = str(item.get("todo_id", ""))
        todo = todo_map.get(todo_id)
        if not todo:
            continue
        if "trello_checklist_id" in item:
            todo.trello_checklist_id = str(item["trello_checklist_id"]) if item.get("trello_checklist_id") else None
        if "trello_checklist_item_id" in item:
            todo.trello_checklist_item_id = str(item["trello_checklist_item_id"]) if item.get("trello_checklist_item_id") else None
        todo.updated = today
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
        todo.updated = today
        counts["completed"] += 1
        # Leaf todos (no parent, no children) get archived
        if not todo.parent and not todo.children:
            to_archive.append(todo)
            for t in todos:
                if todo.id in t.blocks:
                    t.blocks.remove(todo.id)
                    t.updated = today
                if todo.id in t.blocked_by:
                    t.blocked_by.remove(todo.id)
                    t.updated = today

    # 7. Reopen todos
    for raw_todo_id in data.reopened_locally:
        todo = todo_map.get(str(raw_todo_id))
        if not todo or todo.status not in TERMINAL_STATUSES:
            continue
        todo.status = "pending"
        todo.updated = today
        counts["reopened"] += 1

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
            "JSON sync plan with batched operations for both sides. "
            "When auto_apply=True, pull operations (pull_create, pull_update, "
            "pull_complete, pull_reopen, pull_create_root) are applied locally "
            "immediately and the response includes project_info so the caller "
            "can execute push operations via Trello MCP tools."
        )
    )
    def proj_trello_diff(
        trello_card_json: str,
        auto_apply: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, proj_name = result

        plan = compute_diff(trello_card_json, cfg, proj_name)

        if not auto_apply:
            return json.dumps(plan.to_dict(), indent=2)

        # auto_apply mode: apply pull operations server-side
        meta = storage.load_meta(cfg, proj_name)
        response: dict[str, object] = {
            "plan": plan.to_dict(),
            "project_info": {
                "mcp_server": cfg.trello.mcp_server,
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
            "link_trello_card_id. All changes are applied atomically."
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
