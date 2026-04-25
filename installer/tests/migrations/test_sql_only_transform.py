# installer/tests/migrations/test_sql_only_transform.py
"""Tests for sql_only_transform.migrate_yaml_to_sql."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from installer.migrations.sql_only_transform import migrate_yaml_to_sql


def _init_db(project_dir: Path, project_name: str) -> None:
    """Create a minimal data.db with todos, archive_todos, decisions tables."""
    db_path = project_dir / "data.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            created TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT '',
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
        );
        CREATE TABLE IF NOT EXISTS archive_todos (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            created TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT '',
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
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            text TEXT NOT NULL,
            todo_id TEXT,
            tags TEXT DEFAULT '[]'
        );
        """
    )
    conn.commit()
    conn.close()


def _setup_v2_project(project_dir: Path, name: str = "demo") -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "proj.yaml").write_text(f"name: {name}\nschema_version: 2\n")
    _init_db(project_dir, name)
    return project_dir


@pytest.fixture
def v2_project(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    return _setup_v2_project(root)


def test_migrate_todos_and_archive(v2_project: Path) -> None:
    """Todos and archive are written to SQL; YAML files are deleted."""
    (v2_project / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "First",
                    "status": "pending",
                    "priority": "high",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                    "tags": ["tag1"],
                }
            ]
        )
    )
    (v2_project / "archive.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "2",
                    "title": "Done",
                    "status": "done",
                    "priority": "low",
                    "created": "2026-01-01",
                    "updated": "2026-01-02",
                    "tags": [],
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM todos").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == "1"
    assert rows[0]["title"] == "First"
    assert rows[0]["project"] == "demo"
    assert json.loads(rows[0]["tags"]) == ["tag1"]

    archive_rows = conn.execute("SELECT * FROM archive_todos").fetchall()
    assert len(archive_rows) == 1
    assert archive_rows[0]["id"] == "2"
    conn.close()

    # YAML files deleted
    assert not (v2_project / "todos.yaml").exists()
    assert not (v2_project / "archive.yaml").exists()


def test_migrate_dict_valued_field_serialised_to_json(v2_project: Path) -> None:
    """Nested mappings (e.g. trello_sync_state) round-trip as JSON text.

    Real proj-plugin todos serialise TrelloSyncState via dataclasses.asdict,
    which yaml.safe_dump emits as a nested mapping. sqlite3 cannot bind dicts
    directly, so the transform must JSON-encode them.
    """
    sync_state = {
        "card_id": "C1",
        "checklist_id": "CL1",
        "checklist_item_id": "I1",
        "last_synced": "2026-01-02T00:00:00",
    }
    (v2_project / "todos.yaml").write_text("[]")
    (v2_project / "archive.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "9",
                    "title": "Synced",
                    "status": "done",
                    "priority": "medium",
                    "created": "2026-01-01",
                    "updated": "2026-01-02",
                    "trello_sync_state": sync_state,
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT trello_sync_state FROM archive_todos WHERE id='9'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert json.loads(row["trello_sync_state"]) == sync_state


def test_migrate_decisions(v2_project: Path) -> None:
    """Decisions are written to SQL from decisions.yaml."""
    (v2_project / "todos.yaml").write_text("[]")
    (v2_project / "archive.yaml").write_text("[]")
    (v2_project / "decisions.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "timestamp": "2026-01-01T10:00:00",
                    "decision": "Use SQL-only storage",
                    "todo_id": "42",
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM decisions").fetchall()
    assert len(rows) == 1
    assert rows[0]["timestamp"] == "2026-01-01T10:00:00"
    assert rows[0]["text"] == "Use SQL-only storage"
    assert rows[0]["todo_id"] == "42"
    conn.close()

    assert not (v2_project / "decisions.yaml").exists()


def test_migrate_empty_yaml_files(v2_project: Path) -> None:
    """Empty YAML files produce no SQL rows; files are still deleted."""
    (v2_project / "todos.yaml").write_text("[]")
    (v2_project / "archive.yaml").write_text("[]")
    (v2_project / "decisions.yaml").write_text("[]")

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    assert conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    conn.close()

    assert not (v2_project / "todos.yaml").exists()


def test_migrate_yaml_absent_is_noop(v2_project: Path) -> None:
    """If YAML files are absent, operation completes without error."""
    # No YAML files present — all already deleted or never existed
    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    assert conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 0
    conn.close()


def test_migrate_creates_db_when_absent(v2_project: Path) -> None:
    """Missing data.db is auto-created with full schema; YAML rows migrate."""
    (v2_project / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "X",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                }
            ]
        )
    )
    # Remove data.db — v1 projects with git_enabled=false reach v2 without one.
    (v2_project / "data.db").unlink()

    migrate_yaml_to_sql(v2_project)

    assert (v2_project / "data.db").exists()
    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, title, project FROM todos").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == "1"
    assert rows[0]["project"] == "demo"
    conn.close()
    assert not (v2_project / "todos.yaml").exists()
