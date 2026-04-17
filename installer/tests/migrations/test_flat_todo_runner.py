# installer/tests/migrations/test_flat_todo_runner.py
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.types import MigrationState, PendingProject, RecoveryPath


def _setup_project(root: Path) -> PendingProject:
    root.mkdir(parents=True)
    (root / "proj.yaml").write_text(yaml.safe_dump({"name": "demo"}))
    (root / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "1",
                    "title": "p",
                    "parent": None,
                    "children": ["1.1"],
                    "tags": [],
                },
                {"id": "1.1", "title": "c", "parent": "1", "children": [], "tags": []},
            ]
        ),
    )
    (root / "archive.yaml").write_text("[]\n")
    conn = sqlite3.connect(root / "data.db")
    conn.executescript(
        """
        CREATE TABLE todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);
        INSERT INTO todos VALUES ('1','p',NULL,'["1.1"]','[]',2);
        INSERT INTO todos VALUES ('1.1','c','1','[]','[]',1);
        CREATE TABLE archive_todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);
        """,
    )
    conn.commit()
    conn.close()
    return PendingProject(
        name="demo",
        path=root,
        proj_yaml_path=root / "proj.yaml",
        current_version=1,
    )


def test_happy_path_commits(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    runner = FlatTodoMigration(project=project, run_ts="ts1", backup_root=backup_root)
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert runner.state == MigrationState.COMMITTED
    assert read_schema_version(project.proj_yaml_path) == 2
    todos = yaml.safe_load((project.path / "todos.yaml").read_text())
    assert "group:1" in todos[1]["tags"]


def test_rollback_on_flatten_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    runner = FlatTodoMigration(project=project, run_ts="ts", backup_root=backup_root)
    runner.plan()
    runner.confirm()

    # Inject failure in flatten step
    from installer.migrations import flat_todo as mod

    monkeypatch.setattr(
        mod, "flatten_todos_sql", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        runner.execute_local()

    # YAML was flattened before SQL (by design) — restore reverts it
    assert runner.state == MigrationState.FAILED
    todos = yaml.safe_load((project.path / "todos.yaml").read_text())
    assert todos[0]["children"] == ["1.1"]  # restored
    assert read_schema_version(project.proj_yaml_path) == 1


def test_bump_only_recovery_for_already_flat(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    # Pre-flatten manually
    (project.path / "todos.yaml").write_text(
        yaml.safe_dump(
            [
                {"id": "1", "title": "p", "tags": []},
                {"id": "1.1", "title": "c", "tags": ["group:1"]},
            ]
        ),
    )
    conn = sqlite3.connect(project.path / "data.db")
    conn.executescript(
        "DROP TABLE todos; CREATE TABLE todos (id TEXT PRIMARY KEY, title TEXT, tags TEXT);"
        "INSERT INTO todos VALUES ('1','p','[]');"
        "INSERT INTO todos VALUES ('1.1','c','[\"group:1\"]');",
    )
    conn.commit()
    conn.close()

    backup_root = tmp_path / "backups"
    runner = FlatTodoMigration(project=project, run_ts="ts", backup_root=backup_root)
    runner.plan()
    assert runner.plan_result.recovery_path == RecoveryPath.BUMP_ONLY
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert read_schema_version(project.proj_yaml_path) == 2
