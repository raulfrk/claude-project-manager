"""Tests for proj_migrate_ids MCP tool."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
    Todo,
)
from server.tools.migrate import _migrate_project


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


def _make_todo(tid: str, title: str, parent: str | None = None, children: list[str] | None = None, created: str = "2026-01-01") -> Todo:
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

        assert "alpha: would migrate 2 todos" in result
        assert "T001 -> 1" in result
        assert "T002 -> 2" in result

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

        assert "T001 -> 1" in result
        assert "T002 -> 1.1" in result

    def test_dry_run_no_backup_created(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "alpha", todos)

        _migrate_project(cfg, "alpha", dry_run=True)

        backup = storage.todos_path(cfg, "alpha").with_suffix(".yaml.bak")
        assert not backup.exists()


class TestMigrateProjectActual:
    def test_migrates_root_todos(self, cfg: ProjConfig) -> None:
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
            _make_todo("T003", "Third"),
        ]
        _setup_project_with_todos(cfg, "beta", todos)

        result = _migrate_project(cfg, "beta", dry_run=False)

        assert "beta: migrated 3 todos" in result
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

        backup = storage.todos_path(cfg, "gamma").with_suffix(".yaml.bak")
        assert backup.exists()

    def test_backup_contains_original_data(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "gamma", todos)
        original_text = storage.todos_path(cfg, "gamma").read_text()

        _migrate_project(cfg, "gamma", dry_run=False)

        backup = storage.todos_path(cfg, "gamma").with_suffix(".yaml.bak")
        assert backup.read_text() == original_text

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

    def test_result_message_includes_backup_path(self, cfg: ProjConfig) -> None:
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "zeta", todos)

        result = _migrate_project(cfg, "zeta", dry_run=False)

        assert "backup:" in result
        assert "todos.yaml.bak" in result


class TestMigrateProjectEdgeCases:
    def test_no_todos_returns_skip_message(self, cfg: ProjConfig) -> None:
        _setup_project_with_todos(cfg, "empty", [])

        result = _migrate_project(cfg, "empty", dry_run=False)

        assert "no todos to migrate" in result

    def test_already_migrated_skipped(self, cfg: ProjConfig) -> None:
        # Todos with numeric IDs (already migrated)
        todos = [_make_todo("1", "First"), _make_todo("2", "Second")]
        _setup_project_with_todos(cfg, "migrated", todos)

        result = _migrate_project(cfg, "migrated", dry_run=False)

        assert "already migrated (skipped)" in result

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

        assert "T001 -> 1" in result
        assert "T002 -> 1.1" in result
        assert "T003 -> 1.1.1" in result

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

        # Both IDs appear in the mapping output
        assert "T001 -> 1" in result
        assert "T002 -> 2" in result

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
        """If shutil.copy2 fails, the migration aborts and no todos are modified."""
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "fail_backup", todos)
        original_text = storage.todos_path(cfg, "fail_backup").read_text()

        with patch("server.tools.migrate.shutil.copy2", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _migrate_project(cfg, "fail_backup", dry_run=False)

        # todos.yaml must be unchanged
        assert storage.todos_path(cfg, "fail_backup").read_text() == original_text
        # saved todos still have T-prefix IDs
        saved = storage.load_todos(cfg, "fail_backup")
        assert all(t.id.startswith("T") for t in saved)
        # backup file must not exist (copy failed)
        backup = storage.todos_path(cfg, "fail_backup").with_suffix(".yaml.bak")
        assert not backup.exists()

    def test_rename_dir_failure_raises_mid_migration(self, cfg: ProjConfig) -> None:
        """If rename_todo_dir raises for one todo, the exception propagates out."""
        todos = [
            _make_todo("T001", "First"),
            _make_todo("T002", "Second"),
        ]
        _setup_project_with_todos(cfg, "fail_rename", todos)

        boom = OSError("rename permission denied")

        with patch.object(storage, "rename_todo_dir", side_effect=boom):
            with pytest.raises(OSError, match="rename permission denied"):
                _migrate_project(cfg, "fail_rename", dry_run=False)

    def test_backup_created_before_rename_and_save(self, cfg: ProjConfig) -> None:
        """The .bak file must exist at the moment rename_todo_dir is first called."""
        todos = [_make_todo("T001", "Task")]
        _setup_project_with_todos(cfg, "backup_order", todos)
        backup_path = storage.todos_path(cfg, "backup_order").with_suffix(".yaml.bak")

        backup_existed_during_rename: list[bool] = []

        original_rename = storage.rename_todo_dir

        def tracking_rename(c: ProjConfig, p: str, old: str, new: str) -> bool:
            backup_existed_during_rename.append(backup_path.exists())
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
        backup_path = storage.todos_path(cfg, "partial_fail").with_suffix(".yaml.bak")

        call_count = 0
        original_rename = storage.rename_todo_dir

        def fail_on_second(c: ProjConfig, p: str, old: str, new: str) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("second rename failed")
            return original_rename(c, p, old, new)

        with patch.object(storage, "rename_todo_dir", side_effect=fail_on_second):
            with pytest.raises(OSError, match="second rename failed"):
                _migrate_project(cfg, "partial_fail", dry_run=False)

        # Backup must still exist so the user can restore
        assert backup_path.exists(), "Backup was removed or never created after partial failure"


class TestProjMigrateIdsTool:
    @pytest.mark.anyio
    async def test_tool_registered(self, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_migrate_ids")
        assert "No projects found to migrate." in result or isinstance(result, str)

    @pytest.mark.anyio
    async def test_tool_dry_run_flag(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool, setup_project

        setup_project(cfg, "tool_test", str(Path(cfg.tracking_dir) / "tool_test"))
        # Add a T-prefixed todo
        todos = [_make_todo("T001", "Task")]
        storage.save_todos(cfg, "tool_test", todos)

        result = await call_tool(mcp_app, "proj_migrate_ids", dry_run=True)
        assert "would migrate" in result

        # Verify file not actually modified
        saved = storage.load_todos(cfg, "tool_test")
        assert saved[0].id == "T001"

    @pytest.mark.anyio
    async def test_tool_no_projects(self, cfg: ProjConfig, mcp_app) -> None:  # type: ignore[no-untyped-def]
        from tests.conftest import call_tool

        result = await call_tool(mcp_app, "proj_migrate_ids")
        assert "No projects found to migrate." in result
