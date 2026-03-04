"""MCP tool for migrating todo IDs from T-prefix format to numeric dot-notation."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from server.lib import storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from server.lib.models import ProjConfig


def _assign_ids(
    parent_todos: list,
    all_todos: list,
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


def _build_id_mapping(todos: list) -> dict[str, str]:
    """Build old→new ID mapping for all todos, sorted by creation date."""
    root_todos = sorted(
        [t for t in todos if t.parent is None],
        key=lambda t: (t.created, t.id),
    )
    id_map: dict[str, str] = {}
    _assign_ids(root_todos, todos, id_map)
    return id_map


def _apply_remap(todos: list, id_map: dict[str, str]) -> None:
    """Apply id_map to all todo fields in-place."""
    for todo in todos:
        todo.id = id_map.get(todo.id, todo.id)
        todo.parent = id_map.get(todo.parent, todo.parent) if todo.parent else None
        todo.children = [id_map.get(c, c) for c in todo.children]
        todo.blocks = [id_map.get(b, b) for b in todo.blocks]
        todo.blocked_by = [id_map.get(b, b) for b in todo.blocked_by]
        # Set next_child_id = len(children) + 1
        todo.next_child_id = len(todo.children) + 1


def _migrate_project(cfg: ProjConfig, project_name: str, dry_run: bool = False) -> str:
    """Migrate a single project's todo IDs from T-prefix format to numeric dot-notation."""
    todos = storage.load_todos(cfg, project_name)
    meta = storage.load_meta(cfg, project_name)

    if not todos:
        return f"{project_name}: no todos to migrate"

    # Check if already migrated (no T-prefixed IDs)
    t_ids = [t for t in todos if t.id.startswith("T")]
    if not t_ids:
        return f"{project_name}: already migrated (skipped)"

    # Build old→new ID mapping
    id_map = _build_id_mapping(todos)

    # Remap all todos
    _apply_remap(todos, id_map)

    # Update meta
    root_count = len([t for t in todos if t.parent is None])
    meta.next_todo_id = root_count + 1

    if dry_run:
        mapping_lines = "\n".join(
            f"  {old} -> {new}" for old, new in sorted(id_map.items())
        )
        return f"{project_name}: would migrate {len(id_map)} todos\n{mapping_lines}"

    # Backup todos.yaml
    todos_file = storage.todos_path(cfg, project_name)
    backup_file = todos_file.with_suffix(".yaml.bak")
    shutil.copy2(todos_file, backup_file)

    # Rename content dirs (before saving, using old IDs from id_map keys)
    for old_id, new_id in id_map.items():
        storage.rename_todo_dir(cfg, project_name, old_id, new_id)

    # Save
    storage.save_todos(cfg, project_name, todos)
    storage.save_meta(cfg, meta)

    return f"{project_name}: migrated {len(id_map)} todos (backup: {backup_file})"


def register(app: FastMCP) -> None:
    """Register the proj_migrate_ids tool with the MCP app."""

    @app.tool(
        description=(
            "Migrate all project todo IDs from T001 format to numeric dot-notation "
            "(1, 1.1, 2, etc.). Backs up todos.yaml before rewriting. "
            "Renames todo content directories to match new IDs. Migrates ALL tracked projects."
        )
    )
    def proj_migrate_ids(dry_run: bool = False) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)

        results = []
        for project_name in index.projects:
            try:
                result = _migrate_project(cfg, project_name, dry_run=dry_run)
                results.append(result)
            except Exception as e:
                results.append(f"{project_name}: ERROR - {e}")

        if not results:
            return "No projects found to migrate."

        return "\n".join(results)
