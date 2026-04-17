"""MCP tool for migrating todo IDs from T-prefix format to numeric dot-notation."""

from __future__ import annotations

import contextlib
import json
import re
import shutil
from datetime import datetime
from typing import TYPE_CHECKING

import yaml

from server.lib import storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP

    from server.lib.models import JsonValue, ProjConfig, Todo


def _assign_ids(
    parent_todos: list[Todo],
    all_todos: list[Todo],
    id_map: dict[str, str],
    prefix: str = "",
) -> None:
    """Recursively assign numeric dot-notation IDs to todos, populating id_map."""
    for i, todo in enumerate(parent_todos, 1):
        new_id = f"{prefix}{i}" if prefix else str(i)
        id_map[todo.id] = new_id
        # Find and recursively assign children
        children = sorted(
            [t for t in all_todos if t.parent == todo.id],
            key=lambda t: (t.created, t.id),
        )
        _assign_ids(children, all_todos, id_map, prefix=f"{new_id}.")


def _build_id_mapping(todos: list[Todo]) -> dict[str, str]:
    """Build old→new ID mapping for all todos, sorted by creation date."""
    root_todos = sorted(
        [t for t in todos if t.parent is None],
        key=lambda t: (t.created, t.id),
    )
    id_map: dict[str, str] = {}
    _assign_ids(root_todos, todos, id_map)
    return id_map


def _apply_remap(todos: list[Todo], id_map: dict[str, str]) -> None:
    """Apply id_map to all todo fields in-place."""
    for todo in todos:
        todo.id = id_map.get(todo.id, todo.id)
        todo.parent = id_map.get(todo.parent, todo.parent) if todo.parent else None
        todo.children = [id_map.get(c, c) for c in todo.children]
        todo.blocks = [id_map.get(b, b) for b in todo.blocks]
        todo.blocked_by = [id_map.get(b, b) for b in todo.blocked_by]
        # Set next_child_id = len(children) + 1
        todo.next_child_id = len(todo.children) + 1


def _backup_file(path: Path, timestamp: str) -> Path | None:
    """Create timestamped backup. Returns backup path, or None if source doesn't exist."""
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak-{timestamp}")
    shutil.copy2(path, backup)
    return backup


def _restore_backups(backups: dict[Path, Path | None]) -> None:
    """Restore all backed-up YAML files."""
    for original, backup in backups.items():
        if backup and backup.exists():
            shutil.copy2(backup, original)


def _restore_sqlite_from_backups(
    cfg: ProjConfig, project_name: str, backups: dict[Path, Path | None]
) -> None:
    """Restore SQLite state from YAML backup files. Called on rollback.

    Uses sql_todos/sql_decisions directly (not storage wrappers) so that
    mocked storage.save_todos in tests does not interfere with restore.
    """
    from server.lib import sql_todos as _sqlt
    from server.lib.models import Todo as _Todo

    # Restore YAML files from backups first
    _restore_backups(backups)

    with contextlib.suppress(Exception):
        todos_yaml = storage.todos_path(cfg, project_name)
        if todos_yaml.exists():
            raw = yaml.safe_load(todos_yaml.read_text()) or {}
            raw_todos = raw.get("todos", []) if isinstance(raw, dict) else []
            todos_objs = [_Todo.from_dict(t) for t in raw_todos if isinstance(t, dict)]
            _sqlt.save_todos(cfg, project_name, todos_objs)

    with contextlib.suppress(Exception):
        archive_yaml = storage.archive_path(cfg, project_name)
        if archive_yaml.exists():
            raw = yaml.safe_load(archive_yaml.read_text()) or {}
            raw_todos = raw.get("todos", []) if isinstance(raw, dict) else []
            archived_objs = [_Todo.from_dict(t) for t in raw_todos if isinstance(t, dict)]
            _sqlt.replace_archived_todos(cfg, project_name, archived_objs)

    with contextlib.suppress(Exception):
        decisions_yaml = storage.decisions_path(cfg, project_name)
        if decisions_yaml.exists():
            raw_list = yaml.safe_load(decisions_yaml.read_text()) or []
            if isinstance(raw_list, list):
                storage.replace_decisions(cfg, project_name, raw_list)


def _migrate_decisions(decisions: list[dict[str, JsonValue]], id_map: dict[str, str]) -> int:
    """Remap T-prefix IDs in decisions list in-place. Returns count of modified entries."""
    count = 0
    for entry in decisions:
        modified = False
        old_tid = str(entry.get("todo_id", ""))
        if old_tid and old_tid in id_map:
            entry["todo_id"] = id_map[old_tid]
            modified = True
        for field in ("decision", "context"):
            text = entry.get(field, "")
            if not isinstance(text, str):
                continue
            new_text = text
            for old_id, new_id in id_map.items():
                new_text = re.sub(rf"\b{re.escape(old_id)}\b", new_id, new_text)
            if new_text != text:
                entry[field] = new_text
                modified = True
        if modified:
            count += 1
    return count


