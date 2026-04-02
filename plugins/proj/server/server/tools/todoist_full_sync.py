"""
proj_todoist_full_sync -- full-cycle Todoist sync executed within the MCP layer.

Reduces model-side orchestration from ~10 tool calls to 1 by handling:
fetch -> diff -> execute push ops -> apply pull ops -> return summary.
"""

from __future__ import annotations

import base64
import difflib
import json
import logging
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import Todo
from server.lib.retry import retry_link
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ── Priority mapping ─────────────────────────────────────────────────────────

_TODOIST_TO_LOCAL: dict[str, str] = {"p1": "high", "p2": "high", "p3": "medium", "p4": "low"}
_LOCAL_TO_TODOIST: dict[str, str] = {"high": "p2", "medium": "p3", "low": "p4"}

_UTC = timezone.utc


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string for time precision."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


def _today() -> str:
    return str(date.today())


def _todoist_date(updated_at: str) -> str:
    """Extract date portion from Todoist ISO datetime."""
    return updated_at[:10] if updated_at else ""


def _ghost_check(title: str, archived: list[Todo], threshold: float = 0.7) -> bool:
    """Return True if title matches an archived todo (exact or fuzzy)."""
    if not archived:
        return False
    lower_title = title.lower()
    titles = [t.title for t in archived]
    if any(t.lower() == lower_title for t in titles):
        return True
    return bool(difflib.get_close_matches(title, titles, n=1, cutoff=threshold))


def _apply_description_sync(
    local_notes: str,
    local_synced: str,
    todoist_desc: str,
) -> tuple[str, str]:
    """Apply description sync-link logic.

    Returns (new_notes, new_todoist_description_synced).
    """
    if todoist_desc == local_synced:
        return local_notes, local_synced
    if not local_notes:
        return todoist_desc, todoist_desc
    return local_notes + "\n\n---\n" + todoist_desc, todoist_desc


def _parse_todoist_priority(task: dict[str, Any]) -> str:
    """Map Todoist priority to local priority string."""
    raw = task.get("priority")
    if isinstance(raw, str) and raw.startswith("p"):
        return _TODOIST_TO_LOCAL.get(raw, "low")
    if isinstance(raw, int):
        return _TODOIST_TO_LOCAL.get(f"p{raw}", "low")
    return "low"


def _parse_todoist_labels(task: dict[str, Any]) -> list[str]:
    """Extract labels list from task."""
    labels = task.get("labels")
    return [str(x) for x in labels] if isinstance(labels, list) else []  # type: ignore[union-attr]


def _parse_todoist_due(task: dict[str, Any]) -> str | None:
    """Extract due date from task."""
    due_raw = task.get("due")
    if isinstance(due_raw, dict) and "date" in due_raw:  # type: ignore[operator]
        return str(due_raw["date"])  # type: ignore[index]
    return None


def _parse_todoist_updated(task: dict[str, Any]) -> str:
    """Extract date from updatedAt or updated_at field."""
    raw: str = str(task.get("updatedAt") or task.get("updated_at") or "")
    return _todoist_date(raw)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class SyncPlan:
    """Result of comparing Todoist tasks with local todos."""

    pull_create: list[dict[str, object]] = field(default_factory=list)
    pull_update: list[dict[str, object]] = field(default_factory=list)
    pull_complete: list[str] = field(default_factory=list)
    push_create: list[dict[str, object]] = field(default_factory=list)
    push_create_phase2: list[dict[str, object]] = field(default_factory=list)
    push_update: list[dict[str, object]] = field(default_factory=list)
    push_complete: list[str] = field(default_factory=list)
    ghost_close: list[str] = field(default_factory=list)
    potential_links: list[dict] = field(default_factory=list)
    root_only_cleanup: list[dict[str, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.pull_create, self.pull_update, self.pull_complete,
            self.push_create, self.push_create_phase2, self.push_update, self.push_complete,
            self.ghost_close, self.potential_links, self.root_only_cleanup,
        ])

    def to_dict(self) -> dict[str, object]:
        return {
            "pull_create": self.pull_create,
            "pull_update": self.pull_update,
            "pull_complete": self.pull_complete,
            "push_create": self.push_create,
            "push_create_phase2": self.push_create_phase2,
            "push_update": self.push_update,
            "push_complete": self.push_complete,
            "ghost_close": self.ghost_close,
            "potential_links": self.potential_links,
            "root_only_cleanup": self.root_only_cleanup,
            "summary": {
                "pull_create_count": len(self.pull_create),
                "pull_update_count": len(self.pull_update),
                "pull_complete_count": len(self.pull_complete),
                "push_create_count": len(self.push_create),
                "push_create_phase2_count": len(self.push_create_phase2),
                "push_update_count": len(self.push_update),
                "push_complete_count": len(self.push_complete),
                "ghost_close_count": len(self.ghost_close),
                "potential_links_count": len(self.potential_links),
                "root_only_cleanup_count": len(self.root_only_cleanup),
            },
        }


@dataclass
class ApplyInput:
    """Input for applying sync changes locally."""

    created_locally: list[dict[str, Any]] = field(default_factory=list)
    updated_locally: list[dict[str, Any]] = field(default_factory=list)
    completed_locally: list[str] = field(default_factory=list)
    link_todoist_ids: list[dict[str, str]] = field(default_factory=list)
    cleared_todoist_ids: list[str] = field(default_factory=list)


