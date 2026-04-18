# installer/tests/migrations/e2e/test_e2e_v2_to_v3.py
"""E2E: already-flat (v2) project migrates to SQL-only (v3) successfully.

Verifies:
- YAML files (todos.yaml, archive.yaml, decisions.yaml) are deleted
- data.db contains all migrated rows
- schema_version bumped to 3 in proj.yaml
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.orchestrator import run_migrations_for_project
from installer.migrations.types import PendingProject


def _init_db(project_dir: Path) -> None:
    db_path = project_dir / "data.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY, project TEXT NOT NULL,
            title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            created TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]', git_branch TEXT,
            git_commits TEXT NOT NULL DEFAULT '[]',
            blocks TEXT NOT NULL DEFAULT '[]',
            blocked_by TEXT NOT NULL DEFAULT '[]',
            notes TEXT NOT NULL DEFAULT '',
            has_requirements INTEGER NOT NULL DEFAULT 0,
            has_research INTEGER NOT NULL DEFAULT 0,
            todoist_task_id TEXT, todoist_desc_synced TEXT NOT NULL DEFAULT '',
            trello_card_id TEXT, trello_checklist_id TEXT,
            trello_checklist_item_id TEXT, jira_issue_key TEXT,
            jira_comment_ids TEXT NOT NULL DEFAULT '[]',
            due_date TEXT, trello_sync_state TEXT
        );
        CREATE TABLE IF NOT EXISTS archive_todos (
            id TEXT PRIMARY KEY, project TEXT NOT NULL,
            title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            created TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]', git_branch TEXT,
            git_commits TEXT NOT NULL DEFAULT '[]',
            blocks TEXT NOT NULL DEFAULT '[]',
            blocked_by TEXT NOT NULL DEFAULT '[]',
            notes TEXT NOT NULL DEFAULT '',
            has_requirements INTEGER NOT NULL DEFAULT 0,
            has_research INTEGER NOT NULL DEFAULT 0,
            todoist_task_id TEXT, todoist_desc_synced TEXT NOT NULL DEFAULT '',
            trello_card_id TEXT, trello_checklist_id TEXT,
            trello_checklist_item_id TEXT, jira_issue_key TEXT,
            jira_comment_ids TEXT NOT NULL DEFAULT '[]',
            due_date TEXT, trello_sync_state TEXT
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


@pytest.fixture
def v2_project(tmp_path: Path) -> PendingProject:
    root = tmp_path / "myapp"
    root.mkdir()
    (root / ".schema-version").write_text("2\n")

    (root / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "Implement SQL-only storage",
                    "status": "done",
                    "priority": "high",
                    "created": "2026-01-01",
                    "updated": "2026-04-01",
                    "tags": ["group:parent"],
                    "todoist_task_id": "tod-1",
                },
                {
                    "id": "2",
                    "title": "Write tests",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-02",
                    "updated": "2026-04-01",
                    "tags": [],
                },
            ]
        )
    )
    (root / "archive.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "0",
                    "title": "Old task",
                    "status": "done",
                    "priority": "low",
                    "created": "2025-12-01",
                    "updated": "2025-12-31",
                    "tags": [],
                }
            ]
        )
    )
    (root / "decisions.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "timestamp": "2026-04-01T10:00:00",
                    "decision": "Use SQL as single source of truth",
                    "context": "Eliminated YAML+SQL hybrid",
                }
            ]
        )
    )
    _init_db(root)
    return PendingProject(
        name="myapp",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=2,
    )


def test_v2_to_v3_migration(v2_project: PendingProject, tmp_path: Path) -> None:
    """Full v2→v3 E2E: YAML gone, SQL populated, schema bumped to 3."""
    backup_root = tmp_path / "backups"
    result = run_migrations_for_project(v2_project, "e2e-ts", backup_root)

    # Migration completed successfully
    assert result.stopped_at == 3
    assert result.reason == "complete"

    # schema_version bumped to 3
    assert read_schema_version(v2_project.schema_version_path) == 3

    # YAML files deleted
    assert not (v2_project.path / "todos.yaml").exists()
    assert not (v2_project.path / "archive.yaml").exists()
    assert not (v2_project.path / "decisions.yaml").exists()

    # Todos in SQL
    conn = sqlite3.connect(v2_project.path / "data.db")
    conn.row_factory = sqlite3.Row
    todos = conn.execute("SELECT * FROM todos ORDER BY id").fetchall()
    archive = conn.execute("SELECT * FROM archive_todos").fetchall()
    decisions = conn.execute("SELECT * FROM decisions").fetchall()
    conn.close()

    assert len(todos) == 2
    assert todos[0]["id"] == "1"
    assert todos[0]["title"] == "Implement SQL-only storage"
    assert todos[0]["project"] == "myapp"
    assert json.loads(todos[0]["tags"]) == ["group:parent"]
    assert todos[0]["todoist_task_id"] == "tod-1"

    assert len(archive) == 1
    assert archive[0]["id"] == "0"

    assert len(decisions) == 1
    assert decisions[0]["text"] == "Use SQL as single source of truth"
    assert decisions[0]["timestamp"] == "2026-04-01T10:00:00"
