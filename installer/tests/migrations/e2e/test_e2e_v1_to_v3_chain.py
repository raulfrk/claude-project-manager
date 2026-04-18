# installer/tests/migrations/e2e/test_e2e_v1_to_v3_chain.py
"""E2E: legacy v1 project chains through FlatTodoMigration then SqlOnlyMigration → v3.

Verifies:
- v1 project (nested parent/children, no schema_version) reaches v3 via full chain
- YAML files deleted
- data.db contains flattened todos with group: tags
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
def v1_project(tmp_path: Path) -> PendingProject:
    root = tmp_path / "legacy"
    root.mkdir()
    # v1: no .schema-version file → treated as v1 (absent = 1)

    (root / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "Parent feature",
                    "status": "pending",
                    "priority": "high",
                    "created": "2025-06-01",
                    "updated": "2025-06-01",
                    "tags": [],
                    "parent": None,
                    "children": ["1.1", "1.2"],
                },
                {
                    "id": "1.1",
                    "title": "Sub-task A",
                    "status": "done",
                    "priority": "medium",
                    "created": "2025-06-02",
                    "updated": "2025-06-10",
                    "tags": [],
                    "parent": "1",
                    "children": [],
                },
                {
                    "id": "1.2",
                    "title": "Sub-task B",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2025-06-02",
                    "updated": "2025-06-02",
                    "tags": [],
                    "parent": "1",
                    "children": [],
                },
            ]
        )
    )
    (root / "archive.yaml").write_text(yaml.safe_dump([]))
    (root / "decisions.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "timestamp": "2025-06-01T09:00:00",
                    "decision": "Start with sub-tasks",
                    "context": "Break down the feature first",
                }
            ]
        )
    )
    _init_db(root)
    return PendingProject(
        name="legacy",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=1,
    )


def test_v1_to_v3_chain_migration(v1_project: PendingProject, tmp_path: Path) -> None:
    """Full v1→v2→v3 chain: nested YAML flattened then moved to SQL."""
    backup_root = tmp_path / "backups"
    result = run_migrations_for_project(v1_project, "e2e-ts", backup_root)

    # Migration completed successfully through full chain
    assert result.stopped_at == 3
    assert result.reason == "complete"

    # schema_version bumped to 3
    assert read_schema_version(v1_project.schema_version_path) == 3

    # YAML files deleted
    assert not (v1_project.path / "todos.yaml").exists()
    assert not (v1_project.path / "archive.yaml").exists()
    assert not (v1_project.path / "decisions.yaml").exists()

    # Todos in SQL — parent/children flattened to group: tags
    conn = sqlite3.connect(v1_project.path / "data.db")
    conn.row_factory = sqlite3.Row
    todos = conn.execute("SELECT * FROM todos ORDER BY id").fetchall()
    archive = conn.execute("SELECT * FROM archive_todos").fetchall()
    decisions = conn.execute("SELECT * FROM decisions").fetchall()
    conn.close()

    assert len(todos) == 3
    assert len(archive) == 0

    # FlatTodoMigration adds group:<parent_id> tag to children; parent keeps empty tags
    ids = {row["id"]: row for row in todos}
    assert "1" in ids
    assert "1.1" in ids
    assert "1.2" in ids

    # Children get group:<parent_id> tag
    child_a_tags = json.loads(ids["1.1"]["tags"])
    assert "group:1" in child_a_tags

    child_b_tags = json.loads(ids["1.2"]["tags"])
    assert "group:1" in child_b_tags

    # All rows have correct project name
    for row in todos:
        assert row["project"] == "legacy"

    # Decision migrated
    assert len(decisions) == 1
    assert decisions[0]["text"] == "Start with sub-tasks"
    assert decisions[0]["timestamp"] == "2025-06-01T09:00:00"
