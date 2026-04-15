"""Unit tests for sql_archive CRUD module."""

from __future__ import annotations

from server.lib.db import ensure_db
from server.lib.models import ProjConfig, Todo
from server.lib.sql_archive import archive_and_remove_todos, migrate_done_to_archive
from server.lib.sql_todos import (
    load_archived_todos,
    load_todos,
    save_archived_todos_append,
    save_todos,
)


def make_todo(
    id: str = "1",
    title: str = "Test",
    status: str = "pending",
    priority: str = "medium",
    created: str = "2026-01-01",
) -> Todo:
    return Todo(id=id, title=title, status=status, priority=priority, created=created)


class TestArchiveAndRemoveTodos:
    def test_moves_to_archive_keeps_remaining(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        t1 = make_todo("1", "Keep")
        t2 = make_todo("2", "Archive Me", status="done")
        save_todos(cfg, "myproject", [t1, t2])
        archive_and_remove_todos(cfg, "myproject", remaining=[t1], to_archive=[t2])
        active = load_todos(cfg, "myproject")
        archived = load_archived_todos(cfg, "myproject")
        assert len(active) == 1
        assert active[0].title == "Keep"
        assert len(archived) == 1
        assert archived[0].title == "Archive Me"

    def test_all_to_archive(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        todos = [make_todo("1", status="done"), make_todo("2", status="cancelled")]
        save_todos(cfg, "myproject", todos)
        archive_and_remove_todos(cfg, "myproject", remaining=[], to_archive=todos)
        active = load_todos(cfg, "myproject")
        archived = load_archived_todos(cfg, "myproject")
        assert active == []
        assert len(archived) == 2

    def test_empty_to_archive_only_replaces_remaining(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        t1 = make_todo("1", "Alpha")
        t2 = make_todo("2", "Beta")
        save_todos(cfg, "myproject", [t1, t2])
        archive_and_remove_todos(cfg, "myproject", remaining=[t1], to_archive=[])
        active = load_todos(cfg, "myproject")
        archived = load_archived_todos(cfg, "myproject")
        assert len(active) == 1
        assert active[0].title == "Alpha"
        assert archived == []

    def test_empty_remaining_and_empty_archive(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        archive_and_remove_todos(cfg, "myproject", remaining=[], to_archive=[])
        active = load_todos(cfg, "myproject")
        archived = load_archived_todos(cfg, "myproject")
        assert active == []
        assert archived == []

    def test_archive_does_not_overwrite_existing_archived(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        existing_archived = make_todo("99", "Old Archived", status="done")
        save_archived_todos_append(cfg, "myproject", [existing_archived])
        t1 = make_todo("1", "Keep")
        t2 = make_todo("2", "New Archive", status="done")
        save_todos(cfg, "myproject", [t1, t2])
        archive_and_remove_todos(cfg, "myproject", remaining=[t1], to_archive=[t2])
        archived = load_archived_todos(cfg, "myproject")
        titles = {t.title for t in archived}
        assert "Old Archived" in titles
        assert "New Archive" in titles


class TestMigrateDoneToArchive:
    def test_empty_todos_returns_zero_counts(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        # save_todos creates the db; storage.load_todos is called internally
        save_todos(cfg, "myproject", [])
        result = migrate_done_to_archive(cfg, "myproject")
        assert result == {"archived_count": 0, "remaining_count": 0}

    def test_moves_done_leaf_to_archive(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        t_done = make_todo("1", "Done Task", status="done")
        t_pending = make_todo("2", "Pending Task", status="pending")
        save_todos(cfg, "myproject", [t_done, t_pending])
        result = migrate_done_to_archive(cfg, "myproject")
        assert result["archived_count"] == 1
        assert result["remaining_count"] == 1
        active = load_todos(cfg, "myproject")
        archived = load_archived_todos(cfg, "myproject")
        assert len(active) == 1
        assert active[0].title == "Pending Task"
        assert len(archived) == 1
        assert archived[0].title == "Done Task"

    def test_moves_cancelled_to_archive(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        t = make_todo("1", "Cancelled", status="cancelled")
        save_todos(cfg, "myproject", [t])
        result = migrate_done_to_archive(cfg, "myproject")
        assert result["archived_count"] == 1
        assert result["remaining_count"] == 0

    def test_pending_not_archived(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        todos = [
            make_todo("1", "Pending", status="pending"),
            make_todo("2", "In Progress", status="in_progress"),
        ]
        save_todos(cfg, "myproject", todos)
        result = migrate_done_to_archive(cfg, "myproject")
        assert result["archived_count"] == 0
        assert result["remaining_count"] == 2

    def test_parent_with_all_done_children_archived(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        parent = make_todo("1", "Parent", status="done")
        parent.children = ["1.1", "1.2"]
        child1 = make_todo("1.1", "Child1", status="done")
        child1.parent = "1"
        child2 = make_todo("1.2", "Child2", status="done")
        child2.parent = "1"
        save_todos(cfg, "myproject", [parent, child1, child2])
        result = migrate_done_to_archive(cfg, "myproject")
        assert result["archived_count"] == 3
        assert result["remaining_count"] == 0

    def test_parent_with_pending_child_not_archived(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        parent = make_todo("1", "Parent", status="done")
        parent.children = ["1.1"]
        child = make_todo("1.1", "Child", status="pending")
        child.parent = "1"
        save_todos(cfg, "myproject", [parent, child])
        migrate_done_to_archive(cfg, "myproject")
        # Done parent with a pending child — neither should be archived
        active = load_todos(cfg, "myproject")
        assert len(active) == 2
