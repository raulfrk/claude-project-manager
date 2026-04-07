"""Tests for proj_migrate_ids MCP tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    Todo,
)
from server.tools.migrate import _cleanup_config, _migrate_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(c)
    return c


def _setup_project_with_todos(
    cfg: ProjConfig,
    name: str,
    todos: list[Todo],
) -> None:
    """Create a project with the given todos already saved."""
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True)
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=str(proj_dir))],
        dates=ProjectDates(created=today, last_updated=today),
        next_todo_id=len([t for t in todos if t.parent is None]) + 1,
    )
    storage.save_meta(cfg, meta)
    storage.save_todos(cfg, name, todos)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)


def _make_todo(
    tid: str,
    title: str,
    parent: str | None = None,
    children: list[str] | None = None,
    created: str = "2026-01-01",
) -> Todo:
    return Todo(
        id=tid,
        title=title,
        created=created,
        updated=created,
        parent=parent,
        children=children or [],
    )


class TestMigrateProjectDryRun:
    def test_dry_run_shows_mapping(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First task"),
            _make_todo("T002", "Second task"),
        ]
        _setup_project_with_todos(cfg, "alpha", todos)

        result = _migrate_project(cfg, "alpha", dry_run=True)

        assert result["project"] == "alpha"
        assert result["reason"] == "dry_run"
        assert result["id_count"] == 2
        assert result["mapping"]["T001"] == "1"
        assert result["mapping"]["T002"] == "2"

    def test_dry_run_does_not_modify_todos(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First task"),
        ]
        _setup_project_with_todos(cfg, "alpha", todos)

        _migrate_project(cfg, "alpha", dry_run=True)

        saved = storage.load_todos(cfg, "alpha")
        assert saved[0].id == "T001"

    def test_dry_run_shows_child_mapping(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Parent", children=["T002"]),
            _make_todo("T002", "Child", parent="T001"),
        ]
        _setup_project_with_todos(cfg, "alpha", todos)

        result = _migrate_project(cfg, "alpha", dry_run=True)

        assert result["mapping"]["T001"] == "1"
        assert result["mapping"]["T002"] == "1.1"

    def test_dry_run_no_backup_created(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "alpha", todos)

        _migrate_project(cfg, "alpha", dry_run=True)

        # No .bak-* files should exist in the project dir
        proj_dir = Path(cfg.tracking_dir) / "alpha"
        bak_files = list(proj_dir.glob("*.bak-*"))
        assert not bak_files


class TestMigrateProjectActual:
    def test_migrates_root_todos(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
            _make_todo("T003", "Third"),
        ]
        _setup_project_with_todos(cfg, "beta", todos)

        result = _migrate_project(cfg, "beta", dry_run=False)

        assert result["project"] == "beta"
        assert result["migrated"] is True
        assert result["id_count"] == 3
        saved = storage.load_todos(cfg, "beta")
        ids = [t.id for t in saved]
        assert "1" in ids
        assert "2" in ids
        assert "3" in ids
        assert not any(i.startswith("T") for i in ids)

    def test_migrates_child_todos(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Parent", children=["T002", "T003"]),
            _make_todo("T002", "Child A", parent="T001"),
            _make_todo("T003", "Child B", parent="T001"),
        ]
        _setup_project_with_todos(cfg, "beta", todos)

        _migrate_project(cfg, "beta", dry_run=False)

        saved = storage.load_todos(cfg, "beta")
        by_title = {t.title: t for t in saved}
        assert by_title["Parent"].id == "1"
        assert by_title["Child A"].id == "1.1"
        assert by_title["Child B"].id == "1.2"
        assert by_title["Child A"].parent == "1"
        assert by_title["Child B"].parent == "1"

    def test_migrates_parent_children_references(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Parent", children=["T002"]),
            _make_todo("T002", "Child", parent="T001"),
        ]
        _setup_project_with_todos(cfg, "beta", todos)

        _migrate_project(cfg, "beta", dry_run=False)

        saved = storage.load_todos(cfg, "beta")
        parent = next(t for t in saved if t.title == "Parent")
        assert "1.1" in parent.children

    def test_migrates_blocks_and_blocked_by(self, cfg: ProjConfig) -> None:
        t1 = _make_todo("T001", "Blocker")
        t1.blocks = ["T002"]
        t2 = _make_todo("T002", "Blocked")
        t2.blocked_by = ["T001"]
        todos = [t1, t2]
        _setup_project_with_todos(cfg, "beta", todos)

        _migrate_project(cfg, "beta", dry_run=False)

        saved = storage.load_todos(cfg, "beta")
        by_title = {t.title: t for t in saved}
        assert "2" in by_title["Blocker"].blocks
        assert "1" in by_title["Blocked"].blocked_by

    def test_backup_created(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "gamma", todos)

        _migrate_project(cfg, "gamma", dry_run=False)

        proj_dir = Path(cfg.tracking_dir) / "gamma"
        bak_files = list(proj_dir.glob("todos.yaml.bak-*"))
        assert len(bak_files) == 1

    def test_backup_contains_original_data(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "gamma", todos)
        original_text = storage.todos_path(cfg, "gamma").read_text()

        _migrate_project(cfg, "gamma", dry_run=False)

        proj_dir = Path(cfg.tracking_dir) / "gamma"
        bak_files = list(proj_dir.glob("todos.yaml.bak-*"))
        assert len(bak_files) == 1
        assert bak_files[0].read_text() == original_text

    def test_updates_meta_next_todo_id(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "delta", todos)

        _migrate_project(cfg, "delta", dry_run=False)

        meta = storage.load_meta(cfg, "delta")
        assert meta.next_todo_id == 3  # 2 root todos → next = 3

    def test_updates_next_child_id_on_parent(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Parent", children=["T002", "T003"]),
            _make_todo("T002", "Child A", parent="T001"),
            _make_todo("T003", "Child B", parent="T001"),
        ]
        _setup_project_with_todos(cfg, "delta", todos)

        _migrate_project(cfg, "delta", dry_run=False)

        saved = storage.load_todos(cfg, "delta")
        parent = next(t for t in saved if t.title == "Parent")
        assert parent.next_child_id == 3  # 2 children → next = 3

    def test_renames_content_dirs(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "epsilon", todos)
        # Create a content dir for T001
        content_dir = storage.todo_content_dir(cfg, "epsilon", "T001")
        content_dir.mkdir(parents=True)
        (content_dir / "requirements.md").write_text("# Requirements\n")

        _migrate_project(cfg, "epsilon", dry_run=False)

        old_dir = storage.todo_content_dir(cfg, "epsilon", "T001")
        new_dir = storage.todo_content_dir(cfg, "epsilon", "1")
        assert not old_dir.exists()
        assert new_dir.exists()
        assert (new_dir / "requirements.md").exists()

    def test_result_dict_includes_counts(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "zeta", todos)

        result = _migrate_project(cfg, "zeta", dry_run=False)

        assert result["migrated"] is True
        assert result["id_count"] == 1
        assert "archive_count" in result
        assert "decisions_count" in result


class TestMigrateProjectEdgeCases:
    def test_no_todos_returns_skip_message(self, cfg: ProjConfig) -> None:
        _setup_project_with_todos(cfg, "empty", [])

        result = _migrate_project(cfg, "empty", dry_run=False)

        assert result["migrated"] is False
        assert result["reason"] == "no todos"

    def test_already_migrated_skipped(self, cfg: ProjConfig) -> None:
        # Todos with numeric IDs (already migrated)
        todos = [_make_todo("1", "First"), _make_todo("2", "Second")]
        _setup_project_with_todos(cfg, "migrated", todos)

        result = _migrate_project(cfg, "migrated", dry_run=False)

        assert result["migrated"] is False
        assert result["reason"] == "already migrated"

    def test_deterministic_ordering_by_created(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T002", "Earlier", created="2026-01-01"),
            _make_todo("T001", "Later", created="2026-01-02"),
        ]
        _setup_project_with_todos(cfg, "order_test", todos)

        _migrate_project(cfg, "order_test", dry_run=False)

        saved = storage.load_todos(cfg, "order_test")
        by_title = {t.title: t for t in saved}
        # Earlier creation date gets lower numeric ID
        assert by_title["Earlier"].id == "1"
        assert by_title["Later"].id == "2"

    def test_tie_broken_by_old_id(self, cfg: ProjConfig) -> None:
        # Same creation date — tie-break by old ID string
        todos = [
            _make_todo("T002", "Beta", created="2026-01-01"),
            _make_todo("T001", "Alpha", created="2026-01-01"),
        ]
        _setup_project_with_todos(cfg, "tie_test", todos)

        _migrate_project(cfg, "tie_test", dry_run=False)

        saved = storage.load_todos(cfg, "tie_test")
        by_title = {t.title: t for t in saved}
        # T001 < T002 lexicographically, so Alpha gets ID 1
        assert by_title["Alpha"].id == "1"
        assert by_title["Beta"].id == "2"


class TestMigrateDeepNesting:
    def test_migrates_three_level_hierarchy(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Root", children=["T002"]),
            _make_todo("T002", "Child", parent="T001", children=["T003"]),
            _make_todo("T003", "Grandchild", parent="T002"),
        ]
        _setup_project_with_todos(cfg, "deep", todos)

        _migrate_project(cfg, "deep", dry_run=False)

        saved = storage.load_todos(cfg, "deep")
        by_title = {t.title: t for t in saved}
        assert by_title["Root"].id == "1"
        assert by_title["Child"].id == "1.1"
        assert by_title["Grandchild"].id == "1.1.1"

    def test_grandchild_parent_reference_updated(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Root", children=["T002"]),
            _make_todo("T002", "Child", parent="T001", children=["T003"]),
            _make_todo("T003", "Grandchild", parent="T002"),
        ]
        _setup_project_with_todos(cfg, "deep_refs", todos)

        _migrate_project(cfg, "deep_refs", dry_run=False)

        saved = storage.load_todos(cfg, "deep_refs")
        by_title = {t.title: t for t in saved}
        assert by_title["Grandchild"].parent == "1.1"
        assert "1.1.1" in by_title["Child"].children

    def test_dry_run_shows_three_level_mapping(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Root", children=["T002"]),
            _make_todo("T002", "Child", parent="T001", children=["T003"]),
            _make_todo("T003", "Grandchild", parent="T002"),
        ]
        _setup_project_with_todos(cfg, "deep_dry", todos)

        result = _migrate_project(cfg, "deep_dry", dry_run=True)

        assert result["mapping"]["T001"] == "1"
        assert result["mapping"]["T002"] == "1.1"
        assert result["mapping"]["T003"] == "1.1.1"

    def test_next_child_id_set_correctly_at_all_levels(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Root", children=["T002", "T003"]),
            _make_todo("T002", "Child A", parent="T001", children=["T004"]),
            _make_todo("T003", "Child B", parent="T001"),
            _make_todo("T004", "Grandchild", parent="T002"),
        ]
        _setup_project_with_todos(cfg, "deep_counter", todos)

        _migrate_project(cfg, "deep_counter", dry_run=False)

        saved = storage.load_todos(cfg, "deep_counter")
        by_title = {t.title: t for t in saved}
        # Root has 2 children → next_child_id = 3
        assert by_title["Root"].next_child_id == 3
        # Child A has 1 child → next_child_id = 2
        assert by_title["Child A"].next_child_id == 2
        # Child B has 0 children → next_child_id = 1
        assert by_title["Child B"].next_child_id == 1
        # Grandchild has 0 children → next_child_id = 1
        assert by_title["Grandchild"].next_child_id == 1


class TestMigrateBlockingRelationships:
    def test_dry_run_shows_blocking_ids_in_mapping(self, cfg: ProjConfig) -> None:
        t1 = _make_todo("T001", "Blocker")
        t1.blocks = ["T002"]
        t2 = _make_todo("T002", "Blocked")
        t2.blocked_by = ["T001"]
        _setup_project_with_todos(cfg, "block_dry", [t1, t2])

        result = _migrate_project(cfg, "block_dry", dry_run=True)

        # Both IDs appear in the mapping
        assert result["mapping"]["T001"] == "1"
        assert result["mapping"]["T002"] == "2"

    def test_child_blocking_relationship_remapped(self, cfg: ProjConfig) -> None:
        # Child T002 is blocked by sibling T003 under same parent T001
        parent = _make_todo("T001", "Parent", children=["T002", "T003"])
        t2 = _make_todo("T002", "Child A", parent="T001")
        t2.blocked_by = ["T003"]
        t3 = _make_todo("T003", "Child B", parent="T001")
        t3.blocks = ["T002"]
        _setup_project_with_todos(cfg, "child_block", [parent, t2, t3])

        _migrate_project(cfg, "child_block", dry_run=False)

        saved = storage.load_todos(cfg, "child_block")
        by_title = {t.title: t for t in saved}
        assert "1.2" in by_title["Child A"].blocked_by
        assert "1.1" in by_title["Child B"].blocks

    def test_blocks_across_root_todos_remapped(self, cfg: ProjConfig) -> None:
        t1 = _make_todo("T001", "First", created="2026-01-01")
        t1.blocks = ["T003"]
        t2 = _make_todo("T002", "Second", created="2026-01-02")
        t3 = _make_todo("T003", "Third", created="2026-01-03")
        t3.blocked_by = ["T001"]
        _setup_project_with_todos(cfg, "root_block", [t1, t2, t3])

        _migrate_project(cfg, "root_block", dry_run=False)

        saved = storage.load_todos(cfg, "root_block")
        by_title = {t.title: t for t in saved}
        assert by_title["First"].id == "1"
        assert by_title["Third"].id == "3"
        assert "3" in by_title["First"].blocks
        assert "1" in by_title["Third"].blocked_by


class TestMigrateRollbackAndInterrupt:
    def test_backup_write_failure_raises_before_any_changes(self, cfg: ProjConfig) -> None:
        """If shutil.copy2 fails during backup, the migration aborts and no todos are modified."""
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "fail_backup", todos)
        original_text = storage.todos_path(cfg, "fail_backup").read_text()

        with (
            patch(
                "server.tools.migrate.shutil.copy2",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError, match="disk full"),
        ):
            _migrate_project(cfg, "fail_backup", dry_run=False)

        # todos.yaml must be unchanged
        assert storage.todos_path(cfg, "fail_backup").read_text() == original_text
        # saved todos still have T-prefix IDs
        saved = storage.load_todos(cfg, "fail_backup")
        assert all(t.id.startswith("T") for t in saved)
        # no backup files should exist (copy failed)
        proj_dir = Path(cfg.tracking_dir) / "fail_backup"
        bak_files = list(proj_dir.glob("*.bak-*"))
        assert not bak_files

    def test_rename_dir_failure_raises_mid_migration(self, cfg: ProjConfig) -> None:
        """If rename_todo_dir raises for one todo, the exception propagates out."""
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "fail_rename", todos)

        boom = OSError("rename permission denied")

        with (
            patch.object(storage, "rename_todo_dir", side_effect=boom),
            pytest.raises(OSError, match="rename permission denied"),
        ):
            _migrate_project(cfg, "fail_rename", dry_run=False)

    def test_backup_created_before_rename_and_save(self, cfg: ProjConfig) -> None:
        """The .bak-* file must exist at the moment rename_todo_dir is first called."""
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "backup_order", todos)
        proj_dir = Path(cfg.tracking_dir) / "backup_order"

        backup_existed_during_rename: list[bool] = []

        original_rename = storage.rename_todo_dir

        def tracking_rename(c: ProjConfig, p: str, old: str, new: str) -> bool:
            bak_files = list(proj_dir.glob("todos.yaml.bak-*"))
            backup_existed_during_rename.append(len(bak_files) > 0)
            return original_rename(c, p, old, new)

        with patch.object(storage, "rename_todo_dir", side_effect=tracking_rename):
            _migrate_project(cfg, "backup_order", dry_run=False)

        assert backup_existed_during_rename, "rename_todo_dir was never called"
        assert all(backup_existed_during_rename), (
            "Backup did not exist when rename_todo_dir was called — "
            "backup must be written before any renames"
        )

    def test_partial_rename_failure_backup_still_exists(self, cfg: ProjConfig) -> None:
        """When rename_todo_dir fails mid-loop, the backup created before the loop
        must still be present on disk so the user can recover the original data."""
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "partial_fail", todos)
        proj_dir = Path(cfg.tracking_dir) / "partial_fail"

        call_count = 0
        original_rename = storage.rename_todo_dir

        def fail_on_second(c: ProjConfig, p: str, old: str, new: str) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("second rename failed")
            return original_rename(c, p, old, new)

        with (
            patch.object(
                storage,
                "rename_todo_dir",
                side_effect=fail_on_second,
            ),
            pytest.raises(OSError, match="second rename failed"),
        ):
            _migrate_project(cfg, "partial_fail", dry_run=False)

        # Backup must still exist so the user can restore
        bak_files = list(proj_dir.glob("todos.yaml.bak-*"))
        assert bak_files, "Backup was removed or never created after partial failure"


class TestMigrateArchiveAndDecisions:
    def test_migrate_includes_archive(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "Active task"),
            _make_todo("T002", "Another active"),
        ]
        _setup_project_with_todos(cfg, "arc", todos)
        # Archive a todo whose ID is in the active id_map
        archived = [_make_todo("T001", "Archived copy of T001")]
        storage.save_archived_todos(cfg, "arc", archived)

        result = _migrate_project(cfg, "arc", dry_run=False)

        assert result["archive_count"] == 1
        loaded = storage.load_archived_todos(cfg, "arc")
        assert len(loaded) == 1
        assert loaded[0].id == "1"
        assert not loaded[0].id.startswith("T")

    def test_migrate_includes_decisions(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "dec", todos)
        entry = storage.build_decision_entry(
            decision="Chose approach A",
            context="Some context",
            todo_id="T001",
        )
        storage.append_decision(cfg, "dec", entry)

        _migrate_project(cfg, "dec", dry_run=False)

        decisions = storage.load_decisions(cfg, "dec")
        assert len(decisions) == 1
        assert decisions[0]["todo_id"] == "1"

    def test_migrate_decisions_free_text_replaced(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "dec_text", todos)
        entry = storage.build_decision_entry(
            decision="Implemented T001 feature",
            context="Related to T002",
            todo_id="T001",
        )
        storage.append_decision(cfg, "dec_text", entry)

        _migrate_project(cfg, "dec_text", dry_run=False)

        decisions = storage.load_decisions(cfg, "dec_text")
        assert "T001" not in decisions[0]["decision"]
        assert "1" in decisions[0]["decision"]
        assert "T002" not in decisions[0]["context"]
        assert "2" in decisions[0]["context"]

    def test_migrate_decisions_unmapped_pattern_unchanged(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Only task")]
        _setup_project_with_todos(cfg, "dec_unmapped", todos)
        entry = storage.build_decision_entry(
            decision="Relates to T999 somehow",
            context="",
            todo_id="",
        )
        storage.append_decision(cfg, "dec_unmapped", entry)

        _migrate_project(cfg, "dec_unmapped", dry_run=False)

        decisions = storage.load_decisions(cfg, "dec_unmapped")
        assert "T999" in decisions[0]["decision"]

    def test_migrate_auto_rollback_on_failure(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "First"), _make_todo("T002", "Second")]
        _setup_project_with_todos(cfg, "rollback", todos)
        archived = [_make_todo("T003", "Archived")]
        storage.save_archived_todos(cfg, "rollback", archived)
        entry = storage.build_decision_entry(decision="A decision", context="", todo_id="T001")
        storage.append_decision(cfg, "rollback", entry)

        original_todos = storage.todos_path(cfg, "rollback").read_text()
        original_archive = storage.archive_path(cfg, "rollback").read_text()
        original_decisions = storage.decisions_path(cfg, "rollback").read_text()

        # Fail during save_todos (after backups are created, during mutation)

        def boom(*args, **kwargs):
            raise RuntimeError("simulated write failure")

        with (
            patch.object(storage, "save_todos", side_effect=boom),
            pytest.raises(RuntimeError, match="simulated write failure"),
        ):
            _migrate_project(cfg, "rollback", dry_run=False)

        # All files should be restored from backups
        assert storage.todos_path(cfg, "rollback").read_text() == original_todos
        assert storage.archive_path(cfg, "rollback").read_text() == original_archive
        assert storage.decisions_path(cfg, "rollback").read_text() == original_decisions

    def test_migrate_json_return_structure(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "ret", todos)

        result = _migrate_project(cfg, "ret", dry_run=False)

        assert result["migrated"] is True
        assert result["project"] == "ret"
        assert result["id_count"] == 1
        assert "archive_count" in result
        assert "decisions_count" in result

    def test_migrate_empty_archive(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "no_arc", todos)
        # No archive.yaml created

        result = _migrate_project(cfg, "no_arc", dry_run=False)

        assert result["migrated"] is True
        assert result["archive_count"] == 0

    def test_migrate_empty_decisions(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "no_dec", todos)
        # No decisions.yaml created

        result = _migrate_project(cfg, "no_dec", dry_run=False)

        assert result["migrated"] is True
        assert result["decisions_count"] == 0

    def test_migrate_preserves_sync_ids_on_archived(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Active")]
        _setup_project_with_todos(cfg, "sync_arc", todos)
        arc_todo = _make_todo("T002", "Synced archived")
        arc_todo.todoist_task_id = "todoist-123"
        arc_todo.trello_card_id = "trello-abc"
        arc_todo.trello_checklist_id = "checklist-xyz"
        storage.save_archived_todos(cfg, "sync_arc", [arc_todo])

        _migrate_project(cfg, "sync_arc", dry_run=False)

        loaded = storage.load_archived_todos(cfg, "sync_arc")
        synced = next(t for t in loaded if t.title == "Synced archived")
        assert synced.todoist_task_id == "todoist-123"
        assert synced.trello_card_id == "trello-abc"
        assert synced.trello_checklist_id == "checklist-xyz"


class TestProjMigrateIdsTool:
    @pytest.mark.anyio
    async def test_tool_registered(self, mcp_app: FastMCP) -> None:
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_migrate_ids")
        parsed = json.loads(result)
        assert "results" in parsed
        assert "dry_run" in parsed

    @pytest.mark.anyio
    async def test_tool_dry_run_flag(self, cfg: ProjConfig, mcp_app: FastMCP) -> None:
        from tests.conftest import call_tool, setup_project

        setup_project(cfg, "tool_test", str(Path(cfg.tracking_dir) / "tool_test"))
        # Add a T-prefixed todo
        todos = [_make_todo("T001", "Task")]
        storage.save_todos(cfg, "tool_test", todos)

        result = await call_tool(mcp_app, "proj_migrate_ids", dry_run=True)
        parsed = json.loads(result)
        assert parsed["dry_run"] is True
        assert parsed["results"][0]["reason"] == "dry_run"

        # Verify file not actually modified
        saved = storage.load_todos(cfg, "tool_test")
        assert saved[0].id == "T001"

    @pytest.mark.anyio
    async def test_tool_no_projects(self, cfg: ProjConfig, mcp_app: FastMCP) -> None:
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_migrate_ids")
        parsed = json.loads(result)
        assert parsed["results"] == []


class TestCleanupConfig:
    def test_cleanup_config_removes_investigation_tools(self, cfg: ProjConfig) -> None:
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.setdefault("permissions", {})["investigation_tools"] = ["some_tool"]
        storage._write_yaml(config_path, raw)

        result = _cleanup_config(cfg)

        assert result["cleaned"] is True
        assert "permissions.investigation_tools" in result["removed"]
        reloaded = storage._load_yaml(config_path)
        assert "investigation_tools" not in reloaded.get("permissions", {})

    def test_cleanup_config_removes_mcp_server(self, cfg: ProjConfig) -> None:
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.setdefault("sync", {}).setdefault("todoist", {})["mcp_server"] = "todoist-mcp"
        storage._write_yaml(config_path, raw)

        result = _cleanup_config(cfg)

        assert result["cleaned"] is True
        assert "sync.todoist.mcp_server" in result["removed"]
        reloaded = storage._load_yaml(config_path)
        assert "mcp_server" not in reloaded.get("sync", {}).get("todoist", {})

    def test_cleanup_config_removes_both(self, cfg: ProjConfig) -> None:
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.setdefault("permissions", {})["investigation_tools"] = ["tool"]
        raw.setdefault("sync", {}).setdefault("todoist", {})["mcp_server"] = "server"
        storage._write_yaml(config_path, raw)

        result = _cleanup_config(cfg)

        assert result["cleaned"] is True
        assert len(result["removed"]) == 2
        assert "permissions.investigation_tools" in result["removed"]
        assert "sync.todoist.mcp_server" in result["removed"]

    def test_cleanup_config_nothing_to_clean(self, cfg: ProjConfig) -> None:
        # Remove the default mcp_server so there is truly nothing to clean
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.get("sync", {}).get("todoist", {}).pop("mcp_server", None)
        storage._write_yaml(config_path, raw)

        result = _cleanup_config(cfg)

        assert result == {"cleaned": False, "reason": "nothing to clean"}

    def test_cleanup_config_dry_run(self, cfg: ProjConfig) -> None:
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.setdefault("permissions", {})["investigation_tools"] = ["tool"]
        raw.setdefault("sync", {}).setdefault("todoist", {})["mcp_server"] = "server"
        storage._write_yaml(config_path, raw)

        result = _cleanup_config(cfg, dry_run=True)

        assert result["cleaned"] is False
        assert result["dry_run"] is True
        assert "permissions.investigation_tools" in result["would_remove"]
        assert "sync.todoist.mcp_server" in result["would_remove"]
        # Verify nothing was actually removed
        reloaded = storage._load_yaml(config_path)
        assert "investigation_tools" in reloaded["permissions"]
        assert "mcp_server" in reloaded["sync"]["todoist"]

    def test_cleanup_config_creates_backup(self, cfg: ProjConfig) -> None:
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.setdefault("permissions", {})["investigation_tools"] = ["tool"]
        storage._write_yaml(config_path, raw)

        _cleanup_config(cfg)

        bak_files = list(config_path.parent.glob("proj.yaml.bak-*"))
        assert len(bak_files) == 1

    def test_cleanup_config_rollback_on_write_failure(self, cfg: ProjConfig) -> None:
        config_path = storage.config_path()
        raw = storage._load_yaml(config_path)
        raw.setdefault("permissions", {})["investigation_tools"] = ["tool"]
        storage._write_yaml(config_path, raw)
        original_text = config_path.read_text()

        with (
            patch.object(
                storage,
                "_write_yaml",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError, match="disk full"),
        ):
            _cleanup_config(cfg)

        # Config should be restored from backup
        assert config_path.read_text() == original_text


class TestMigrateIdsToolMultiProject:
    @pytest.mark.anyio
    async def test_tool_multi_project_iteration(self, cfg: ProjConfig, mcp_app: FastMCP) -> None:
        from tests.conftest import call_tool

        _setup_project_with_todos(
            cfg,
            "proj_a",
            [
                _make_todo("T001", "Task A1"),
                _make_todo("T002", "Task A2"),
            ],
        )
        _setup_project_with_todos(
            cfg,
            "proj_b",
            [
                _make_todo("T001", "Task B1"),
            ],
        )

        result = await call_tool(mcp_app, "proj_migrate_ids")
        parsed = json.loads(result)

        assert len(parsed["results"]) == 2
        by_project = {r["project"]: r for r in parsed["results"]}
        assert by_project["proj_a"]["migrated"] is True
        assert by_project["proj_a"]["id_count"] == 2
        assert by_project["proj_b"]["migrated"] is True
        assert by_project["proj_b"]["id_count"] == 1

    @pytest.mark.anyio
    async def test_tool_per_project_error_isolation(
        self,
        cfg: ProjConfig,
        mcp_app: FastMCP,
    ) -> None:
        from tests.conftest import call_tool

        _setup_project_with_todos(cfg, "good", [_make_todo("T001", "OK task")])
        _setup_project_with_todos(cfg, "bad", [_make_todo("T001", "Doomed task")])

        real_save = storage.save_todos

        def selective_fail(c, project_name, todos):
            if project_name == "bad":
                raise RuntimeError("simulated failure")
            return real_save(c, project_name, todos)

        with patch.object(storage, "save_todos", side_effect=selective_fail):
            result = await call_tool(mcp_app, "proj_migrate_ids")

        parsed = json.loads(result)
        by_project = {r["project"]: r for r in parsed["results"]}
        assert by_project["good"]["migrated"] is True
        assert by_project["bad"]["migrated"] is False
        assert "error" in by_project["bad"]


class TestMigrateDirectoryRollback:
    def test_renames_happen_after_yaml_writes(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "order_check", todos)
        content_dir = storage.todo_content_dir(cfg, "order_check", "T001")
        content_dir.mkdir(parents=True)

        call_log: list[str] = []
        real_save = storage.save_todos
        real_rename = storage.rename_todo_dir

        def tracking_save(c, project_name, t):
            call_log.append("save_todos")
            return real_save(c, project_name, t)

        def tracking_rename(c, project_name, old, new):
            call_log.append("rename_todo_dir")
            return real_rename(c, project_name, old, new)

        with (
            patch.object(storage, "save_todos", side_effect=tracking_save),
            patch.object(storage, "rename_todo_dir", side_effect=tracking_rename),
        ):
            _migrate_project(cfg, "order_check", dry_run=False)

        assert "save_todos" in call_log
        assert "rename_todo_dir" in call_log
        save_idx = call_log.index("save_todos")
        rename_idx = call_log.index("rename_todo_dir")
        assert save_idx < rename_idx, "rename_todo_dir must happen after save_todos"

    def test_renames_reversed_on_failure(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "rev_check", todos)
        # Create content dirs for both
        dir1 = storage.todo_content_dir(cfg, "rev_check", "T001")
        dir1.mkdir(parents=True)
        (dir1 / "notes.md").write_text("first notes")
        dir2 = storage.todo_content_dir(cfg, "rev_check", "T002")
        dir2.mkdir(parents=True)
        (dir2 / "notes.md").write_text("second notes")

        call_count = 0
        real_rename = storage.rename_todo_dir

        def fail_on_second(c, project_name, old, new):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("second rename failed")
            return real_rename(c, project_name, old, new)

        with (
            patch.object(
                storage,
                "rename_todo_dir",
                side_effect=fail_on_second,
            ),
            pytest.raises(OSError, match="second rename failed"),
        ):
            _migrate_project(cfg, "rev_check", dry_run=False)

        # The first rename should have been reversed — original dir name restored
        # Since the rollback reverses the first successful rename, the old dir
        # should exist again (or at least the new-name dir should not exist)
        assert dir1.exists(), "First renamed dir was not reversed after failure"
        assert (dir1 / "notes.md").read_text() == "first notes"