# ── Core logic (standalone functions) ─────────────────────────────────────────


def _find_link_candidate(
    local_todo: dict, todoist_tasks: list[dict], threshold: float = 0.7
) -> dict | None:
    """Find a Todoist task that likely matches an unlinked local todo by title similarity."""
    import re
    import unicodedata

    def normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s).lower()
        s = re.sub(r"[^\w\s]", "", s)
        return " ".join(s.split())

    def similarity(a: str, b: str) -> float:
        a_words = set(normalize(a).split())
        b_words = set(normalize(b).split())
        if not a_words or not b_words:
            return 0.0
        intersection = a_words & b_words
        return len(intersection) / max(len(a_words), len(b_words))

    local_title = local_todo.get("title", "")
    best_match = None
    best_score = 0.0
    for task in todoist_tasks:
        task_content = task.get("content", "")
        score = similarity(local_title, task_content)
        if score > best_score:
            best_score = score
            best_match = task
    if best_score >= threshold and best_match:
        return {"todo": local_todo, "task": best_match, "score": best_score}
    return None


def _find_link_candidate_reverse(
    todoist_task: dict, local_todos: list[Todo], threshold: float = 0.7
) -> dict | None:
    """Find a local todo that likely matches an unlinked Todoist task by title similarity."""
    import re
    import unicodedata

    def normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s).lower()
        s = re.sub(r"[^\w\s]", "", s)
        return " ".join(s.split())

    def similarity(a: str, b: str) -> float:
        a_words = set(normalize(a).split())
        b_words = set(normalize(b).split())
        if not a_words or not b_words:
            return 0.0
        intersection = a_words & b_words
        return len(intersection) / max(len(a_words), len(b_words))

    task_content = todoist_task.get("content", "")
    best_match: Todo | None = None
    best_score = 0.0
    for todo in local_todos:
        score = similarity(task_content, todo.title)
        if score > best_score:
            best_score = score
            best_match = todo
    if best_score >= threshold and best_match:
        return {"local_todo": best_match, "todoist_task": todoist_task, "score": best_score}
    return None


