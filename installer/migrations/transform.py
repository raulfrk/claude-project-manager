from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REMOVED_KEYS = ("parent", "children", "next_child_id")
LEGACY_COLS = {"parent", "children", "next_child_id"}


def flatten_todos_yaml(path: Path) -> None:
    """Rewrite todos.yaml in place: parent/children → group:<parent> tag.

    Idempotent. Writes atomically (temp + rename). Preserves all other fields.
    Orphan children (parent id missing from todos) keep their data but get no
    group tag and a WARNING is logged.
    """
    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} root must be a list")
    ids = {t["id"] for t in data if "id" in t}

    for todo in data:
        parent = todo.pop("parent", None)
        todo.pop("children", None)
        todo.pop("next_child_id", None)
        if parent is None:
            continue
        tag = f"group:{parent}"
        tags = todo.setdefault("tags", [])
        if parent not in ids:
            log.warning(
                "orphan child todo id=%s references missing parent=%s; no group tag added",
                todo.get("id"),
                parent,
            )
            continue
        if tag not in tags:
            tags.append(tag)

    _atomic_write_yaml(path, data)


def _atomic_write_yaml(path: Path, data: list) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        yaml.safe_dump(data, tmp, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def flatten_todos_sql(db_path: Path) -> None:
    """Drop parent/children/next_child_id columns from todos + archive_todos.

    Uses SQLite rebuild pattern: CREATE new table → INSERT SELECT compatible cols →
    DROP old → RENAME. Idempotent: skips tables that don't have the legacy columns.
    Skips silently if db_path doesn't exist (git_enabled=false setups).
    """
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table in ("todos", "archive_todos"):
            _rebuild_table_without_legacy_cols(conn, table)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rebuild_table_without_legacy_cols(conn: sqlite3.Connection, table: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        return  # table doesn't exist in this db
    all_cols = [
        (r[1], r[2], r[3], r[4], r[5]) for r in rows
    ]  # name, type, notnull, default, pk
    keep = [c for c in all_cols if c[0] not in LEGACY_COLS]
    if len(keep) == len(all_cols):
        return  # already flat

    col_defs: list[str] = []
    for name, col_type, notnull, dflt, pk in keep:
        parts = [f'"{name}"', col_type or "TEXT"]
        if notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        if pk:
            parts.append("PRIMARY KEY")
        col_defs.append(" ".join(parts))

    new_table = f"{table}__new"
    col_list = ", ".join(f'"{c[0]}"' for c in keep)
    conn.execute(f'CREATE TABLE "{new_table}" ({", ".join(col_defs)})')
    conn.execute(
        f'INSERT INTO "{new_table}" ({col_list}) SELECT {col_list} FROM "{table}"'
    )
    conn.execute(f'DROP TABLE "{table}"')
    conn.execute(f'ALTER TABLE "{new_table}" RENAME TO "{table}"')
