"""Decisions CRUD via SQLite — structured columns, ordered by insertion (id ASC)."""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import TYPE_CHECKING

from server.lib.db import ensure_db, get_connection

if TYPE_CHECKING:
    import sqlite3

    from server.lib.models import Decision, ProjConfig


_log = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    text TEXT NOT NULL,
    todo_id TEXT,
    tags TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_decisions_todo_id ON decisions(todo_id);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    """Create decisions table + indexes if absent. Idempotent.

    Also migrates legacy schema (project, data) from pre-3d64138 to the
    current (text, todo_id, tags) schema. Old rows' JSON data is parsed
    into the new columns; the `context` field is dropped (never used in
    the new model).
    """
    if _has_legacy_decisions_schema(conn):
        _migrate_legacy_decisions(conn)
    conn.executescript(_CREATE_TABLE_SQL)


def _has_legacy_decisions_schema(conn: sqlite3.Connection) -> bool:
    """True iff `decisions` table exists AND still has pre-3d64138 shape
    (`data` column present, `text` column absent)."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
    if not cols:
        return False
    return "data" in cols and "text" not in cols


def _migrate_legacy_decisions(conn: sqlite3.Connection) -> None:
    """Rename legacy table, recreate with new schema, copy parsed rows back.

    Legacy row's `data` column is a JSON blob with keys
    {timestamp, decision, context, todo_id, tags}. The `decision` field
    becomes `text`; `context` is discarded (new model has no equivalent).
    Rows whose JSON can't be parsed are skipped with a warning to avoid
    poisoning the new table.
    """
    _log.info("Migrating legacy decisions schema → structured columns")
    conn.executescript(
        """
        ALTER TABLE decisions RENAME TO decisions_legacy;
        DROP INDEX IF EXISTS idx_decisions_project;
        """
    )
    # Create new table before reading legacy so the INSERTs below have a target.
    conn.executescript(_CREATE_TABLE_SQL)
    rows = conn.execute(
        "SELECT id, timestamp, data FROM decisions_legacy ORDER BY id ASC"
    ).fetchall()
    for row in rows:
        try:
            blob = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            _log.warning(
                "Skipping legacy decisions row id=%s — malformed JSON in data column",
                row["id"],
            )
            continue
        text = str(blob.get("decision") or blob.get("text") or "").strip()
        if not text:
            _log.warning(
                "Skipping legacy decisions row id=%s — missing decision/text field",
                row["id"],
            )
            continue
        todo_id_raw = blob.get("todo_id")
        todo_id = str(todo_id_raw) if todo_id_raw else None
        tags_raw = blob.get("tags", [])
        tags = tags_raw if isinstance(tags_raw, list) else []
        conn.execute(
            "INSERT INTO decisions (timestamp, text, todo_id, tags) VALUES (?, ?, ?, ?)",
            (row["timestamp"], text, todo_id, json.dumps(tags)),
        )
    conn.execute("DROP TABLE decisions_legacy")


def load_decisions(cfg: ProjConfig, project_name: str) -> list[Decision]:
    """Load all decisions ordered by insertion order (id ASC).

    Returns [] if none found.
    """
    from server.lib.models import Decision

    db_file = ensure_db(cfg, project_name)
    with get_connection(db_file) as conn:
        rows = conn.execute(
            "SELECT id, timestamp, text, todo_id, tags FROM decisions ORDER BY id ASC",
        ).fetchall()
    return [
        Decision(
            id=row["id"],
            timestamp=row["timestamp"],
            text=row["text"],
            todo_id=row["todo_id"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
        )
        for row in rows
    ]


def save_decisions(cfg: ProjConfig, project_name: str, decisions: list[Decision]) -> None:
    """Replace all decisions atomically (DELETE + bulk INSERT)."""
    db_file = ensure_db(cfg, project_name)
    with get_connection(db_file) as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM decisions")
        for d in decisions:
            conn.execute(
                "INSERT INTO decisions (timestamp, text, todo_id, tags) VALUES (?, ?, ?, ?)",
                (
                    d.timestamp,
                    d.text,
                    d.todo_id,
                    json.dumps(d.tags),
                ),
            )
        conn.execute("COMMIT")


def append_decision(cfg: ProjConfig, project_name: str, decision: Decision) -> Decision:
    """Single INSERT; returns Decision with assigned id.

    The timestamp is stored as-is (even empty string) for legacy compat.
    Callers should provide a valid ISO timestamp for new entries.
    """
    db_file = ensure_db(cfg, project_name)
    with get_connection(db_file) as conn:
        cursor = conn.execute(
            "INSERT INTO decisions (timestamp, text, todo_id, tags) VALUES (?, ?, ?, ?)",
            (
                decision.timestamp,
                decision.text,
                decision.todo_id,
                json.dumps(decision.tags),
            ),
        )
        assigned_id = int(cursor.lastrowid) if cursor.lastrowid is not None else None
    return dataclasses.replace(decision, id=assigned_id)
