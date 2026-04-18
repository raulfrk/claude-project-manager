# installer/tests/migrations/test_migration_orchestrator.py
"""Tests for migration orchestrator (chains v1→v2→v3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.orchestrator import run_migrations_for_project
from installer.migrations.types import PendingProject


def _init_db(project_dir: Path) -> None:
    """Create a minimal data.db with the tables needed for both migrations."""
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


def _make_v1_project(root: Path) -> PendingProject:
    """v1 project: nested parent/children in todos.yaml, no schema_version.

    The DB uses the full production schema (matching db.py _TODO_COLUMNS) so
    that after FlatTodoMigration (which drops parent/children/next_child_id),
    the remaining columns are compatible with SqlOnlyMigration's INSERT.
    """
    root.mkdir(parents=True, exist_ok=True)
    # v1: no .schema-version file → treated as v1 (absent = 1)
    (root / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "Parent",
                    "parent": None,
                    "children": ["1.1"],
                    "tags": [],
                },
                {
                    "id": "1.1",
                    "title": "Child",
                    "parent": "1",
                    "children": [],
                    "tags": [],
                },
            ]
        )
    )
    (root / "archive.yaml").write_text("[]")
    (root / "decisions.yaml").write_text("[]")
    # Use the flat-schema DB (flatten_todos_sql is idempotent — no-op when
    # legacy columns are absent). FlatTodoMigration rewrites the YAML only.
    _init_db(root)
    return PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=1,
    )


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


def test_orchestrator_v1_chains_through_both_migrations(tmp_path: Path) -> None:
    """v1 project: FlatTodoMigration then SqlOnlyMigration → v3."""
    project = _make_v1_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    result = run_migrations_for_project(project, "ts1", backup_root)
    assert result.stopped_at == 3
    assert result.reason == "complete"
    assert read_schema_version(project.schema_version_path) == 3
    assert not (project.path / "todos.yaml").exists()
    assert not (project.path / "decisions.yaml").exists()


def test_orchestrator_v2_runs_sql_only_only(tmp_path: Path) -> None:
    """v2 project: only SqlOnlyMigration runs; ends at v3."""
    project = _make_v2_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    result = run_migrations_for_project(project, "ts1", backup_root)
    assert result.stopped_at == 3
    assert result.reason == "complete"
    assert read_schema_version(project.schema_version_path) == 3
    assert not (project.path / "todos.yaml").exists()


def test_orchestrator_v3_is_noop(tmp_path: Path) -> None:
    """v3 project: already up-to-date, no migrations run."""
    root = tmp_path / "p"
    root.mkdir()
    (root / ".schema-version").write_text("3\n")
    _init_db(root)
    project = PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=3,
    )
    result = run_migrations_for_project(project, "ts1", tmp_path / "backups")
    assert result.stopped_at == 3
    assert result.reason == "complete"


def test_orchestrator_stops_at_v2_when_sql_only_fails(tmp_path: Path) -> None:
    """If sql-only phase fails, project stays at v2; reason recorded."""
    project = _make_v2_project(tmp_path / "p")
    backup_root = tmp_path / "backups"

    with patch(
        "installer.migrations.sql_only.migrate_yaml_to_sql",
        side_effect=RuntimeError("db locked"),
    ):
        result = run_migrations_for_project(project, "ts1", backup_root)

    assert result.stopped_at == 2
    assert "sql-only failed" in result.reason
    # Project still at v2 — YAML files restored from backup
    assert read_schema_version(project.schema_version_path) == 2
    assert (project.path / "todos.yaml").exists()
