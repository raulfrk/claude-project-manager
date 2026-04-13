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
import re
import warnings
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import JsonValue, ProjConfig, Todo
from server.lib.retry import retry_link
from server.tools.config import require_project

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ── Priority mapping ─────────────────────────────────────────────────────────

_TODOIST_TO_LOCAL: dict[str, str] = {"p1": "high", "p2": "high", "p3": "medium", "p4": "low"}
_LOCAL_TO_TODOIST: dict[str, str] = {"high": "p2", "medium": "p3", "low": "p4"}

_UTC = UTC


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string for time precision."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


def _today() -> str:
    return str(date.today())


def _todoist_date(updated_at: str) -> str:
    """Normalise a Todoist ISO datetime to a naive UTC datetime string.

    Strips the trailing 'Z' / '+00:00' offset so the result can be compared
    directly against local_todo.updated (also a naive UTC string).
    Returns "" when the input is empty.
    """
    if not updated_at:
        return ""
    # Strip timezone suffix so both sides are naive ISO strings
    return updated_at.rstrip("Z").split("+")[0].split("-00:00")[0]


def _ts_newer(a: str, b: str) -> bool:
    """Return True if timestamp *a* is strictly newer than *b*.

    Both are expected to be naive ISO 8601 strings (no timezone).
    Falls back to string comparison when parsing fails, which is safe
    for well-formed ISO strings of the same format.
    """
    try:
        return datetime.fromisoformat(a) > datetime.fromisoformat(b)
    except (ValueError, TypeError):
        return a > b


def _content_differs(local: Todo, task: dict[str, JsonValue]) -> bool:
    """Return True if local todo content differs from the Todoist task.

    Compares the fields that would be pushed: title, priority, labels, due date.
    Used as a guard before push_update so identical data never triggers a push.
    """
    todoist_priority = _parse_todoist_priority(task)
    if local.title != str(task.get("content", "")):
        logger.warning(
            "content_differs[%s]: title %r != %r",
            task.get("id", "?"),
            local.title,
            task.get("content", ""),
        )
        return True
    if local.priority != todoist_priority:
        logger.warning(
            "content_differs[%s]: priority %r != %r (raw=%r)",
            task.get("id", "?"),
            local.priority,
            todoist_priority,
            task.get("priority"),
        )
        return True
    todoist_labels = _parse_todoist_labels(task)
    if sorted(local.tags) != sorted(todoist_labels):
        logger.warning(
            "content_differs[%s]: labels %r != %r",
            task.get("id", "?"),
            local.tags,
            todoist_labels,
        )
        return True
    todoist_due = _parse_todoist_due(task)
    if (local.due_date or None) != (todoist_due or None):
        logger.warning(
            "content_differs[%s]: due %r != %r",
            task.get("id", "?"),
            local.due_date,
            todoist_due,
        )
        return True
    return False


