"""Flat-schema invariants: no parent/children/next_child_id in todos or archive_todos."""

from __future__ import annotations

from pathlib import Path

from server.lib.db import ensure_db, get_connection
from server.lib.models import ProjConfig


def _col_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _index_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}


def test_ensure_db_creates_flat_todos_schema(tmp_path: Path) -> None:
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db = ensure_db(cfg, "demo")
    with get_connection(db) as conn:
        cols = _col_names(conn, "todos")
    assert "parent" not in cols, f"todos.parent must be dropped, got cols={sorted(cols)}"
    assert "children" not in cols, "todos.children must be dropped"
    assert "next_child_id" not in cols, "todos.next_child_id must be dropped"


def test_ensure_db_creates_flat_archive_schema(tmp_path: Path) -> None:
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db = ensure_db(cfg, "demo")
    with get_connection(db) as conn:
        cols = _col_names(conn, "archive_todos")
    assert "parent" not in cols
    assert "children" not in cols
    assert "next_child_id" not in cols


def test_ensure_db_has_no_parent_index(tmp_path: Path) -> None:
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db = ensure_db(cfg, "demo")
    with get_connection(db) as conn:
        indexes = _index_names(conn, "todos")
    assert "idx_todos_parent" not in indexes, (
        f"stale parent index must be dropped, got indexes={sorted(indexes)}"
    )


def test_ensure_db_idempotent_on_pre_migrated_db(tmp_path: Path) -> None:
    """Simulate the real bug: DB where `parent` col was dropped by the flat-todo
    migration. Re-opening must NOT try to CREATE INDEX on todos(parent).
    """
    cfg = ProjConfig(tracking_dir=str(tmp_path))
    (tmp_path / "demo").mkdir()
    db_path = tmp_path / "demo" / "data.db"
    # Pre-migrated schema: flat todos (no parent/children/next_child_id), all other cols present
    import sqlite3

    flat_cols = """
        id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        priority TEXT NOT NULL DEFAULT 'medium',
        created TEXT NOT NULL, updated TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]',
        git_branch TEXT,
        git_commits TEXT NOT NULL DEFAULT '[]',
        blocks TEXT NOT NULL DEFAULT '[]',
        blocked_by TEXT NOT NULL DEFAULT '[]',
        notes TEXT NOT NULL DEFAULT '',
        has_requirements INTEGER NOT NULL DEFAULT 0,
        has_research INTEGER NOT NULL DEFAULT 0,
        todoist_task_id TEXT,
        todoist_desc_synced TEXT NOT NULL DEFAULT '',
        trello_card_id TEXT,
        trello_checklist_id TEXT,
        trello_checklist_item_id TEXT,
        jira_issue_key TEXT,
        jira_comment_ids TEXT NOT NULL DEFAULT '[]',
        due_date TEXT,
        trello_sync_state TEXT
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(f"CREATE TABLE todos ({flat_cols})")
        conn.execute(f"CREATE TABLE archive_todos ({flat_cols})")
    # This call must NOT raise sqlite3.OperationalError
    ensure_db(cfg, "demo")
