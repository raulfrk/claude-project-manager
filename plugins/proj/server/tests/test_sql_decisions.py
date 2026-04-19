"""Unit tests for sql_decisions structured CRUD module."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from server.lib.db import ensure_db, get_connection
from server.lib.models import Decision, ProjConfig
from server.lib.sql_decisions import (
    append_decision,
    ensure_table,
    load_decisions,
    save_decisions,
)


def test_ensure_table_is_idempotent(cfg: ProjConfig) -> None:
    """ensure_table can be called multiple times without error."""
    db_file = ensure_db(cfg, "demo")
    with get_connection(db_file) as conn:
        ensure_table(conn)
        ensure_table(conn)  # second call must not raise
    decisions = load_decisions(cfg, "demo")
    assert decisions == []


def test_load_decisions_empty_returns_empty_list(cfg: ProjConfig) -> None:
    result = load_decisions(cfg, "demo")
    assert result == []


def test_append_decision_assigns_id(cfg: ProjConfig) -> None:
    d = Decision(timestamp="2026-01-01T00:00:00", text="Use SQLite")
    returned = append_decision(cfg, "demo", d)
    assert returned.id is not None
    assert isinstance(returned.id, int)
    assert returned.id >= 1
    assert returned.text == "Use SQLite"


def test_load_decisions_returns_insertion_order(cfg: ProjConfig) -> None:
    for i in range(3):
        append_decision(
            cfg,
            "demo",
            Decision(timestamp=f"2026-01-0{i + 1}T00:00:00", text=f"Decision {i}"),
        )
    result = load_decisions(cfg, "demo")
    assert len(result) == 3
    assert result[0].text == "Decision 0"
    assert result[1].text == "Decision 1"
    assert result[2].text == "Decision 2"
    assert result[0].id < result[1].id < result[2].id


def test_save_decisions_replaces_all(cfg: ProjConfig) -> None:
    for i in range(3):
        append_decision(
            cfg,
            "demo",
            Decision(timestamp="2026-01-01T00:00:00", text=f"Old {i}"),
        )
    new_decisions = [
        Decision(timestamp="2026-06-01T00:00:00", text="New A"),
        Decision(timestamp="2026-06-02T00:00:00", text="New B"),
    ]
    save_decisions(cfg, "demo", new_decisions)
    result = load_decisions(cfg, "demo")
    assert len(result) == 2
    assert result[0].text == "New A"
    assert result[1].text == "New B"


def test_ensure_table_migrates_old_schema(cfg: ProjConfig, tmp_path: Path) -> None:
    """Regression: todo 681 — legacy decisions schema (project, data) must migrate.

    Old schema (commit 30ccca6): (id, project, timestamp, data) where data was
    a JSON blob. New schema (commit 3d64138): (id, timestamp, text, todo_id, tags).

    `CREATE TABLE IF NOT EXISTS` is a no-op on existing tables, so ensure_table
    must detect legacy columns and migrate in-place.
    """
    # Build a legacy DB file at the exact path ensure_db uses.
    db_file = Path(cfg.tracking_dir).expanduser() / "legacy" / "data.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE INDEX idx_decisions_project ON decisions(project);
        """
    )
    conn.execute(
        "INSERT INTO decisions (project, timestamp, data) VALUES (?, ?, ?)",
        (
            "legacy",
            "2026-04-01T12:00:00",
            json.dumps(
                {
                    "timestamp": "2026-04-01T12:00:00",
                    "decision": "Use SQLite",
                    "todo_id": "42",
                    "tags": ["architecture"],
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO decisions (project, timestamp, data) VALUES (?, ?, ?)",
        (
            "legacy",
            "2026-04-02T09:00:00",
            json.dumps(
                {
                    "timestamp": "2026-04-02T09:00:00",
                    "decision": "Add flat-todo model",
                    "todo_id": "",
                    "tags": ["session-extracted"],
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    # Trigger ensure_table via the normal ensure_db path.
    ensure_db(cfg, "legacy")

    # New schema must now be in place AND legacy rows must have survived.
    with get_connection(db_file) as inspect:
        cols = {row["name"] for row in inspect.execute("PRAGMA table_info(decisions)").fetchall()}
    assert {"id", "timestamp", "text", "todo_id", "tags"} <= cols
    assert "data" not in cols  # old column removed

    loaded = load_decisions(cfg, "legacy")
    assert len(loaded) == 2
    texts = {d.text for d in loaded}
    assert texts == {"Use SQLite", "Add flat-todo model"}
    by_text = {d.text: d for d in loaded}
    assert by_text["Use SQLite"].todo_id == "42"
    assert by_text["Use SQLite"].tags == ["architecture"]
    assert by_text["Add flat-todo model"].todo_id in (None, "")
    assert by_text["Add flat-todo model"].tags == ["session-extracted"]


def test_decision_dataclass_roundtrip(cfg: ProjConfig) -> None:
    """Full roundtrip: all fields preserved across append → load."""
    d = Decision(
        timestamp="2026-03-15T10:30:00",
        text="Switch to SQL-only storage",
        todo_id="647",
        tags=["architecture", "storage"],
    )
    returned = append_decision(cfg, "demo", d)
    assert returned.id is not None

    loaded = load_decisions(cfg, "demo")
    assert len(loaded) == 1
    item = loaded[0]
    assert item.text == "Switch to SQL-only storage"
    assert item.timestamp == "2026-03-15T10:30:00"
    assert item.todo_id == "647"
    assert item.tags == ["architecture", "storage"]
    assert item.id == returned.id
