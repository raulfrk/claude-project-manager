"""Tests for migrate_done_to_archive in storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import ProjConfig, Todo
from tests.conftest import setup_project


@pytest.fixture()
def tmp_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)
    return cfg


PROJECT = "test-proj"


def _make_todo(
    tid: str,
    status: str = "pending",
    parent: str | None = None,
    children: list[str] | None = None,
    blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
) -> Todo:
    return Todo(
        id=tid,
        title=f"Todo {tid}",
        status=status,
        parent=parent,
        children=children or [],
        blocks=blocks or [],
        blocked_by=blocked_by or [],
    )


def _setup(cfg: ProjConfig, todos: list[Todo]) -> None:
    setup_project(cfg, PROJECT, "/tmp/fake-repo")
    storage.save_todos(cfg, PROJECT, todos)


class TestBasicMigration:
    def test_basic_migration(self, tmp_cfg: ProjConfig) -> None:
        """Create 10 todos, complete 8, run migrate → todos.yaml has 2, archive has 8."""
        todos = [_make_todo(str(i), status="done" if i < 9 else "pending") for i in range(1, 11)]
        _setup(tmp_cfg, todos)

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 8
        assert result["remaining_count"] == 2

        remaining = storage.load_todos(tmp_cfg, PROJECT)
        assert len(remaining) == 2
        archived = storage.load_archived_todos(tmp_cfg, PROJECT)
        assert len(archived) == 8


class TestIncludeDoneMerge:
    def test_include_done_merge(self, tmp_cfg: ProjConfig) -> None:
        """After migration, active + archived = original total."""
        todos = [_make_todo(str(i), status="done" if i < 9 else "pending") for i in range(1, 11)]
        _setup(tmp_cfg, todos)

        storage.migrate_done_to_archive(tmp_cfg, PROJECT)

        remaining = storage.load_todos(tmp_cfg, PROJECT)
        archived = storage.load_archived_todos(tmp_cfg, PROJECT)
        assert len(remaining) + len(archived) == 10
        # All original IDs present
        all_ids = {t.id for t in remaining} | {t.id for t in archived}
        assert all_ids == {str(i) for i in range(1, 11)}


class TestDoneParentPendingChild:
    def test_done_parent_pending_child_not_archived(self, tmp_cfg: ProjConfig) -> None:
        """Done parent with pending child → parent NOT archived."""
        parent = _make_todo("1", status="done", children=["2"])
        child = _make_todo("2", status="pending", parent="1")
        _setup(tmp_cfg, [parent, child])

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 0
        assert result["remaining_count"] == 2


class TestDoneChildPendingParent:
    def test_done_child_pending_parent(self, tmp_cfg: ProjConfig) -> None:
        """Done child under pending parent → child IS archived, parent stays."""
        parent = _make_todo("1", status="pending", children=["2"])
        child = _make_todo("2", status="done", parent="1")
        _setup(tmp_cfg, [parent, child])

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 1
        assert result["remaining_count"] == 1

        remaining = storage.load_todos(tmp_cfg, PROJECT)
        assert remaining[0].id == "1"


class TestDoneParentAllDoneChildren:
    def test_done_parent_all_done_children(self, tmp_cfg: ProjConfig) -> None:
        """Done parent + all done children → entire family archived."""
        parent = _make_todo("1", status="done", children=["2", "3"])
        child1 = _make_todo("2", status="done", parent="1")
        child2 = _make_todo("3", status="done", parent="1")
        _setup(tmp_cfg, [parent, child1, child2])

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 3
        assert result["remaining_count"] == 0


class TestBlockedByCleanup:
    def test_blocked_by_cleanup(self, tmp_cfg: ProjConfig) -> None:
        """Archive todo A → B's blocked_by no longer contains A."""
        a = _make_todo("A", status="done", blocks=["B"])
        b = _make_todo("B", status="pending", blocked_by=["A"])
        _setup(tmp_cfg, [a, b])

        storage.migrate_done_to_archive(tmp_cfg, PROJECT)

        remaining = storage.load_todos(tmp_cfg, PROJECT)
        assert len(remaining) == 1
        assert remaining[0].id == "B"
        assert "A" not in remaining[0].blocked_by
        assert "A" not in remaining[0].blocks


class TestIdempotent:
    def test_idempotent(self, tmp_cfg: ProjConfig) -> None:
        """Running migrate twice → second run archives 0."""
        todos = [_make_todo(str(i), status="done") for i in range(1, 6)]
        _setup(tmp_cfg, todos)

        result1 = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result1["archived_count"] == 5

        result2 = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result2["archived_count"] == 0
        assert result2["remaining_count"] == 0


class TestEmptyCase:
    def test_no_done_todos(self, tmp_cfg: ProjConfig) -> None:
        """No done todos → archived_count=0."""
        todos = [_make_todo(str(i), status="pending") for i in range(1, 4)]
        _setup(tmp_cfg, todos)

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 0
        assert result["remaining_count"] == 3


class TestCancelledStatus:
    def test_cancelled_also_archived(self, tmp_cfg: ProjConfig) -> None:
        """Cancelled todos are also terminal and should be archived."""
        todos = [
            _make_todo("1", status="cancelled"),
            _make_todo("2", status="done"),
            _make_todo("3", status="pending"),
        ]
        _setup(tmp_cfg, todos)

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 2
        assert result["remaining_count"] == 1


class TestNestedFamily:
    def test_deep_nested_all_done(self, tmp_cfg: ProjConfig) -> None:
        """Grandparent → parent → child, all done → entire family archived."""
        gp = _make_todo("1", status="done", children=["2"])
        p = _make_todo("2", status="done", parent="1", children=["3"])
        c = _make_todo("3", status="done", parent="2")
        _setup(tmp_cfg, [gp, p, c])

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        assert result["archived_count"] == 3

    def test_deep_nested_pending_grandchild(self, tmp_cfg: ProjConfig) -> None:
        """Grandparent → parent → child(pending) → grandparent NOT archived."""
        gp = _make_todo("1", status="done", children=["2"])
        p = _make_todo("2", status="done", parent="1", children=["3"])
        c = _make_todo("3", status="pending", parent="2")
        _setup(tmp_cfg, [gp, p, c])

        result = storage.migrate_done_to_archive(tmp_cfg, PROJECT)
        # Neither grandparent nor parent should be archived (pending descendant)
        assert result["archived_count"] == 0
        assert result["remaining_count"] == 3
