# installer/tests/migrations/e2e/test_e2e_rollback.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.types import PendingProject


def test_rollback_isolated_to_failing_project(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force SQL flatten to raise on "side" but not on the other projects
    from installer.migrations import transform as tr

    real = tr.flatten_todos_sql

    def selective(db_path: Path) -> None:
        if "side" in str(db_path):
            raise RuntimeError("simulated ALTER failure")
        real(db_path)

    monkeypatch.setattr(tr, "flatten_todos_sql", selective)
    monkeypatch.setattr(
        "installer.migrations.flat_todo.flatten_todos_sql",
        selective,
    )

    projects = [
        PendingProject(
            name=name,
            path=home_with_projects / "projects" / name,
            schema_version_path=home_with_projects
            / "projects"
            / name
            / ".schema-version",
            current_version=1,
        )
        for name in ("cpm", "side", "legacy")
    ]

    backup_root = home_with_projects / ".claude" / "migrations"
    results: list[tuple[str, str]] = []
    for p in projects:
        runner = FlatTodoMigration(
            project=p,
            run_ts="e2e-rb",
            backup_root=backup_root,
            integrations=[],  # local-only — no SaaS mocks needed
        )
        runner.plan()
        runner.confirm()
        try:
            runner.execute_local()
            runner.commit()
            results.append((p.name, "ok"))
        except Exception:
            results.append((p.name, "failed"))

    assert results == [("cpm", "ok"), ("side", "failed"), ("legacy", "ok")]

    assert read_schema_version(projects[0].schema_version_path) == 2
    assert read_schema_version(projects[1].schema_version_path) == 1  # reverted
    assert read_schema_version(projects[2].schema_version_path) == 2

    side_todos = yaml.safe_load(
        (projects[1].path / "todos.yaml").read_text(),
    )
    assert side_todos[0].get("children") == ["1.1"]  # restored nested form
