# installer/tests/migrations/test_sql_only_runner.py
"""Tests for SqlOnlyMigration runner (v2 → v3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.sql_only import SqlOnlyMigration
from installer.migrations.types import MigrationState, PendingProject


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


def _make_v2_project(root: Path) -> PendingProject:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".schema-version").write_text("2\n")
    (root / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "A todo",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                }
            ]
        )
    )
    (root / "archive.yaml").write_text("[]")
    (root / "decisions.yaml").write_text("[]")
    _init_db(root)
    return PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=2,
    )


def test_happy_path_commits(tmp_path: Path) -> None:
    """Full v2→v3 migration: plan → confirm → execute_local → commit."""
    project = _make_v2_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    runner = SqlOnlyMigration(project=project, run_ts="ts1", backup_root=backup_root)
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()

    assert runner.state == MigrationState.COMMITTED
    assert read_schema_version(project.schema_version_path) == 3
    assert not (project.path / "todos.yaml").exists()
    assert not (project.path / "archive.yaml").exists()
    assert not (project.path / "decisions.yaml").exists()

    conn = sqlite3.connect(project.path / "data.db")
    row_count = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
    conn.close()
    assert row_count == 1


def test_rollback_on_transform_failure(tmp_path: Path) -> None:
    """If _flatten raises, state transitions to FAILED and YAML files are restored."""
    project = _make_v2_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    runner = SqlOnlyMigration(project=project, run_ts="ts1", backup_root=backup_root)
    runner.plan()
    runner.confirm()

    with patch(
        "installer.migrations.sql_only.migrate_yaml_to_sql",
        side_effect=RuntimeError("simulated failure"),
    ):
        with pytest.raises(RuntimeError, match="simulated failure"):
            runner.execute_local()

    assert runner.state == MigrationState.FAILED
    # YAML files restored from backup
    assert (project.path / "todos.yaml").exists()
    assert (project.path / ".schema-version").exists()


def test_bump_only_when_yaml_absent(tmp_path: Path) -> None:
    """If YAML files already absent, skip flatten and jump straight to RESYNCED."""
    root = tmp_path / "p"
    root.mkdir()
    (root / ".schema-version").write_text("2\n")
    # No YAML files — already SQL-only
    _init_db(root)
    project = PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=2,
    )
    backup_root = tmp_path / "backups"
    runner = SqlOnlyMigration(project=project, run_ts="ts1", backup_root=backup_root)
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()

    assert runner.state == MigrationState.COMMITTED
    assert read_schema_version(project.schema_version_path) == 3
