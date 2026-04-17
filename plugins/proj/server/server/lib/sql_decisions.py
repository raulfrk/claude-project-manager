"""Decisions CRUD via SQLite — structured columns, ordered by insertion (id ASC)."""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

from server.lib.db import ensure_db, get_connection

if TYPE_CHECKING:
    import sqlite3

    from server.lib.models import Decision, ProjConfig


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
    """Create decisions table + indexes if absent. Idempotent."""
    conn.executescript(_CREATE_TABLE_SQL)


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
