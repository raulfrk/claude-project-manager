"""MCP tools for batched Trello sync — diff and apply.

Card-per-todo model (v2): each todo becomes its own Trello card.
- Todo cards go in the "tasks" list
- Project tracking cards go in the "projects" list
- Parent-child relationships use Trello card-to-card attachments
- Card titles use format: [project-name] [todo-id] Title
- Card descriptions contain status, priority, tags, blocked_by, notes

Sync uses last-changed-wins: each todo carries a TrelloSyncState snapshot
recording the card title, list, and description hash at last sync time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.models import JsonValue, ProjConfig, Todo, TrelloSyncState
from server.lib.retry import retry_link
from server.tools.config import require_project

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_UTC = UTC

# Trello card description max length
_DESC_MAX_LEN = 16384


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


# ── Title formatting ────────────────────────────────────────────────────────


def format_card_title(project_name: str, todo_id: str, title: str) -> str:
    """Format a Trello card title: [project-name] [todo-id] Title."""
    return f"[{project_name}] [{todo_id}] {title}"


def parse_card_title(card_name: str) -> tuple[str, str, str] | None:
    """Parse a card title back into (project_name, todo_id, title).

    Returns None if the title doesn't match the expected format.
    """
    m = re.match(r"^\[([^\]]*)\]\s+\[([^\]]*)\]\s+(.+)$", card_name)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


# ── Description generation ──────────────────────────────────────────────────


def build_card_description(todo: Todo, project_name: str = "") -> str:
    """Build a Trello card description from a todo's fields.

    Uses sorted keys for deterministic output (important for hash stability).
    """
    lines: list[str] = []

    # Status and priority
    status = getattr(todo.status, "value", todo.status)
    priority = getattr(todo.priority, "value", todo.priority)
    lines.append(f"**Status**: {status}")
    lines.append(f"**Priority**: {priority}")

    if project_name:
        lines.append(f"**Project**: {project_name}")

    # Due date
    if todo.due_date:
        lines.append(f"**Due**: {todo.due_date}")

    # Tags
    if todo.tags:
        tags_str = ", ".join(sorted(todo.tags))
        lines.append(f"**Tags**: {tags_str}")

    # Blocked by
    if todo.blocked_by:
        blocked_str = ", ".join(sorted(todo.blocked_by))
        lines.append(f"**Blocked by**: {blocked_str}")

    # Children
    if todo.children:
        children_str = ", ".join(todo.children)
        lines.append(f"**Children**: {children_str}")

    # Notes
    if todo.notes:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(todo.notes)

    desc = "\n".join(lines)

    # Truncate if needed
    if len(desc) > _DESC_MAX_LEN:
        desc = desc[: _DESC_MAX_LEN - 3] + "..."

    return desc


def build_project_card_description(
    meta: object,
    todos: list[Todo],
    project_name: str,
) -> str:
    """Build a Trello card description for a project tracking card.

    Args:
        meta: ProjectMeta object with status, tags, etc.
        todos: list of all project todos (for summary counts)
        project_name: project name for display
    """
    lines: list[str] = []

    status = getattr(meta, "status", "active")
    lines.append(f"**Project**: {project_name}")
    lines.append(f"**Status**: {status}")

    # Todo summary
    total = len(todos)
    done = sum(1 for t in todos if t.status in TERMINAL_STATUSES)
    pending = total - done
    lines.append(f"**Todos**: {total} total, {done} done, {pending} pending")

    # Root todos list
    roots = [t for t in todos if t.parent is None]
    if roots:
        lines.append("")
        lines.append("## Root Todos")
        for r in roots:
            status_icon = "x" if r.status in TERMINAL_STATUSES else " "
            lines.append(f"- [{status_icon}] [{r.id}] {r.title}")

    desc = "\n".join(lines)
    if len(desc) > _DESC_MAX_LEN:
        desc = desc[: _DESC_MAX_LEN - 3] + "..."
    return desc


def compute_desc_hash(desc: str) -> str:
    """Compute a deterministic hash for a card description."""
    return hashlib.md5(desc.encode("utf-8"), usedforsecurity=False).hexdigest()


# ── Topological ordering ───────────────────────────────────────────────────


def _topo_sort_todos(todos: list[Todo]) -> list[Todo]:
    """Sort todos so parents come before children (topological order).

    Todos without parents come first, then children in order of depth.
    """
    todo_map = {t.id: t for t in todos}
    visited: set[str] = set()
    result: list[Todo] = []

    def _visit(tid: str) -> None:
        if tid in visited:
            return
        visited.add(tid)
        todo = todo_map.get(tid)
        if not todo:
            return
        # Visit parent first
        if todo.parent and todo.parent in todo_map:
            _visit(todo.parent)
        result.append(todo)

    for t in todos:
        _visit(t.id)

    return result


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class CardOp:
    """A single card operation in the sync plan."""

    todo_id: str
    card_id: str = ""
    title: str = ""
    desc: str = ""
    list_id: str = ""
    list_name: str = ""
    parent_todo_id: str = ""

    def to_dict(self) -> dict[str, JsonValue]:
        d: dict[str, JsonValue] = {"todo_id": self.todo_id}
        if self.card_id:
            d["card_id"] = self.card_id
        if self.title:
            d["title"] = self.title
        if self.desc:
            d["desc"] = self.desc
        if self.list_id:
            d["list_id"] = self.list_id
        if self.list_name:
            d["list_name"] = self.list_name
        if self.parent_todo_id:
            d["parent_todo_id"] = self.parent_todo_id
        return d


@dataclass
class TrelloSyncPlan:
    """Result of comparing Trello cards with local todos (card-per-todo model)."""

    # Push operations (local -> Trello)
    push_create_card: list[dict[str, JsonValue]] = field(default_factory=list)
    push_update_card: list[dict[str, JsonValue]] = field(default_factory=list)
    push_move_card: list[dict[str, JsonValue]] = field(default_factory=list)
    push_archive_card: list[dict[str, JsonValue]] = field(default_factory=list)
    push_attach_link: list[dict[str, JsonValue]] = field(default_factory=list)

    # Pull operations (Trello -> local)
    pull_update: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_move: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_complete: list[str] = field(default_factory=list)
    pull_reopen: list[str] = field(default_factory=list)

    # Metadata
    conflicts: list[dict[str, JsonValue]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    project_card_create: bool = False
    project_card_update: bool = False

    # Lists to auto-create
    lists_to_create: list[str] = field(default_factory=list)

    # Legacy checklist-based fields (used by trello_full_sync)
    push_create_checklist: list[dict[str, JsonValue]] = field(default_factory=list)
    push_create_item: list[dict[str, JsonValue]] = field(default_factory=list)
    push_update_item: list[dict[str, JsonValue]] = field(default_factory=list)
    push_complete_item: list[dict[str, JsonValue]] = field(default_factory=list)
    push_delete_item: list[dict[str, JsonValue]] = field(default_factory=list)
    push_rename_checklist: list[dict[str, JsonValue]] = field(default_factory=list)
    push_reopen_item: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_delete: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_create: list[dict[str, JsonValue]] = field(default_factory=list)
    pull_create_root: list[dict[str, JsonValue]] = field(default_factory=list)
    card_create: bool = False
    list_mismatches: list[dict[str, JsonValue]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.push_create_card,
                self.push_update_card,
                self.push_move_card,
                self.push_archive_card,
                self.push_attach_link,
                self.pull_update,
                self.pull_move,
                self.pull_complete,
                self.pull_reopen,
                self.conflicts,
                self.project_card_create,
                self.project_card_update,
                self.lists_to_create,
            ]
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "push_create_card": self.push_create_card,
            "push_update_card": self.push_update_card,
            "push_move_card": self.push_move_card,
            "push_archive_card": self.push_archive_card,
            "push_attach_link": self.push_attach_link,
            "pull_update": self.pull_update,
            "pull_move": self.pull_move,
            "pull_complete": self.pull_complete,
            "pull_reopen": self.pull_reopen,
            "conflicts": self.conflicts,
            "warnings": self.warnings,
            "project_card_create": self.project_card_create,
            "project_card_update": self.project_card_update,
            "lists_to_create": self.lists_to_create,
            "summary": {
                "push_create_card_count": len(self.push_create_card),
                "push_update_card_count": len(self.push_update_card),
                "push_move_card_count": len(self.push_move_card),
                "push_archive_card_count": len(self.push_archive_card),
                "push_attach_link_count": len(self.push_attach_link),
                "pull_update_count": len(self.pull_update),
                "pull_move_count": len(self.pull_move),
                "pull_complete_count": len(self.pull_complete),
                "pull_reopen_count": len(self.pull_reopen),
                "conflict_count": len(self.conflicts),
            },
        }


@dataclass
class TrelloApplyInput:
    """Input for applying Trello sync changes locally."""

    updated_locally: list[dict[str, JsonValue]] = field(default_factory=list)
    completed_locally: list[str] = field(default_factory=list)
    reopened_locally: list[str] = field(default_factory=list)
    link_card_ids: list[dict[str, str]] = field(default_factory=list)
    link_project_card_id: str | None = None

    # Legacy checklist-based fields (used by trello_full_sync)
    link_trello_card_id: str | None = None
    created_locally: list[dict[str, JsonValue]] = field(default_factory=list)
    created_root_locally: list[dict[str, JsonValue]] = field(default_factory=list)


# ── Rate limiting ───────────────────────────────────────────────────────────


@dataclass
class RateLimitConfig:
    """Configuration for Trello API rate limiting."""

    delay_ms: int = 100  # delay between API calls in milliseconds
    backoff_base_ms: int = 500  # base delay for exponential backoff on 429
    max_retries: int = 3  # max retries per call on 429


# ── Diff engine ─────────────────────────────────────────────────────────────


def _resolve_target_list(
    todo: Todo,
    cfg: ProjConfig,
    meta: object,
) -> str:
    """Determine which Trello list a todo card should be in.

    Returns the list name from list_mappings config.
    """
    proj_lm = getattr(meta, "trello", None)
    if proj_lm and hasattr(proj_lm, "list_mappings") and proj_lm.list_mappings is not None:
        lm = proj_lm.list_mappings
    else:
        lm = cfg.trello.list_mappings

    if todo.status in TERMINAL_STATUSES:
        return lm.done
    return lm.tasks


def compute_diff(
    trello_cards_json: str,
    cfg: ProjConfig,
    name: str,
) -> TrelloSyncPlan:
    """Compare local todos vs Trello cards and produce a card-based sync plan.

    Args:
        trello_cards_json: JSON string containing:
            - "cards": list of Trello card objects (id, name, desc, idList, list)
            - "lists": list of Trello list objects (id, name)
            - "project_card": optional project tracking card object
        cfg: proj config
        name: project name
    """
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    archived = storage.load_archived_todos(cfg, name)

    plan = TrelloSyncPlan()

    # Parse Trello state
    try:
        trello_data: dict[str, JsonValue] = (
            json.loads(trello_cards_json) if trello_cards_json else {}
        )
    except json.JSONDecodeError:
        trello_data = {}

    cards_raw = trello_data.get("cards", [])
    trello_cards: list[dict[str, JsonValue]] = (
        [c for c in cards_raw if isinstance(c, dict)] if isinstance(cards_raw, list) else []
    )

    lists_raw = trello_data.get("lists", [])
    trello_lists: list[dict[str, JsonValue]] = (
        [lst for lst in lists_raw if isinstance(lst, dict)] if isinstance(lists_raw, list) else []
    )

    # Build lookups
    todo_map = {t.id: t for t in todos}
    archived_card_ids = {t.trello_card_id for t in archived if t.trello_card_id}

    # Trello card lookup by ID
    trello_card_by_id: dict[str, dict[str, JsonValue]] = {}
    for card in trello_cards:
        cid = str(card.get("id", ""))
        if cid:
            trello_card_by_id[cid] = card

    # Trello list name lookup
    list_name_by_id: dict[str, str] = {}
    list_id_by_name: dict[str, str] = {}
    for lst in trello_lists:
        lid = str(lst.get("id", ""))
        lname = str(lst.get("name", ""))
        if lid and lname:
            list_name_by_id[lid] = lname
            list_id_by_name[lname.lower()] = lid

    # Determine required lists
    proj_lm = (
        meta.trello.list_mappings
        if meta.trello.list_mappings is not None
        else cfg.trello.list_mappings
    )
    required_lists = {proj_lm.tasks, proj_lm.done, proj_lm.projects}
    required_lists.discard("")
    for req_list in required_lists:
        if req_list.lower() not in list_id_by_name:
            plan.lists_to_create.append(req_list)

    # Check project tracking card
    project_card = trello_data.get("project_card")
    if not meta.trello_card_id:
        plan.project_card_create = True
    elif isinstance(project_card, dict):
        # Check if project card description needs updating
        current_desc = str(project_card.get("desc", ""))
        expected_desc = build_project_card_description(meta, todos, name)
        if compute_desc_hash(current_desc) != compute_desc_hash(expected_desc):
            plan.project_card_update = True

    # ── Linked todos: compare local vs Trello cards ─────────────────

    seen_card_ids: set[str] = set()

    for todo in todos:
        if not todo.trello_card_id:
            # Unlinked todo -> needs card creation
            expected_title = format_card_title(name, todo.id, todo.title)
            expected_desc = build_card_description(todo, name)
            target_list = _resolve_target_list(todo, cfg, meta)
            plan.push_create_card.append(
                {
                    "todo_id": todo.id,
                    "title": expected_title,
                    "desc": expected_desc,
                    "list_name": target_list,
                    "parent_todo_id": todo.parent or "",
                }
            )
            continue

        seen_card_ids.add(todo.trello_card_id)

        trello_card = trello_card_by_id.get(todo.trello_card_id)
        if not trello_card:
            # Card was deleted in Trello -- clear link, re-create
            plan.warnings.append(
                f"Card {todo.trello_card_id} for todo {todo.id} not found in Trello; will re-create"
            )
            # Clear the stale link so it gets re-created
            todo.trello_card_id = None
            expected_title = format_card_title(name, todo.id, todo.title)
            expected_desc = build_card_description(todo, name)
            target_list = _resolve_target_list(todo, cfg, meta)
            plan.push_create_card.append(
                {
                    "todo_id": todo.id,
                    "title": expected_title,
                    "desc": expected_desc,
                    "list_name": target_list,
                    "parent_todo_id": todo.parent or "",
                }
            )
            continue

        # Card exists -- check for changes
        trello_title = str(trello_card.get("name", ""))
        trello_desc = str(trello_card.get("desc", ""))
        trello_list_id = str(trello_card.get("idList", ""))
        bool(trello_card.get("closed", False))

        expected_title = format_card_title(name, todo.id, todo.title)
        expected_desc = build_card_description(todo, name)
        expected_list = _resolve_target_list(todo, cfg, meta)
        expected_list_id = list_id_by_name.get(expected_list.lower(), "")

        ss = todo.trello_sync_state

        if ss is None or not ss.last_sync:
            # First sync: push local state (local wins)
            if trello_title != expected_title or compute_desc_hash(
                trello_desc
            ) != compute_desc_hash(expected_desc):
                plan.push_update_card.append(
                    {
                        "todo_id": todo.id,
                        "card_id": todo.trello_card_id,
                        "title": expected_title,
                        "desc": expected_desc,
                    }
                )
            if expected_list_id and trello_list_id != expected_list_id:
                plan.push_move_card.append(
                    {
                        "todo_id": todo.id,
                        "card_id": todo.trello_card_id,
                        "list_id": expected_list_id,
                        "list_name": expected_list,
                    }
                )
            # Check if Trello card is in done list but local isn't done
            trello_list_name = list_name_by_id.get(trello_list_id, "")
            if (
                trello_list_name.lower() == proj_lm.done.lower()
                and todo.status not in TERMINAL_STATUSES
            ):
                plan.pull_complete.append(todo.id)
            elif (
                trello_list_name.lower() != proj_lm.done.lower()
                and todo.status in TERMINAL_STATUSES
            ):
                # Trello says active but local says done
                plan.push_move_card.append(
                    {
                        "todo_id": todo.id,
                        "card_id": todo.trello_card_id,
                        "list_id": list_id_by_name.get(proj_lm.done.lower(), ""),
                        "list_name": proj_lm.done,
                    }
                )
        else:
            # ── Last-changed-wins logic ─────────────────────────────
            local_changed_title = expected_title != ss.synced_name
            local_changed_desc = compute_desc_hash(expected_desc) != ss.desc_hash
            local_changed_list = expected_list_id and expected_list_id != ss.list_id
            local_changed = local_changed_title or local_changed_desc or local_changed_list

            trello_changed_title = trello_title != ss.synced_name
            trello_changed_desc = compute_desc_hash(trello_desc) != ss.desc_hash
            trello_changed_list = trello_list_id != ss.list_id
            trello_changed = trello_changed_title or trello_changed_desc or trello_changed_list

            if local_changed and trello_changed:
                # Conflict -- use timestamps for resolution
                local_ts = todo.updated or ""
                trello_ts = ss.trello_updated if ss.trello_updated else ""
                resolution = "trello" if trello_ts and trello_ts > local_ts else "local"

                plan.conflicts.append(
                    {
                        "todo_id": todo.id,
                        "local_title": expected_title,
                        "trello_title": trello_title,
                        "local_updated": local_ts,
                        "trello_updated": trello_ts,
                        "resolution": resolution,
                    }
                )

                if resolution == "trello":
                    _emit_pull_for_card(
                        plan,
                        todo,
                        trello_title,
                        trello_list_id,
                        list_name_by_id,
                        proj_lm,
                        name,
                    )
                else:
                    plan.warnings.append(
                        f"Conflict on todo {todo.id}: both sides changed since last sync; "
                        f"local wins (local_updated={local_ts}, trello_updated={trello_ts})"
                    )
                    _emit_push_for_card(
                        plan,
                        todo,
                        expected_title,
                        expected_desc,
                        expected_list_id,
                        expected_list,
                        trello_title,
                        trello_desc,
                        trello_list_id,
                    )
            elif local_changed:
                _emit_push_for_card(
                    plan,
                    todo,
                    expected_title,
                    expected_desc,
                    expected_list_id,
                    expected_list,
                    trello_title,
                    trello_desc,
                    trello_list_id,
                )
            elif trello_changed:
                _emit_pull_for_card(
                    plan,
                    todo,
                    trello_title,
                    trello_list_id,
                    list_name_by_id,
                    proj_lm,
                    name,
                )
            # else: neither changed -> skip

    # ── Pull: scan Trello cards for changes to linked todos ─────────
    # Build reverse lookup: trello_card_id -> todo
    card_id_to_todo: dict[str, Todo] = {}
    for t in todos:
        if t.trello_card_id:
            card_id_to_todo[t.trello_card_id] = t

    # Determine mapped list names (lowercase) for filtering
    mapped_list_names: set[str] = set()
    for ln in (proj_lm.tasks, proj_lm.done, proj_lm.projects, proj_lm.created):
        if ln:
            mapped_list_names.add(ln.lower())

    for card_id, card in trello_card_by_id.items():
        if card_id in seen_card_ids:
            continue

        card_list_id = str(card.get("idList", ""))
        card_list_name = list_name_by_id.get(card_list_id, "")

        # Skip cards in unmapped lists
        if card_list_name and card_list_name.lower() not in mapped_list_names:
            logger.debug(
                "Skipping card %s in unmapped list '%s'",
                card_id,
                card_list_name,
            )
            continue

        if card_id in archived_card_ids:
            # Card belongs to archived todo -- archive in Trello if not closed
            if not card.get("closed", False):
                plan.push_archive_card.append(
                    {
                        "card_id": card_id,
                        "reason": "archived_todo",
                    }
                )
            continue

        # Check if this card is linked to a local todo (via card_id_to_todo)
        linked_todo = card_id_to_todo.get(card_id)
        if not linked_todo:
            # Unlinked card -- try to match by parsing title
            card_name = str(card.get("name", ""))
            parsed = parse_card_title(card_name)
            if parsed:
                _, parsed_todo_id, _ = parsed
                if parsed_todo_id in todo_map:
                    logger.info(
                        "Unlinked card %s matches todo %s by title"
                        " but has no trello_card_id link; skipping",
                        card_id,
                        parsed_todo_id,
                    )
            else:
                logger.debug(
                    "Skipping unlinked card %s (no matching local todo)",
                    card_id,
                )
            continue

        # Card is linked but was already processed in the todos loop above
        # (this branch shouldn't normally be reached since seen_card_ids tracks them)

    # ── Attachment links for new cards ──────────────────────────────
    # (computed after card creation -- actual attachment happens in apply phase)
    for create_op in plan.push_create_card:
        parent_tid = str(create_op.get("parent_todo_id", ""))
        if parent_tid:
            parent = todo_map.get(parent_tid)
            if parent and parent.trello_card_id:
                plan.push_attach_link.append(
                    {
                        "child_todo_id": str(create_op["todo_id"]),
                        "parent_card_id": parent.trello_card_id,
                    }
                )

    # Sort card creation in topological order (parents before children)
    if plan.push_create_card:
        id_order = {t.id: i for i, t in enumerate(_topo_sort_todos(todos))}
        plan.push_create_card.sort(key=lambda op: id_order.get(str(op.get("todo_id", "")), 999999))

    return plan


def _emit_push_for_card(
    plan: TrelloSyncPlan,
    todo: Todo,
    expected_title: str,
    expected_desc: str,
    expected_list_id: str,
    expected_list_name: str,
    trello_title: str,
    trello_desc: str,
    trello_list_id: str,
) -> None:
    """Emit push operations for a linked card where local wins."""
    if expected_title != trello_title or compute_desc_hash(expected_desc) != compute_desc_hash(
        trello_desc
    ):
        plan.push_update_card.append(
            {
                "todo_id": todo.id,
                "card_id": todo.trello_card_id,
                "title": expected_title,
                "desc": expected_desc,
            }
        )
    if expected_list_id and trello_list_id != expected_list_id:
        plan.push_move_card.append(
            {
                "todo_id": todo.id,
                "card_id": todo.trello_card_id,
                "list_id": expected_list_id,
                "list_name": expected_list_name,
            }
        )


def _emit_pull_for_card(
    plan: TrelloSyncPlan,
    todo: Todo,
    trello_title: str,
    trello_list_id: str,
    list_name_by_id: dict[str, str],
    list_mappings: object,
    project_name: str,
) -> None:
    """Emit pull operations for a linked card where Trello wins."""
    # Parse title to extract the actual todo title
    parsed = parse_card_title(trello_title)
    if parsed:
        _, _, actual_title = parsed
    else:
        actual_title = trello_title

    expected_title = format_card_title(project_name, todo.id, todo.title)
    if trello_title != expected_title:
        plan.pull_update.append(
            {
                "todo_id": todo.id,
                "title": actual_title,
            }
        )

    # Check list-based status
    trello_list_name = list_name_by_id.get(trello_list_id, "")
    done_list = getattr(list_mappings, "done", "Done")

    if trello_list_name.lower() == done_list.lower() and todo.status not in TERMINAL_STATUSES:
        plan.pull_complete.append(todo.id)
    elif trello_list_name.lower() != done_list.lower() and todo.status in TERMINAL_STATUSES:
        plan.pull_reopen.append(todo.id)


# ── Apply logic ──────────────────────────────────────────────────────────────


def apply_changes(
    data: TrelloApplyInput,
    cfg: ProjConfig,
    name: str,
    *,
    push_confirmed: bool = False,
) -> dict[str, int]:
    """Apply Trello sync changes to local todos atomically. Returns counts dict."""
    meta = storage.load_meta(cfg, name)
    todos = storage.load_todos(cfg, name)
    todo_map = {t.id: t for t in todos}
    now = _now()

    counts = {
        "updated": 0,
        "completed": 0,
        "reopened": 0,
        "linked": 0,
    }

    # 1. Update existing todos (title changes from Trello)
    for item in data.updated_locally:
        todo_id = str(item.get("todo_id", ""))
        todo = todo_map.get(todo_id)
        if not todo:
            continue
        if "title" in item and item["title"] is not None:
            todo.title = str(item["title"])
        todo.updated = now
        counts["updated"] += 1

    # 2. Link card IDs (after push card creation returns Trello IDs)
    trk_dir = str(storage.tracking_dir(cfg, name))
    for link_item in data.link_card_ids:
        todo_id = str(link_item.get("todo_id", ""))
        card_id = str(link_item.get("card_id", ""))
        todo = todo_map.get(todo_id)
        if not todo or not card_id:
            continue

        def _link_card(t: Todo | None = todo, cid: str = card_id) -> None:
            if t is None:
                raise ValueError("Todo must not be None when linking card")
            t.trello_card_id = cid

        try:
            retry_link(
                _link_card,
                orphan_context={
                    "tracking_dir": trk_dir,
                    "external_id": card_id,
                    "todo_id": todo_id,
                    "service": "trello",
                },
            )
            todo.updated = now
            counts["linked"] += 1
        except Exception:
            logger.warning(
                "Failed to link Trello card %s to todo %s; logged as orphaned resource",
                card_id,
                todo_id,
            )

    # 3. Link project card ID
    if data.link_project_card_id:
        meta.trello_card_id = data.link_project_card_id

    # 4. Complete todos
    for raw_todo_id in data.completed_locally:
        todo = todo_map.get(str(raw_todo_id))
        if not todo or todo.status in TERMINAL_STATUSES:
            continue
        todo.status = TodoStatus.DONE
        todo.updated = now
        counts["completed"] += 1

    # 5. Reopen todos
    for raw_todo_id in data.reopened_locally:
        todo = todo_map.get(str(raw_todo_id))
        if not todo or todo.status not in TERMINAL_STATUSES:
            continue
        todo.status = "pending"
        todo.updated = now
        counts["reopened"] += 1

    # 6. Record trello_sync_state on all synced todos
    if push_confirmed:
        sync_now = _now()
        # Resolve list IDs for all todos
        for todo in todos:
            if todo.trello_card_id:
                expected_title = format_card_title(name, todo.id, todo.title)
                expected_desc = build_card_description(todo, name)
                _resolve_target_list(todo, cfg, meta)

                todo.trello_sync_state = TrelloSyncState(
                    last_sync=sync_now,
                    synced_name=expected_title,
                    card_id=todo.trello_card_id,
                    list_id="",  # Will be populated by caller with actual Trello list ID
                    desc_hash=compute_desc_hash(expected_desc),
                )

    # Save atomically
    storage.save_meta(cfg, meta)
    storage.save_todos(cfg, name, todos)

    return counts


# ── MCP tool registration ────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register Trello sync tools."""

    @app.tool(
        description=(
            "Compare Trello cards with local todos and produce a card-based sync plan. "
            "Takes Trello state as JSON with 'cards' (list of card objects), 'lists' "
            "(list of list objects), and optional 'project_card'. Returns a JSON sync "
            "plan with card-level operations (create, update, move, archive). "
            "Uses last-changed-wins logic with conflict detection. "
            "When auto_apply=True, pull operations are applied locally immediately. "
            "Set summary_only=True to return only summary counts."
        )
    )
    def proj_trello_diff(
        trello_cards_json: str,
        auto_apply: bool = False,
        summary_only: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, proj_name = result

        plan = compute_diff(trello_cards_json, cfg, proj_name)

        if not auto_apply:
            plan_dict = plan.to_dict()
            if summary_only:
                return json.dumps({"summary": plan_dict["summary"]}, indent=2)
            return json.dumps(plan_dict, indent=2)

        # auto_apply mode: apply pull operations server-side
        meta = storage.load_meta(cfg, proj_name)
        plan_dict = plan.to_dict()
        response: dict[str, JsonValue] = {
            "plan": {"summary": plan_dict["summary"]} if summary_only else plan_dict,
            "project_info": {
                "mcp_server": "trello",
                "board_id": meta.trello.board_id or cfg.trello.default_board_id,
                "trello_card_id": meta.trello_card_id or "",
            },
        }

        has_pulls = bool(plan.pull_update or plan.pull_complete or plan.pull_reopen)
        if has_pulls:
            pull_data = TrelloApplyInput(
                updated_locally=plan.pull_update,
                completed_locally=plan.pull_complete,
                reopened_locally=plan.pull_reopen,
            )
            counts = apply_changes(pull_data, cfg, proj_name)
            response["auto_applied"] = counts
        else:
            auto: JsonValue = {
                "updated": 0,
                "completed": 0,
                "reopened": 0,
                "linked": 0,
            }
            response["auto_applied"] = auto

        return json.dumps(response, indent=2)

    @app.tool(
        description=(
            "Apply Trello sync results to local todos in bulk. Takes a JSON "
            "object with: updated_locally, completed_locally, reopened_locally, "
            "link_card_ids (list of {todo_id, card_id}), "
            "link_project_card_id. All changes are applied atomically. "
            "Records trello_sync_state on each synced todo after apply."
        )
    )
    def proj_trello_apply(
        apply_json: str,
        push_confirmed: bool = False,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, proj_name = result

        try:
            raw: dict[str, JsonValue] = json.loads(apply_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        def _dict_list(v: JsonValue) -> list[dict[str, JsonValue]]:
            return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

        def _str_list(v: JsonValue) -> list[str]:
            return [str(x) for x in v] if isinstance(v, list) else []

        def _str_dict_list(v: JsonValue) -> list[dict[str, str]]:
            return (
                [{str(k): str(val) for k, val in x.items()} for x in v if isinstance(x, dict)]
                if isinstance(v, list)
                else []
            )

        card_id_raw = raw.get("link_project_card_id")
        data = TrelloApplyInput(
            updated_locally=_dict_list(raw.get("updated_locally", [])),
            completed_locally=_str_list(raw.get("completed_locally", [])),
            reopened_locally=_str_list(raw.get("reopened_locally", [])),
            link_card_ids=_str_dict_list(raw.get("link_card_ids", [])),
            link_project_card_id=str(card_id_raw) if isinstance(card_id_raw, str) else None,
        )
        counts = apply_changes(data, cfg, proj_name, push_confirmed=push_confirmed)
        return json.dumps({"status": "ok", "counts": counts})
