"""YAML ↔ SQLite migration helpers for proj storage."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from server.lib.db import db_path, ensure_db, get_connection

if TYPE_CHECKING:
    from server.lib.models import ProjConfig

logger = logging.getLogger(__name__)

# Module-level cache — reset on process restart naturally.
_migrated_projects: set[str] = set()


def _yaml_safe_load(path: Path) -> object:
    """Load YAML file, return {} or [] based on expected type if missing/corrupt."""
    try:
        with path.open() as f:
            return yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError):
        return None


def migrate_yaml_to_sqlite(cfg: ProjConfig, project_name: str) -> dict[str, int | str]:
    """One-time YAML → SQLite migration. Idempotent.

    Steps:
    1. Compute db_path for project
    2. If data.db already exists AND has rows in todos OR project_meta table: return
       {"status": "already_migrated", ...}
    3. If data.db exists but empty (partial/crashed migration): delete it and re-migrate
    4. Load from YAML files directly (NOT via storage.load_* to avoid circular calls)
    5. Open connection, init_schema
    6. Batch INSERT all todos into todos table
    7. Batch INSERT all archived todos into archive_todos table
    8. INSERT OR REPLACE meta into project_meta table
    9. Batch INSERT decisions into decisions table
    10. COMMIT (use 'with conn:' transaction)
    11. ONLY after successful commit: rename YAML files to .bak
    12. Return counts
    """
    from server.lib import sql_todos
    from server.lib.models import ProjectMeta, Todo

    path = db_path(cfg, project_name)
    tdir = Path(cfg.tracking_dir).expanduser() / project_name

    # Check if already migrated
    if path.exists():
        conn = get_connection(path)
        try:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as n FROM todos WHERE project=?", (project_name,)
                ).fetchone()
                todo_count = row["n"] if row else 0
            except Exception:
                todo_count = 0

            try:
                row = conn.execute(
                    "SELECT COUNT(*) as n FROM project_meta WHERE name=?", (project_name,)
                ).fetchone()
                meta_count = row["n"] if row else 0
            except Exception:
                meta_count = 0
        finally:
            conn.close()

        if todo_count > 0 or meta_count > 0:
            logger.debug("Project %r already migrated to SQLite", project_name)
            return {
                "status": "already_migrated",
                "migrated_todos": 0,
                "migrated_archived": 0,
                "migrated_decisions": 0,
            }

        # Exists but empty — partial/crashed migration, delete and re-migrate
        logger.warning("Partial migration detected for %r — re-migrating", project_name)
        path.unlink()

    # Load from YAML directly
    todos_yaml_path = tdir / "todos.yaml"
    archive_yaml_path = tdir / "archive.yaml"
    meta_yaml_path = tdir / "meta.yaml"
    decisions_yaml_path = tdir / "decisions.yaml"

    todos_raw_data = _yaml_safe_load(todos_yaml_path)
    archive_raw_data = _yaml_safe_load(archive_yaml_path)
    meta_raw_data = _yaml_safe_load(meta_yaml_path)
    decisions_raw_data = _yaml_safe_load(decisions_yaml_path)

    # Parse todos
    todos_list: list[dict[str, object]] = []
    if isinstance(todos_raw_data, dict):
        raw = todos_raw_data.get("todos", [])
        if isinstance(raw, list):
            todos_list = [t for t in raw if isinstance(t, dict)]

    # Parse archived todos
    archive_list: list[dict[str, object]] = []
    if isinstance(archive_raw_data, dict):
        raw = archive_raw_data.get("todos", [])
        if isinstance(raw, list):
            archive_list = [t for t in raw if isinstance(t, dict)]

    # Parse meta
    meta_dict: dict[str, object] = {}
    if isinstance(meta_raw_data, dict):
        meta_dict = meta_raw_data

    # Parse decisions
    decisions_list: list[dict[str, object]] = []
    if isinstance(decisions_raw_data, list):
        decisions_list = [d for d in decisions_raw_data if isinstance(d, dict)]

    # Convert todo dicts → Todo objects → rows
    todos_objs = [Todo.from_dict(t) for t in todos_list]  # type: ignore[arg-type]
    archive_objs = [Todo.from_dict(t) for t in archive_list]  # type: ignore[arg-type]

    # Open DB, init schema, migrate in one transaction
    db_file = ensure_db(cfg, project_name)
    conn = get_connection(db_file)
    try:
        with conn:
            # Insert active todos
            if todos_objs:
                rows = []
                for todo in todos_objs:
                    row = sql_todos._todo_to_row(todo)
                    row["project"] = project_name
                    rows.append(row)
                cols = list(rows[0].keys())
                placeholders = ", ".join(f":{c}" for c in cols)
                col_names = ", ".join(cols)
                conn.executemany(
                    f"INSERT INTO todos ({col_names}) VALUES ({placeholders})",  # noqa: S608
                    rows,
                )

            # Insert archived todos
            if archive_objs:
                rows = []
                for todo in archive_objs:
                    row = sql_todos._todo_to_row(todo)
                    row["project"] = project_name
                    rows.append(row)
                cols = list(rows[0].keys())
                placeholders = ", ".join(f":{c}" for c in cols)
                col_names = ", ".join(cols)
                conn.executemany(
                    f"INSERT INTO archive_todos ({col_names}) VALUES ({placeholders})",  # noqa: S608
                    rows,
                )

            # Insert meta (if present)
            if meta_dict:
                try:
                    meta = ProjectMeta.from_dict(meta_dict)  # type: ignore[arg-type]
                    meta.dates.last_updated = str(date.today())
                    payload = json.dumps(dataclasses.asdict(meta))
                    conn.execute(
                        "INSERT OR REPLACE INTO project_meta (name, data) VALUES (?, ?)",
                        (project_name, payload),
                    )
                except Exception:
                    logger.warning("Failed to migrate meta for %r — skipping", project_name)

            # Insert decisions
            for decision in decisions_list:
                timestamp = decision.get("timestamp") or ""
                conn.execute(
                    "INSERT INTO decisions (project, timestamp, data) VALUES (?, ?, ?)",
                    (project_name, timestamp, json.dumps(decision)),
                )
    finally:
        conn.close()

    # Only after successful commit: rename YAML files to .bak
    for yaml_path in [todos_yaml_path, archive_yaml_path, meta_yaml_path, decisions_yaml_path]:
        if yaml_path.exists():
            bak_path = yaml_path.with_suffix(yaml_path.suffix + ".bak")
            try:
                yaml_path.rename(bak_path)
            except Exception as exc:
                logger.warning("Could not rename %s → %s: %s", yaml_path, bak_path, exc)

    logger.info(
        "Migrated project %r: %d todos, %d archived, %d decisions",
        project_name,
        len(todos_objs),
        len(archive_objs),
        len(decisions_list),
    )
    return {
        "migrated_todos": len(todos_objs),
        "migrated_archived": len(archive_objs),
        "migrated_decisions": len(decisions_list),
    }


def export_sqlite_to_yaml(cfg: ProjConfig, project_name: str) -> list[Path]:
    """Export SQLite data back to YAML files (for git commits).

    Called by tracking_git_flush before git add -A.

    Steps:
    1. Load todos from sql_todos.load_todos
    2. Load archived todos from sql_todos.load_archived_todos
    3. Load meta from sql_meta.load_meta
    4. Load decisions from sql_decisions.load_decisions
    5. Write YAML files
    6. Return list of paths written
    """
    import os
    import tempfile

    from server.lib import sql_decisions, sql_meta, sql_todos

    tdir = Path(cfg.tracking_dir).expanduser() / project_name
    tdir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    def _write_yaml(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        tmp = Path(tmp_str)
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    # todos.yaml
    todos = sql_todos.load_todos(cfg, project_name)
    todos_path = tdir / "todos.yaml"
    _write_yaml(todos_path, {"todos": [t.to_dict() for t in todos]})
    written.append(todos_path)

    # archive.yaml
    archived = sql_todos.load_archived_todos(cfg, project_name)
    archive_path = tdir / "archive.yaml"
    _write_yaml(archive_path, {"todos": [t.to_dict() for t in archived]})
    written.append(archive_path)

    # meta.yaml
    try:
        meta = sql_meta.load_meta(cfg, project_name)
        meta_path = tdir / "meta.yaml"
        _write_yaml(meta_path, dataclasses.asdict(meta))
        written.append(meta_path)
    except FileNotFoundError:
        logger.warning("No meta found for %r — skipping meta.yaml export", project_name)

    # decisions.yaml
    decisions = sql_decisions.load_decisions(cfg, project_name)
    decisions_path = tdir / "decisions.yaml"
    _write_yaml(decisions_path, decisions)
    written.append(decisions_path)

    return written


def _ensure_migrated(cfg: ProjConfig, project_name: str) -> None:
    """Auto-migration hook — call at start of load_todos/load_meta.

    If data.db doesn't exist: run migrate_yaml_to_sqlite.
    If data.db exists: no-op.
    Uses module-level set to avoid re-checking on every call.
    """
    if project_name in _migrated_projects:
        return

    path = db_path(cfg, project_name)
    if not path.exists():
        migrate_yaml_to_sqlite(cfg, project_name)

    _migrated_projects.add(project_name)
