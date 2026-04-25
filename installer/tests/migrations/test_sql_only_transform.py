# installer/tests/migrations/test_sql_only_transform.py
"""Tests for sql_only_transform.migrate_yaml_to_sql.

The wizard transform is now a thin shim over the proj plugin's canonical
`migrate_yaml_to_sqlite`. These tests assert the contract the wizard
relies on: every Todo field round-trips, meta.yaml populates the
project_meta table, YAMLs are renamed to .bak instead of deleted, and
the function is idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from installer.migrations.sql_only_transform import migrate_yaml_to_sql


def _setup_v2_project(tmp_path: Path, name: str = "demo") -> Path:
    """Build an empty v2 project dir (no data.db — runtime migrate creates it)."""
    project_dir = tmp_path / name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "proj.yaml").write_text(f"name: {name}\nschema_version: 2\n")
    return project_dir


@pytest.fixture
def v2_project(tmp_path: Path) -> Path:
    return _setup_v2_project(tmp_path)


def _wrap(todos: list[dict]) -> str:
    return yaml.safe_dump({"todos": todos})


def test_migrate_todos_and_archive(v2_project: Path) -> None:
    """Active and archived todos land in their respective tables."""
    (v2_project / "todos.yaml").write_text(
        _wrap(
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
        _wrap(
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
    assert rows[0]["project"] == "demo"
    assert json.loads(rows[0]["tags"]) == ["tag1"]

    archive_rows = conn.execute("SELECT * FROM archive_todos").fetchall()
    assert len(archive_rows) == 1
    assert archive_rows[0]["id"] == "2"
    conn.close()


def test_yamls_renamed_to_bak(v2_project: Path) -> None:
    """Migrated YAMLs are preserved as <name>.bak, not deleted."""
    (v2_project / "todos.yaml").write_text(_wrap([]))
    (v2_project / "archive.yaml").write_text(_wrap([]))
    (v2_project / "decisions.yaml").write_text("[]")

    migrate_yaml_to_sql(v2_project)

    assert not (v2_project / "todos.yaml").exists()
    assert not (v2_project / "archive.yaml").exists()
    assert not (v2_project / "decisions.yaml").exists()
    assert (v2_project / "todos.yaml.bak").exists()
    assert (v2_project / "archive.yaml.bak").exists()
    assert (v2_project / "decisions.yaml.bak").exists()


def test_meta_yaml_populates_project_meta(v2_project: Path) -> None:
    """meta.yaml is migrated into the project_meta table (regression: was
    silently skipped by the old hand-rolled wizard transform)."""
    (v2_project / "todos.yaml").write_text(_wrap([]))
    (v2_project / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "demo",
                "description": "demo project",
                "status": "active",
                "priority": "medium",
                "tags": [],
                "next_todo_id": 7,
                "dates": {"created": "2026-01-01", "last_updated": "2026-01-02"},
            }
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT data FROM project_meta WHERE name='demo'").fetchone()
    conn.close()
    assert row is not None
    payload = json.loads(row["data"])
    assert payload["next_todo_id"] == 7
    assert (v2_project / "meta.yaml.bak").exists()


def test_git_nested_mapping_populates_columns(v2_project: Path) -> None:
    """`git: {branch, commits}` (real Todo.to_dict shape) lands in
    git_branch + git_commits cols. Regression: old hand-rolled wizard
    expected flat git_branch/git_commits keys → silently dropped data."""
    (v2_project / "todos.yaml").write_text(
        _wrap(
            [
                {
                    "id": "1",
                    "title": "Wired to git",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                    "git": {
                        "branch": "feat/x",
                        "commits": ["abc123", "def456"],
                    },
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT git_branch, git_commits FROM todos WHERE id='1'"
    ).fetchone()
    conn.close()
    assert row["git_branch"] == "feat/x"
    assert json.loads(row["git_commits"]) == ["abc123", "def456"]


def test_jira_synced_comment_ids_preserved(v2_project: Path) -> None:
    """YAML field `jira_synced_comment_ids` lands in `jira_comment_ids`
    column. Regression: name mismatch silently dropped sync state."""
    (v2_project / "todos.yaml").write_text(
        _wrap(
            [
                {
                    "id": "1",
                    "title": "synced",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                    "jira_issue_key": "PROJ-9",
                    "jira_synced_comment_ids": ["c1", "c2"],
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT jira_comment_ids FROM todos WHERE id='1'").fetchone()
    conn.close()
    assert json.loads(row["jira_comment_ids"]) == ["c1", "c2"]


def test_todoist_description_synced_preserved(v2_project: Path) -> None:
    """YAML field `todoist_description_synced` lands in `todoist_desc_synced`
    column. Regression: name mismatch silently dropped sync state."""
    (v2_project / "todos.yaml").write_text(
        _wrap(
            [
                {
                    "id": "1",
                    "title": "synced",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                    "todoist_task_id": "t1",
                    "todoist_description_synced": "last synced body",
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT todoist_desc_synced FROM todos WHERE id='1'").fetchone()
    conn.close()
    assert row["todoist_desc_synced"] == "last synced body"


def test_trello_sync_state_dict_round_trips(v2_project: Path) -> None:
    """Nested trello_sync_state mapping serialises to JSON in the column
    (regression: pre-shim wizard hit `Error binding parameter — type 'dict'
    is not supported`)."""
    sync_state = {
        "last_sync": "2026-01-02T00:00:00",
        "synced_name": "Synced",
        "card_id": "C1",
        "list_id": "L1",
        "desc_hash": "deadbeef",
    }
    (v2_project / "todos.yaml").write_text(_wrap([]))
    (v2_project / "archive.yaml").write_text(
        _wrap(
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
    persisted = json.loads(row["trello_sync_state"])
    # Only assert fields we set; runtime fills missing fields with defaults.
    for key, value in sync_state.items():
        assert persisted[key] == value


def test_migrate_decisions(v2_project: Path) -> None:
    """Decisions.yaml is migrated to the decisions table."""
    (v2_project / "todos.yaml").write_text(_wrap([]))
    (v2_project / "decisions.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "timestamp": "2026-01-01T10:00:00",
                    "text": "Use SQL-only storage",
                    "todo_id": "42",
                }
            ]
        )
    )

    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM decisions").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["timestamp"] == "2026-01-01T10:00:00"
    assert rows[0]["text"] == "Use SQL-only storage"
    assert rows[0]["todo_id"] == "42"


def test_migrate_creates_db_when_absent(v2_project: Path) -> None:
    """Missing data.db is auto-created (regression: pre-fix wizard raised
    'data.db not found — run cpm-install first')."""
    (v2_project / "todos.yaml").write_text(
        _wrap(
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
    assert not (v2_project / "data.db").exists()

    migrate_yaml_to_sql(v2_project)

    assert (v2_project / "data.db").exists()
    conn = sqlite3.connect(v2_project / "data.db")
    n = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
    conn.close()
    assert n == 1


def test_migrate_idempotent(v2_project: Path) -> None:
    """Re-running the migration on an already-migrated project is a no-op."""
    (v2_project / "todos.yaml").write_text(
        _wrap(
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

    migrate_yaml_to_sql(v2_project)
    # Second run should not raise; data unchanged.
    migrate_yaml_to_sql(v2_project)

    conn = sqlite3.connect(v2_project / "data.db")
    n = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
    conn.close()
    assert n == 1
