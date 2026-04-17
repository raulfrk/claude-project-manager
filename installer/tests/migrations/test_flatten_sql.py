# installer/tests/migrations/test_flatten_sql.py
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from installer.migrations.transform import flatten_todos_sql


def _schema(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    path = tmp_path / "data.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE todos (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT,
            priority TEXT,
            parent TEXT,
            children TEXT,
            next_child_id INTEGER,
            tags TEXT
        );
        CREATE TABLE archive_todos (
            id TEXT PRIMARY KEY,
            title TEXT,
            parent TEXT,
            children TEXT,
            next_child_id INTEGER,
            tags TEXT
        );
        INSERT INTO todos VALUES
          ('1','p','pending','high',NULL,'["1.1"]',2,'[]'),
          ('1.1','c','pending','medium','1','[]',1,'["group:1"]');
        INSERT INTO archive_todos VALUES
          ('9','done',NULL,'[]',1,'[]');
        """,
    )
    conn.commit()
    conn.close()
    return path


def test_flatten_removes_columns_from_todos(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    conn = sqlite3.connect(legacy_db)
    cols = _schema(conn, "todos")
    assert "parent" not in cols
    assert "children" not in cols
    assert "next_child_id" not in cols
    assert {"id", "title", "status", "priority", "tags"} <= set(cols)


def test_flatten_removes_columns_from_archive(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    conn = sqlite3.connect(legacy_db)
    cols = _schema(conn, "archive_todos")
    assert "parent" not in cols
    assert "children" not in cols


def test_flatten_preserves_data(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    conn = sqlite3.connect(legacy_db)
    ids = [r[0] for r in conn.execute("SELECT id FROM todos ORDER BY id")]
    assert ids == ["1", "1.1"]
    row = conn.execute(
        "SELECT id,title,status,priority,tags FROM todos WHERE id='1.1'"
    ).fetchone()
    assert row == ("1.1", "c", "pending", "medium", '["group:1"]')


def test_flatten_idempotent(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    flatten_todos_sql(legacy_db)  # should be a no-op
    conn = sqlite3.connect(legacy_db)
    cols = _schema(conn, "todos")
    assert "parent" not in cols


def test_flatten_skips_when_db_absent(tmp_path: Path) -> None:
    flatten_todos_sql(tmp_path / "nope.db")  # must not raise
