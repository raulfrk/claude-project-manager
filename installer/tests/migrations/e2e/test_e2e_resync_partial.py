# installer/tests/migrations/e2e/test_e2e_resync_partial.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.detect import read_schema_version
from installer.migrations.entry import MIGRATION_ROOT
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.types import PendingProject


@respx.mock
def test_trello_500_leaves_local_committed(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import installer.migrations.integrations.trello as t

    monkeypatch.setattr(t, "_update_local_trello_card_id", lambda *a, **k: None)

    respx.post("https://api.trello.com/1/cards").mock(return_value=Response(500))

    project = PendingProject(
        name="cpm",
        path=home_with_projects / "projects" / "cpm",
        proj_yaml_path=home_with_projects / "projects" / "cpm" / "proj.yaml",
        current_version=1,
    )
    runner = FlatTodoMigration(
        project=project,
        run_ts="e2e-partial",
        backup_root=MIGRATION_ROOT / "e2e-partial",
        integrations=[TrelloResync()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()

    assert read_schema_version(project.proj_yaml_path) == 2
    todos = yaml.safe_load((project.path / "todos.yaml").read_text())
    assert "group:1" in [tag for t in todos for tag in t.get("tags", [])]
    assert len(runner.resync_failures) >= 1