def compute_diff(
    todoist_tasks: list[dict[str, Any]],
    cfg: Any,
    name: str,
) -> SyncPlan:
    """Compare Todoist tasks with local todos. Returns a SyncPlan."""
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    archived = storage.load_archived_todos(cfg, name)

    # Resolve effective_root_only
    project_ro = meta.todoist.root_only
    global_ro = cfg.todoist.root_only
    effective_root_only = project_ro if project_ro is not None else global_ro

    # Build lookup maps
    todoist_by_id: dict[str, dict[str, Any]] = {}
    for task in todoist_tasks:
        tid = str(task.get("id", ""))
        if tid:
            todoist_by_id[tid] = task

    local_by_todoist_id: dict[str, Todo] = {}
    local_unlinked: list[Todo] = []
    local_open_with_todoist_id: list[Todo] = []

    for todo in todos:
        if todo.todoist_task_id:
            local_by_todoist_id[todo.todoist_task_id] = todo
            if todo.status not in TERMINAL_STATUSES:
                local_open_with_todoist_id.append(todo)
        elif todo.status not in TERMINAL_STATUSES:
            local_unlinked.append(todo)

    plan = SyncPlan()

    # Track local todo IDs matched via link candidates so they're excluded from push_create
    linked_local_ids: set[str] = set()

    # ── Todoist -> Local (pull) ───────────────────────────────────────

    for todoist_id, task in todoist_by_id.items():
        content = str(task.get("content", ""))
        local_priority = _parse_todoist_priority(task)
        todoist_labels = _parse_todoist_labels(task)
        todoist_desc = str(task.get("description", "") or "")
        todoist_due = _parse_todoist_due(task)
        todoist_updated = _parse_todoist_updated(task)

        if todoist_id not in local_by_todoist_id:
            # New task from Todoist — ghost check
            if _ghost_check(content, archived):
                plan.ghost_close.append(todoist_id)
                continue
            # Link candidate check: see if an unlinked local todo matches this Todoist task
            link_match = _find_link_candidate_reverse(task, local_unlinked)
            if link_match:
                matched_todo: Todo = link_match["local_todo"]
                plan.potential_links.append({
                    "local_todo": {"id": matched_todo.id, "title": matched_todo.title},
                    "todoist_task": {"id": todoist_id, "content": content},
                    "score": link_match["score"],
                })
                linked_local_ids.add(matched_todo.id)
                continue
            # Prepare for local creation
            new_notes, new_synced = _apply_description_sync("", "", todoist_desc)
            plan.pull_create.append({
                "title": content,
                "priority": local_priority,
                "tags": todoist_labels,
                "notes": new_notes,
                "due_date": todoist_due,
                "todoist_task_id": todoist_id,
                "todoist_description_synced": new_synced,
            })
        else:
            # Existing — check timestamps
            local_todo = local_by_todoist_id[todoist_id]
            if todoist_updated > local_todo.updated:
                # Todoist is newer — prepare update
                new_notes, new_synced = _apply_description_sync(
                    local_todo.notes, local_todo.todoist_description_synced, todoist_desc
                )
                update_entry: dict[str, object] = {
                    "todo_id": local_todo.id,
                    "title": content,
                    "priority": local_priority,
                    "tags": todoist_labels,
                    "notes": new_notes,
                    "due_date": todoist_due,
                    "todoist_description_synced": new_synced,
                }
                # Check if Todoist task is completed
                if task.get("isCompleted") or task.get("checked"):
                    update_entry["complete"] = True
                plan.pull_update.append(update_entry)

    # ── Closed/deleted propagation ────────────────────────────────────

    for todo in local_open_with_todoist_id:
        if todo.todoist_task_id and todo.todoist_task_id not in todoist_by_id:
            plan.pull_complete.append(todo.id)

    # ── Local -> Todoist (push) ───────────────────────────────────────

    # Root-only cleanup
    if effective_root_only:
        for todoist_id, task in todoist_by_id.items():
            if task.get("parentId"):
                local_todo = local_by_todoist_id.get(todoist_id)
                if local_todo and local_todo.parent:
                    plan.root_only_cleanup.append({
                        "todoist_task_id": todoist_id,
                        "todo_id": local_todo.id,
                    })

    # Split unlinked into roots (phase 1) and children-of-unlinked (phase 2)
    # Exclude todos that were matched as link candidates to prevent duplicate push_create
    remaining_unlinked = [t for t in local_unlinked if t.id not in linked_local_ids]
    unlinked_ids = {t.id for t in remaining_unlinked}
    unlinked_roots: list[Todo] = []
    unlinked_children: list[Todo] = []
    for todo in remaining_unlinked:
        if effective_root_only and todo.parent:
            continue
        if todo.parent and todo.parent in unlinked_ids:
            unlinked_children.append(todo)
        else:
            unlinked_roots.append(todo)

    # Phase 1: roots and children whose parent already has a todoist_task_id
    for todo in sorted(unlinked_roots, key=lambda t: t.id):
        todoist_priority = _LOCAL_TO_TODOIST.get(todo.priority, "p4")
        parent_todoist_id: str | None = None
        if todo.parent:
            parent_todo = next((t for t in todos if t.id == todo.parent), None)
            if parent_todo and parent_todo.todoist_task_id:
                parent_todoist_id = parent_todo.todoist_task_id

        entry: dict[str, object] = {
            "todo_id": todo.id,
            "content": todo.title,
            "priority": todoist_priority,
            "description": todo.notes,
            "labels": todo.tags,
        }
        if todo.due_date:
            entry["dueString"] = todo.due_date
        if parent_todoist_id:
            entry["parentId"] = parent_todoist_id
        if meta.todoist_project_id:
            entry["project_id"] = meta.todoist_project_id
        if todo.status == TodoStatus.DONE:
            entry["complete_after_create"] = True
        plan.push_create.append(entry)

    # Phase 2: children whose parent is also unlinked (needs phase 1 to resolve parent)
    for todo in sorted(unlinked_children, key=lambda t: t.id):
        todoist_priority = _LOCAL_TO_TODOIST.get(todo.priority, "p4")
        entry_p2: dict[str, object] = {
            "todo_id": todo.id,
            "content": todo.title,
            "priority": todoist_priority,
            "description": todo.notes,
            "labels": todo.tags,
            "_parent_local_id": todo.parent,
        }
        if todo.due_date:
            entry_p2["dueString"] = todo.due_date
        if meta.todoist_project_id:
            entry_p2["project_id"] = meta.todoist_project_id
        if todo.status == TodoStatus.DONE:
            entry_p2["complete_after_create"] = True
        plan.push_create_phase2.append(entry_p2)

    # Push updates for linked todos where local is newer
    for todoist_id, task in todoist_by_id.items():
        if todoist_id in local_by_todoist_id:
            local_todo = local_by_todoist_id[todoist_id]
            todoist_updated = _parse_todoist_updated(task)
            if local_todo.updated > todoist_updated and local_todo.status not in TERMINAL_STATUSES:
                todoist_priority = _LOCAL_TO_TODOIST.get(local_todo.priority, "p4")
                update_entry_push: dict[str, object] = {
                    "id": todoist_id,
                    "content": local_todo.title,
                    "priority": todoist_priority,
                    "description": local_todo.notes,
                    "labels": local_todo.tags,
                }
                if local_todo.due_date:
                    update_entry_push["dueString"] = local_todo.due_date
                plan.push_update.append(update_entry_push)
            elif local_todo.status in TERMINAL_STATUSES:
                # Local is done, Todoist still open
                if not (task.get("isCompleted") or task.get("checked")):
                    plan.push_complete.append(todoist_id)

    # ── Fix parent linkage for linked todos missing Todoist parentId ──
    for todoist_id, task in todoist_by_id.items():
        if todoist_id not in local_by_todoist_id:
            continue
        local_todo = local_by_todoist_id[todoist_id]
        if not local_todo.parent:
            continue
        # Local todo has a parent — find parent's todoist_task_id
        parent_todo = next((t for t in todos if t.id == local_todo.parent), None)
        if not parent_todo or not parent_todo.todoist_task_id:
            continue
        # Check if Todoist task already has the correct parent_id set
        if task.get("parentId"):
            continue
        # Todoist task is missing parentId — push an update to set it
        plan.push_update.append({
            "id": todoist_id,
            "parentId": parent_todo.todoist_task_id,
        })

    return plan


