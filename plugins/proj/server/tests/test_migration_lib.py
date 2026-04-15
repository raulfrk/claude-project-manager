"""Tests for server.lib.migration — YAML→SQLite migration, idempotency, bak renaming."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import server.lib.migration as _mig
from server.lib.db import db_path, get_connection
from server.lib.migration import migrate_yaml_to_sqlite
from server.lib.models import ProjConfig

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT = "migtest"

TODO_TEMPLATE: dict = {
    "id": "1",
    "title": "Test todo",
    "status": "pending",
    "priority": "medium",
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

DECISION_TEMPLATE: dict = {
    "timestamp": "2026-01-01T00:00:00",
    "decision": "Use SQLite",
    "context": "Performance",
    "todo_id": None,
    "tags": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_todo(id: str, title: str) -> dict:
    t = dict(TODO_TEMPLATE)
    t["id"] = id
    t["title"] = title
    return t


def _make_decision(suffix: str = "1") -> dict:
    d = dict(DECISION_TEMPLATE)
    d["timestamp"] = f"2026-01-0{suffix}T00:00:00"
    return d


def _minimal_meta(name: str) -> dict:
    return {
        "name": name,
        "description": "Test",
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


def _count(cfg: ProjConfig, project: str, table: str) -> int:
    path = db_path(cfg, project)
    conn = get_connection(path)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) as n FROM {table} WHERE project=?", (project,)
        ).fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path: Path) -> ProjConfig:
    return ProjConfig(tracking_dir=str(tmp_path / "tracking"))


@pytest.fixture(autouse=True)
def clear_module_cache() -> None:  # type: ignore[return]
    """Clear module-level _migrated_projects cache between tests."""
    _mig._migrated_projects.clear()
    yield
    _mig._migrated_projects.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migrate_todos_archive_decisions(cfg: ProjConfig) -> None:
    """Basic migration with todos, archive, decisions → correct counts returned."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Alpha"), _make_todo("2", "Beta")]
    archived = [_make_todo("3", "Gamma")]
    decisions = [_make_decision("1"), _make_decision("2")]
    _write_yaml_files(
        tdir,
        todos=todos,
        archived=archived,
        decisions=decisions,
        meta=_minimal_meta(PROJECT),
    )

    result = migrate_yaml_to_sqlite(cfg, PROJECT)

    assert result.get("status") != "already_migrated"
    assert result["migrated_todos"] == 2
    assert result["migrated_archived"] == 1
    assert result["migrated_decisions"] == 2
    assert _count(cfg, PROJECT, "todos") == 2
    assert _count(cfg, PROJECT, "archive_todos") == 1


def test_migrate_idempotent(cfg: ProjConfig) -> None:
    """Second run returns already_migrated status without overwriting data."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Only todo")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    migrate_yaml_to_sqlite(cfg, PROJECT)
    result2 = migrate_yaml_to_sqlite(cfg, PROJECT)

    assert result2["status"] == "already_migrated"
    assert _count(cfg, PROJECT, "todos") == 1


def test_yaml_files_renamed_to_bak(cfg: ProjConfig) -> None:
    """After successful migration, YAML files are renamed to .bak."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Todo A")]
    decisions = [_make_decision("1")]
    _write_yaml_files(
        tdir,
        todos=todos,
        archived=[],
        decisions=decisions,
        meta=_minimal_meta(PROJECT),
    )

    migrate_yaml_to_sqlite(cfg, PROJECT)

    assert not (tdir / "todos.yaml").exists()
    assert (tdir / "todos.yaml.bak").exists()
    assert (tdir / "decisions.yaml.bak").exists()
    assert (tdir / "meta.yaml.bak").exists()


def test_migrate_empty_yaml_files(cfg: ProjConfig) -> None:
    """Migration with empty YAML files returns 0 counts."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    _write_yaml_files(
        tdir,
        todos=[],
        archived=[],
        decisions=[],
        meta=_minimal_meta(PROJECT),
    )

    result = migrate_yaml_to_sqlite(cfg, PROJECT)

    assert result["migrated_todos"] == 0
    assert result["migrated_archived"] == 0
    assert result["migrated_decisions"] == 0


def test_module_cache_prevents_duplicate_migration(cfg: ProjConfig) -> None:
    """_migrated_projects cache prevents re-checking DB on subsequent calls."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Cached")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    # First migration
    migrate_yaml_to_sqlite(cfg, PROJECT)

    # Manually populate the module-level set so _ensure_migrated short-circuits
    cache_key = (cfg.tracking_dir, PROJECT)
    assert cache_key not in _mig._migrated_projects  # not set by migrate_yaml_to_sqlite

    # _ensure_migrated populates the cache
    _mig._ensure_migrated(cfg, PROJECT)
    assert cache_key in _mig._migrated_projects

    # Second call should be a no-op (cache hit, no DB check)
    _mig._ensure_migrated(cfg, PROJECT)
    assert cache_key in _mig._migrated_projects


def test_module_cache_cleared_between_tests(cfg: ProjConfig) -> None:
    """autouse clear_module_cache fixture ensures cache is empty at test start."""
    assert len(_mig._migrated_projects) == 0


def test_migrate_no_yaml_files(cfg: ProjConfig) -> None:
    """Migration with no YAML files at all returns 0 counts (missing files → empty)."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    tdir.mkdir(parents=True, exist_ok=True)
    # No YAML files written

    result = migrate_yaml_to_sqlite(cfg, PROJECT)

    assert result["migrated_todos"] == 0
    assert result["migrated_archived"] == 0
    assert result["migrated_decisions"] == 0


def test_partial_crash_recovery(cfg: ProjConfig) -> None:
    """Empty data.db from crashed migration is deleted and re-migrated."""
    tdir = Path(cfg.tracking_dir) / PROJECT
    todos = [_make_todo("1", "Recovery")]
    _write_yaml_files(tdir, todos=todos, archived=[], decisions=[], meta=_minimal_meta(PROJECT))

    # Simulate crashed migration: empty data.db
    db = db_path(cfg, PROJECT)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"")

    result = migrate_yaml_to_sqlite(cfg, PROJECT)

    assert db.exists()
    assert result["migrated_todos"] == 1
    assert _count(cfg, PROJECT, "todos") == 1
