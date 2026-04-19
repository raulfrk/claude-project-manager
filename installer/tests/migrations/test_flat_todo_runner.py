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
    (root / ".schema-version").write_text("1\n")
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
        schema_version_path=root / ".schema-version",
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
    assert read_schema_version(project.schema_version_path) == 2
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
    assert read_schema_version(project.schema_version_path) == 1


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
    assert read_schema_version(project.schema_version_path) == 2


from installer.migrations.integrations.base import ResyncResult  # noqa: E402


class FakeIntegration:
    name = "fake"
    called: list[str] = []

    def enabled_for(self, project) -> bool:
        return True

    def plan(self, project, migrated):
        return []

    def execute(self, project, actions):
        FakeIntegration.called.append(project.name)
        return ResyncResult()


def test_runner_invokes_enabled_integrations(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    FakeIntegration.called = []
    runner = FlatTodoMigration(
        project=project,
        run_ts="ts",
        backup_root=backup_root,
        integrations=[FakeIntegration()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert FakeIntegration.called == ["demo"]
    assert runner.state == MigrationState.COMMITTED


def test_plan_populates_todo_ref_parent_before_flatten(tmp_path: Path) -> None:
    """Integration plan() receives TodoRefs with parent set from pre-flatten yaml.

    Regression guard for todo 668: if `_plan()` ever moved to after `_flatten()`,
    TodoRef.parent would be None for every child (flatten strips parent field),
    and TrelloResync / JiraResync would find zero parent-child relationships to
    promote. This test captures the exact argument list handed to integ.plan()
    to prove parent references survive.
    """
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"

    captured: dict[str, list] = {}

    class CaptureIntegration:
        name = "capture"

        def enabled_for(self, project):
            return True

        def plan(self, project, migrated):
            captured["migrated"] = list(migrated)
            return []

        def execute(self, project, actions):
            from installer.migrations.integrations.base import ResyncResult

            return ResyncResult()

    runner = FlatTodoMigration(
        project=project,
        run_ts="ts",
        backup_root=backup_root,
        integrations=[CaptureIntegration()],
    )
    runner.plan()

    refs = captured["migrated"]
    parents = [r for r in refs if r.parent is None]
    children = [r for r in refs if r.parent is not None]
    assert len(parents) == 1 and parents[0].id == "1"
    assert len(children) == 1
    assert children[0].id == "1.1"
    assert children[0].parent == "1"


def test_resync_failure_does_not_revert_local(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"

    class FailingIntegration:
        name = "fail"

        def enabled_for(self, project):
            return True

        def plan(self, project, migrated):
            from installer.migrations.integrations.base import Action

            return [Action(kind="noop", target_id="x", payload={})]

        def execute(self, project, actions):
            from installer.migrations.integrations.base import (
                FailedAction,
                ResyncResult,
            )

            return ResyncResult(failed=[FailedAction(actions[0], "E", "m", True)])

    runner = FlatTodoMigration(
        project=project,
        run_ts="ts",
        backup_root=backup_root,
        integrations=[FailingIntegration()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert (
        runner.state == MigrationState.COMMITTED
    )  # local committed despite failed resync
    assert runner.resync_failures  # collected for summary
