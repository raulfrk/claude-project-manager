"""MCP tools for todo management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.enums import MANUAL_TAG, TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import JsonValue, ProjectMeta, ProjConfig, Todo
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_UTC = timezone.utc


def _todo_hook_fields(todo: Todo, meta: ProjectMeta, name: str, *, todos: list[Todo] | None = None) -> dict[str, JsonValue]:
    """Return enriched fields for hook dispatch from a todo and its project metadata."""
    fields: dict[str, JsonValue] = {
        "title": todo.title,
        "priority": todo.priority,
        "tags": todo.tags,
        "notes": todo.notes,
        "due_date": todo.due_date,
        "todoist_task_id": todo.todoist_task_id,
        "trello_card_id": meta.trello_card_id,
        "trello_checklist_id": todo.trello_checklist_id,
        "trello_checklist_item_id": todo.trello_checklist_item_id,
        "jira_issue_key": todo.jira_issue_key,
        "project_name": name,
        "todoist_project_id": meta.todoist_project_id,
    }
    # Resolve parent's Todoist task ID for child todos so hooks can set parentId.
    if todo.parent and todos:
        parent_todo = next((t for t in todos if t.id == todo.parent), None)
        if parent_todo and parent_todo.todoist_task_id:
            fields["parent_todoist_task_id"] = parent_todo.todoist_task_id
        if parent_todo and parent_todo.trello_checklist_id:
            fields["parent_trello_checklist_id"] = parent_todo.trello_checklist_id
    return fields


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string for time precision."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


def _save(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    storage.save_todos(cfg, project_name, todos)


def _collect_family(todo_id: str, todos_list: list[Todo]) -> set[str]:
    """Recursively collect a todo and all its descendants."""
    todo_map = {t.id: t for t in todos_list}
    if todo_id not in todo_map:
        return set()
    family: set[str] = {todo_id}
    for child_id in todo_map[todo_id].children:
        family.update(_collect_family(child_id, todos_list))
    return family


def _complete_leaf(
    cfg: ProjConfig,
    name: str,
    todo: Todo,
    todos: list[Todo],
    today: str,
) -> str:
    """CASE 1: LEAF (no parent, no children) — archive immediately."""
    todo_id = todo.id
    todo.status = TodoStatus.DONE
    todo.updated = today
    remaining = [t for t in todos if t.id != todo_id]
    for t in remaining:
        changed = False
        if todo_id in t.blocks:
            t.blocks.remove(todo_id)
            changed = True
        if todo_id in t.blocked_by:
            t.blocked_by.remove(todo_id)
            changed = True
        if changed:
            t.updated = today
    storage.archive_and_remove_todos(cfg, name, remaining, [todo])
    return json.dumps({"result": f"Archived {todo_id}.", "todo_id": todo_id})


def _complete_child(
    cfg: ProjConfig,
    name: str,
    todo: Todo,
    todos: list[Todo],
    today: str,
) -> str:
    """CASE 2: CHILD (has parent) — mark done, stay in active until parent completes."""
    todo.status = TodoStatus.DONE
    todo.updated = today
    storage.save_todos(cfg, name, todos)
    return json.dumps({"result": f"Marked {todo.id} as done (will archive with parent when parent completes).", "todo_id": todo.id})


def _complete_parent(
    cfg: ProjConfig,
    name: str,
    todo: Todo,
    todos: list[Todo],
    today: str,
) -> str:
    """CASE 3: PARENT (has children) — validate all done, archive whole family atomically."""
    todo_map = {t.id: t for t in todos}
    todo_id = todo.id
    undone = [
        c for c in todo.children
        if (child := todo_map.get(c)) is not None and child.status != TodoStatus.DONE
    ]
    if undone:
        return json.dumps({"error": f"Cannot complete {todo_id}: children not done yet: {', '.join(undone)}."})
    family_ids = _collect_family(todo_id, todos)
    family = [t for t in todos if t.id in family_ids]
    for t in family:
        t.status = TodoStatus.DONE
        t.updated = today
    remaining = [t for t in todos if t.id not in family_ids]
    for t in remaining:
        changed = False
        if any(b in family_ids for b in t.blocks):
            t.blocks = [b for b in t.blocks if b not in family_ids]
            changed = True
        if any(b in family_ids for b in t.blocked_by):
            t.blocked_by = [b for b in t.blocked_by if b not in family_ids]
            changed = True
        if changed:
            t.updated = today
    storage.archive_and_remove_todos(cfg, name, remaining, family)
    return json.dumps({"result": f"Archived {todo_id} and family ({len(family)} todo(s)).", "todo_id": todo_id})


def _filter_todos(
    todos: list[Todo],
    *,
    status: str | None,
    tag: str | None,
    blocked: bool | None,
    limit: int,
    offset: int,
    active_only: bool = False,
) -> list[Todo]:
    """Apply status/tag/blocked filters and pagination to a todo list."""
    if active_only:
        todos = [t for t in todos if t.status in (TodoStatus.PENDING, TodoStatus.IN_PROGRESS)]
    elif status == "open":
        todos = [t for t in todos if t.status not in TERMINAL_STATUSES]
    elif status is not None:
        todos = [t for t in todos if t.status == status]
    if tag:
        todos = [t for t in todos if tag in t.tags]
    if blocked is True:
        todos = [t for t in todos if t.blocked_by]
    elif blocked is False:
        todos = [t for t in todos if not t.blocked_by]
    todos = todos[offset : offset + limit] if limit else todos[offset:]
    return todos


def register(app: FastMCP) -> None:
    """Register todo_add, todo_list, todo_get, todo_update, todo_complete, todo_block, todo_unblock, todo_delete, todo_ready, todo_add_child, todo_batch_add_children, todo_tree, todo_set_content_flag, todo_check_executable, and proj_identify_batches tools with the MCP app."""

    @app.tool(description="Add a new todo to a project.")
    def todo_add(
        title: str,
        priority: str | None = None,
        tags: list[str] | None = None,
        blocked_by: list[str] | None = None,
        parent: str | None = None,
        notes: str = "",
        due_date: str | None = None,
        todoist_task_id: str | None = None,
        trello_checklist_item_id: str | None = None,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        meta = storage.load_meta(cfg, name)
        todos = storage.load_todos(cfg, name)
        today = _now()
        parent_todo = None
        if parent:
            parent_todo = next((t for t in todos if t.id == parent), None)
            if not parent_todo:
                return json.dumps({"error": f"Parent todo '{parent}' not found."})

        if due_date is not None and not due_date.strip():
            return json.dumps({"error": "due_date cannot be empty. Omit it or provide a value (e.g. '2026-03-15' or 'next Friday')."})

        todo = Todo(
            id=next_todo_id(meta, parent=parent_todo),
            title=title,
            priority=priority if priority is not None else cfg.default_priority,
            tags=tags if tags is not None else [],
            blocked_by=blocked_by or [],
            parent=parent,
            notes=notes,
            due_date=due_date,
            todoist_task_id=todoist_task_id,
            trello_checklist_item_id=trello_checklist_item_id,
            created=today,
            updated=today,
        )
        if parent_todo:
            parent_todo.children.append(todo.id)
            parent_todo.updated = today
        todos.append(todo)
        storage.save_todos(cfg, name, todos)
        storage.save_meta(cfg, meta)
        return json.dumps({"result": f"Added todo {todo.id}: {title}", "todo_id": todo.id, **_todo_hook_fields(todo, meta, name, todos=todos)})

    @app.tool(
        description=(
            "List todos for a project, with optional status/tag filters. "
            "status='active' (default) returns pending+in_progress only; "
            "status='open' returns all non-done/non-cancelled todos; "
            "pass status=None to return all statuses including done. "
            "Use limit and offset for pagination (limit=0 means no limit). "
            "Set compact=True for one-line summaries to reduce context usage. "
            "Set max_items>0 to truncate output."
        )
    )
    def todo_list(
        project_name: str | None = None,
        status: str | None = "active",
        tag: str | None = None,
        blocked: bool | None = None,
        limit: int = 0,
        offset: int = 0,
        compact: bool = False,
        max_items: int = 0,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        active_only = status == "active"
        filtered = _filter_todos(
            todos,
            status=None if active_only else status,
            tag=tag,
            blocked=blocked,
            limit=limit,
            offset=offset,
            active_only=active_only,
        )
        if not filtered:
            return "No todos matching filters."
        truncated = 0
        if max_items > 0 and len(filtered) > max_items:
            truncated = len(filtered) - max_items
            filtered = filtered[:max_items]
        if compact:
            lines = []
            for t in filtered:
                tags_str = ",".join(t.tags) if t.tags else ""
                lines.append(f"{t.id} | {t.status} | {t.title} | {t.priority} | {tags_str}")
            if truncated:
                lines.append(f"... {truncated} more items")
            return json.dumps({"result": "\n".join(lines), "truncated": truncated, "count": len(filtered)})
        result_json = json.dumps([t.to_dict() for t in filtered], indent=2)
        if truncated:
            result_json += f"\n... {truncated} more items"
        return result_json

    @app.tool(
        description=(
            "List all todos including archived (active + archive.yaml), with optional filters. "
            "status='open' returns all non-done/non-cancelled todos. "
            "Use limit and offset for pagination (limit=0 means no limit)."
        )
    )
    def todo_list_all(
        project_name: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        blocked: bool | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name) + storage.load_archived_todos(cfg, name)
        filtered = _filter_todos(
            todos,
            status=status,
            tag=tag,
            blocked=blocked,
            limit=limit,
            offset=offset,
        )
        if not filtered:
            return "No todos matching filters."
        return json.dumps([t.to_dict() for t in filtered], indent=2)

    @app.tool(description="Get a single todo by ID.")
    def todo_get(todo_id: str, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            archived = storage.load_archived_todos(cfg, name)
            todo = next((t for t in archived if t.id == todo_id), None)
        if not todo:
            return f"Todo '{todo_id}' not found."
        return json.dumps(todo.to_dict(), indent=2)

    @app.tool(description="Update a todo's fields.")
    def todo_update(
        todo_id: str,
        title: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        todoist_task_id: str | None = None,
        due_date: str | None = None,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return json.dumps({"status": "not_found", "todo_id": todo_id})
        if title is not None:
            todo.title = title
        if status is not None:
            todo.status = status
        if priority is not None:
            todo.priority = priority
        if tags is not None:
            todo.tags = tags
        if notes is not None:
            todo.notes = notes
        if todoist_task_id is not None:
            todo.todoist_task_id = todoist_task_id
        if due_date is not None:
            if not due_date.strip():
                return "due_date cannot be empty. Omit it or provide a value."
            todo.due_date = due_date
        todo.updated = _now()
        meta = storage.load_meta(cfg, name)
        storage.save_todos(cfg, name, todos)
        return json.dumps({"result": f"Updated todo {todo_id}.", "todo_id": todo_id, **_todo_hook_fields(todo, meta, name)})

    @app.tool(description="Mark a todo as done.")
    def todo_complete(todo_id: str, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return f"Todo '{todo_id}' not found."
        today = _now()
        meta = storage.load_meta(cfg, name)

        if todo.parent:
            result_str = _complete_child(cfg, name, todo, todos, today)
        elif todo.children:
            result_str = _complete_parent(cfg, name, todo, todos, today)
        else:
            result_str = _complete_leaf(cfg, name, todo, todos, today)

        result_data = json.loads(result_str)
        result_data.update(_todo_hook_fields(todo, meta, name))
        return json.dumps(result_data)

    @app.tool(description="Revert a completed todo back to pending.")
    def todo_uncomplete(todo_id: str, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            # Check if it's archived
            archived = storage.load_archived_todos(cfg, name)
            if any(t.id == todo_id for t in archived):
                return json.dumps({"error": f"todo {todo_id} is archived — cannot uncomplete"})
            return json.dumps({"error": f"todo {todo_id} not found"})
        status_val = todo.status.value if isinstance(todo.status, TodoStatus) else todo.status
        if status_val != TodoStatus.DONE.value:
            return json.dumps({"error": f"todo {todo_id} is not completed (status: {status_val})"})
        todo.status = TodoStatus.PENDING
        todo.updated = _now()
        meta = storage.load_meta(cfg, name)
        storage.save_todos(cfg, name, todos)
        return json.dumps({"id": todo_id, "status": "pending", **_todo_hook_fields(todo, meta, name)})

    @app.tool(
        description=(
            "Check if a todo is executable (not tagged `manual`). "
            "Returns the todo JSON if executable, or an error message if manual-tagged. "
            "Skills should call this before implementing a todo."
        )
    )
    def todo_check_executable(todo_id: str, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return json.dumps({"error": f"Todo '{todo_id}' not found."})
        if MANUAL_TAG in todo.tags:
            return json.dumps({
                "error": f"⚠️ Todo '{todo_id}' is tagged `manual` — execute it yourself, then run `/proj:todo done {todo_id}`",
                "todo_id": todo_id,
            })
        return json.dumps(todo.to_dict(), indent=2)

    @app.tool(description="Set blocking relationships between todos.")
    def todo_block(
        todo_id: str,
        blocks_ids: list[str],
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo_map = {t.id: t for t in todos}
        blocker = todo_map.get(todo_id)
        if not blocker:
            return json.dumps({"error": f"Todo '{todo_id}' not found."})
        today = _now()
        self_refs = [bid for bid in blocks_ids if bid == todo_id]
        if self_refs:
            return json.dumps({"error": f"Error: todo cannot block itself ('{todo_id}')."})
        for blocked_id in blocks_ids:
            target = todo_map.get(blocked_id)
            if not target:
                continue
            if blocked_id not in blocker.blocks:
                blocker.blocks.append(blocked_id)
            if todo_id not in target.blocked_by:
                target.blocked_by.append(todo_id)
            target.updated = today
        blocker.updated = today
        storage.save_todos(cfg, name, todos)
        return json.dumps({"result": f"{todo_id} now blocks: {', '.join(blocks_ids)}", "todo_id": todo_id})

    @app.tool(description="Remove blocking relationships for a todo.")
    def todo_unblock(todo_id: str, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo_map = {t.id: t for t in todos}
        today = _now()
        todo = todo_map.get(todo_id)
        if not todo:
            return json.dumps({"error": f"Todo '{todo_id}' not found."})
        for blocked_id in todo.blocks:
            target = todo_map.get(blocked_id)
            if target and todo_id in target.blocked_by:
                target.blocked_by.remove(todo_id)
                target.updated = today
        todo.blocks = []
        todo.updated = today
        storage.save_todos(cfg, name, todos)
        return json.dumps({"result": f"Removed all blocking relationships from {todo_id}.", "todo_id": todo_id})

    @app.tool(description="Delete a todo (also cleans up blocks/blocked_by references).")
    def todo_delete(todo_id: str, project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return json.dumps({"error": f"Todo '{todo_id}' not found."})
        meta = storage.load_meta(cfg, name)
        snapshot = _todo_hook_fields(todo, meta, name)
        today = _now()
        # Clean up references
        for t in todos:
            if todo_id in t.blocks:
                t.blocks.remove(todo_id)
                t.updated = today
            if todo_id in t.blocked_by:
                t.blocked_by.remove(todo_id)
                t.updated = today
            if todo_id in t.children:
                t.children.remove(todo_id)
                t.updated = today
        todos = [t for t in todos if t.id != todo_id]
        storage.save_todos(cfg, name, todos)
        return json.dumps({"result": f"Deleted todo {todo_id}.", "todo_id": todo_id, **snapshot})

    @app.tool(
        description=(
            "List todos that are ready to start (pending, no blockers). "
            "Use limit and offset for pagination (limit=0 means no limit)."
        )
    )
    def todo_ready(
        project_name: str | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        ready = _filter_todos(
            todos,
            status=TodoStatus.PENDING,
            tag=None,
            blocked=False,
            limit=limit,
            offset=offset,
        )
        if not ready:
            return "No todos ready to start."
        return json.dumps([t.to_dict() for t in ready], indent=2)

    @app.tool(description="Add a child todo under a parent todo.")
    def todo_add_child(
        parent_id: str,
        title: str,
        priority: str | None = None,
        tags: list[str] | None = None,
        blocked_by: list[str] | None = None,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        meta = storage.load_meta(cfg, name)
        todos = storage.load_todos(cfg, name)
        parent = next((t for t in todos if t.id == parent_id), None)
        if not parent:
            return json.dumps({"error": f"Parent todo '{parent_id}' not found."})
        today = _now()
        child = Todo(
            id=next_todo_id(meta, parent=parent),
            title=title,
            priority=priority or cfg.default_priority,
            tags=tags or [],
            blocked_by=blocked_by or [],
            parent=parent_id,
            created=today,
            updated=today,
        )
        if child.id not in parent.children:
            parent.children.append(child.id)
        parent.updated = today
        todos.append(child)
        storage.save_todos(cfg, name, todos)
        storage.save_meta(cfg, meta)
        return json.dumps({"result": f"Added child todo {child.id} under {parent_id}: {title}", "todo_id": child.id, **_todo_hook_fields(child, meta, name, todos=todos)})

    @app.tool(
        description=(
            "Batch-add multiple children (with optional nesting) under a parent todo. "
            "Accepts a JSON array of child specs and optional blocking pairs. "
            "All children are created atomically in a single save."
        )
    )
    def todo_batch_add_children(
        parent_id: str,
        children: str,
        blocking_pairs: str = "[]",
        project_name: str | None = None,
    ) -> str:
        """Add multiple children under a parent in one atomic operation.

        Parameters
        ----------
        parent_id : str
            ID of the existing parent todo.
        children : str
            JSON array of child specs. Each spec is an object with:
              - title (str, required)
              - priority (str, optional)
              - tags (list[str], optional)
              - notes (str, optional)
              - children (list[spec], optional — nested sub-children)
        blocking_pairs : str
            JSON array of [blocker_idx, blocked_idx] pairs where each index
            refers to the 0-based position in the depth-first flattened list
            of created children.
        project_name : str | None
            Project name override.
        """
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        # --- Validate parent ---
        meta = storage.load_meta(cfg, name)
        todos = storage.load_todos(cfg, name)
        parent = next((t for t in todos if t.id == parent_id), None)
        if not parent:
            return json.dumps({"error": f"Parent todo '{parent_id}' not found."})

        # --- Parse JSON inputs ---
        try:
            child_specs: list[dict[str, JsonValue]] = json.loads(children)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON for children: {exc}"})
        if not isinstance(child_specs, list) or not child_specs:
            return json.dumps({"error": "children must be a non-empty JSON array."})

        try:
            pairs: list[list[int]] = json.loads(blocking_pairs)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON for blocking_pairs: {exc}"})
        if not isinstance(pairs, list):
            return json.dumps({"error": "blocking_pairs must be a JSON array."})

        today = _now()
        created: list[dict[str, str]] = []  # {id, title, parent}

        def _flatten(
            specs: list[dict[str, JsonValue]],
            parent_todo: Todo,
        ) -> None:
            """Depth-first walk: create Todo for each spec, recurse into nested children."""
            for spec in specs:
                title = spec.get("title")
                if not isinstance(title, str) or not title.strip():
                    continue  # skip specs without a valid title
                prio_raw = spec.get("priority")
                priority = str(prio_raw) if isinstance(prio_raw, str) else cfg.default_priority
                tags_raw = spec.get("tags")
                tags = list(tags_raw) if isinstance(tags_raw, list) else []
                notes_raw = spec.get("notes")
                notes = str(notes_raw) if isinstance(notes_raw, str) else ""

                child = Todo(
                    id=next_todo_id(meta, parent=parent_todo),
                    title=title,
                    priority=priority,
                    tags=[str(t) for t in tags],
                    parent=parent_todo.id,
                    notes=notes,
                    created=today,
                    updated=today,
                )
                if child.id not in parent_todo.children:
                    parent_todo.children.append(child.id)
                parent_todo.updated = today
                todos.append(child)
                created.append({"id": child.id, "title": child.title, "parent": parent_todo.id})

                # Recurse into nested children
                nested_raw = spec.get("children")
                if isinstance(nested_raw, list) and nested_raw:
                    _flatten(nested_raw, child)

        _flatten(child_specs, parent)

        # --- Resolve blocking pairs ---
        pair_errors: list[str] = []
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                pair_errors.append(f"Invalid pair (expected [int, int]): {pair}")
                continue
            blocker_idx, blocked_idx = pair
            if not isinstance(blocker_idx, int) or not isinstance(blocked_idx, int):
                pair_errors.append(f"Indices must be integers: {pair}")
                continue
            if blocker_idx < 0 or blocker_idx >= len(created):
                pair_errors.append(f"blocker_idx {blocker_idx} out of range (0..{len(created)-1})")
                continue
            if blocked_idx < 0 or blocked_idx >= len(created):
                pair_errors.append(f"blocked_idx {blocked_idx} out of range (0..{len(created)-1})")
                continue
            if blocker_idx == blocked_idx:
                pair_errors.append(f"Self-blocking not allowed: {pair}")
                continue
            blocker_id = created[blocker_idx]["id"]
            blocked_id = created[blocked_idx]["id"]
            todo_map = {t.id: t for t in todos}
            blocker_todo = todo_map[blocker_id]
            blocked_todo = todo_map[blocked_id]
            if blocked_id not in blocker_todo.blocks:
                blocker_todo.blocks.append(blocked_id)
            if blocker_id not in blocked_todo.blocked_by:
                blocked_todo.blocked_by.append(blocker_id)

        # --- Single atomic save ---
        storage.save_todos(cfg, name, todos)
        storage.save_meta(cfg, meta)

        result_data: dict[str, JsonValue] = {
            "created": created,
            "count": len(created),
        }
        if pair_errors:
            result_data["blocking_errors"] = pair_errors
        return json.dumps(result_data)

    def _has_active_descendant(todo_dict: dict[str, JsonValue]) -> bool:
        """Return True if this node or any descendant has a status other than 'done'."""
        if todo_dict.get("status") != "done":
            return True
        children_raw = todo_dict.get("_children", [])
        if isinstance(children_raw, list):
            for child in children_raw:
                if isinstance(child, dict) and _has_active_descendant(child):
                    return True
        return False

    def _filter_tree_node(todo_dict: dict[str, JsonValue]) -> dict[str, JsonValue] | None:
        """Recursively prune done nodes with no active descendants.

        Returns None if the node should be excluded entirely.
        """
        if todo_dict.get("status") == "done" and not _has_active_descendant(todo_dict):
            return None
        filtered: list[dict[str, JsonValue]] = []
        children_raw = todo_dict.get("_children", [])
        if isinstance(children_raw, list):
            for child in children_raw:
                if isinstance(child, dict):
                    result = _filter_tree_node(child)
                    if result is not None:
                        filtered.append(result)
        out = dict(todo_dict)
        out["_children"] = filtered
        return out

    _STATUS_EMOJI: dict[str, str] = {
        "pending": "\U0001f532",       # 🔲
        "in_progress": "\U0001f504",   # 🔄
        "done": "\u2705",             # ✅
    }

    def _compact_tree_line(node: dict[str, JsonValue], depth: int = 0) -> list[str]:
        """Render a tree node as compact indented lines."""
        indent = "  " * depth
        status = str(node.get("status", "pending"))
        emoji = _STATUS_EMOJI.get(status, "\U0001f532")
        nid = str(node.get("id", ""))
        title = str(node.get("title", ""))[:60]
        priority = str(node.get("priority", "medium"))
        blocked_by = node.get("blocked_by", [])
        blocked_info = ""
        if isinstance(blocked_by, list) and blocked_by:
            blocked_info = f" [blocked by {','.join(str(b) for b in blocked_by)}]"
        line = f"{indent}{emoji} {nid} \u2014 {title} ({priority}){blocked_info}"
        lines = [line]
        children = node.get("_children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    lines.extend(_compact_tree_line(child, depth + 1))
        return lines

    def _count_tree_nodes(roots: list[dict[str, JsonValue]]) -> int:
        """Count total nodes in a tree structure."""
        count = 0
        for node in roots:
            count += 1
            children = node.get("_children", [])
            if isinstance(children, list):
                count += _count_tree_nodes(children)
        return count

    @app.tool(
        description=(
            "Return todos as a tree structure (JSON with nested children). "
            "By default excludes done todos; done parents are kept when they have "
            "non-done descendants. Pass include_done=True to return all todos. "
            "Set compact=True for indented one-line summaries to reduce context usage. "
            "Set max_items>0 to truncate output."
        )
    )
    def todo_tree(
        project_name: str | None = None,
        include_done: bool = False,
        compact: bool = False,
        max_items: int = 0,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        if include_done:
            archived = storage.load_archived_todos(cfg, name)
            todos = todos + archived
        todo_map = {t.id: t.to_dict() for t in todos}
        # Add nested children list
        for t in todos:
            todo_map[t.id]["_children"] = []
        for t in todos:
            if t.parent and t.parent in todo_map:
                children_list = todo_map[t.parent]["_children"]
                if isinstance(children_list, list):
                    children_list.append(todo_map[t.id])
        roots = [todo_map[t.id] for t in todos if t.parent is None]
        if not include_done:
            roots = [r for r in (_filter_tree_node(root) for root in roots) if r is not None]
        # Detect orphaned todos: have a parent ID that no longer exists in todo_map
        orphaned = [
            todo_map[t.id] for t in todos
            if t.parent is not None and t.parent not in todo_map
        ]
        if not include_done:
            orphaned = [o for o in orphaned if _filter_tree_node(o) is not None]
        if orphaned:
            roots.append({"id": "__orphaned__", "title": "⚠️ Orphaned", "_children": orphaned})

        total_nodes = _count_tree_nodes(roots)
        truncated = 0
        if max_items > 0 and total_nodes > max_items:
            truncated = total_nodes - max_items

        if compact:
            lines: list[str] = []
            for root in roots:
                lines.extend(_compact_tree_line(root))
            if max_items > 0 and len(lines) > max_items:
                truncated = len(lines) - max_items
                lines = lines[:max_items]
            if truncated:
                lines.append(f"... {truncated} more items")
            return json.dumps({"result": "\n".join(lines), "truncated": truncated, "count": len(roots)})

        result_json = json.dumps(roots, indent=2)
        if truncated:
            result_json += f"\n... {truncated} more items"
        return result_json

    @app.tool(
        description=(
            "Topological sort of todo IDs by blocked_by graph. "
            "Returns independent parallel batches with cycle detection."
        )
    )
    def proj_identify_batches(
        todo_ids: list[str],
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        all_todos = storage.load_todos(cfg, name)
        todo_map = {t.id: t for t in all_todos}

        # Identify missing IDs
        missing = [tid for tid in todo_ids if tid not in todo_map]
        found_ids = [tid for tid in todo_ids if tid in todo_map]
        requested_set = set(found_ids)

        # Build in-degree map and adjacency list (within requested set only)
        in_degree: dict[str, int] = {tid: 0 for tid in found_ids}
        # adjacency: blocker -> list of todos it unblocks
        adjacency: dict[str, list[str]] = {tid: [] for tid in found_ids}

        for tid in found_ids:
            todo = todo_map[tid]
            for blocker_id in todo.blocked_by:
                if blocker_id in requested_set:
                    in_degree[tid] += 1
                    adjacency[blocker_id].append(tid)

        # Kahn's algorithm — BFS level by level
        from collections import deque

        queue: deque[str] = deque(tid for tid in found_ids if in_degree[tid] == 0)
        batches: list[list[str]] = []
        visited_count = 0

        while queue:
            batch = sorted(queue)  # sort for deterministic output
            batches.append(batch)
            visited_count += len(batch)
            queue.clear()
            next_level: list[str] = []
            for tid in batch:
                for dependent in adjacency[tid]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_level.append(dependent)
            queue.extend(next_level)

        # Detect cycles — any unvisited nodes remain
        cycles: list[str] = []
        if visited_count < len(found_ids):
            cycle_nodes = {tid for tid in found_ids if in_degree[tid] > 0}
            # Build cycle descriptions by tracing each cycle node
            reported: set[str] = set()
            for start in sorted(cycle_nodes):
                if start in reported:
                    continue
                # Trace a cycle path starting from `start`
                path: list[str] = []
                visited_trace: set[str] = set()
                node = start
                while node not in visited_trace and node in cycle_nodes:
                    path.append(node)
                    visited_trace.add(node)
                    # Follow first blocker that is also in cycle_nodes
                    nexts = [
                        b
                        for b in todo_map[node].blocked_by
                        if b in cycle_nodes and b in requested_set
                    ]
                    node = nexts[0] if nexts else node
                    if node == start or node not in cycle_nodes:
                        break
                path.append(start)  # close the cycle
                # Mark all nodes in path as reported
                for n in path:
                    reported.add(n)
                cycle_desc = " → ".join(path)
                cycles.append(cycle_desc)

        order = [tid for batch in batches for tid in batch]
        return json.dumps(
            {"batches": batches, "order": order, "cycles": cycles, "missing": missing}
        )

    @app.tool(description="Mark has_requirements or has_research flags on a todo. Idempotent.")
    def todo_set_content_flag(
        todo_id: str,
        has_requirements: bool | None = None,
        has_research: bool | None = None,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return json.dumps({"error": f"Todo '{todo_id}' not found."})
        if has_requirements is not None:
            todo.has_requirements = has_requirements
        if has_research is not None:
            todo.has_research = has_research
        todo.updated = _now()
        storage.save_todos(cfg, name, todos)
        return json.dumps({"result": f"Updated content flags for {todo_id}.", "todo_id": todo_id})

    @app.tool(description="Find archived todos by title using fuzzy matching.")
    def proj_find_archived_by_title(
        title: str,
        threshold: float = 0.7,
        project_name: str | None = None,
    ) -> str:
        """
        Search archived todos by title using exact and fuzzy matching.

        Returns JSON:
        {
            "exact_match": {"id": str, "title": str} | null,
            "fuzzy_matches": [{"id": str, "title": str, "ratio": float}],
            "count": int
        }
        """
        import difflib

        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        archived = storage.load_archived_todos(cfg, name)
        if not archived:
            return json.dumps({"exact_match": None, "fuzzy_matches": [], "count": 0})

        # 1. Exact match (case-insensitive)
        exact = next((t for t in archived if t.title.lower() == title.lower()), None)
        if exact:
            return json.dumps(
                {
                    "exact_match": {"id": exact.id, "title": exact.title},
                    "fuzzy_matches": [],
                    "count": 1,
                }
            )

        # 2. Fuzzy match
        titles = [t.title for t in archived]
        close = difflib.get_close_matches(title, titles, n=5, cutoff=threshold)
        fuzzy: list[dict[str, JsonValue]] = []
        for match_title in close:
            todo = next(t for t in archived if t.title == match_title)
            ratio = difflib.SequenceMatcher(None, title.lower(), match_title.lower()).ratio()
            fuzzy.append({"id": todo.id, "title": todo.title, "ratio": round(ratio, 3)})
        fuzzy.sort(key=lambda x: float(x["ratio"]) if isinstance(x["ratio"], (int, float)) else 0.0, reverse=True)
        return json.dumps({"exact_match": None, "fuzzy_matches": fuzzy, "count": len(fuzzy)})