def _cleanup_config(
    cfg: ProjConfig, dry_run: bool = False, timestamp: str = ""
) -> dict[str, JsonValue]:
    """Remove deprecated fields from proj.yaml. Returns result dict."""
    config_path = storage.config_path()
    raw = storage._load_yaml(config_path)
    removed = []

    perms = raw.get("permissions", {})
    if isinstance(perms, dict) and "investigation_tools" in perms:
        removed.append("permissions.investigation_tools")
        if not dry_run:
            del perms["investigation_tools"]

    sync_raw = raw.get("sync", {})
    sync_todoist = sync_raw.get("todoist", {}) if isinstance(sync_raw, dict) else {}
    if isinstance(sync_todoist, dict) and "mcp_server" in sync_todoist:
        removed.append("sync.todoist.mcp_server")
        if not dry_run:
            del sync_todoist["mcp_server"]

    if not removed:
        return {"cleaned": False, "reason": "nothing to clean"}

    if dry_run:
        return {"cleaned": False, "dry_run": True, "would_remove": removed}

    if not timestamp:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = _backup_file(config_path, timestamp)
    try:
        storage._write_yaml(config_path, raw)
    except Exception:
        if backup:
            shutil.copy2(backup, config_path)
        raise

    return {"cleaned": True, "removed": removed}


def _migrate_project(
    cfg: ProjConfig, project_name: str, dry_run: bool = False
) -> dict[str, JsonValue]:
    """Migrate a single project's todo IDs from T-prefix format to numeric dot-notation."""
    todos = storage.load_todos(cfg, project_name)
    meta = storage.load_meta(cfg, project_name)

    if not todos:
        return {"project": project_name, "migrated": False, "reason": "no todos"}

    # Check if already migrated (no T-prefixed IDs)
    t_ids = [t for t in todos if t.id.startswith("T")]
    if not t_ids:
        return {"project": project_name, "migrated": False, "reason": "already migrated"}

    # Build old→new ID mapping
    id_map = _build_id_mapping(todos)

    # Remap all todos
    _apply_remap(todos, id_map)

    # Update meta
    root_count = len([t for t in todos if t.parent is None])
    meta.next_todo_id = root_count + 1

    if dry_run:
        archived = storage.load_archived_todos(cfg, project_name)
        decisions = storage.load_decisions(cfg, project_name)
        return {
            "project": project_name,
            "migrated": False,
            "reason": "dry_run",
            "id_count": len(id_map),
            "archive_count": len(archived),
            "decisions_count": len(decisions),
            "mapping": dict(sorted(id_map.items())),
        }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Export current SQLite state to YAML files so they can be backed up
    from server.lib.migration import export_sqlite_to_yaml

    export_sqlite_to_yaml(cfg, project_name)

    # Create backups of the exported YAML files
    backups: dict[Path, Path | None] = {
        storage.todos_path(cfg, project_name): _backup_file(
            storage.todos_path(cfg, project_name), timestamp
        ),
        storage.meta_path(cfg, project_name): _backup_file(
            storage.meta_path(cfg, project_name), timestamp
        ),
        storage.archive_path(cfg, project_name): _backup_file(
            storage.archive_path(cfg, project_name), timestamp
        ),
        storage.decisions_path(cfg, project_name): _backup_file(
            storage.decisions_path(cfg, project_name), timestamp
        ),
    }

    renamed: list[tuple[str, str]] = []
    try:
        # Save remapped active todos to SQLite
        storage.save_todos(cfg, project_name, todos)
        storage.save_meta(cfg, meta)

        # Migrate archived todos in SQLite
        archived = storage.load_archived_todos(cfg, project_name)
        archive_count = 0
        if archived:
            _apply_remap(archived, id_map)
            storage.replace_archived_todos(cfg, project_name, archived)
            archive_count = len(archived)

        # Migrate decisions in SQLite
        decisions = storage.load_decisions(cfg, project_name)
        decisions_count = 0
        if decisions:
            decisions_count = _migrate_decisions(decisions, id_map)
            if decisions_count:
                storage.replace_decisions(cfg, project_name, decisions)

        # Directory renames LAST (after all SQLite writes committed)
        for old_id, new_id in id_map.items():
            if storage.rename_todo_dir(cfg, project_name, old_id, new_id):
                renamed.append((old_id, new_id))
    except Exception:
        # Reverse directory renames first
        for old_id, new_id in reversed(renamed):
            with contextlib.suppress(Exception):
                storage.rename_todo_dir(cfg, project_name, new_id, old_id)
        # Restore SQLite state from YAML backups
        _restore_sqlite_from_backups(cfg, project_name, backups)
        raise

    return {
        "project": project_name,
        "migrated": True,
        "id_count": len(id_map),
        "archive_count": archive_count,
        "decisions_count": decisions_count,
    }


def register(app: FastMCP) -> None:
    """Register the proj_migrate_ids tool with the MCP app."""

    @app.tool(
        description=(
            "Migrate all project todo IDs from T001 format to numeric dot-notation "
            "(1, 1.1, 2, etc.). Backs up todos.yaml, meta.yaml, archive.yaml, and "
            "decisions.yaml before rewriting. Renames todo content directories to match "
            "new IDs. Migrates ALL tracked projects. Returns structured JSON."
        )
    )
    def proj_migrate_ids(dry_run: bool = False) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)

        results: list[dict[str, JsonValue]] = []
        for project_name in index.projects:
            try:
                result = _migrate_project(cfg, project_name, dry_run=dry_run)
                results.append(result)
            except Exception as e:
                results.append({"project": project_name, "migrated": False, "error": str(e)})

        if not results:
            return json.dumps({"results": [], "dry_run": dry_run})

        return json.dumps({"results": results, "dry_run": dry_run})
