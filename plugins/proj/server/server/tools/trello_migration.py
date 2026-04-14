"""Auto-migration from Trello checklist model (v1) to card-per-todo model (v2).

Detects todos that still have `trello_checklist_id` or `trello_checklist_item_id`
set and migrates them to the card-per-todo model by creating individual Trello
cards and establishing parent-child attachment links.

Idempotent: todos that already have `trello_card_id` set are skipped.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.models import JsonValue, ProjConfig, ProjectMeta, Todo
from server.tools.trello_sync import (
    _topo_sort_todos,
    build_card_description,
    format_card_title,
)

if TYPE_CHECKING:
    from pathlib import Path

# Type alias for the Trello tool caller function
CallTrelloFn = Callable[[str, dict[str, JsonValue]], JsonValue]

logger = logging.getLogger(__name__)

_UTC = UTC


def _needs_migration(todos: list[Todo]) -> bool:
    """Return True if any todo has legacy checklist fields set."""
    return any(t.trello_checklist_id or t.trello_checklist_item_id for t in todos)


def _backup_todos(cfg: ProjConfig, name: str) -> Path:
    """Create a timestamped backup of todos before migration.

    Exports current SQLite state to todos.yaml first (if not already present),
    then copies the file. Returns the backup file path.
    """
    src = storage.todos_path(cfg, name)
    if not src.exists():
        # todos.yaml may have been migrated to SQLite — export it first
        from server.lib.migration import export_sqlite_to_yaml

        export_sqlite_to_yaml(cfg, name)

    backup_dir = storage.tracking_dir(cfg, name) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=_UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"trello-migration-{timestamp}.yaml"
    shutil.copy2(src, backup_path)
    logger.info("Trello migration backup: %s", backup_path)
    return backup_path


def migrate_checklist_to_card(
    cfg: ProjConfig,
    name: str,
    meta: ProjectMeta,
    todos: list[Todo],
    *,
    call_trello: CallTrelloFn | None = None,
) -> dict[str, JsonValue]:
    """Migrate todos from checklist model to card-per-todo model.

    Args:
        cfg: proj config
        name: project name
        meta: project metadata (for board_id resolution)
        todos: list of all project todos (mutated in place)
        call_trello: callable(tool_name, params) -> JsonValue; if None,
            uses the inter-plugin _call_trello_tool from trello_full_sync.

    Returns a migration summary dict with counts and any errors.
    """
    if call_trello is None:
        from server.tools.trello_full_sync import _call_trello_tool

        call_trello = _call_trello_tool

    # Detect which todos need migration
    to_migrate = [
        t
        for t in todos
        if (t.trello_checklist_id or t.trello_checklist_item_id) and not t.trello_card_id
    ]

    if not to_migrate:
        return {
            "migrated": 0,
            "skipped": 0,
            "errors": [],
            "backup_path": "",
            "already_migrated": True,
        }

    # Backup before making changes
    backup_path = _backup_todos(cfg, name)

    # Resolve target list for new cards
    board_id = meta.trello.board_id or cfg.trello.default_board_id
    if not board_id:
        return {
            "migrated": 0,
            "skipped": 0,
            "errors": ["No Trello board_id configured"],
            "backup_path": str(backup_path),
            "already_migrated": False,
        }

    # Get list ID for tasks list
    proj_lm = (
        meta.trello.list_mappings
        if meta.trello.list_mappings is not None
        else cfg.trello.list_mappings
    )
    tasks_list_name = proj_lm.tasks

    lists_data: list[dict[str, JsonValue]] = []
    try:
        raw = call_trello("get_lists", {"board_id": board_id})
        lists_data = [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    except Exception as e:
        return {
            "migrated": 0,
            "skipped": 0,
            "errors": [f"Failed to fetch board lists: {e}"],
            "backup_path": str(backup_path),
            "already_migrated": False,
        }

    tasks_list_id = ""
    for lst in lists_data:
        lname = str(lst.get("name", ""))
        if lname.lower() == tasks_list_name.lower():
            tasks_list_id = str(lst.get("id", ""))
            break

    if not tasks_list_id:
        # Try to create the tasks list
        try:
            result = call_trello("create_list", {"board_id": board_id, "name": tasks_list_name})
            if isinstance(result, dict):
                tasks_list_id = str(result.get("id", ""))
        except Exception as e:
            return {
                "migrated": 0,
                "skipped": 0,
                "errors": [
                    f"Tasks list '{tasks_list_name}' not found and could not be created: {e}"
                ],
                "backup_path": str(backup_path),
                "already_migrated": False,
            }

    if not tasks_list_id:
        return {
            "migrated": 0,
            "skipped": 0,
            "errors": [f"Could not resolve tasks list '{tasks_list_name}'"],
            "backup_path": str(backup_path),
            "already_migrated": False,
        }

    # Topological sort: parents before children
    sorted_todos = _topo_sort_todos(to_migrate)
    todo_map = {t.id: t for t in todos}

    migrated = 0
    skipped = 0
    errors: list[str] = []
    attachments_created = 0

    for todo in sorted_todos:
        # Double-check idempotency (may have been set by parent processing)
        if todo.trello_card_id:
            skipped += 1
            continue

        title = format_card_title(name, todo.id, todo.title)
        desc = build_card_description(todo, name)

        # Create the card
        try:
            card_result = call_trello(
                "add_card_to_list",
                {
                    "list_id": tasks_list_id,
                    "name": title,
                    "desc": desc,
                },
            )
            card_data = card_result if isinstance(card_result, dict) else {}
            new_card_id = str(card_data.get("id", ""))
        except Exception as e:
            errors.append(f"Failed to create card for todo {todo.id}: {e}")
            continue

        if not new_card_id:
            errors.append(f"Card creation returned no ID for todo {todo.id}")
            continue

        # Set card ID and clear legacy fields
        todo.trello_card_id = new_card_id
        todo.trello_checklist_id = None
        todo.trello_checklist_item_id = None
        todo.trello_sync_state = None  # Will be set fresh on next sync
        migrated += 1

        # Create parent-child attachment link
        if todo.parent:
            parent = todo_map.get(todo.parent)
            if parent and parent.trello_card_id:
                try:
                    call_trello(
                        "add_attachment",
                        {
                            "card_id": new_card_id,
                            "url": f"https://trello.com/c/{parent.trello_card_id}",
                            "name": f"Parent: {parent.title}",
                        },
                    )
                    attachments_created += 1
                except Exception as e:
                    errors.append(f"Failed to link todo {todo.id} to parent {todo.parent}: {e}")

    # Also clear legacy fields on todos that already had trello_card_id
    # (they were skipped for card creation but still may have stale checklist fields)
    for todo in todos:
        if todo.trello_card_id and (todo.trello_checklist_id or todo.trello_checklist_item_id):
            todo.trello_checklist_id = None
            todo.trello_checklist_item_id = None

    # Save updated todos
    storage.save_todos(cfg, name, todos)

    summary: dict[str, JsonValue] = {
        "migrated": migrated,
        "skipped": skipped,
        "attachments_created": attachments_created,
        "errors": errors,
        "backup_path": str(backup_path),
        "already_migrated": False,
    }

    if errors:
        logger.warning(
            "Trello migration completed with %d errors (migrated=%d, skipped=%d)",
            len(errors),
            migrated,
            skipped,
        )
    else:
        logger.info(
            "Trello migration complete: migrated=%d, skipped=%d, attachments=%d",
            migrated,
            skipped,
            attachments_created,
        )

    return summary
