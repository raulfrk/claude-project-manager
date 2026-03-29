"""MCP tools for batched Todoist sync — diff and apply."""

from __future__ import annotations

import difflib
import json
import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import TYPE_CHECKING, Any

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import Todo
from server.lib.retry import retry_link
from server.tools.config import require_project

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

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
    return [str(x) for x in labels] if isinstance(labels, list) else []  # type: ignore[union-attr]  # list[object] from JSON; items are str at runtime


def _parse_todoist_due(task: dict[str, Any]) -> str | None:
    """Extract due date from task."""
    due_raw = task.get("due")
    if isinstance(due_raw, dict) and "date" in due_raw:  # type: ignore[operator]  # dict from JSON
        return str(due_raw["date"])  # type: ignore[index]  # dict access valid at runtime
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
    import unicodedata, re

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
    """Find a local todo that likely matches an unlinked Todoist task by title similarity.

    Reverse direction of _find_link_candidate: given a Todoist task, find the
    best-matching local Todo object.
    """
    import unicodedata, re

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
            tags=list(item["tags"]) if isinstance(item.get("tags"), list) else [],  # type: ignore[arg-type]  # list[object] from JSON; list[str] at runtime
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
            todo.tags = list(item["tags"])  # type: ignore[arg-type]  # list[object] from JSON; list[str] at runtime
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


# ── MCP tool registration ────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register todoist sync tools."""

    @app.tool(
        description=(
            "Compare Todoist tasks with local todos and produce a sync plan. "
            "Takes Todoist task data as JSON (from find-tasks). Returns a JSON "
            "sync plan with batched operations for both sides. "
            "When auto_apply=True, pull operations (pull_create, pull_update, "
            "pull_complete) are applied locally immediately and the response "
            "includes project_info (mcp_server, todoist_project_id) so the "
            "caller can skip separate config_load/proj_get_active calls. "
            "Set summary_only=True to return only summary counts, not full plan arrays."
        )
    )
    def proj_todoist_diff(
        todoist_tasks_json: str,
        auto_apply: bool = False,
        summary_only: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        try:
            todoist_tasks: list[dict[str, Any]] = json.loads(todoist_tasks_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        plan = compute_diff(todoist_tasks, cfg, name)

        if not auto_apply:
            plan_dict = plan.to_dict()
            if summary_only:
                return json.dumps({"summary": plan_dict["summary"]}, indent=2)
            return json.dumps(plan_dict, indent=2)

        # auto_apply mode: apply pull operations server-side
        meta = storage.load_meta(cfg, name)
        plan_dict = plan.to_dict()
        response: dict[str, object] = {
            "plan": {"summary": plan_dict["summary"]} if summary_only else plan_dict,
            "project_info": {
                "mcp_server": "todoist",  # Deprecated: config field ignored; local plugin uses fixed "todoist" prefix
                "todoist_project_id": meta.todoist_project_id or "",
            },
        }

        has_pulls = bool(plan.pull_create or plan.pull_update or plan.pull_complete)
        if has_pulls:
            pull_data = ApplyInput(
                created_locally=plan.pull_create,  # type: ignore[arg-type]
                updated_locally=plan.pull_update,  # type: ignore[arg-type]
                completed_locally=plan.pull_complete,
            )
            counts = apply_changes(pull_data, cfg, name)
            response["auto_applied"] = counts
        else:
            response["auto_applied"] = {
                "created": 0, "updated": 0, "completed": 0,
                "linked": 0, "cleared": 0,
            }

        return json.dumps(response, indent=2)

    @app.tool(
        description=(
            "Apply sync results to local todos in bulk. Takes a JSON "
            "object with: created_locally, updated_locally, "
            "completed_locally, link_todoist_ids, cleared_todoist_ids. "
            "All changes are applied atomically in a single save."
        )
    )
    def proj_todoist_apply(
        apply_json: str,
        push_confirmed: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        try:
            raw: dict[str, Any] = json.loads(apply_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        data = ApplyInput(
            created_locally=raw.get("created_locally", []),
            updated_locally=raw.get("updated_locally", []),
            completed_locally=raw.get("completed_locally", []),
            link_todoist_ids=raw.get("link_todoist_ids", []),
            cleared_todoist_ids=raw.get("cleared_todoist_ids", []),
        )
        counts = apply_changes(data, cfg, name, push_confirmed=push_confirmed)
        return json.dumps({"status": "ok", "counts": counts})
