"""Tests for storage.py SQL-only behaviour (schema_version=3 guard)."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import sql_todos, storage
from server.lib.models import Decision, ProjConfig, Todo
from server.lib.schema_version import LegacyProjectError
from tests.conftest import make_v3_project


@pytest.fixture()
def cfg_v3(tmp_path: Path, cfg: ProjConfig) -> tuple[ProjConfig, str]:
    """Create a v3 project fixture."""
    return make_v3_project(tmp_path, cfg, name="demo")


def test_load_todos_reads_from_sql(cfg_v3: tuple[ProjConfig, str]) -> None:
    cfg, name = cfg_v3
    # Seed directly via sql_todos
    t = Todo(
        id="1",
        title="SQL Todo",
        status="pending",
        priority="medium",
        created="2026-01-01",
        updated="2026-01-01",
    )
    sql_todos.save_todos(cfg, name, [t])

    loaded = storage.load_todos(cfg, name)
    assert len(loaded) == 1
    assert loaded[0].id == "1"
    assert loaded[0].title == "SQL Todo"


def test_save_todos_writes_sql_only_no_yaml_file(cfg_v3: tuple[ProjConfig, str]) -> None:
    cfg, name = cfg_v3
    t = Todo(
        id="1",
        title="No YAML",
        status="pending",
        priority="medium",
        created="2026-01-01",
        updated="2026-01-01",
    )
    storage.save_todos(cfg, name, [t])

    # No todos.yaml should be written
    todos_yaml = Path(cfg.tracking_dir) / name / "todos.yaml"
    assert not todos_yaml.exists()

    # Data should be readable via SQL
    loaded = storage.load_todos(cfg, name)
    assert len(loaded) == 1


def test_load_decisions_reads_from_sql(cfg_v3: tuple[ProjConfig, str]) -> None:
    from server.lib.sql_decisions import append_decision

    cfg, name = cfg_v3
    d = Decision(timestamp="2026-01-01T00:00:00", text="Use SQL-only storage")
    append_decision(cfg, name, d)

    loaded = storage.load_decisions(cfg, name)
    assert len(loaded) == 1
    assert loaded[0]["decision"] == "Use SQL-only storage"


def test_append_decision_adds_row(cfg_v3: tuple[ProjConfig, str]) -> None:
    cfg, name = cfg_v3
    entry = storage.build_decision_entry(
        decision="Append test",
        context="",
        todo_id="42",
    )
    storage.append_decision(cfg, name, entry)

    loaded = storage.load_decisions(cfg, name)
    assert len(loaded) == 1
    assert loaded[0]["decision"] == "Append test"


def test_storage_raises_legacy_project_error_on_v2(tmp_path: Path, cfg: ProjConfig) -> None:
    """load_todos must raise LegacyProjectError for schema_version=2 projects."""
    from server.lib.db import ensure_db

    proj_dir = Path(cfg.tracking_dir) / "legacy"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / ".schema-version").write_text("2\n")
    ensure_db(cfg, "legacy")

    with pytest.raises(LegacyProjectError, match="cpm-install --migrate"):
        storage.load_todos(cfg, "legacy")
