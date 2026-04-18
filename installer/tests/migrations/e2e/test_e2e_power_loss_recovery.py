# installer/tests/migrations/e2e/test_e2e_power_loss_recovery.py
from __future__ import annotations

from pathlib import Path

import pytest

from installer.migrations.detect import read_schema_version
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.types import PendingProject, RecoveryPath


def test_bump_only_path_after_interrupted_run(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = PendingProject(
        name="cpm",
        path=home_with_projects / "projects" / "cpm",
        schema_version_path=home_with_projects / "projects" / "cpm" / ".schema-version",
        current_version=1,
    )
    # Simulate SIGKILL between FLATTENED and COMMITTED by running through flatten
    # and then crashing before commit writes schema_version.

    class CrashingRunner(FlatTodoMigration):
        def _commit(self) -> None:  # crash after flatten succeeded
            raise SystemExit("crash")

    backup_root = home_with_projects / ".claude" / "migrations"
    runner = CrashingRunner(
        project=project,
        run_ts="crash-run",
        backup_root=backup_root,
        integrations=[],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    with pytest.raises((SystemExit, RuntimeError)):
        runner.commit()

    # schema_version still 1 because commit crashed (restore reverts)
    # However, the backup restores the original todos.yaml, so we need to
    # manually flatten again to simulate a true power-loss scenario where
    # the process died AFTER flatten but BEFORE commit (no restore happened).
    # Re-flatten the todos manually to simulate the partially-written state:
    from installer.migrations.transform import flatten_todos_yaml

    flatten_todos_yaml(project.path / "todos.yaml")

    # Now schema_version is still 1 (commit never ran)
    assert read_schema_version(project.schema_version_path) == 1

    # Second run should detect already-flat and take BUMP_ONLY path
    runner2 = FlatTodoMigration(
        project=project,
        run_ts="recovery-run",
        backup_root=backup_root,
        integrations=[],
    )
    plan = runner2.plan()
    assert plan.recovery_path == RecoveryPath.BUMP_ONLY
    runner2.confirm()
    runner2.execute_local()
    runner2.commit()
    assert read_schema_version(project.schema_version_path) == 2