def apply_changes(
    data: ApplyInput,
    cfg: Any,
    name: str,
    push_confirmed: bool = False,
) -> dict[str, Any]:
    """Apply sync changes to local todos atomically. Returns counts dict.

    When *push_confirmed* is False (default, used during the pull phase),
    ``todoist_description_synced`` values are **not** persisted on todos.
    Instead they are collected and returned under the key
    ``"staged_description_synced"`` so the caller can apply them after the
    push succeeds (by calling ``apply_changes`` again with the staged values
    and *push_confirmed=True*).

    When *push_confirmed* is True the description-synced values are written
    to todo storage normally.
    """
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    todo_map = {t.id: t for t in todos}
    today = _now()

    counts: dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "completed": 0,
        "linked": 0,
        "cleared": 0,
    }

    # Staged description_synced values when push_confirmed is False
    staged_description_synced: dict[str, str] = {}

    # 1. Create new todos
    for item in data.created_locally:
        parent_id = str(item["parent"]) if item.get("parent") else None
        parent_todo = todo_map.get(parent_id) if parent_id else None
        desc_synced_value = str(item.get("todoist_description_synced", ""))
        todo = Todo(
            id=next_todo_id(meta, parent=parent_todo),
            title=str(item.get("title", "")),
            priority=str(item.get("priority", cfg.default_priority)),
            tags=list(item["tags"]) if isinstance(item.get("tags"), list) else [],  # type: ignore[arg-type]
            notes=str(item.get("notes", "")),
            due_date=str(item["due_date"]) if item.get("due_date") else None,
            todoist_task_id=str(item["todoist_task_id"]) if item.get("todoist_task_id") else None,
            todoist_description_synced=desc_synced_value if push_confirmed else "",
            created=today,
            updated=today,
        )
        if not push_confirmed and desc_synced_value:
            staged_description_synced[todo.id] = desc_synced_value
        if parent_todo:
            parent_todo.children.append(todo.id)
            parent_todo.updated = today
        todos.append(todo)
        todo_map[todo.id] = todo
        counts["created"] += 1

    # 2. Update existing todos
    for item in data.updated_locally:
        todo_id = str(item.get("todo_id", ""))
        todo = todo_map.get(todo_id)
        if not todo:
            continue
        if "title" in item and item["title"] is not None:
            todo.title = str(item["title"])
        if "priority" in item and item["priority"] is not None:
            todo.priority = str(item["priority"])
        if "tags" in item and isinstance(item["tags"], list):
            todo.tags = list(item["tags"])  # type: ignore[arg-type]
        if "notes" in item and item["notes"] is not None:
            todo.notes = str(item["notes"])
        if "due_date" in item:
            todo.due_date = str(item["due_date"]) if item["due_date"] else None
        if "todoist_task_id" in item:
            todo.todoist_task_id = str(item["todoist_task_id"]) if item["todoist_task_id"] else None
        if "todoist_description_synced" in item:
            desc_synced_value = str(item.get("todoist_description_synced", ""))
            if push_confirmed:
                todo.todoist_description_synced = desc_synced_value
            else:
                staged_description_synced[todo_id] = desc_synced_value
        todo.updated = today
        counts["updated"] += 1

    # 3. Link todoist IDs (after push_create returns Todoist task IDs)
    tracking_path = str(storage.tracking_dir(cfg, name))
    for item in data.link_todoist_ids:
        todo_id = str(item.get("todo_id", ""))
        todoist_task_id = str(item.get("todoist_task_id", ""))
        todo = todo_map.get(todo_id)
        if todo and todoist_task_id:
            try:
                def _do_link(t=todo, tid=todoist_task_id, ts=today):  # noqa: E731
                    t.todoist_task_id = tid
                    t.updated = ts

                retry_link(
                    _do_link,
                    max_retries=3,
                    orphan_context={
                        "tracking_dir": tracking_path,
                        "external_id": todoist_task_id,
                        "todo_id": todo_id,
                        "service": "todoist",
                    },
                )
                counts["linked"] += 1
            except Exception as exc:
                warnings.warn(
                    f"Failed to link Todoist task {todoist_task_id} to todo "
                    f"{todo_id} after retries; orphaned resource logged: {exc}",
                    stacklevel=2,
                )
                logger.warning(
                    "Orphaned Todoist task %s (todo %s): %s",
                    todoist_task_id, todo_id, exc,
                )

    # 4. Clear todoist IDs (root_only cleanup)
    for raw_todo_id in data.cleared_todoist_ids:
        todo = todo_map.get(str(raw_todo_id))
        if todo:
            todo.todoist_task_id = None
            todo.updated = today
            counts["cleared"] += 1

    # 5. Complete todos — handle archival properly
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
            todo.todoist_description_synced = ""
            to_archive.append(todo)
            # Clean up blocking references
            for t in todos:
                if todo.id in t.blocks:
                    t.blocks.remove(todo.id)
                    t.updated = today
                if todo.id in t.blocked_by:
                    t.blocked_by.remove(todo.id)
                    t.updated = today

    # Save atomically
    storage.save_meta(cfg, meta)
    if to_archive:
        remaining = [t for t in todos if t not in to_archive]
        storage.archive_and_remove_todos(cfg, name, remaining, to_archive)
    else:
        storage.save_todos(cfg, name, todos)

    counts["staged_description_synced"] = staged_description_synced
    return counts


