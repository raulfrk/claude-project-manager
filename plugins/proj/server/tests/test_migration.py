"""Tests for server.lib.migration — YAML→SQLite round-trip, idempotency, recovery."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import server.lib.migration as _mig
from server.lib.db import db_path, get_connection
from server.lib.migration import _ensure_migrated, export_sqlite_to_yaml, migrate_yaml_to_sqlite
from server.lib.models import ProjConfig

# ── Fixtures ──────────────────────────────────────────────────────────────────

PROJECT = "testproj"

TODO_DICT_TEMPLATE = {
    "id": "1",
    "title": "Test todo",
    "status": "pending",
    "priority": "high",
    "created": "2026-01-01",
    "updated": "2026-01-01",
    "parent": None,
    "children": [],
    "next_child_id": 1,
    "tags": [],
    "git": {"branch": None, "commits": []},
    "blocks": [],
    "blocked_by": [],
    "notes": "",
    "has_requirements": False,
    "has_research": False,
    "todoist_task_id": None,
    "todoist_description_synced": "",
    "trello_card_id": None,
    "trello_checklist_id": None,
    "trello_checklist_item_id": None,
    "jira_issue_key": None,
    "jira_synced_comment_ids": [],
    "due_date": None,
    "trello_sync_state": None,
}

DECISION_TEMPLATE = {
    "timestamp": "2026-01-01T00:00:00",
    "decision": "Use SQLite",
    "context": "Performance",
    "todo_id": None,
    "tags": [],
}


@pytest.fixture
def tmp_cfg(tmp_path: Path) -> ProjConfig:
    return ProjConfig(tracking_dir=str(tmp_path / "tracking"))


@pytest.fixture(autouse=True)
def clear_cache() -> None:  # type: ignore[return]
    _mig._migrated_projects.clear()
    yield
    _mig._migrated_projects.clear()


def _make_todo(id: str, title: str) -> dict:
    t = dict(TODO_DICT_TEMPLATE)
    t["id"] = id
    t["title"] = title
    return t


def _make_decision(id_suffix: str) -> dict:
    d = dict(DECISION_TEMPLATE)
    d["timestamp"] = f"2026-01-0{id_suffix}T00:00:00"
    return d


def _write_yaml_files(
    tdir: Path,
    todos: list[dict] | None = None,
    archived: list[dict] | None = None,
    decisions: list[dict] | None = None,
    meta: dict | None = None,
) -> None:
    tdir.mkdir(parents=True, exist_ok=True)
    if todos is not None:
        (tdir / "todos.yaml").write_text(yaml.dump({"todos": todos}))
    if archived is not None:
        (tdir / "archive.yaml").write_text(yaml.dump({"todos": archived}))
    if meta is not None:
        (tdir / "meta.yaml").write_text(yaml.dump(meta))
    if decisions is not None:
        (tdir / "decisions.yaml").write_text(yaml.dump(decisions))


def _minimal_meta(name: str) -> dict:
    return {
        "name": name,
        "description": "Test project",
        "repos": [],
        "dates": {"created": "2026-01-01", "last_updated": "2026-01-01"},
        "active": True,
        "agent_instructions": "",
        "permissions": [],
        "todoist_project_id": None,
        "trello_board_id": None,
        "trello_list_id": None,
        "trello_card_id": None,
        "trello_project_label_id": None,
        "trello_task_label_id": None,
        "jira_project_key": None,
        "jira_epic_key": None,
    }


def _count(cfg: ProjConfig, project: str, table: str) -> int:
    path = db_path(cfg, project)
    conn = get_connection(path)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) as n FROM {table} WHERE project=?",
            (project,),
        ).fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_migrate_basic(tmp_cfg: ProjConfig) -> None:
    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "First todo"), _make_todo("2", "Second todo")]
    archived = [_make_todo("3", "Archived todo")]
    decisions = [_make_decision("1"), _make_decision("2")]
    _write_yaml_files(
        tdir, todos=todos, archived=archived, decisions=decisions, meta=_minimal_meta(PROJECT)
    )

    result = migrate_yaml_to_sqlite(tmp_cfg, PROJECT)

    db = db_path(tmp_cfg, PROJECT)
    assert db.exists()
    assert _count(tmp_cfg, PROJECT, "todos") == 2
    assert _count(tmp_cfg, PROJECT, "archive_todos") == 1
    assert result["migrated_decisions"] == 2
    assert (tdir / "todos.yaml.bak").exists()


def test_migrate_idempotent(tmp_cfg: ProjConfig) -> None:
    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "First todo"), _make_todo("2", "Second todo")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    migrate_yaml_to_sqlite(tmp_cfg, PROJECT)
    result2 = migrate_yaml_to_sqlite(tmp_cfg, PROJECT)

    assert result2["status"] == "already_migrated"
    assert _count(tmp_cfg, PROJECT, "todos") == 2


def test_migrate_preserves_title(tmp_cfg: ProjConfig) -> None:
    from server.lib import sql_todos

    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "My special title")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    migrate_yaml_to_sqlite(tmp_cfg, PROJECT)

    loaded = sql_todos.load_todos(tmp_cfg, PROJECT)
    assert any(t.title == "My special title" for t in loaded)


def test_export_round_trip(tmp_cfg: ProjConfig) -> None:
    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Round-trip todo")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    migrate_yaml_to_sqlite(tmp_cfg, PROJECT)

    # todos.yaml renamed to .bak after migration
    assert not (tdir / "todos.yaml").exists()

    export_sqlite_to_yaml(tmp_cfg, PROJECT)

    todos_yaml = tdir / "todos.yaml"
    assert todos_yaml.exists()
    data = yaml.safe_load(todos_yaml.read_text())
    assert isinstance(data, dict)
    assert "todos" in data
    assert isinstance(data["todos"], list)
    assert len(data["todos"]) == 1
    assert data["todos"][0]["title"] == "Round-trip todo"


def test_ensure_migrated_creates_db(tmp_cfg: ProjConfig) -> None:
    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    tdir.mkdir(parents=True, exist_ok=True)

    db = db_path(tmp_cfg, PROJECT)
    assert not db.exists()

    _ensure_migrated(tmp_cfg, PROJECT)

    assert db.exists()


def test_ensure_migrated_noop_when_exists(tmp_cfg: ProjConfig) -> None:
    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Existing todo")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    migrate_yaml_to_sqlite(tmp_cfg, PROJECT)
    _mig._migrated_projects.clear()

    # Should not raise, DB already has rows → already_migrated path
    _ensure_migrated(tmp_cfg, PROJECT)

    assert _count(tmp_cfg, PROJECT, "todos") == 1


def test_partial_migration_recovery(tmp_cfg: ProjConfig) -> None:
    tdir = Path(tmp_cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Recovery todo"), _make_todo("2", "Another todo")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    # Simulate crashed migration: empty data.db exists
    db = db_path(tmp_cfg, PROJECT)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"")

    result = migrate_yaml_to_sqlite(tmp_cfg, PROJECT)

    assert db.exists()
    assert _count(tmp_cfg, PROJECT, "todos") == 2
    assert result["migrated_todos"] == 2
