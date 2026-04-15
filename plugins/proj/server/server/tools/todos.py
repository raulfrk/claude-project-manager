"""MCP tools for todo management."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import JsonValue, ProjConfig, ProjectMeta, Todo
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_UTC = UTC
logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    """Collapse whitespace and lowercase for dedup comparison."""
    return " ".join(title.split()).lower()


# Module-level lock serializes batch completions across threads. Acquired
# BEFORE the Phase 2 loop and released after, so concurrent batches with
# overlapping parents cannot interleave saves and produce a partial family
# archive.
_BATCH_COMPLETE_LOCK = threading.Lock()

# ── Trello list ID resolution (cached per board) ──────────────────────────────

_trello_board_lists_cache: dict[str, list[dict[str, JsonValue]]] = {}


def _resolve_trello_socket() -> str:
    """Read Trello plugin socket path from registry, fall back to legacy."""
    registry_file = Path.home() / ".claude" / "sockets" / "trello"
    try:
        path = registry_file.read_text().strip()
        if path and Path(path).exists():
            return path
    except (FileNotFoundError, OSError):
        pass
    import tempfile

    _tmp = tempfile.gettempdir()
    candidates = sorted(
        Path(_tmp).glob("claude-cpm-trello-*.sock"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return str(candidates[0])
    return str(Path(_tmp) / "claude-cpm-trello.sock")


def _get_board_lists(board_id: str) -> list[dict[str, JsonValue]]:
    """Fetch board lists from Trello, with in-process cache."""
    if board_id in _trello_board_lists_cache:
        return _trello_board_lists_cache[board_id]
    try:
        import httpx

        sock_path = _resolve_trello_socket()
        transport = httpx.HTTPTransport(uds=sock_path)
        with httpx.Client(transport=transport, timeout=10.0) as client:
            resp = client.post(
                "http://localhost/hook",
                json={"tool": "get_lists", "params": {"board_id": board_id}},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "result" in data:
                result = data["result"]
                if isinstance(result, str):
                    result = json.loads(result)
                if isinstance(result, list):
                    _trello_board_lists_cache[board_id] = result
                    return result
            if isinstance(data, list):
                _trello_board_lists_cache[board_id] = data
                return data
    except Exception:
        logger.debug("Failed to fetch Trello board lists for %s", board_id, exc_info=True)
    return []


def _resolve_list_id(board_id: str, list_name: str) -> str:
    """Resolve a Trello list name to its ID on the given board."""
    if not board_id or not list_name:
        return ""
    board_lists = _get_board_lists(board_id)
    for lst in board_lists:
        if not isinstance(lst, dict):
            continue
        if lst.get("name") == list_name or lst.get("id") == list_name:
            return str(lst.get("id", ""))
    return ""


def _resolve_trello_list_ids(cfg: ProjConfig) -> dict[str, str]:
    """Resolve all configured Trello list names to IDs.

    Returns a dict of {role: list_id} e.g. {"tasks": "abc123", "done": "def456"}.
    Only resolves when Trello sync is enabled and a board is configured.
    """
    if not cfg.trello.enabled or not cfg.trello.default_board_id:
        return {}
    board_id = cfg.trello.default_board_id
    mappings = cfg.trello.list_mappings
    result: dict[str, str] = {}
    for role, name in [
        ("tasks", mappings.tasks),
        ("done", mappings.done),
        ("projects", mappings.projects),
        ("default", cfg.trello.default_list),
        ("archived", mappings.archived),
    ]:
        if name:
            lid = _resolve_list_id(board_id, name)
            if lid:
                result[role] = lid
    return result


def _enrich_trello_dict(
    trello_dict: dict[str, JsonValue],
    trello_list_ids: dict[str, str],
) -> dict[str, JsonValue]:
    """Overwrite list_mappings names with resolved IDs and add default_list_id."""
    lm = trello_dict.get("list_mappings")
    if isinstance(lm, dict):
        for role, lid in trello_list_ids.items():
            if role in lm:
                lm[role] = lid
    if "default" in trello_list_ids:
        trello_dict["default_list_id"] = trello_list_ids["default"]
    return trello_dict


def _todo_hook_fields(
    todo: Todo,
    meta: ProjectMeta,
    name: str,
    *,
    todos: list[Todo] | None = None,
    cfg: ProjConfig | None = None,
) -> dict[str, JsonValue]:
    """Return enriched fields for hook dispatch from a todo and its project metadata."""
    fields: dict[str, JsonValue] = {
        "title": todo.title,
        "priority": todo.priority,
        "tags": todo.tags,
        "notes": todo.notes,
        "due_date": todo.due_date,
        "todoist_task_id": todo.todoist_task_id,
        "trello_project_card_id": meta.trello_card_id,
        "trello_card_id": todo.trello_card_id,
        "jira_issue_key": todo.jira_issue_key,
        "jira_project_key": meta.jira_issue_key.split("-")[0] if meta.jira_issue_key else None,
        "project_name": name,
        "todoist_project_id": meta.todoist_project_id,
    }
    # Resolve parent's Todoist task ID for child todos so hooks can set parentId.
    if todo.parent and todos:
        parent_todo = next((t for t in todos if t.id == todo.parent), None)
        if parent_todo and parent_todo.todoist_task_id:
            fields["parent_todoist_task_id"] = parent_todo.todoist_task_id
        if parent_todo and parent_todo.trello_card_id:
            fields["parent_trello_card_id"] = parent_todo.trello_card_id
        if parent_todo and parent_todo.trello_checklist_id:
            fields["parent_trello_checklist_id"] = parent_todo.trello_checklist_id
    # Inject sync config and resolved list IDs so hooks can use direct Trello tools.
    # The list_mappings values are overwritten with resolved IDs (instead of names)
    # so ${sync.trello.list_mappings.done} etc. resolve to actual Trello list IDs.
    if cfg is not None:
        trello_list_ids = _resolve_trello_list_ids(cfg)
        trello_dict = _enrich_trello_dict(cfg.trello.to_dict(), trello_list_ids)
        fields["sync"] = {
            "trello": trello_dict,
            "todoist": cfg.todoist.to_dict(),
        }
        # Top-level convenience fields for hook param_mapping
        fields["trello_list_id"] = trello_list_ids.get("tasks", "")
        fields["trello_done_list_id"] = trello_list_ids.get("done", "")
        fields["trello_projects_list_id"] = trello_list_ids.get("projects", "")
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
    return json.dumps(
        {
            "result": f"Marked {todo.id} as done (will archive with parent when parent completes).",
            "todo_id": todo.id,
        }
    )


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
        c
        for c in todo.children
        if (child := todo_map.get(c)) is not None and child.status != TodoStatus.DONE
    ]
    if undone:
        return json.dumps(
            {"error": f"Cannot complete {todo_id}: children not done yet: {', '.join(undone)}."}
        )
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
    return json.dumps(
        {"result": f"Archived {todo_id} and family ({len(family)} todo(s)).", "todo_id": todo_id}
    )


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


def todo_export_yaml(project_name: str | None = None) -> str:
    """Export project data from SQLite back to YAML files.

    Use for emergency recovery, debugging, or forcing a git-committable snapshot.
    Exports: todos.yaml, archive.yaml, meta.yaml, decisions.yaml

    Returns a JSON string listing the paths written and counts.
    """
    from server.lib.migration import export_sqlite_to_yaml

    cfg = storage.load_config()
    result = require_project(project_name)
    if isinstance(result, str):
        return result
    cfg, name = result
    try:
        paths = export_sqlite_to_yaml(cfg, name)
        return json.dumps(
            {
                "exported": [str(p) for p in paths],
                "project": name,
                "message": f"Exported {len(paths)} files to {storage.tracking_dir(cfg, name)}",
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e), "project": name})


def _batch_add_children(
    cfg: ProjConfig,
    name: str,
    parent_todo: Todo,
    child_specs: list[dict[str, JsonValue]],
    blocking_pairs: list[list[int]],
    today: str,
    todos: list[Todo],
    meta: ProjectMeta,
) -> str:
    """Core batch-add logic: create child todos under parent_todo atomically.

    Returns JSON result string. Caller must ensure todos/meta are already loaded.
    This function mutates todos and meta in place and performs the atomic save.
    """
    created: list[dict[str, str]] = []
    skipped_duplicates: list[str] = []
    _batch_titles: dict[str, set[str]] = {}

    def _flatten(
        specs: list[dict[str, JsonValue]],
        parent: Todo,
    ) -> None:
        for spec in specs:
            title = spec.get("title")
            if not isinstance(title, str) or not title.strip():
                continue

            norm_title = _normalize_title(title)
            existing_siblings = [
                t for t in todos if t.parent == parent.id and t.status not in ("done", "cancelled")
            ]
            existing_match = next(
                (t for t in existing_siblings if _normalize_title(t.title) == norm_title),
                None,
            )
            if existing_match:
                skipped_duplicates.append(f"{title} (exists: {existing_match.id})")
                continue
            batch_key = parent.id
            if batch_key not in _batch_titles:
                _batch_titles[batch_key] = set()
            if norm_title in _batch_titles[batch_key]:
                skipped_duplicates.append(f"{title} (duplicate in batch)")
                continue
            _batch_titles[batch_key].add(norm_title)

            prio_raw = spec.get("priority")
            priority = str(prio_raw) if isinstance(prio_raw, str) else cfg.default_priority
            tags_raw = spec.get("tags")
            tags = list(tags_raw) if isinstance(tags_raw, list) else []
            notes_raw = spec.get("notes")
            notes = str(notes_raw) if isinstance(notes_raw, str) else ""

            child = Todo(
                id=next_todo_id(meta, parent=parent),
                title=title,
                priority=priority,
                tags=[str(t) for t in tags],
                parent=parent.id,
                notes=notes,
                created=today,
                updated=today,
            )
            if child.id not in parent.children:
                parent.children.append(child.id)
            parent.updated = today
            todos.append(child)
            created.append({"id": child.id, "title": child.title, "parent": parent.id})

            nested_raw = spec.get("children")
            if isinstance(nested_raw, list) and nested_raw:
                _flatten([x for x in nested_raw if isinstance(x, dict)], child)

    _flatten(child_specs, parent_todo)

    # Resolve blocking pairs
    pair_errors: list[str] = []
    todo_map = {t.id: t for t in todos}
    for pair in blocking_pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            pair_errors.append(f"Invalid pair (expected [int, int]): {pair}")
            continue
        blocker_idx, blocked_idx = pair
        if not isinstance(blocker_idx, int) or not isinstance(blocked_idx, int):
            pair_errors.append(f"Indices must be integers: {pair}")
            continue
        if blocker_idx < 0 or blocker_idx >= len(created):
            pair_errors.append(f"blocker_idx {blocker_idx} out of range (0..{len(created) - 1})")
            continue
        if blocked_idx < 0 or blocked_idx >= len(created):
            pair_errors.append(f"blocked_idx {blocked_idx} out of range (0..{len(created) - 1})")
            continue
        if blocker_idx == blocked_idx:
            pair_errors.append(f"Self-blocking not allowed: {pair}")
            continue
        blocker_id = created[blocker_idx]["id"]
        blocked_id = created[blocked_idx]["id"]
        blocker_todo = todo_map[blocker_id]
        blocked_todo = todo_map[blocked_id]
        if blocked_id not in blocker_todo.blocks:
            blocker_todo.blocks.append(blocked_id)
        if blocker_id not in blocked_todo.blocked_by:
            blocked_todo.blocked_by.append(blocker_id)

    # Single atomic save
    storage.save_todos(cfg, name, todos)
    storage.save_meta(cfg, meta)

    # Build todoist_tasks for hook-053 param mapping
    created_index: dict[str, int] = {c["id"]: i for i, c in enumerate(created)}
    todoist_tasks: list[dict[str, JsonValue]] = []
    for c in created:
        if c["parent"] == parent_todo.id:
            todoist_tasks.append(
                {
                    "content": c["title"],
                    "projectId": meta.todoist_project_id,
                    "parentId": parent_todo.todoist_task_id,
                    "_parent_index": -1,
                    "_local_id": c["id"],
                }
            )
        else:
            todoist_tasks.append(
                {
                    "content": c["title"],
                    "projectId": meta.todoist_project_id,
                    "_parent_index": created_index[c["parent"]],
                    "_local_id": c["id"],
                }
            )
    # Resolve Trello list IDs for hook dispatch
    trello_list_ids = _resolve_trello_list_ids(cfg)
    trello_dict = _enrich_trello_dict(cfg.trello.to_dict(), trello_list_ids)
    tasks_list_id = trello_list_ids.get("tasks", "")

    trello_batch_cards: list[dict[str, str]] = []
    if tasks_list_id:
        for c in created:
            trello_batch_cards.append({"list_id": tasks_list_id, "name": c["title"]})

    # Also expose created_ids for convenient access
    created_ids = [c["id"] for c in created]

    result_data: dict[str, JsonValue] = {
        "created": created,
        "created_ids": created_ids,
        "count": len(created),
        "project_name": name,
        "todoist_project_id": meta.todoist_project_id,
        "trello_project_card_id": meta.trello_card_id,
        "trello_card_id": parent_todo.trello_card_id,
        "parent_todoist_task_id": parent_todo.todoist_task_id,
        "todoist_tasks": todoist_tasks,
        "trello_batch_cards": trello_batch_cards,
        "sync": {
            "trello": trello_dict,
            "todoist": cfg.todoist.to_dict(),
        },
    }
    if pair_errors:
        result_data["blocking_errors"] = pair_errors
    if skipped_duplicates:
        result_data["skipped_duplicates"] = skipped_duplicates
    return json.dumps(result_data)


def register(app: FastMCP) -> None:
    """Register todo management tools with the MCP app.

    Registers todo_add, todo_list, todo_get, todo_update,
    todo_complete, todo_delete, todo_ready,
    todo_tree, todo_set_content_flag,
    proj_identify_batches, todo_analyze_graph, and
    proj_find_archived_by_title.
    """

    @app.tool(
        description=(
            "Add a new todo to a project. "
            "Pass children= (JSON array of child specs) to batch-add children atomically. "
            "Children-only mode: omit title and pass parent= + children= to add children to an "
            "existing parent without creating a new root todo. "
            "blocking_pairs= is a JSON array of [blocker_idx, blocked_idx] pairs (0-based, "
            "depth-first) to set blocking relationships among the created children."
        )
    )
    def todo_add(
        title: str = "",
        priority: str | None = None,
        tags: list[str] | None = None,
        blocked_by: list[str] | None = None,
        parent: str | None = None,
        notes: str = "",
        due_date: str | None = None,
        todoist_task_id: str | None = None,
        project_name: str | None = None,
        force_create: bool = False,
        children: str = "[]",
        blocking_pairs: str = "[]",
    ) -> str:
        _child_specs_raw = children.strip() if children and children.strip() != "[]" else "[]"
        _bp_raw = blocking_pairs.strip() if blocking_pairs else "[]"

        # Children-only mode: no title, add children to existing parent
        if not title or not title.strip():
            if parent:
                result = require_project(project_name)
                if isinstance(result, str):
                    return result
                cfg, name = result
                meta = storage.load_meta(cfg, name)
                todos = storage.load_todos(cfg, name)
                today = _now()
                _parent_todo = next((t for t in todos if t.id == parent), None)
                if not _parent_todo:
                    return json.dumps({"error": f"Parent todo '{parent}' not found."})
                try:
                    _specs = json.loads(_child_specs_raw)
                except json.JSONDecodeError as e:
                    return json.dumps({"error": f"Invalid JSON for children: {e}"})
                if not isinstance(_specs, list) or not _specs:
                    return json.dumps({"error": "children must be a non-empty JSON array."})
                try:
                    _bp = json.loads(_bp_raw)
                except json.JSONDecodeError as e:
                    return json.dumps({"error": f"Invalid JSON for blocking_pairs: {e}"})
                return _batch_add_children(cfg, name, _parent_todo, _specs, _bp, today, todos, meta)
            return json.dumps({"error": "title is required when not using children-only mode."})

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
            return json.dumps(
                {
                    "error": (
                        "due_date cannot be empty. Omit it or"
                        " provide a value (e.g. '2026-03-15'"
                        " or 'next Friday')."
                    )
                }
            )
        if due_date is not None and due_date.strip():
            import re as _re

            if not _re.match(r"^\d{4}-\d{2}-\d{2}$", due_date.strip()):
                return json.dumps(
                    {
                        "error": (
                            f"due_date must be YYYY-MM-DD format, got '{due_date}'. "
                            "Example: '2026-03-15'."
                        )
                    }
                )

        # Dedup guard: reject if same normalized title exists under same parent
        if not force_create:
            norm_title = _normalize_title(title)
            scope_todos = [
                t for t in todos if t.parent == parent and t.status not in ("done", "cancelled")
            ]
            existing = next(
                (t for t in scope_todos if _normalize_title(t.title) == norm_title),
                None,
            )
            if existing:
                return json.dumps(
                    {
                        "error": f"Todo with same title already exists: {existing.id}",
                        "existing_id": existing.id,
                    }
                )

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
            created=today,
            updated=today,
        )
        if parent_todo:
            parent_todo.children.append(todo.id)
            parent_todo.updated = today
        todos.append(todo)

        # If children specified, batch-add them under the newly created todo
        if _child_specs_raw != "[]":
            try:
                _specs = json.loads(_child_specs_raw)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid children JSON: {e}"})
            if isinstance(_specs, list) and _specs:
                try:
                    _bp = json.loads(_bp_raw)
                except json.JSONDecodeError as e:
                    return json.dumps({"error": f"Invalid blocking_pairs JSON: {e}"})
                # Pass in-memory todos/meta (already contain root todo) — single atomic save
                batch_result_str = _batch_add_children(
                    cfg, name, todo, _specs, _bp, today, todos, meta
                )
                batch_data = json.loads(batch_result_str)
                return json.dumps(
                    {
                        "result": f"Added todo {todo.id}: {title}",
                        "todo_id": todo.id,
                        **_todo_hook_fields(todo, meta, name, todos=todos, cfg=cfg),
                        "children_result": batch_data,
                    }
                )

        storage.save_todos(cfg, name, todos)
        storage.save_meta(cfg, meta)
        return json.dumps(
            {
                "result": f"Added todo {todo.id}: {title}",
                "todo_id": todo.id,
                **_todo_hook_fields(todo, meta, name, todos=todos, cfg=cfg),
            }
        )

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
            return json.dumps(
                {"result": "\n".join(lines), "truncated": truncated, "count": len(filtered)}
            )
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

    @app.tool(
        description=(
            "Update a todo's fields. Pass blocked_by_set to replace the full list of "
            "todos that block this one (use [] to clear all blockers)."
        )
    )
    def todo_update(
        todo_id: str,
        title: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        todoist_task_id: str | None = None,
        due_date: str | None = None,
        blocked_by_set: list[str] | None = None,
        project_name: str | None = None,
        skip_hooks: bool = False,
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
        if blocked_by_set is not None:
            todo_map = {t.id: t for t in todos}
            # Validate all blocker IDs exist
            unknown = [bid for bid in blocked_by_set if bid not in todo_map]
            if unknown:
                return json.dumps({"error": f"Unknown blocker IDs: {unknown}"})
            # Self-blocking guard
            if todo_id in blocked_by_set:
                return json.dumps({"error": f"Todo cannot block itself: {todo_id}"})
            today = _now()
            # Remove this todo from blocks lists of currently blocking todos
            for blocker_id in todo.blocked_by:
                blocker = todo_map.get(blocker_id)
                if blocker and todo_id in blocker.blocks:
                    blocker.blocks.remove(todo_id)
                    blocker.updated = today
            # Set new blocked_by list
            todo.blocked_by = list(blocked_by_set)
            # Add this todo to blocks lists of new blockers
            for blocker_id in blocked_by_set:
                blocker = todo_map.get(blocker_id)
                if blocker and todo_id not in blocker.blocks:
                    blocker.blocks.append(todo_id)
                    blocker.updated = today
        todo.updated = _now()
        meta = storage.load_meta(cfg, name)
        storage.save_todos(cfg, name, todos)

        # Scope guard: only honour skip_hooks when the update contains
        # exclusively sync-ID fields (no real user-facing fields changed).
        _non_sync_fields_present = any(
            v is not None for v in (title, status, priority, tags, notes, due_date)
        )
        honour_skip = skip_hooks and not _non_sync_fields_present

        result_dict: dict[str, JsonValue] = {
            "result": f"Updated todo {todo_id}.",
            "todo_id": todo_id,
            **_todo_hook_fields(todo, meta, name, todos=todos, cfg=cfg),
        }
        if honour_skip:
            result_dict["_skip_hooks"] = True
        return json.dumps(result_dict)

    def _batch_complete(
        todo_ids: list[str],
        note: str,
        project_name: str | None,
    ) -> str:
        _ = note  # reserved for future completion-note annotation
        # ── Phase 0 — empty check ──────────────────────────────────────────
        if not todo_ids:
            return json.dumps(
                {
                    "error": "todo_ids cannot be empty.",
                    "completed_ids": [],
                    "skipped_ids": [],
                    "invalid_ids": [],
                }
            )

        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        # ── Phase 1a — cross-project detection BEFORE dedupe ─────────────
        # Scan the project index for any id that lives in a different
        # project. Cross-project batches are not allowed.
        cross_project_ids: list[str] = []
        try:
            index = storage.load_index(cfg)
            for other_name in index.projects:
                if other_name == name:
                    continue
                try:
                    other_todos = storage.load_todos(cfg, other_name)
                except FileNotFoundError:
                    continue
                other_ids = {t.id for t in other_todos}
                for tid in todo_ids:
                    if tid in other_ids and tid not in cross_project_ids:
                        cross_project_ids.append(tid)
        except Exception:
            logger.debug("Cross-project scan failed", exc_info=True)
        if cross_project_ids:
            return json.dumps(
                {
                    "error": "Cross-project batch not allowed.",
                    "invalid_ids": cross_project_ids,
                    "completed_ids": [],
                    "skipped_ids": [],
                }
            )

        # ── Phase 1b — order-preserving dedupe ────────────────────────────
        deduped_ids: list[str] = list(dict.fromkeys(todo_ids))

        # ── Phase 1c — existence + status validation ──────────────────────
        todos = storage.load_todos(cfg, name)
        todo_map = {t.id: t for t in todos}
        invalid_ids: list[str] = []
        cancelled_ids: list[str] = []
        skipped_ids: list[str] = []
        to_complete: list[str] = []
        for tid in deduped_ids:
            todo = todo_map.get(tid)
            if todo is None:
                invalid_ids.append(tid)
                continue
            status_val = todo.status.value if isinstance(todo.status, TodoStatus) else todo.status
            if status_val == "cancelled":
                cancelled_ids.append(tid)
                continue
            if status_val == TodoStatus.DONE.value:
                skipped_ids.append(tid)
                continue
            to_complete.append(tid)

        if invalid_ids or cancelled_ids:
            return json.dumps(
                {
                    "error": "Validation failed.",
                    "invalid_ids": invalid_ids,
                    "cancelled_ids": cancelled_ids,
                    "reason": (
                        "missing ids" if invalid_ids else "cancelled todos cannot be completed"
                    ),
                    "completed_ids": [],
                    "skipped_ids": skipped_ids,
                }
            )

        # ── Phase 2 — sequenced save+archive under lock ───────────────────
        # Acquire the module-level threading.Lock BEFORE the loop so
        # concurrent batches with overlapping parents cannot interleave.
        today = _now()
        completed_ids: list[str] = []
        archive_family_ids: set[str] = set()
        # Captured while holding the lock, used post-lock for Phase 3/4.
        todoist_task_ids: list[str] = []
        trello_card_ids: list[str] = []
        jira_issue_keys: list[str] = []

        with _BATCH_COMPLETE_LOCK:
            # Phase 2a: fcntl.flock around the todos.yaml file for
            # cross-process safety. Non-blocking to surface contention
            # as an error rather than hang.
            todos_file = storage.todos_path(cfg, name)
            try:
                todos_file.parent.mkdir(parents=True, exist_ok=True)
                todos_file.touch(exist_ok=True)
                lock_fd = todos_file.open("r+b")
            except OSError as exc:
                return json.dumps(
                    {
                        "error": f"Failed to open todos.yaml for locking: {exc}",
                        "completed_ids": [],
                        "skipped_ids": skipped_ids,
                    }
                )
            try:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return json.dumps(
                        {
                            "error": (
                                "Another todos.yaml writer holds the file lock. Retry shortly."
                            ),
                            "completed_ids": [],
                            "skipped_ids": skipped_ids,
                        }
                    )

                # Re-load todos under the lock to guarantee latest state.
                todos = storage.load_todos(cfg, name)
                todo_map = {t.id: t for t in todos}

                # Re-validate — state may have changed since Phase 1c.
                still_to_complete: list[str] = []
                for tid in to_complete:
                    todo = todo_map.get(tid)
                    if todo is None:
                        invalid_ids.append(tid)
                        continue
                    status_val = (
                        todo.status.value if isinstance(todo.status, TodoStatus) else todo.status
                    )
                    if status_val == TodoStatus.DONE.value:
                        if tid not in skipped_ids:
                            skipped_ids.append(tid)
                        continue
                    if status_val == "cancelled":
                        cancelled_ids.append(tid)
                        continue
                    still_to_complete.append(tid)

                if invalid_ids or cancelled_ids:
                    return json.dumps(
                        {
                            "error": "Validation failed under lock.",
                            "invalid_ids": invalid_ids,
                            "cancelled_ids": cancelled_ids,
                            "completed_ids": [],
                            "skipped_ids": skipped_ids,
                        }
                    )

                # In-memory Phase 2 loop: mark each id done and, for leaves
                # or fully-done parents, schedule family archive. Parents
                # with pending children stay in the active list (match
                # _complete_child behavior).
                for tid in still_to_complete:
                    todo = todo_map[tid]
                    todo.status = TodoStatus.DONE
                    todo.updated = today
                    completed_ids.append(tid)
                    if todo.todoist_task_id:
                        todoist_task_ids.append(todo.todoist_task_id)
                    if todo.trello_card_id:
                        trello_card_ids.append(todo.trello_card_id)
                    if todo.jira_issue_key:
                        jira_issue_keys.append(todo.jira_issue_key)

                # Second pass: evaluate archival.
                # - Leaf (no children, no parent): archive this todo alone.
                # - Child (has parent): stay active; parent archives later.
                # - Parent (has children): if EVERY descendant across the
                #   full subtree is done, archive the whole family.
                def _all_descendants_done(root_id: str) -> bool:
                    root = todo_map.get(root_id)
                    if root is None:
                        return False
                    status_val = (
                        root.status.value if isinstance(root.status, TodoStatus) else root.status
                    )
                    if status_val != TodoStatus.DONE.value:
                        return False
                    return all(_all_descendants_done(c) for c in root.children)

                for tid in completed_ids:
                    todo = todo_map[tid]
                    if todo.parent is None and not todo.children:
                        # Leaf with no parent — archive this todo alone.
                        archive_family_ids.add(tid)
                        continue
                    if todo.children and _all_descendants_done(tid):
                        # Parent whose full subtree is now done — archive
                        # the family.
                        archive_family_ids.update(_collect_family(tid, todos))
                    # A child (has parent) is marked done but stays in the
                    # active list until its parent's family archives.
                    # After marking children, also walk up the parent chain
                    # to archive any newly-complete parent families.
                    cur = todo.parent
                    while cur:
                        parent_todo = todo_map.get(cur)
                        if parent_todo is None:
                            break
                        if (
                            _all_descendants_done(cur)
                            and (
                                parent_todo.status.value
                                if isinstance(parent_todo.status, TodoStatus)
                                else parent_todo.status
                            )
                            == TodoStatus.DONE.value
                        ):
                            archive_family_ids.update(_collect_family(cur, todos))
                        cur = parent_todo.parent

                # Build remaining + to_archive lists.
                to_archive = [t for t in todos if t.id in archive_family_ids]
                remaining = [t for t in todos if t.id not in archive_family_ids]

                # Clean up blocks/blocked_by references to archived ids.
                for t in remaining:
                    changed = False
                    if any(b in archive_family_ids for b in t.blocks):
                        t.blocks = [b for b in t.blocks if b not in archive_family_ids]
                        changed = True
                    if any(b in archive_family_ids for b in t.blocked_by):
                        t.blocked_by = [b for b in t.blocked_by if b not in archive_family_ids]
                        changed = True
                    if changed:
                        t.updated = today

                # Phase 2a atomic save: single write at end of the loop.
                if to_archive:
                    storage.archive_and_remove_todos(cfg, name, remaining, to_archive)
                else:
                    storage.save_todos(cfg, name, remaining)
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()

        # ── Phase 3 — pre-enriched payload ────────────────────────────────
        # Build the enriched source payload for hook dispatch. Include both
        # plural and singular keys: plural lists feed batch hook param
        # mappings (ids/card_ids/updates_json), singular keys feed condition
        # evaluation in router_fire_tool (belt-and-braces).
        try:
            meta = storage.load_meta(cfg, name)
        except FileNotFoundError:
            meta = None

        todoist_project_id_val = meta.todoist_project_id if meta is not None else None
        trello_card_id_val = meta.trello_card_id if meta is not None else None
        jira_project_key_val = (
            meta.jira_issue_key.split("-")[0] if meta is not None and meta.jira_issue_key else None
        )

        # Pre-build full Jira bulk-update JSON string because the hook
        # template engine cannot iterate lists. Hooks map
        # updates_json: ${jira_updates_json} and get the native string.
        jira_payload: dict[str, JsonValue] = {
            "updates": [
                {"key": key, "fields": {"resolution": {"name": "Done"}}} for key in jira_issue_keys
            ]
        }
        jira_updates_json: str = json.dumps(jira_payload, ensure_ascii=True)

        # Phase 3a — 90KB whole-field truncation. Estimate payload size and
        # drop whole fields (never mid-string) if over the threshold, so
        # downstream parsers never see sliced JSON.
        # Cap the JSON payload returned to the model at 90 KB to prevent
        # exceeding MCP message-size limits on large batch completions.
        # Fields are dropped whole (never mid-string) in priority order
        # so downstream parsers always receive valid JSON.
        _MAX_SOURCE_BYTES = 90 * 1024
        truncation_notes: list[str] = []

        def _estimate_size(
            payload: dict[str, JsonValue],
        ) -> int:
            return len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))

        result_data: dict[str, JsonValue] = {
            "completed_ids": completed_ids,
            "skipped_ids": skipped_ids,
            "archived_ids": sorted(archive_family_ids),
            "invalid_ids": [],
            "project_name": name,
            "todoist_task_ids": todoist_task_ids,
            "trello_card_ids": trello_card_ids,
            "jira_issue_keys": jira_issue_keys,
            "jira_updates_json": jira_updates_json,
            "todoist_project_id": todoist_project_id_val,
            "trello_card_id": trello_card_id_val,
            "jira_project_key": jira_project_key_val,
            "is_batch": True,
        }

        if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
            # Drop biggest whole fields first: jira_updates_json is the
            # likeliest offender on large batches.
            if "jira_updates_json" in result_data:
                result_data["jira_updates_json"] = ""
                truncation_notes.append(
                    "jira_updates_json dropped: batch exceeded 90KB payload cap"
                )
            if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
                result_data["jira_issue_keys"] = []
                truncation_notes.append("jira_issue_keys dropped: batch exceeded 90KB payload cap")
            if _estimate_size(result_data) > _MAX_SOURCE_BYTES:
                result_data["trello_card_ids"] = []
                truncation_notes.append("trello_card_ids dropped: batch exceeded 90KB payload cap")
        if truncation_notes:
            result_data["truncation_notes"] = truncation_notes

        return json.dumps(result_data, ensure_ascii=True)

    @app.tool(
        description=(
            "Mark one or more todos as done. "
            "Pass todo_id for a single todo, or todo_ids (list) for a batch. "
            "Batch path (2+ ids) is atomic with a single hook dispatch. "
            "For 1 id, either param works."
        )
    )
    def todo_complete(
        todo_id: str | None = None,
        todo_ids: list[str] | None = None,
        note: str = "",
        project_name: str | None = None,
    ) -> str:
        if todo_id is not None and todo_ids is not None:
            return json.dumps({"error": "Provide todo_id OR todo_ids, not both."})

        # Route: todo_ids param → batch path (any length, including 0/1).
        # todo_id param (only) → single-complete path.
        if todo_ids is not None:
            return _batch_complete(todo_ids, note, project_name)

        if todo_id is None:
            return json.dumps({"error": "Provide todo_id (single) or todo_ids (batch)."})

        # Single-complete path.
        single_id = todo_id
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == single_id), None)
        if not todo:
            return f"Todo '{single_id}' not found."
        today = _now()
        meta = storage.load_meta(cfg, name)

        if todo.parent:
            result_str = _complete_child(cfg, name, todo, todos, today)
        elif todo.children:
            result_str = _complete_parent(cfg, name, todo, todos, today)
        else:
            result_str = _complete_leaf(cfg, name, todo, todos, today)

        result_data = json.loads(result_str)
        result_data.update(_todo_hook_fields(todo, meta, name, cfg=cfg))
        # Add todoist_task_ids list for hook compat (hooks now use list param).
        result_data["todoist_task_ids"] = [todo.todoist_task_id] if todo.todoist_task_id else []
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
        return json.dumps(
            {"id": todo_id, "status": "pending", **_todo_hook_fields(todo, meta, name, cfg=cfg)}
        )

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
        snapshot = _todo_hook_fields(todo, meta, name, cfg=cfg)
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
        "pending": "\U0001f532",  # 🔲
        "in_progress": "\U0001f504",  # 🔄
        "done": "\u2705",  # ✅
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
                count += _count_tree_nodes([x for x in children if isinstance(x, dict)])
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
            todo_map[t.id] for t in todos if t.parent is not None and t.parent not in todo_map
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
            return json.dumps(
                {"result": "\n".join(lines), "truncated": truncated, "count": len(roots)}
            )

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
        in_degree: dict[str, int] = dict.fromkeys(found_ids, 0)
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
        fuzzy.sort(
            key=lambda x: float(x["ratio"]) if isinstance(x["ratio"], (int, float)) else 0.0,
            reverse=True,
        )
        return json.dumps({"exact_match": None, "fuzzy_matches": fuzzy, "count": len(fuzzy)})

    @app.tool(
        description=(
            "Analyze the blocking graph of all non-done todos. "
            "Returns per-todo metrics (critical path depth, transitive fan-out), "
            "tiers, cycles, critical path, and orphans."
        )
    )
    def todo_analyze_graph(project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        all_todos = storage.load_todos(cfg, name)

        # Filter to non-terminal todos
        active_todos = [t for t in all_todos if t.status not in TERMINAL_STATUSES]
        active_ids = {t.id for t in active_todos}
        todo_map = {t.id: t for t in active_todos}

        # Build adjacency: blocker -> list of dependents (within active set)
        adjacency: dict[str, list[str]] = {tid: [] for tid in active_ids}
        in_degree: dict[str, int] = dict.fromkeys(active_ids, 0)

        for t in active_todos:
            for blocker_id in t.blocked_by:
                if blocker_id in active_ids:
                    adjacency[blocker_id].append(t.id)
                    in_degree[t.id] += 1

        # Also build reverse adjacency scoped to active set (blocks within active)
        blocks_map: dict[str, list[str]] = {tid: [] for tid in active_ids}
        for t in active_todos:
            for blocker_id in t.blocked_by:
                if blocker_id in active_ids:
                    blocks_map[blocker_id].append(t.id)

        # --- Kahn's algorithm for tiers and cycle detection ---
        from collections import deque

        kahn_in_degree = dict(in_degree)
        queue: deque[str] = deque(tid for tid in active_ids if kahn_in_degree[tid] == 0)
        tiers: list[list[str]] = []
        visited_count = 0

        while queue:
            batch = sorted(queue)
            tiers.append(batch)
            visited_count += len(batch)
            queue.clear()
            next_level: list[str] = []
            for tid in batch:
                for dependent in adjacency[tid]:
                    kahn_in_degree[dependent] -= 1
                    if kahn_in_degree[dependent] == 0:
                        next_level.append(dependent)
            queue.extend(next_level)

        # Detect cycles
        cycles: list[str] = []
        if visited_count < len(active_ids):
            cycle_nodes = {tid for tid in active_ids if kahn_in_degree[tid] > 0}
            reported: set[str] = set()
            for start in sorted(cycle_nodes):
                if start in reported:
                    continue
                path: list[str] = []
                visited_trace: set[str] = set()
                node = start
                while node not in visited_trace and node in cycle_nodes:
                    path.append(node)
                    visited_trace.add(node)
                    nexts = [
                        b for b in todo_map[node].blocked_by if b in cycle_nodes and b in active_ids
                    ]
                    node = nexts[0] if nexts else node
                    if node == start or node not in cycle_nodes:
                        break
                path.append(start)
                for n in path:
                    reported.add(n)
                cycles.append(" → ".join(path))

        # --- Critical path depth (longest path from node to any leaf, DFS + memo) ---
        # Skip cycle nodes to avoid infinite recursion in DFS
        cycle_node_set = {tid for tid in active_ids if kahn_in_degree[tid] > 0}
        acyclic_ids = active_ids - cycle_node_set
        cp_depth: dict[str, int] = {}

        def _critical_depth(tid: str) -> int:
            if tid in cp_depth:
                return cp_depth[tid]
            dependents = [d for d in adjacency[tid] if d in acyclic_ids]
            if not dependents:
                cp_depth[tid] = 0
                return 0
            depth = 1 + max(_critical_depth(d) for d in dependents)
            cp_depth[tid] = depth
            return depth

        for tid in acyclic_ids:
            _critical_depth(tid)
        # Cycle nodes get depth -1 (indeterminate)
        for tid in cycle_node_set:
            cp_depth[tid] = -1

        # --- Transitive fan-out (count of all downstream dependents, DFS + memo) ---
        fan_out: dict[str, int] = {}
        fan_out_cache: dict[str, set[str]] = {}

        def _fan_out_set(tid: str) -> set[str]:
            if tid in fan_out_cache:
                return fan_out_cache[tid]
            dependents = [d for d in adjacency[tid] if d in acyclic_ids]
            if not dependents:
                fan_out_cache[tid] = set()
                fan_out[tid] = 0
                return set()
            all_downstream: set[str] = set()
            for d in dependents:
                all_downstream.add(d)
                all_downstream |= _fan_out_set(d)
            fan_out_cache[tid] = all_downstream
            fan_out[tid] = len(all_downstream)
            return all_downstream

        for tid in acyclic_ids:
            _fan_out_set(tid)
        # Cycle nodes get fan_out -1 (indeterminate)
        for tid in cycle_node_set:
            fan_out[tid] = -1

        # --- Critical path: longest chain from any root to any leaf ---
        roots = [tid for tid in active_ids if in_degree[tid] == 0]
        critical_path: list[str] = []
        if roots:
            # Find root with highest critical_path_depth
            best_root = max(roots, key=lambda tid: cp_depth.get(tid, 0))
            # Trace path by following dependent with highest critical_path_depth
            current = best_root
            critical_path.append(current)
            while True:
                dependents = [d for d in adjacency[current] if d in active_ids]
                if not dependents:
                    break
                next_node = max(dependents, key=lambda d: cp_depth.get(d, 0))
                critical_path.append(next_node)
                current = next_node

        critical_path_set = set(critical_path)

        # --- Orphans: no blocked_by and no blocks within active set ---
        orphans = sorted(tid for tid in active_ids if in_degree[tid] == 0 and not adjacency[tid])

        # Build per-todo result
        todo_results: list[dict[str, JsonValue]] = []
        for t in sorted(active_todos, key=lambda t: t.id):
            scoped_blocked_by = [b for b in t.blocked_by if b in active_ids]
            scoped_blocks = list(adjacency[t.id])
            todo_results.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "priority": t.priority,
                    "blocked_by": scoped_blocked_by,
                    "blocks": scoped_blocks,
                    "tags": t.tags,
                    "children": t.children,
                    "critical_path_depth": cp_depth.get(t.id, 0),
                    "transitive_fan_out": fan_out.get(t.id, 0),
                    "is_on_critical_path": t.id in critical_path_set,
                }
            )

        return json.dumps(
            {
                "todos": todo_results,
                "tiers": tiers,
                "cycles": cycles,
                "critical_path": critical_path,
                "orphans": orphans,
            }
        )

    @app.tool(
        description=(
            "Migrate legacy done/cancelled todos from todos.yaml to archive.yaml. "
            "Safe to run multiple times (idempotent). "
            "Use when todos.yaml has accumulated many completed todos that slow down parsing."
        ),
    )
    def todo_archive_done(project_name: str | None = None) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
        stats = storage.migrate_done_to_archive(cfg, name)
        return json.dumps(stats)

    @app.tool(
        description=(
            "Patch a todo's notes via find/replace. Avoids resending the full "
            "notes content. count=1 replaces first occurrence, count=0 replaces all."
        ),
    )
    def todo_notes_patch(
        todo_id: str,
        find: str,
        replace: str,
        count: int = 1,
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
        if find not in (todo.notes or ""):
            return json.dumps({"error": f"Pattern not found in notes for todo {todo_id}"})
        notes = todo.notes or ""
        if count == 0:
            occurrences = notes.count(find)
            todo.notes = notes.replace(find, replace)
        else:
            occurrences = min(count, notes.count(find))
            todo.notes = notes.replace(find, replace, count)
        todo.updated = _now()
        meta = storage.load_meta(cfg, name)
        storage.save_todos(cfg, name, todos)
        return json.dumps(
            {
                "result": "patched",
                "todo_id": todo_id,
                "occurrences": occurrences,
                **_todo_hook_fields(todo, meta, name, todos=todos, cfg=cfg),
            }
        )

    @app.tool(
        description=(
            "Append text to a todo's notes. Avoids resending the full "
            "notes content on every update."
        ),
    )
    def todo_notes_append(
        todo_id: str,
        text: str,
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
        if todo.notes:
            todo.notes = todo.notes + "\n" + text
        else:
            todo.notes = text
        todo.updated = _now()
        meta = storage.load_meta(cfg, name)
        storage.save_todos(cfg, name, todos)
        return json.dumps(
            {
                "result": "appended",
                "todo_id": todo_id,
                "notes_length": len(todo.notes),
                **_todo_hook_fields(todo, meta, name, todos=todos, cfg=cfg),
            }
        )

    @app.tool(
        description=(
            "Export project data from SQLite back to YAML files. "
            "Use for emergency recovery, debugging, or forcing a git-committable snapshot. "
            "Exports: todos.yaml, archive.yaml, meta.yaml, decisions.yaml"
        ),
    )
    def _todo_export_yaml(project_name: str | None = None) -> str:
        return todo_export_yaml(project_name)