# -- Inter-plugin call helpers ------------------------------------------------


def _resolve_todoist_socket() -> str:
    """Read Todoist plugin socket path from registry, fall back to legacy."""
    registry_file = Path.home() / ".claude" / "sockets" / "todoist"
    try:
        path = registry_file.read_text().strip()
        if path:
            return path
    except (FileNotFoundError, OSError):
        pass
    return "/tmp/claude-hooks-todoist.sock"


def _call_todoist_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Call a Todoist MCP tool via inter-plugin Unix domain socket."""
    sock_path = _resolve_todoist_socket()
    transport = httpx.HTTPTransport(uds=sock_path)
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            "http://localhost/hook",
            json={"tool": tool_name, "params": params},
        )
        resp.raise_for_status()
        return resp.json()


# -- Push operation helpers ---------------------------------------------------


def _execute_push_creates(
    tasks: list[dict[str, Any]],
    project_todoist_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Execute phase-1 push_create operations via todoist_add_tasks.

    Returns (succeeded, errors, id_map) where id_map maps local todo_id
    to the newly created Todoist task ID.
    """
    if not tasks:
        return [], [], {}

    succeeded: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}

    # Build payloads for batch create
    add_payloads: list[dict[str, Any]] = []
    for task in tasks:
        payload: dict[str, Any] = {
            "content": task.get("content", ""),
            "priority": task.get("priority", "p4"),
        }
        if task.get("description"):
            payload["description"] = task["description"]
        if task.get("labels"):
            payload["labels"] = task["labels"]
        if task.get("dueString"):
            payload["dueString"] = task["dueString"]
        if task.get("parentId"):
            payload["parentId"] = task["parentId"]
        if task.get("project_id"):
            payload["project_id"] = task["project_id"]
        add_payloads.append(payload)

    try:
        result = _call_todoist_tool("todoist_add_tasks", {"tasks": add_payloads})
        # todoist_add_tasks returns {"successes": [...], "failures": [...]}
        if isinstance(result, dict):
            created_tasks = result.get("successes", result.get("tasks", []))
        elif isinstance(result, list):
            created_tasks = result
        else:
            created_tasks = []
        for i, task in enumerate(tasks):
            todo_id = str(task.get("todo_id", ""))
            if i < len(created_tasks):
                todoist_id = str(created_tasks[i].get("id", ""))
                if todoist_id:
                    id_map[todo_id] = todoist_id
                    task["result_todoist_id"] = todoist_id
                    succeeded.append(task)
                else:
                    errors.append({
                        "operation_type": "push_create",
                        "error": "No ID returned for created task",
                        "retryable": True,
                        "retry_payload": task,
                    })
            else:
                # Response was truncated — the task may have been created anyway.
                # Look it up by content+project before marking as an error so we
                # don't create a duplicate on the next sync or retry.
                recovered_id = _find_existing_todoist_task(
                    task.get("project_id", "") or (project_todoist_id or ""),
                    task.get("content", ""),
                )
                if recovered_id:
                    id_map[todo_id] = recovered_id
                    task["result_todoist_id"] = recovered_id
                    succeeded.append(task)
                else:
                    errors.append({
                        "operation_type": "push_create",
                        "error": "Task not in response",
                        "retryable": True,
                        "retry_payload": task,
                    })
    except Exception as e:
        # All tasks in this batch failed
        for task in tasks:
            errors.append({
                "operation_type": "push_create",
                "error": str(e),
                "retryable": True,
                "retry_payload": task,
            })

    # Handle complete_after_create for successfully created tasks
    complete_ids = [
        id_map[str(t.get("todo_id", ""))]
        for t in tasks
        if t.get("complete_after_create") and str(t.get("todo_id", "")) in id_map
    ]
    if complete_ids:
        try:
            _call_todoist_tool("todoist_complete_tasks", {"ids": complete_ids})
        except Exception as e:
            logger.warning("Failed to complete newly created tasks: %s", e)

    return succeeded, errors, id_map