def _ghost_check(title: str, archived: list[Todo], threshold: float = 0.7) -> bool:
    """Return True if title matches an archived todo (exact or fuzzy)."""
    if not archived:
        return False
    lower_title = title.lower()
    titles = [t.title for t in archived]
    if any(t.lower() == lower_title for t in titles):
        return True
    return bool(difflib.get_close_matches(title, titles, n=1, cutoff=threshold))


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Normalize a title for dedup comparison: lowercase, collapse whitespace, strip."""
    return _WHITESPACE_RE.sub(" ", title.strip()).lower()


def _reconcile_unlinked_todos(
    todos: list[Todo],
    todoist_tasks: list[dict[str, JsonValue]],
    cfg: ProjConfig,
    name: str,
) -> int:
    """Pre-sync reconciliation: link local todos with null todoist_task_id to
    existing Todoist tasks by normalized title match.

    Only auto-links when the match is unambiguous: exactly one unlinked local
    todo matches exactly one unclaimed Todoist task on the same normalized title.
    Ambiguous matches (multiple candidates) are left for the potential_links
    confirmation flow in compute_diff.

    Returns the number of todos that were reconciled (linked).
    """
    # Collect unlinked local todos (open, no todoist_task_id)
    unlinked = [t for t in todos if not t.todoist_task_id and t.status not in TERMINAL_STATUSES]
    if not unlinked or not todoist_tasks:
        return 0

    # Build index: normalized title -> list of Todoist tasks
    todoist_by_norm_title: dict[str, list[dict[str, JsonValue]]] = {}
    # Track which Todoist task IDs are already claimed by local todos
    claimed_todoist_ids: set[str] = {t.todoist_task_id for t in todos if t.todoist_task_id}
    for task in todoist_tasks:
        tid = str(task.get("id", ""))
        if not tid or tid in claimed_todoist_ids:
            continue
        norm = _normalize_title(str(task.get("content", "")))
        if norm:
            todoist_by_norm_title.setdefault(norm, []).append(task)

    if not todoist_by_norm_title:
        return 0

    # Build index: normalized title -> list of unlinked local todos
    local_by_norm_title: dict[str, list[Todo]] = {}
    for todo in unlinked:
        norm = _normalize_title(todo.title)
        if norm:
            local_by_norm_title.setdefault(norm, []).append(todo)

    # Build parent todoist_task_id lookup for context matching
    local_by_id: dict[str, Todo] = {t.id: t for t in todos}

    link_ops: list[dict[str, str]] = []
    matched_todoist_ids: set[str] = set()
    matched_local_ids: set[str] = set()

    for norm_title, local_group in local_by_norm_title.items():
        todoist_group = todoist_by_norm_title.get(norm_title)
        if not todoist_group:
            continue

        # Filter already-matched from both sides
        avail_local = [t for t in local_group if t.id not in matched_local_ids]
        avail_todoist = [
            c for c in todoist_group if str(c.get("id", "")) not in matched_todoist_ids
        ]

        if not avail_local or not avail_todoist:
            continue

        # Unambiguous case: 1 local <-> 1 Todoist with parent-context evidence.
        # Only auto-link when parent context confirms the match. Without parent
        # context, 1:1 matches go through the potential_links confirmation flow
        # in compute_diff (could be a coincidental title match).
        if len(avail_local) == 1 and len(avail_todoist) == 1:
            todo = avail_local[0]
            candidate = avail_todoist[0]
            todoist_id = str(candidate.get("id", ""))
            # Require parent-context confirmation for auto-link
            if todoist_id and todo.parent:
                parent_todo = local_by_id.get(todo.parent)
                parent_todoist_id = parent_todo.todoist_task_id if parent_todo else None
                cand_parent = str(candidate.get("parent_id", "") or "")
                if parent_todoist_id and cand_parent == parent_todoist_id:
                    link_ops.append({"todo_id": todo.id, "todoist_task_id": todoist_id})
                    matched_todoist_ids.add(todoist_id)
                    matched_local_ids.add(todo.id)
                    logger.info(
                        "Reconciled todo %s (%r) -> Todoist task %s",
                        todo.id,
                        todo.title,
                        todoist_id,
                    )
            continue

        # Ambiguous case: try parent-context disambiguation
        for todo in avail_local:
            if todo.id in matched_local_ids:
                continue
            if not todo.parent:
                continue
            parent_todo = local_by_id.get(todo.parent)
            parent_todoist_id = parent_todo.todoist_task_id if parent_todo else None
            if not parent_todoist_id:
                continue
            for candidate in avail_todoist:
                cid = str(candidate.get("id", ""))
                if cid in matched_todoist_ids:
                    continue
                if str(candidate.get("parent_id", "") or "") == parent_todoist_id:
                    link_ops.append({"todo_id": todo.id, "todoist_task_id": cid})
                    matched_todoist_ids.add(cid)
                    matched_local_ids.add(todo.id)
                    logger.info(
                        "Reconciled (parent-ctx) todo %s (%r) -> Todoist task %s",
                        todo.id,
                        todo.title,
                        cid,
                    )
                    break

    # Persist links
    if link_ops:
        link_data = ApplyInput(link_todoist_ids=link_ops)
        apply_changes(link_data, cfg, name, push_confirmed=True)
        logger.info("Pre-sync reconciliation linked %d todos", len(link_ops))

    return len(link_ops)


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


def _parse_todoist_priority(task: dict[str, JsonValue]) -> str:
    """Map Todoist priority to local priority string.

    Handles both raw Todoist API values (integers like 4, or p-strings like "p4")
    and already-converted local strings ("low", "medium", "high") that come back
    from TodoistTask.to_dict() via todoist_find_tasks.
    """
    raw = task.get("priority")
    if raw in ("low", "medium", "high"):
        return str(raw)
    if isinstance(raw, str) and raw.startswith("p"):
        return _TODOIST_TO_LOCAL.get(raw, "low")
    if isinstance(raw, int):
        return _TODOIST_TO_LOCAL.get(f"p{raw}", "low")
    return "low"


def _parse_todoist_labels(task: dict[str, JsonValue]) -> list[str]:
    """Extract labels list from task."""
    labels = task.get("labels")
    return [str(x) for x in labels] if isinstance(labels, list) else []


def _parse_todoist_due(task: dict[str, JsonValue]) -> str | None:
    """Extract due date from task."""
    due_raw = task.get("due")
    if isinstance(due_raw, dict) and "date" in due_raw:
        return str(due_raw["date"])
    return None


def _parse_todoist_updated(task: dict[str, JsonValue]) -> str:
    """Extract updated_at date from task dict."""
    raw: str = str(task.get("updated_at") or "")
    return _todoist_date(raw)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class SyncPlan:
    """Result of comparing Todoist tasks with local todos."""

    pull_create: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_update: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_complete: list[str] = field(default_factory=list)
    push_create: list[dict[str, JsonValue]] = field(default_factory=list)
    push_create_phase2: list[dict[str, JsonValue]] = field(default_factory=list)
    push_update: list[dict[str, JsonValue]] = field(default_factory=list)
    push_complete: list[str] = field(default_factory=list)
    push_reopen: list[str] = field(default_factory=list)
    ghost_close: list[str] = field(default_factory=list)
    potential_links: list[dict[str, JsonValue]] = field(default_factory=list)
    root_only_cleanup: list[dict[str, str]] = field(default_factory=list)
    stale_ids_skipped: int = 0
    archived_completions_pushed: int = 0

    def is_empty(self) -> bool:
        return not any(
            [
                self.pull_create,
                self.pull_update,
                self.pull_complete,
                self.push_create,
                self.push_create_phase2,
                self.push_update,
                self.push_complete,
                self.push_reopen,
                self.ghost_close,
                self.potential_links,
                self.root_only_cleanup,
            ]
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "pull_create": self.pull_create,
            "pull_update": self.pull_update,
            "pull_complete": self.pull_complete,
            "push_create": self.push_create,
            "push_create_phase2": self.push_create_phase2,
            "push_update": self.push_update,
            "push_complete": self.push_complete,
            "push_reopen": self.push_reopen,
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
                "push_reopen_count": len(self.push_reopen),
                "ghost_close_count": len(self.ghost_close),
                "potential_links_count": len(self.potential_links),
                "root_only_cleanup_count": len(self.root_only_cleanup),
                "archived_completions_pushed_count": self.archived_completions_pushed,
            },
        }


@dataclass
class ApplyInput:
    """Input for applying sync changes locally."""

    created_locally: list[dict[str, JsonValue]] = field(default_factory=list)
    updated_locally: list[dict[str, JsonValue]] = field(default_factory=list)
    completed_locally: list[str] = field(default_factory=list)
    link_todoist_ids: list[dict[str, str]] = field(default_factory=list)
    cleared_todoist_ids: list[str] = field(default_factory=list)


# ── Core logic (standalone functions) ─────────────────────────────────────────


def _compute_todoist_depth(task_id: str, todoist_by_id: dict[str, dict[str, JsonValue]]) -> int:
    """Walk the parent_id chain counting hops. Returns 0 for root tasks.

    Uses a ``seen`` set for cycle detection and caps at depth 10.
    """
    depth = 0
    current = task_id
    seen: set[str] = set()
    while depth < 10:
        task = todoist_by_id.get(current)
        if task is None:
            break
        parent = str(task.get("parent_id") or "")
        if not parent:
            break
        if parent == current:
            # Self-reference — stop immediately
            break
        if parent in seen:
            break
        seen.add(current)
        current = parent
        depth += 1
    return depth


def _find_link_candidate(
    local_todo: dict[str, JsonValue],
    todoist_tasks: list[dict[str, JsonValue]],
    threshold: float = 0.7,
) -> dict[str, JsonValue] | None:
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

    local_title = str(local_todo.get("title", ""))
    best_match = None
    best_score = 0.0
    for task in todoist_tasks:
        task_content = str(task.get("content", ""))
        score = similarity(local_title, task_content)
        if score > best_score:
            best_score = score
            best_match = task
    if best_score >= threshold and best_match:
        return {"todo": local_todo, "task": best_match, "score": best_score}
    return None


def _find_link_candidate_reverse(
    todoist_task: dict[str, JsonValue], local_todos: list[Todo], threshold: float = 0.7
) -> dict[str, Todo | JsonValue] | None:
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

    task_content = str(todoist_task.get("content", ""))
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


def _infer_parent_link_from_children(
    todoist_id: str,
    todoist_by_id: Mapping[str, JsonValue],
    local_by_todoist_id: dict[str, Todo],
    local_by_id: dict[str, Todo],
) -> Todo | None:
    """Infer local parent by checking whether Todoist children are already linked locally.

    Returns the local parent Todo if ALL linked Todoist children agree on the same
    local parent. Returns None if no linked children exist, children disagree, or
    no local child has a parent set.
    """
    todoist_children = [
        t
        for t in todoist_by_id.values()
        if isinstance(t, dict) and str(t.get("parent_id") or "") == todoist_id
    ]
    if not todoist_children:
        return None

    local_child_parents: set[str] = set()
    for child_task in todoist_children:
        child_id = str(child_task.get("id", ""))
        linked_local = local_by_todoist_id.get(child_id)
        if linked_local and linked_local.parent:
            local_child_parents.add(linked_local.parent)

    if len(local_child_parents) != 1:
        return None  # No linked children, or children disagree on parent

    parent_id = next(iter(local_child_parents))
    return local_by_id.get(parent_id)


def _collect_descendant_todoist_ids(
    todo: Todo,
    local_by_id: dict[str, Todo],
    allowed_ids: set[str] | None = None,
) -> list[str]:
    """Walk todo.children recursively, collecting todoist_task_ids of terminal descendants.

    When *allowed_ids* is provided, only IDs present in the set are included.
    This filters out stale IDs whose Todoist tasks are no longer in the active fetch.
    """
    result: list[str] = []
    seen: set[str] = set()
    stack = list(todo.children) if todo.children else []
    while stack:
        child_id = stack.pop()
        if child_id in seen:
            continue
        seen.add(child_id)
        child = local_by_id.get(child_id)
        if child is None:
            continue
        if (
            child.todoist_task_id
            and child.status in TERMINAL_STATUSES
            and (allowed_ids is None or child.todoist_task_id in allowed_ids)
        ):
            result.append(child.todoist_task_id)
        if child.children:
            stack.extend(child.children)
    return list(dict.fromkeys(result))


def compute_diff(
    todoist_tasks: list[dict[str, JsonValue]],
    cfg: ProjConfig,
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
    todoist_by_id: dict[str, dict[str, JsonValue]] = {}
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

    # Build a set of Todoist IDs claimed by archived todos. Used to suppress
    # re-pulling and to reconcile any still-open Todoist tasks below.
    archived_todoist_ids: set[str] = {
        t.todoist_task_id
        for t in archived
        if t.todoist_task_id and t.todoist_task_id not in local_by_todoist_id
    }

    plan = SyncPlan()

    # Track local todo IDs matched via link candidates so they're excluded from push_create
    linked_local_ids: set[str] = set()

    # Pre-build local_by_id for child-inference lookups (O(n) once, not per task)
    local_by_id: dict[str, Todo] = {t.id: t for t in todos}

    # ── Todoist -> Local (pull) ───────────────────────────────────────

    for todoist_id, task in todoist_by_id.items():
        content = str(task.get("content", ""))
        local_priority = _parse_todoist_priority(task)
        todoist_labels = _parse_todoist_labels(task)
        todoist_desc = str(task.get("description", "") or "")
        todoist_due = _parse_todoist_due(task)
        todoist_updated = _parse_todoist_updated(task)

        if todoist_id not in local_by_todoist_id:
            # New task from Todoist — skip if it belongs to an archived todo
            # (was done locally; don't re-pull as a new task)
            if todoist_id in archived_todoist_ids:
                continue
            # Ghost check (title-based fallback for todos archived before ID was saved)
            if _ghost_check(content, archived):
                plan.ghost_close.append(todoist_id)
                continue
            # Child-based parent inference: if this task's Todoist children are already
            # linked to local todos, infer the local parent from those children.
            # This catches duplicates where the local parent is already linked to a
            # different Todoist ID (and therefore not in local_unlinked).
            parent_match = _infer_parent_link_from_children(
                todoist_id, todoist_by_id, local_by_todoist_id, local_by_id
            )
            if parent_match:
                plan.potential_links.append(
                    {
                        "local_todo": {"id": parent_match.id, "title": parent_match.title},
                        "todoist_task": {"id": todoist_id, "content": content},
                        "score": 1.0,
                    }
                )
                linked_local_ids.add(parent_match.id)
                continue
            # Link candidate check: see if an unlinked local todo matches this Todoist task
            link_match = _find_link_candidate_reverse(task, local_unlinked)
            if link_match:
                matched_todo_val = link_match["local_todo"]
                if not isinstance(matched_todo_val, Todo):
                    raise TypeError(f"Expected Todo, got {type(matched_todo_val).__name__}")
                matched_todo: Todo = matched_todo_val
                score = link_match["score"]
                link_entry: dict[str, JsonValue] = {
                    "local_todo": {"id": matched_todo.id, "title": matched_todo.title},
                    "todoist_task": {"id": todoist_id, "content": content},
                    "score": float(score) if isinstance(score, (int, float)) else 0.0,
                }
                plan.potential_links.append(link_entry)
                linked_local_ids.add(matched_todo.id)
                continue
            # Prepare for local creation
            new_notes, new_synced = _apply_description_sync("", "", todoist_desc)
            plan.pull_create.append(
                {
                    "title": content,
                    "priority": local_priority,
                    "tags": todoist_labels,
                    "notes": new_notes,
                    "due_date": todoist_due,
                    "todoist_task_id": todoist_id,
                    "todoist_description_synced": new_synced,
                    "todoist_parent_id": str(task.get("parent_id") or "") or None,
                }
            )
        else:
            # Existing — check timestamps
            local_todo = local_by_todoist_id[todoist_id]
            if _ts_newer(todoist_updated, local_todo.updated):
                # Todoist is newer — prepare update
                new_notes, new_synced = _apply_description_sync(
                    local_todo.notes, local_todo.todoist_description_synced, todoist_desc
                )
                update_entry: dict[str, JsonValue] = {
                    "todo_id": local_todo.id,
                    "title": content,
                    "priority": local_priority,
                    "tags": todoist_labels,
                    "notes": new_notes,
                    "due_date": todoist_due,
                    "todoist_description_synced": new_synced,
                    # Carry Todoist's timestamp so apply_changes can set local
                    # updated to match, preventing an immediate push next sync.
                    "todoist_updated_at": todoist_updated,
                }
                # Check if Todoist task is completed — only pull if Todoist is newer
                if task.get("is_completed") and _ts_newer(todoist_updated, local_todo.updated):
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
            if task.get("parent_id"):
                cleanup_todo = local_by_todoist_id.get(todoist_id)
                if cleanup_todo and cleanup_todo.parent:
                    plan.root_only_cleanup.append(
                        {
                            "todoist_task_id": todoist_id,
                            "todo_id": cleanup_todo.id,
                        }
                    )

    # Split unlinked into roots (phase 1) and children-of-unlinked (phase 2)
    # Exclude todos that were matched as link candidates to prevent duplicate push_create.
    # Also exclude children of child-inferred parents — their parent won't be created via
    # push_create so they'd have an unresolvable _parent_local_id in phase 2.
    remaining_unlinked = [
        t
        for t in local_unlinked
        if t.id not in linked_local_ids and not (t.parent and t.parent in linked_local_ids)
    ]
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

        entry: dict[str, JsonValue] = {
            "todo_id": todo.id,
            "content": todo.title,
            "priority": todoist_priority,
            "description": todo.notes,
            "labels": todo.tags,
        }
        if todo.due_date:
            entry["dueString"] = todo.due_date
        if parent_todoist_id:
            entry["parent_id"] = parent_todoist_id
        if meta.todoist_project_id:
            entry["project_id"] = meta.todoist_project_id
        if todo.status == TodoStatus.DONE:
            entry["complete_after_create"] = True
        plan.push_create.append(entry)

    # Phase 2: children whose parent is also unlinked (needs phase 1 to resolve parent)
    for todo in sorted(unlinked_children, key=lambda t: t.id):
        todoist_priority = _LOCAL_TO_TODOIST.get(todo.priority, "p4")
        entry_p2: dict[str, JsonValue] = {
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
            if (
                _ts_newer(local_todo.updated, todoist_updated)
                and local_todo.status not in TERMINAL_STATUSES
                and _content_differs(local_todo, task)
            ):
                todoist_priority = _LOCAL_TO_TODOIST.get(local_todo.priority, "p4")
                update_entry_push: dict[str, JsonValue] = {
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
                # Local is done, Todoist still open — push complete if local is newer
                if not task.get("is_completed") and _ts_newer(local_todo.updated, todoist_updated):
                    plan.push_complete.append(todoist_id)
            elif local_todo.status not in TERMINAL_STATUSES and task.get("is_completed"):
                # Local is open, Todoist is completed — push reopen if local is newer
                if _ts_newer(local_todo.updated, todoist_updated):
                    plan.push_reopen.append(todoist_id)

    # ── Count stale IDs: locally-done todos whose Todoist task is not in active fetch ──
    push_complete_set = set(plan.push_complete)
    for todoist_id, local_todo in local_by_todoist_id.items():
        if (
            local_todo.status in TERMINAL_STATUSES
            and todoist_id not in push_complete_set
            and todoist_id not in todoist_by_id
        ):
            plan.stale_ids_skipped += 1

    # ── Reconcile: archived local todos whose Todoist task is still open ──
    # Complements the pull-suppression filter above; both use archived_todoist_ids.
    # Intersect with todoist_by_id so we only close tasks that are actually open.
    archived_open_ids = (archived_todoist_ids & todoist_by_id.keys()) - set(plan.push_complete)
    plan.push_complete.extend(archived_open_ids)
    plan.archived_completions_pushed = len(archived_open_ids)

    # ── Parent cascade: collect descendant todoist IDs for completed parents ──
    active_todoist_ids = set(todoist_by_id.keys())
    for todo in todos:
        if todo.children and todo.status in TERMINAL_STATUSES and todo.todoist_task_id:
            descendant_ids = _collect_descendant_todoist_ids(
                todo, local_by_id, allowed_ids=active_todoist_ids
            )
            plan.push_complete.extend(descendant_ids)

    # Filter push_complete to exclude IDs in root_only_cleanup
    cleanup_todoist_ids = {entry["todoist_task_id"] for entry in plan.root_only_cleanup}
    plan.push_complete = [tid for tid in plan.push_complete if tid not in cleanup_todoist_ids]
    # Deduplicate preserving order
    plan.push_complete = list(dict.fromkeys(plan.push_complete))

    # ── Fix parent linkage for linked todos missing Todoist parent_id ──
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
        if task.get("parent_id"):
            continue
        # Todoist task is missing parent_id — push an update to set it
        plan.push_update.append(
            {
                "id": todoist_id,
                "parent_id": parent_todo.todoist_task_id,
            }
        )

    return plan


def apply_changes(
    data: ApplyInput,
    cfg: ProjConfig,
    name: str,
    push_confirmed: bool = False,
) -> dict[str, JsonValue]:
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
    todo: Todo | None

    int_counts: dict[str, int] = {
        "created": 0,
        "updated": 0,
        "completed": 0,
        "linked": 0,
        "relinked": 0,
        "cleared": 0,
    }

    # Staged description_synced values when push_confirmed is False
    staged_description_synced: dict[str, str] = {}

    # 1. Create new todos
    # Build todoist_task_id → local todo id map from existing todos
    todoist_to_local: dict[str, str] = {}
    for t in todos:
        if t.todoist_task_id:
            todoist_to_local[t.todoist_task_id] = t.id

    # Build synthetic todoist_by_id from pull_create items for depth computation
    synthetic_todoist_by_id: dict[str, dict[str, JsonValue]] = {}
    for item in data.created_locally:
        tid = str(item.get("todoist_task_id", ""))
        if tid:
            synthetic_todoist_by_id[tid] = {
                "parent_id": item.get("todoist_parent_id") or "",
            }

    # Sort by Todoist depth ascending so parents are created before children
    data.created_locally.sort(
        key=lambda it: _compute_todoist_depth(
            str(it.get("todoist_task_id", "")), synthetic_todoist_by_id
        )
    )

    # Track orphans: items whose todoist_parent_id couldn't be resolved
    pull_create_orphans: list[tuple[str, str]] = []

    for item in data.created_locally:
        # Resolve parent: explicit "parent" field takes priority
        parent_id = str(item["parent"]) if item.get("parent") else None
        parent_todo = todo_map.get(parent_id) if parent_id else None

        # If no explicit parent, try resolving via todoist_parent_id
        if not parent_todo:
            todoist_parent_id = str(item.get("todoist_parent_id") or "")
            if todoist_parent_id:
                local_parent_id = todoist_to_local.get(todoist_parent_id)
                if local_parent_id:
                    parent_todo = todo_map.get(local_parent_id)
                else:
                    # Parent not found — track as orphan for 448.4
                    item_tid = str(item.get("todoist_task_id", ""))
                    pull_create_orphans.append((item_tid, todoist_parent_id))

        desc_synced_value = str(item.get("todoist_description_synced", ""))
        todo = Todo(
            id=next_todo_id(meta, parent=parent_todo),
            title=str(item.get("title", "")),
            priority=str(item.get("priority", cfg.default_priority)),
            tags=[str(t) for t in tags_raw]
            if isinstance((tags_raw := item.get("tags")), list)
            else [],
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
            todo.parent = parent_todo.id
            parent_todo.children.append(todo.id)
            parent_todo.updated = today
        todos.append(todo)
        todo_map[todo.id] = todo
        # Update todoist_to_local so subsequent children can find this parent
        if todo.todoist_task_id:
            todoist_to_local[todo.todoist_task_id] = todo.id
        int_counts["created"] += 1
    # 2. Update existing todos
    _CONTENT_FIELDS = {"title", "priority", "tags", "notes", "due_date"}
    for item in data.updated_locally:
        todo_id = str(item.get("todo_id", ""))
        todo = todo_map.get(todo_id)
        if not todo:
            continue
        content_changed = False
        if "title" in item and item["title"] is not None:
            todo.title = str(item["title"])
            content_changed = True
        if "priority" in item and item["priority"] is not None:
            todo.priority = str(item["priority"])
            content_changed = True
        if "tags" in item and isinstance(item["tags"], list):
            todo.tags = [str(t) for t in item["tags"]]
            content_changed = True
        if "notes" in item and item["notes"] is not None:
            todo.notes = str(item["notes"])
            content_changed = True
        if "due_date" in item:
            todo.due_date = str(item["due_date"]) if item["due_date"] else None
            content_changed = True
        if "todoist_task_id" in item:
            todo.todoist_task_id = str(item["todoist_task_id"]) if item["todoist_task_id"] else None
        if "todoist_description_synced" in item:
            desc_synced_value = str(item.get("todoist_description_synced", ""))
            if push_confirmed:
                todo.todoist_description_synced = desc_synced_value
            else:
                staged_description_synced[todo_id] = desc_synced_value
        # Only update the timestamp when content actually changed.
        # Use the Todoist timestamp if provided (pull updates) so local updated
        # matches Todoist's updated_at and doesn't immediately trigger a push back.
        # Metadata-only writes (todoist_description_synced, todoist_task_id) must
        # NOT bump updated — they would make the todo look locally newer next sync.
        if content_changed:
            todoist_ts = str(item.get("todoist_updated_at", ""))
            todo.updated = todoist_ts if todoist_ts else today
        int_counts["updated"] += 1
    # 3. Link todoist IDs (after push_create returns Todoist task IDs)
    tracking_path = str(storage.tracking_dir(cfg, name))
    for link_item in data.link_todoist_ids:
        todo_id = str(link_item.get("todo_id", ""))
        todoist_task_id = str(link_item.get("todoist_task_id", ""))
        todo = todo_map.get(todo_id)
        if todo and todoist_task_id:
            try:

                def _do_link(
                    t: Todo | None = todo, tid: str = todoist_task_id, ts: str = today
                ) -> None:  # todo narrowed by guard above
                    if t is None:
                        raise ValueError("Todo must not be None when linking")
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
                int_counts["linked"] += 1
            except Exception as exc:
                warnings.warn(
                    f"Failed to link Todoist task {todoist_task_id} to todo "
                    f"{todo_id} after retries; orphaned resource logged: {exc}",
                    stacklevel=2,
                )
                logger.warning(
                    "Orphaned Todoist task %s (todo %s): %s",
                    todoist_task_id,
                    todo_id,
                    exc,
                )

    # 3b. Re-link orphans whose parents were created in the same batch
    for orphan_todoist_id, todoist_parent_id in pull_create_orphans:
        orphan_local_id = todoist_to_local.get(orphan_todoist_id)
        parent_local_id = todoist_to_local.get(todoist_parent_id)
        if not orphan_local_id or not parent_local_id:
            continue
        orphan_todo = todo_map.get(orphan_local_id)
        parent_todo = todo_map.get(parent_local_id)
        if not orphan_todo or not parent_todo:
            continue
        # Skip if orphan already has a parent (was linked by a later sibling resolution)
        if orphan_todo.parent:
            continue
        orphan_todo.parent = parent_todo.id
        if orphan_todo.id not in parent_todo.children:
            parent_todo.children.append(orphan_todo.id)
        parent_todo.updated = today
        int_counts["relinked"] += 1

    # 4. Clear todoist IDs (root_only cleanup)
    for raw_todo_id in data.cleared_todoist_ids:
        todo = todo_map.get(str(raw_todo_id))
        if todo:
            todo.todoist_task_id = None
            todo.updated = today
            int_counts["cleared"] += 1
    # 5. Complete todos — handle archival properly
    to_archive: list[Todo] = []
    for raw_todo_id in data.completed_locally:
        todo = todo_map.get(str(raw_todo_id))
        if not todo or todo.status in TERMINAL_STATUSES:
            continue
        todo.status = TodoStatus.DONE
        todo.updated = today
        int_counts["completed"] += 1
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

    result: dict[str, JsonValue] = dict(int_counts)
    result["staged_description_synced"] = staged_description_synced
    result["pull_create_orphans"] = [[tid, parent_tid] for tid, parent_tid in pull_create_orphans]
    return result


# -- Inter-plugin call helpers ------------------------------------------------


def _resolve_todoist_socket() -> str:
    """Read Todoist plugin socket path from registry, fall back to legacy."""

    registry_file = Path.home() / ".claude" / "sockets" / "todoist"
    try:
        path = registry_file.read_text().strip()
        if path and Path(path).exists():
            return path
    except (FileNotFoundError, OSError):
        pass
    candidates = sorted(
        Path("/tmp").glob("claude-cpm-todoist-*.sock"),  # noqa: S108
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return str(candidates[0])
    return "/tmp/claude-cpm-todoist.sock"  # noqa: S108


def _check_hook_errors(tool_name: str, result: dict[str, JsonValue]) -> None:
    """Log warnings if the result contains hook dispatch errors.

    The hook dispatch wrapper injects a ``_hooks`` field with ``errors`` and
    ``structured_errors`` when downstream hooks fail. These were previously
    silently discarded by callers of ``_call_todoist_tool``.
    """
    hooks_meta = result.get("_hooks")
    if not isinstance(hooks_meta, dict):
        return
    errors = hooks_meta.get("errors")
    structured = hooks_meta.get("structured_errors")
    if errors:
        logger.warning(
            "Hook errors after %s: %s",
            tool_name,
            errors,
        )
    if structured:
        logger.warning(
            "Hook structured_errors after %s: %s",
            tool_name,
            structured,
        )


def _call_todoist_tool(tool_name: str, params: dict[str, JsonValue]) -> JsonValue:
    """Call a Todoist MCP tool via inter-plugin Unix domain socket.

    The hook transport wraps every response as::

        {"ok": True, "result": <tool_return>}

    where ``<tool_return>`` is whatever the tool function returned — often a
    JSON-encoded string (because FastMCP tools return ``json.dumps(...)``).
    This helper unwraps that envelope and parses the inner JSON string so
    callers always receive the actual tool payload.
    """
    sock_path = _resolve_todoist_socket()
    transport = httpx.HTTPTransport(uds=sock_path)
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            "http://localhost/hook",
            json={"tool": tool_name, "params": params},
        )
        resp.raise_for_status()
        data = resp.json()
        # Unwrap {"ok": True, "result": ...} envelope
        if isinstance(data, dict) and "result" in data:
            result = data["result"]
            # Tools return json.dumps(...) strings — parse them
            if isinstance(result, str):
                try:
                    parsed = cast("JsonValue", json.loads(result))
                except (json.JSONDecodeError, ValueError):
                    return result
                else:
                    # Check for hook errors in parsed result
                    if isinstance(parsed, dict):
                        _check_hook_errors(tool_name, parsed)
                    return parsed
            # Check for hook errors in dict results
            if isinstance(result, dict):
                _check_hook_errors(tool_name, result)
            return cast("JsonValue", result)
        return cast("JsonValue", data)


# -- Push operation helpers ---------------------------------------------------


def _execute_push_creates(
    tasks: list[dict[str, JsonValue]],
    project_todoist_id: str | None,
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]], dict[str, str]]:
    """Execute phase-1 push_create operations via todoist_add_tasks.

    Returns (succeeded, errors, id_map) where id_map maps local todo_id
    to the newly created Todoist task ID.
    """
    if not tasks:
        return [], [], {}

    succeeded: list[dict[str, JsonValue]] = []
    errors: list[dict[str, JsonValue]] = []
    id_map: dict[str, str] = {}

    # Build payloads for batch create
    add_payloads: list[dict[str, JsonValue]] = []
    for task in tasks:
        payload: dict[str, JsonValue] = {
            "content": task.get("content", ""),
            "priority": task.get("priority", "p4"),
        }
        if task.get("description"):
            payload["description"] = task["description"]
        if task.get("labels"):
            payload["labels"] = task["labels"]
        if task.get("dueString"):
            payload["dueString"] = task["dueString"]
        if task.get("parent_id"):
            payload["parent_id"] = task["parent_id"]
        if task.get("project_id"):
            payload["project_id"] = task["project_id"]
        add_payloads.append(payload)

    try:
        result = _call_todoist_tool("todoist_add_tasks", {"tasks": add_payloads})
        # todoist_add_tasks returns {"successes": [...], "failures": [...]}
        created_tasks_raw: JsonValue
        if isinstance(result, dict):
            created_tasks_raw = result.get("successes", result.get("tasks", [])) or []
        elif isinstance(result, list):
            created_tasks_raw = result
        else:
            created_tasks_raw = []
        created_tasks = (
            [x for x in created_tasks_raw if isinstance(x, dict)]
            if isinstance(created_tasks_raw, list)
            else []
        )
        for i, task in enumerate(tasks):
            todo_id = str(task.get("todo_id", ""))
            if i < len(created_tasks):
                todoist_id = str(created_tasks[i].get("id", ""))
                if todoist_id:
                    id_map[todo_id] = todoist_id
                    task["result_todoist_id"] = todoist_id
                    succeeded.append(task)
                else:
                    # Dedup guard: the task may have been created despite
                    # an empty ID in the response.  Look it up before erroring.
                    recovered_id = _find_existing_todoist_task(
                        str(task.get("project_id", "") or "") or (project_todoist_id or ""),
                        str(task.get("content", "")),
                        parent_id=str(task.get("parent_id", "") or "") or None,
                    )
                    if recovered_id:
                        id_map[todo_id] = recovered_id
                        task["result_todoist_id"] = recovered_id
                        succeeded.append(task)
                    else:
                        errors.append(
                            {
                                "operation_type": "push_create",
                                "error": "No ID returned for created task",
                                "retryable": True,
                                "retry_payload": task,
                            }
                        )
            else:
                # Response was truncated — the task may have been created anyway.
                # Look it up by content+project before marking as an error so we
                # don't create a duplicate on the next sync or retry.
                recovered_id = _find_existing_todoist_task(
                    str(task.get("project_id", "") or "") or (project_todoist_id or ""),
                    str(task.get("content", "")),
                    parent_id=str(task.get("parent_id", "") or "") or None,
                )
                if recovered_id:
                    id_map[todo_id] = recovered_id
                    task["result_todoist_id"] = recovered_id
                    succeeded.append(task)
                else:
                    errors.append(
                        {
                            "operation_type": "push_create",
                            "error": "Task not in response",
                            "retryable": True,
                            "retry_payload": task,
                        }
                    )
    except Exception as e:
        # All tasks in this batch failed
        logger.error("push_create batch failed: %s", e, exc_info=True)
        for task in tasks:
            errors.append(
                {
                    "operation_type": "push_create",
                    "error": str(e),
                    "retryable": True,
                    "retry_payload": task,
                }
            )

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
    tasks: list[dict[str, JsonValue]],
    phase1_id_map: dict[str, str],
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]], dict[str, str]]:
    """Execute phase-2 push_create for children whose parents were just created.

    Resolves _parent_local_id to the Todoist ID from phase 1.
    """
    if not tasks:
        return [], [], {}

    resolved: list[dict[str, JsonValue]] = []
    errors: list[dict[str, JsonValue]] = []

    for task in tasks:
        parent_local_id = str(task.get("_parent_local_id", ""))
        if parent_local_id in phase1_id_map:
            task_copy = dict(task)
            task_copy["parent_id"] = phase1_id_map[parent_local_id]
            # Remove internal field
            task_copy.pop("_parent_local_id", None)
            resolved.append(task_copy)
        else:
            errors.append(
                {
                    "operation_type": "push_create_phase2",
                    "error": f"Parent {parent_local_id} not in phase-1 ID map",
                    "retryable": True,
                    "retry_payload": task,
                }
            )

    if not resolved:
        return [], errors, {}

    succeeded, create_errors, id_map = _execute_push_creates(resolved, None)
    errors.extend(create_errors)
    return succeeded, errors, id_map


def _execute_push_updates(
    tasks: list[dict[str, JsonValue]],
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]]]:
    """Execute push_update operations via todoist_update_tasks."""
    if not tasks:
        return [], []

    try:
        _call_todoist_tool("todoist_update_tasks", {"tasks": tasks})
        return tasks, []
    except Exception as e:
        logger.error("push_update failed: %s", e, exc_info=True)
        errors: list[dict[str, JsonValue]] = [
            {
                "operation_type": "push_update",
                "error": str(e),
                "retryable": True,
                "retry_payload": task,
            }
            for task in tasks
        ]
        return [], errors


_PUSH_COMPLETE_BATCH_SIZE = 20


def _execute_push_completes(
    task_ids: list[str],
) -> tuple[list[str], list[dict[str, JsonValue]]]:
    """Execute push_complete operations via todoist_complete_tasks in batches.

    Batches IDs into chunks of ``_PUSH_COMPLETE_BATCH_SIZE`` to stay under the
    30s inter-plugin socket timeout.  Parses per-ID successes/failures from the
    ``todoist_complete_tasks`` response instead of treating the call as
    all-or-nothing.
    """
    if not task_ids:
        return [], []

    all_succeeded: list[str] = []
    all_errors: list[dict[str, JsonValue]] = []

    for i in range(0, len(task_ids), _PUSH_COMPLETE_BATCH_SIZE):
        chunk = task_ids[i : i + _PUSH_COMPLETE_BATCH_SIZE]
        try:
            result = _call_todoist_tool("todoist_complete_tasks", {"ids": chunk})
            # Parse per-ID successes/failures from the response
            successes: list[str]
            failure_list: list[JsonValue]
            if isinstance(result, dict):
                raw_successes = result.get("successes")
                raw_failures = result.get("failures")
                success_list = raw_successes if isinstance(raw_successes, list) else []
                failure_list = raw_failures if isinstance(raw_failures, list) else []
                successes = [
                    str(s["id"]) for s in success_list if isinstance(s, dict) and "id" in s
                ]
            else:
                # Fallback: treat entire chunk as succeeded if response shape is unexpected
                successes = list(chunk)
                failure_list = []
            all_succeeded.extend(successes)
            if failure_list:
                failed_ids = [str(f.get("id", "")) for f in failure_list if isinstance(f, dict)]
                all_errors.append(
                    {
                        "operation_type": "push_complete",
                        "error": f"{len(failure_list)} task(s) failed in chunk",
                        "retryable": True,
                        "retry_payload": {"ids": failed_ids},
                    }
                )
        except Exception as e:
            logger.error("push_complete chunk failed: %s", e, exc_info=True)
            all_errors.append(
                {
                    "operation_type": "push_complete",
                    "error": str(e),
                    "retryable": True,
                    "retry_payload": {"ids": chunk},
                }
            )

    return all_succeeded, all_errors


def _execute_push_reopens(
    task_ids: list[str],
) -> tuple[list[str], list[dict[str, JsonValue]]]:
    """Execute push_reopen operations via todoist_uncomplete_tasks."""
    if not task_ids:
        return [], []

    try:
        _call_todoist_tool("todoist_uncomplete_tasks", {"ids": task_ids})
        return task_ids, []
    except Exception as e:
        logger.error("push_reopen failed: %s", e, exc_info=True)
        errors: list[dict[str, JsonValue]] = [
            {
                "operation_type": "push_reopen",
                "error": str(e),
                "retryable": True,
                "retry_payload": {"ids": task_ids},
            }
        ]
        return [], errors


def _execute_ghost_close(
    task_ids: list[str],
) -> tuple[list[str], list[dict[str, JsonValue]]]:
    """Complete ghost tasks on Todoist."""
    if not task_ids:
        return [], []

    try:
        _call_todoist_tool("todoist_complete_tasks", {"ids": task_ids})
        return task_ids, []
    except Exception as e:
        logger.error("ghost_close failed: %s", e, exc_info=True)
        errors: list[dict[str, JsonValue]] = [
            {
                "operation_type": "ghost_close",
                "error": str(e),
                "retryable": True,
                "retry_payload": {"ids": task_ids},
            }
        ]
        return [], errors


def _execute_root_only_cleanup(
    cleanup_entries: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, JsonValue]]]:
    """Delete child tasks from Todoist for root_only mode."""
    if not cleanup_entries:
        return [], []

    succeeded: list[dict[str, str]] = []
    errors: list[dict[str, JsonValue]] = []

    for entry in cleanup_entries:
        todoist_task_id = entry.get("todoist_task_id", "")
        try:
            _call_todoist_tool("todoist_delete", {"id": todoist_task_id})
            succeeded.append(entry)
        except Exception as e:
            logger.error(
                "root_only_cleanup failed for task %s: %s", todoist_task_id, e, exc_info=True
            )
            errors.append(
                {
                    "operation_type": "root_only_cleanup",
                    "error": str(e),
                    "retryable": True,
                    "retry_payload": entry,
                }
            )

    return succeeded, errors


# -- Retry handling -----------------------------------------------------------


def _find_existing_todoist_task(
    project_id: str,
    content: str,
    parent_id: str | None = None,
) -> str | None:
    """Return the Todoist task ID of a content match in *project_id*, or None.

    Used as a dedup guard before retrying a push_create: if the first attempt
    created the task but the response was truncated, retrying without this check
    would create a duplicate.

    Matching uses normalized titles (case-insensitive, collapsed whitespace).
    When *parent_id* is provided, tasks with that parent are preferred. If no
    parent-constrained match is found, falls back to matching without parent.
    """
    if not project_id:
        logger.warning(
            "Dedup lookup skipped: no project_id for content=%r parent=%s",
            content,
            parent_id,
        )
        return None
    if not content:
        return None
    try:
        raw = _call_todoist_tool("todoist_find_tasks", {"project_id": project_id})
        if isinstance(raw, str):
            tasks: list[JsonValue] = json.loads(raw) if raw else []
        elif isinstance(raw, list):
            tasks = raw
        else:
            tasks = []
        needle = _normalize_title(content)
        # First pass: match with parent_id constraint (if provided)
        fallback_match: str | None = None
        for t in tasks:
            if not isinstance(t, dict):
                continue
            if _normalize_title(str(t.get("content", ""))) != needle:
                continue
            task_id = str(t.get("id", ""))
            if not task_id:
                continue
            # Check parent constraint
            if parent_id:
                task_parent = str(t.get("parent_id", "") or "")
                if task_parent == parent_id:
                    return task_id
                # Remember first title match as fallback (no parent constraint)
                if fallback_match is None:
                    fallback_match = task_id
            else:
                return task_id
        # Fall back to title-only match when parent constraint didn't match
        if fallback_match:
            logger.info(
                "Dedup fallback: parent_id %s not matched, using title-only match %s",
                parent_id,
                fallback_match,
            )
            return fallback_match
    except Exception as exc:
        logger.warning(
            "Dedup lookup failed for project=%s content=%r parent=%s: %s",
            project_id,
            content,
            parent_id,
            exc,
        )
    return None


def _retry_failed_ops(
    failed_ops: list[dict[str, JsonValue]],
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]], list[dict[str, str]]]:
    """Re-attempt previously failed operations.

    Returns (succeeded, still_failed, link_ops) where *link_ops* is a list of
    ``{todo_id, todoist_task_id}`` dicts for push_create ops that were linked
    (either found as existing or newly created) and should be persisted locally.
    """
    succeeded: list[dict[str, JsonValue]] = []
    still_failed: list[dict[str, JsonValue]] = []
    link_ops: list[dict[str, str]] = []

    for entry in failed_ops:
        op_type = str(entry.get("operation_type", "unknown"))
        payload_raw = entry.get("retry_payload", {})
        payload: dict[str, JsonValue] = payload_raw if isinstance(payload_raw, dict) else {}

        try:
            if op_type == "push_create" or op_type == "push_create_phase2":
                # Dedup guard: the original call may have created the task even though
                # its ID was missing from the response (batching truncation). Check first
                # to avoid creating a duplicate on retry.
                project_id = str(payload.get("project_id", ""))
                content = str(payload.get("content", ""))
                parent_id = str(payload.get("parent_id", "") or "")
                existing_id = _find_existing_todoist_task(
                    project_id,
                    content,
                    parent_id=parent_id or None,
                )

                if existing_id:
                    payload["result_todoist_id"] = existing_id
                else:
                    add_payload = {
                        k: v
                        for k, v in payload.items()
                        if k
                        in (
                            "content",
                            "priority",
                            "description",
                            "labels",
                            "dueString",
                            "parent_id",
                            "project_id",
                        )
                    }
                    result = _call_todoist_tool("todoist_add_tasks", {"tasks": [add_payload]})
                    # Extract the new task ID so we can persist it locally
                    if isinstance(result, dict):
                        created_tasks = result.get("successes", result.get("tasks", []))
                    elif isinstance(result, list):
                        created_tasks = result
                    else:
                        created_tasks = []
                    if (
                        isinstance(created_tasks, list)
                        and created_tasks
                        and isinstance(created_tasks[0], dict)
                    ):
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
                ids_raw = payload.get("ids", [])
                ids = ids_raw if isinstance(ids_raw, list) else []
                if ids:
                    _call_todoist_tool("todoist_complete_tasks", {"ids": ids})
                succeeded.append(payload)
            elif op_type == "root_only_cleanup":
                todoist_id = str(payload.get("todoist_task_id", ""))
                if todoist_id:
                    _call_todoist_tool("todoist_delete", {"id": todoist_id})
                succeeded.append(payload)
            else:
                still_failed.append(entry)
                continue
        except Exception as e:
            logger.error("retry op %s failed: %s", op_type, e, exc_info=True)
            still_failed.append(
                {
                    "operation_type": op_type,
                    "error": str(e),
                    "retryable": False,
                    "retry_payload": payload,
                }
            )

    return succeeded, still_failed, link_ops


# -- Summary builder ----------------------------------------------------------


def _build_summary(
    plan: SyncPlan,
    pull_counts: dict[str, JsonValue],
    push_created: int,
    push_created_phase2: int,
    push_updated: int,
    push_completed: int,
    push_reopened: int,
    ghost_closed: int,
    root_cleaned: int,
) -> dict[str, JsonValue]:
    """Build a human-readable summary of what was synced."""
    return {
        "pull": {
            "created": pull_counts.get("created", 0),
            "updated": pull_counts.get("updated", 0),
            "completed": pull_counts.get("completed", 0),
            "linked": pull_counts.get("linked", 0),
            "relinked": pull_counts.get("relinked", 0),
            "cleared": pull_counts.get("cleared", 0),
        },
        "push": {
            "tasks_created": push_created,
            "tasks_created_phase2": push_created_phase2,
            "tasks_updated": push_updated,
            "tasks_completed": push_completed,
            "tasks_reopened": push_reopened,
            "ghost_closed": ghost_closed,
            "root_only_cleaned": root_cleaned,
            "stale_ids_skipped": plan.stale_ids_skipped,
            "archived_completions_pushed": plan.archived_completions_pushed,
        },
    }


def _migrate_parent_links(
    todos: list[Todo], todoist_tasks: list[dict[str, JsonValue]]
) -> dict[str, int]:
    """One-time migration to fix child todos that exist in Todoist as root tasks
    but should be sub-tasks of their parent. Idempotent — safe to run multiple times.

    Returns: {"migrated": N, "already_correct": M, "skipped_unlinked": K}
    """
    todoist_by_id = {t["id"]: t for t in todoist_tasks}
    todo_map = {t.id: t for t in todos}
    counts = {"migrated": 0, "already_correct": 0, "skipped_unlinked": 0}
    updates: list[dict[str, str]] = []

    for todo in todos:
        if not todo.todoist_task_id or not todo.parent:
            continue
        parent = todo_map.get(todo.parent)
        if not parent or not parent.todoist_task_id:
            counts["skipped_unlinked"] += 1
            continue
        task = todoist_by_id.get(todo.todoist_task_id)
        if not task:
            logger.warning(
                "Migration: Todoist task %s not found for todo %s",
                todo.todoist_task_id,
                todo.id,
            )
            continue
        if task.get("parent_id") == parent.todoist_task_id:
            counts["already_correct"] += 1
            continue
        updates.append({"id": todo.todoist_task_id, "parent_id": parent.todoist_task_id})
        counts["migrated"] += 1

    if updates:
        _call_todoist_tool("todoist_update_tasks", {"tasks": json.dumps(updates)})

    return counts


# -- MCP tool registration ---------------------------------------------------


def register(app: FastMCP) -> None:
    """Register proj_todoist_full_sync tool."""

    @app.tool(
        description=(
            "Execute a full Todoist sync cycle for the active project: "
            "fetch tasks -> diff -> execute push ops -> apply pull ops -> return summary. "
            "Reduces the sync flow from ~10 tool calls to 1. "
            'On success: {"status": "success", "summary": {...}}. '
            'On partial failure: {"status": "partial_success",'
            ' "errors": [...], "retry_token": "..."}. '
            'If potential_links exist: {"status": "needs_confirmation", "potential_links": [...]}. '
            "Pass confirmed_links (JSON list of {todo_id, todoist_task_id}) to confirm links. "
            "Pass retry_failures (base64-encoded JSON) to re-attempt only previously failed ops."
        )
    )
    def proj_todoist_full_sync(
        project_name: str | None = None,
        confirmed_links: str | None = None,
        retry_failures: str | None = None,
        migrate: bool = False,
    ) -> str:
        # -- Retry mode: re-attempt only failed ops --
        if retry_failures:
            try:
                raw = json.loads(base64.b64decode(retry_failures))
                # New format: {"project_name": "...", "ops": [...]}
                # Old format (pre-2.10.4): bare list
                failed_ops: list[dict[str, JsonValue]]
                if isinstance(raw, dict) and "ops" in raw:
                    ops_raw = raw["ops"]
                    failed_ops = ops_raw if isinstance(ops_raw, list) else []
                    embedded_project_name = raw.get("project_name")
                else:
                    failed_ops = raw if isinstance(raw, list) else []
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
            return json.dumps(
                {
                    "status": "success",
                    "summary": {"up_to_date": True},
                }
            )

        # 4. Fetch tasks from Todoist via socket
        todoist_tasks: list[dict[str, JsonValue]] = []
        if project_todoist_id:
            try:
                fetch_result = _call_todoist_tool(
                    "todoist_find_tasks",
                    {"project_id": project_todoist_id},
                )
                if isinstance(fetch_result, list):
                    todoist_tasks = [x for x in fetch_result if isinstance(x, dict)]
            except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"Todoist plugin unavailable: {e}",
                    }
                )
            except Exception as e:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"Failed to fetch Todoist tasks: {e}",
                    }
                )

        # 4b. Pre-sync reconciliation: link unlinked local todos to existing
        # Todoist tasks by normalized title before diffing. Prevents duplicates
        # caused by prior hook failures leaving todoist_task_id null.
        reconciled_count = 0
        if todoist_tasks and has_local_todos:
            reconciled_count = _reconcile_unlinked_todos(todos, todoist_tasks, cfg, name)
            if reconciled_count:
                # Reload todos after reconciliation so compute_diff sees the new links
                todos = storage.load_todos(cfg, name)

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
            return json.dumps(
                {
                    "status": "needs_confirmation",
                    "potential_links": plan.potential_links,
                }
            )

        # 8. Empty diff -> up to date
        if plan.is_empty():
            return json.dumps(
                {
                    "status": "success",
                    "summary": {"up_to_date": True},
                }
            )

        # 9. Phase A: Apply pull operations locally (push_confirmed=False)
        has_pulls = bool(plan.pull_create or plan.pull_update or plan.pull_complete)
        if has_pulls:
            pull_data = ApplyInput(
                created_locally=plan.pull_create,
                updated_locally=plan.pull_update,
                completed_locally=plan.pull_complete,
            )
            pull_counts = apply_changes(pull_data, cfg, name, push_confirmed=False)
        else:
            pull_counts: dict[str, JsonValue] = {
                "created": 0,
                "updated": 0,
                "completed": 0,
                "linked": 0,
                "relinked": 0,
                "cleared": 0,
                "staged_description_synced": {},
            }

        staged_desc_raw = pull_counts.get("staged_description_synced", {})
        staged_desc: dict[str, JsonValue] = (
            staged_desc_raw if isinstance(staged_desc_raw, dict) else {}
        )

        # 10. Execute push operations
        all_errors: list[dict[str, JsonValue]] = []
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
            plan.push_create,
            project_todoist_id,
        )
        total_push_created = len(p1_succeeded)
        all_errors.extend(p1_errors)

        # 10d. Push creates (phase 2) — children needing phase-1 parent IDs
        p2_succeeded, p2_errors, phase2_id_map = _execute_push_creates_phase2(
            plan.push_create_phase2,
            phase1_id_map,
        )
        total_push_created_p2 = len(p2_succeeded)
        all_errors.extend(p2_errors)

        # 10e. Push updates
        update_succeeded, update_errors = _execute_push_updates(plan.push_update)
        total_push_updated = len(update_succeeded)
        all_errors.extend(update_errors)

        # 10f. Push completes
        complete_succeeded, complete_errors = _execute_push_completes(plan.push_complete)
        total_push_completed = len(complete_succeeded)
        all_errors.extend(complete_errors)

        # 10g. Push reopens
        reopen_succeeded, reopen_errors = _execute_push_reopens(plan.push_reopen)
        total_push_reopened = len(reopen_succeeded)
        all_errors.extend(reopen_errors)

        # 11. Phase B: Link newly created Todoist IDs and apply staged values
        combined_id_map = {**phase1_id_map, **phase2_id_map}

        # Post-execution linkage fix: re-parent pre-existing children whose
        # parent was created in this sync run (phase 1/2).
        if combined_id_map and todoist_tasks:
            post_link_updates: list[dict[str, JsonValue]] = []
            _post_todoist_by_id = {str(t["id"]): t for t in todoist_tasks}
            _post_local_by_tid: dict[str, Todo] = {}
            _post_todos = storage.load_todos(cfg, name)
            _post_todo_map = {t.id: t for t in _post_todos}
            for t in _post_todos:
                if t.todoist_task_id:
                    _post_local_by_tid[t.todoist_task_id] = t
            for tid, task in _post_todoist_by_id.items():
                if task.get("parent_id"):
                    continue
                local_todo = _post_local_by_tid.get(tid)
                if not local_todo or not local_todo.parent:
                    continue
                parent_todo = _post_todo_map.get(local_todo.parent)
                if not parent_todo:
                    continue
                parent_tid = combined_id_map.get(local_todo.parent) or parent_todo.todoist_task_id
                if parent_tid:
                    post_link_updates.append({"id": tid, "parent_id": parent_tid})
            if post_link_updates:
                _execute_push_updates(post_link_updates)

        link_ops: list[dict[str, str]] = []
        for task in p1_succeeded + p2_succeeded:
            todo_id = str(task.get("todo_id", ""))
            todoist_id = str(task.get("result_todoist_id", ""))
            if todo_id and todoist_id:
                link_ops.append({"todo_id": todo_id, "todoist_task_id": todoist_id})

        # Clear todoist IDs for root_only cleanup
        cleared_ids = [str(entry.get("todo_id", "")) for entry in cleanup_succeeded]

        # Build staged description_synced updates
        staged_updates: list[dict[str, JsonValue]] = []
        if staged_desc:
            for todo_id, desc_val in staged_desc.items():
                staged_updates.append(
                    {
                        "todo_id": todo_id,
                        "todoist_description_synced": desc_val,
                    }
                )

        if link_ops or cleared_ids or staged_updates:
            link_data = ApplyInput(
                link_todoist_ids=link_ops,
                cleared_todoist_ids=cleared_ids,
                updated_locally=staged_updates,
            )
            apply_changes(link_data, cfg, name, push_confirmed=True)

        # 11b. Optional parent-link migration
        migrate_result = None
        if migrate:
            migration_todos = storage.load_todos(cfg, name)
            migration_tasks_raw = _call_todoist_tool(
                "todoist_find_tasks",
                {"project_id": project_todoist_id},
            )
            if isinstance(migration_tasks_raw, list):
                migrate_result = _migrate_parent_links(
                    migration_todos,
                    [x for x in migration_tasks_raw if isinstance(x, dict)],
                )

        # 12. Build response
        summary = _build_summary(
            plan,
            pull_counts,
            total_push_created,
            total_push_created_p2,
            total_push_updated,
            total_push_completed,
            total_push_reopened,
            total_ghost_closed,
            total_root_cleaned,
        )

        if reconciled_count:
            summary["reconciled"] = reconciled_count

        if migrate_result:
            summary["migration"] = migrate_result

        if all_errors:
            # Embed project name so the retry path can persist IDs without
            # needing an active session.
            token_data = {"project_name": name, "ops": all_errors}
            token = base64.b64encode(json.dumps(token_data).encode()).decode()
            return json.dumps(
                {
                    "status": "partial_success",
                    "summary": summary,
                    "errors": all_errors,
                    "retry_token": token,
                }
            )

        return json.dumps(
            {
                "status": "success",
                "summary": summary,
            }
        )