def _execute_push_creates_phase2(
    tasks: list[dict[str, Any]],
    phase1_id_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Execute phase-2 push_create for children whose parents were just created.

    Resolves _parent_local_id to the Todoist ID from phase 1.
    """
    if not tasks:
        return [], [], {}

    resolved: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for task in tasks:
        parent_local_id = str(task.get("_parent_local_id", ""))
        if parent_local_id in phase1_id_map:
            task_copy = dict(task)
            task_copy["parentId"] = phase1_id_map[parent_local_id]
            # Remove internal field
            task_copy.pop("_parent_local_id", None)
            resolved.append(task_copy)
        else:
            errors.append({
                "operation_type": "push_create_phase2",
                "error": f"Parent {parent_local_id} not in phase-1 ID map",
                "retryable": True,
                "retry_payload": task,
            })

    if not resolved:
        return [], errors, {}

    succeeded, create_errors, id_map = _execute_push_creates(resolved, None)
    errors.extend(create_errors)
    return succeeded, errors, id_map


def _execute_push_updates(
    tasks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute push_update operations via todoist_update_tasks."""
    if not tasks:
        return [], []

    try:
        _call_todoist_tool("todoist_update_tasks", {"tasks": tasks})
        return tasks, []
    except Exception as e:
        errors = [{
            "operation_type": "push_update",
            "error": str(e),
            "retryable": True,
            "retry_payload": task,
        } for task in tasks]
        return [], errors


def _execute_push_completes(
    task_ids: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Execute push_complete operations via todoist_complete_tasks."""
    if not task_ids:
        return [], []

    try:
        _call_todoist_tool("todoist_complete_tasks", {"ids": task_ids})
        return task_ids, []
    except Exception as e:
        errors = [{
            "operation_type": "push_complete",
            "error": str(e),
            "retryable": True,
            "retry_payload": {"ids": task_ids},
        }]
        return [], errors


def _execute_ghost_close(
    task_ids: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Complete ghost tasks on Todoist."""
    if not task_ids:
        return [], []

    try:
        _call_todoist_tool("todoist_complete_tasks", {"ids": task_ids})
        return task_ids, []
    except Exception as e:
        errors = [{
            "operation_type": "ghost_close",
            "error": str(e),
            "retryable": True,
            "retry_payload": {"ids": task_ids},
        }]
        return [], errors


def _execute_root_only_cleanup(
    cleanup_entries: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Delete child tasks from Todoist for root_only mode."""
    if not cleanup_entries:
        return [], []

    succeeded: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []

    for entry in cleanup_entries:
        todoist_task_id = entry.get("todoist_task_id", "")
        try:
            _call_todoist_tool("todoist_delete", {"id": todoist_task_id})
            succeeded.append(entry)
        except Exception as e:
            errors.append({
                "operation_type": "root_only_cleanup",
                "error": str(e),
                "retryable": True,
                "retry_payload": entry,
            })

    return succeeded, errors


# -- Retry handling -----------------------------------------------------------


def _find_existing_todoist_task(project_id: str, content: str) -> str | None:
    """Return the Todoist task ID of an exact content match in *project_id*, or None.

    Used as a dedup guard before retrying a push_create: if the first attempt
    created the task but the response was truncated, retrying without this check
    would create a duplicate.
    """
    if not project_id or not content:
        return None
    try:
        raw = _call_todoist_tool("todoist_find_tasks", {"project_id": project_id})
        if isinstance(raw, str):
            tasks: list[Any] = json.loads(raw) if raw else []
        elif isinstance(raw, list):
            tasks = raw
        else:
            tasks = []
        needle = content.strip()
        for t in tasks:
            if isinstance(t, dict) and t.get("content", "").strip() == needle:
                task_id = str(t.get("id", ""))
                return task_id if task_id else None
    except Exception:
        pass
    return None


def _retry_failed_ops(
    failed_ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """Re-attempt previously failed operations.

    Returns (succeeded, still_failed, link_ops) where *link_ops* is a list of
    ``{todo_id, todoist_task_id}`` dicts for push_create ops that were linked
    (either found as existing or newly created) and should be persisted locally.
    """
    succeeded: list[dict[str, Any]] = []
    still_failed: list[dict[str, Any]] = []
    link_ops: list[dict[str, str]] = []

    for entry in failed_ops:
        op_type = entry.get("operation_type", "unknown")
        payload = entry.get("retry_payload", {})

        try:
            if op_type == "push_create" or op_type == "push_create_phase2":
                # Dedup guard: the original call may have created the task even though
                # its ID was missing from the response (batching truncation). Check first
                # to avoid creating a duplicate on retry.
                project_id = payload.get("project_id", "")
                content = payload.get("content", "")
                existing_id = _find_existing_todoist_task(project_id, content)

                if existing_id:
                    payload["result_todoist_id"] = existing_id
                else:
                    add_payload = {
                        k: v for k, v in payload.items()
                        if k in ("content", "priority", "description", "labels", "dueString", "parentId", "project_id")
                    }
                    result = _call_todoist_tool("todoist_add_tasks", {"tasks": [add_payload]})
                    # Extract the new task ID so we can persist it locally
                    if isinstance(result, dict):
                        created_tasks = result.get("successes", result.get("tasks", []))
                    elif isinstance(result, list):
                        created_tasks = result
                    else:
                        created_tasks = []
                    if created_tasks and isinstance(created_tasks[0], dict):
                        new_id = str(created_tasks[0].get("id", ""))
                        if new_id:
                            payload["result_todoist_id"] = new_id
                    payload["result"] = result

                # Collect link op so caller can persist the ID to the local todo
                todo_id = str(payload.get("todo_id", ""))
                todoist_id = str(payload.get("result_todoist_id", ""))
                if todo_id and todoist_id:
                    link_ops.append({"todo_id": todo_id, "todoist_task_id": todoist_id})

                succeeded.append(payload)
            elif op_type == "push_update":
                _call_todoist_tool("todoist_update_tasks", {"tasks": [payload]})
                succeeded.append(payload)
            elif op_type in ("push_complete", "ghost_close"):
                ids = payload.get("ids", [])
                if ids:
                    _call_todoist_tool("todoist_complete_tasks", {"ids": ids})
                succeeded.append(payload)
            elif op_type == "root_only_cleanup":
                todoist_id = payload.get("todoist_task_id", "")
                if todoist_id:
                    _call_todoist_tool("todoist_delete", {"id": todoist_id})
                succeeded.append(payload)
            else:
                still_failed.append(entry)
                continue
        except Exception as e:
            still_failed.append({
                "operation_type": op_type,
                "error": str(e),
                "retryable": False,
                "retry_payload": payload,
            })

    return succeeded, still_failed, link_ops


# -- Summary builder ----------------------------------------------------------


def _build_summary(
    plan: SyncPlan,
    pull_counts: dict[str, Any],
    push_created: int,
    push_created_phase2: int,
    push_updated: int,
    push_completed: int,
    ghost_closed: int,
    root_cleaned: int,
) -> dict[str, Any]:
    """Build a human-readable summary of what was synced."""
    return {
        "pull": {
            "created": pull_counts.get("created", 0),
            "updated": pull_counts.get("updated", 0),
            "completed": pull_counts.get("completed", 0),
            "linked": pull_counts.get("linked", 0),
            "cleared": pull_counts.get("cleared", 0),
        },
        "push": {
            "tasks_created": push_created,
            "tasks_created_phase2": push_created_phase2,
            "tasks_updated": push_updated,
            "tasks_completed": push_completed,
            "ghost_closed": ghost_closed,
            "root_only_cleaned": root_cleaned,
        },
    }


# -- MCP tool registration ---------------------------------------------------


def register(app: FastMCP) -> None:
    """Register proj_todoist_full_sync tool."""

    @app.tool(
        description=(
            "Execute a full Todoist sync cycle for the active project: "
            "fetch tasks -> diff -> execute push ops -> apply pull ops -> return summary. "
            "Reduces the sync flow from ~10 tool calls to 1. "
            "On success: {\"status\": \"success\", \"summary\": {...}}. "
            "On partial failure: {\"status\": \"partial_success\", \"errors\": [...], \"retry_token\": \"...\"}. "
            "If potential_links exist: {\"status\": \"needs_confirmation\", \"potential_links\": [...]}. "
            "Pass confirmed_links (JSON list of {todo_id, todoist_task_id}) to confirm links. "
            "Pass retry_failures (base64-encoded JSON) to re-attempt only previously failed ops."
        )
    )
    def proj_todoist_full_sync(
        project_name: str | None = None,
        confirmed_links: str | None = None,
        retry_failures: str | None = None,
    ) -> str:
        # -- Retry mode: re-attempt only failed ops --
        if retry_failures:
            try:
                raw = json.loads(base64.b64decode(retry_failures))
                # New format: {"project_name": "...", "ops": [...]}
                # Old format (pre-2.10.4): bare list
                if isinstance(raw, dict) and "ops" in raw:
                    failed_ops = raw["ops"]
                    embedded_project_name = raw.get("project_name")
                else:
                    failed_ops = raw
                    embedded_project_name = None
            except (json.JSONDecodeError, Exception) as e:
                return json.dumps({"status": "error", "error": f"Invalid retry_failures: {e}"})

            # Explicit arg takes priority; fall back to what was baked into the token
            effective_project_name = project_name or embedded_project_name

            succeeded, still_failed, retry_link_ops = _retry_failed_ops(failed_ops)

            # Persist any newly linked Todoist IDs back to local todos so future
            # syncs don't try to create the same tasks again.
            if retry_link_ops:
                proj_result = require_project(effective_project_name)
                if not isinstance(proj_result, str):
                    retry_cfg, retry_name = proj_result
                    apply_changes(
                        ApplyInput(link_todoist_ids=retry_link_ops),
                        retry_cfg,
                        retry_name,
                        push_confirmed=True,
                    )

            if still_failed:
                token_data = {"project_name": effective_project_name, "ops": still_failed}
                token = base64.b64encode(json.dumps(token_data).encode()).decode()
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
        project_todoist_id = meta.todoist_project_id

        # 3. Empty project → up_to_date without socket calls
        todos = storage.load_todos(cfg, name)
        has_local_todos = bool(todos)
        has_todoist_project = bool(project_todoist_id)

        if not has_local_todos and not has_todoist_project:
            return json.dumps({
                "status": "success",
                "summary": {"up_to_date": True},
            })

        # 4. Fetch tasks from Todoist via socket
        todoist_tasks: list[dict[str, Any]] = []
        if project_todoist_id:
            try:
                fetch_result = _call_todoist_tool(
                    "todoist_find_tasks",
                    {"project_id": project_todoist_id},
                )
                if isinstance(fetch_result, list):
                    todoist_tasks = fetch_result
                elif isinstance(fetch_result, dict):
                    todoist_tasks = fetch_result.get("tasks", [])
            except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
                return json.dumps({
                    "status": "error",
                    "error": f"Todoist plugin unavailable: {e}",
                })
            except Exception as e:
                return json.dumps({
                    "status": "error",
                    "error": f"Failed to fetch Todoist tasks: {e}",
                })

        # 5. Compute diff
        plan = compute_diff(todoist_tasks, cfg, name)

        # 6. Handle confirmed_links: apply link mappings before continuing
        parsed_links: list[dict[str, str]] = []
        if confirmed_links:
            try:
                parsed_links = json.loads(confirmed_links)
            except json.JSONDecodeError as e:
                return json.dumps({"status": "error", "error": f"Invalid confirmed_links: {e}"})

            # Apply confirmed links
            if parsed_links:
                link_data = ApplyInput(
                    link_todoist_ids=parsed_links,
                )
                apply_changes(link_data, cfg, name, push_confirmed=True)
                # Clear potential_links since they've been confirmed
                plan.potential_links = []
                # Recompute diff after linking
                plan = compute_diff(todoist_tasks, cfg, name)

        # 7. Check for potential_links requiring user confirmation
        if plan.potential_links and not confirmed_links:
            return json.dumps({
                "status": "needs_confirmation",
                "potential_links": plan.potential_links,
            })

        # 8. Empty diff -> up to date
        if plan.is_empty():
            return json.dumps({
                "status": "success",
                "summary": {"up_to_date": True},
            })

        # 9. Phase A: Apply pull operations locally (push_confirmed=False)
        has_pulls = bool(plan.pull_create or plan.pull_update or plan.pull_complete)
        if has_pulls:
            pull_data = ApplyInput(
                created_locally=plan.pull_create,  # type: ignore[arg-type]
                updated_locally=plan.pull_update,  # type: ignore[arg-type]
                completed_locally=plan.pull_complete,
            )
            pull_counts = apply_changes(pull_data, cfg, name, push_confirmed=False)
        else:
            pull_counts = {
                "created": 0, "updated": 0, "completed": 0,
                "linked": 0, "cleared": 0,
                "staged_description_synced": {},
            }

        staged_desc = pull_counts.get("staged_description_synced", {})

        # 10. Execute push operations
        all_errors: list[dict[str, Any]] = []
        total_push_created = 0
        total_push_created_p2 = 0
        total_push_updated = 0
        total_push_completed = 0
        total_ghost_closed = 0
        total_root_cleaned = 0

        # 10a. Ghost close
        ghost_succeeded, ghost_errors = _execute_ghost_close(plan.ghost_close)
        total_ghost_closed = len(ghost_succeeded)
        all_errors.extend(ghost_errors)

        # 10b. Root-only cleanup
        cleanup_succeeded, cleanup_errors = _execute_root_only_cleanup(plan.root_only_cleanup)
        total_root_cleaned = len(cleanup_succeeded)
        all_errors.extend(cleanup_errors)

        # 10c. Push creates (phase 1)
        p1_succeeded, p1_errors, phase1_id_map = _execute_push_creates(
            plan.push_create, project_todoist_id,  # type: ignore[arg-type]
        )
        total_push_created = len(p1_succeeded)
        all_errors.extend(p1_errors)

        # 10d. Push creates (phase 2) — children needing phase-1 parent IDs
        p2_succeeded, p2_errors, phase2_id_map = _execute_push_creates_phase2(
            plan.push_create_phase2, phase1_id_map,  # type: ignore[arg-type]
        )
        total_push_created_p2 = len(p2_succeeded)
        all_errors.extend(p2_errors)

        # 10e. Push updates
        update_succeeded, update_errors = _execute_push_updates(plan.push_update)  # type: ignore[arg-type]
        total_push_updated = len(update_succeeded)
        all_errors.extend(update_errors)

        # 10f. Push completes
        complete_succeeded, complete_errors = _execute_push_completes(plan.push_complete)
        total_push_completed = len(complete_succeeded)
        all_errors.extend(complete_errors)

        # 11. Phase B: Link newly created Todoist IDs and apply staged values
        combined_id_map = {**phase1_id_map, **phase2_id_map}
        link_ops: list[dict[str, str]] = []
        for task in p1_succeeded + p2_succeeded:
            todo_id = str(task.get("todo_id", ""))
            todoist_id = str(task.get("result_todoist_id", ""))
            if todo_id and todoist_id:
                link_ops.append({"todo_id": todo_id, "todoist_task_id": todoist_id})

        # Clear todoist IDs for root_only cleanup
        cleared_ids = [str(entry.get("todo_id", "")) for entry in cleanup_succeeded]

        # Build staged description_synced updates
        staged_updates: list[dict[str, Any]] = []
        if staged_desc:
            for todo_id, desc_val in staged_desc.items():
                staged_updates.append({
                    "todo_id": todo_id,
                    "todoist_description_synced": desc_val,
                })

        if link_ops or cleared_ids or staged_updates:
            link_data = ApplyInput(
                link_todoist_ids=link_ops,
                cleared_todoist_ids=cleared_ids,
                updated_locally=staged_updates,
            )
            apply_changes(link_data, cfg, name, push_confirmed=True)

        # 12. Build response
        summary = _build_summary(
            plan, pull_counts,
            total_push_created, total_push_created_p2,
            total_push_updated, total_push_completed,
            total_ghost_closed, total_root_cleaned,
        )

        if all_errors:
            # Embed project name so the retry path can persist IDs without
            # needing an active session.
            token_data = {"project_name": name, "ops": all_errors}
            token = base64.b64encode(json.dumps(token_data).encode()).decode()
            return json.dumps({
                "status": "partial_success",
                "summary": summary,
                "errors": all_errors,
                "retry_token": token,
            })

        return json.dumps({
            "status": "success",
            "summary": summary,
        })
