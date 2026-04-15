"""Unit tests for sql_todos CRUD module."""

from __future__ import annotations

import pytest

from server.lib.db import ensure_db
from server.lib.models import ProjConfig, Todo, TodoGit, TrelloSyncState
from server.lib.sql_todos import (
    compute_next_todo_id,
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


class TestLoadTodos:
    def test_raises_when_db_missing(self, cfg: ProjConfig) -> None:
        with pytest.raises(FileNotFoundError):
            load_todos(cfg, "nonexistent")

    def test_empty_returns_empty_list(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        result = load_todos(cfg, "myproject")
        assert result == []


class TestSaveTodosRoundtrip:
    def test_basic_roundtrip(self, cfg: ProjConfig) -> None:
        todos = [make_todo("1", "First"), make_todo("2", "Second")]
        save_todos(cfg, "myproject", todos)
        loaded = load_todos(cfg, "myproject")
        assert len(loaded) == 2
        titles = {t.title for t in loaded}
        assert titles == {"First", "Second"}

    def test_fields_preserved(self, cfg: ProjConfig) -> None:
        todo = Todo(
            id="42",
            title="My Task",
            status="in_progress",
            priority="high",
            created="2026-01-01",
            updated="2026-01-02",
            notes="Some notes",
            tags=["infra", "backend"],
            blocked_by=["41"],
        )
        save_todos(cfg, "myproject", [todo])
        loaded = load_todos(cfg, "myproject")
        t = loaded[0]
        assert t.id == "42"
        assert t.title == "My Task"
        assert t.status == "in_progress"
        assert t.priority == "high"
        assert t.created == "2026-01-01"
        assert t.updated == "2026-01-02"
        assert t.notes == "Some notes"
        assert t.tags == ["infra", "backend"]
        assert t.blocked_by == ["41"]

    def test_list_fields_json_serialization(self, cfg: ProjConfig) -> None:
        todo = make_todo("1")
        todo.tags = ["tag1", "tag2"]
        todo.blocked_by = ["99", "100"]
        todo.blocks = ["2", "3"]
        save_todos(cfg, "myproject", [todo])
        loaded = load_todos(cfg, "myproject")
        t = loaded[0]
        assert t.tags == ["tag1", "tag2"]
        assert t.blocked_by == ["99", "100"]
        assert t.blocks == ["2", "3"]

    def test_git_field_roundtrip(self, cfg: ProjConfig) -> None:
        todo = make_todo("1")
        todo.git = TodoGit(branch="feature/test", commits=["abc123", "def456"])
        save_todos(cfg, "myproject", [todo])
        loaded = load_todos(cfg, "myproject")
        t = loaded[0]
        assert t.git.branch == "feature/test"
        assert t.git.commits == ["abc123", "def456"]

    def test_trello_sync_state_roundtrip(self, cfg: ProjConfig) -> None:
        tss = TrelloSyncState(
            last_sync="2026-01-01T10:00:00+00:00",
            synced_name="My Card",
            card_id="card_abc",
            list_id="list_xyz",
            desc_hash="deadbeef",
        )
        todo = make_todo("1")
        todo.trello_sync_state = tss
        save_todos(cfg, "myproject", [todo])
        loaded = load_todos(cfg, "myproject")
        t = loaded[0]
        assert t.trello_sync_state is not None
        assert t.trello_sync_state.last_sync == "2026-01-01T10:00:00+00:00"
        assert t.trello_sync_state.synced_name == "My Card"
        assert t.trello_sync_state.card_id == "card_abc"

    def test_none_trello_sync_state(self, cfg: ProjConfig) -> None:
        todo = make_todo("1")
        todo.trello_sync_state = None
        save_todos(cfg, "myproject", [todo])
        loaded = load_todos(cfg, "myproject")
        assert loaded[0].trello_sync_state is None

    def test_replace_todos_atomically(self, cfg: ProjConfig) -> None:
        save_todos(cfg, "myproject", [make_todo("1", "Old")])
        save_todos(cfg, "myproject", [make_todo("2", "New")])
        loaded = load_todos(cfg, "myproject")
        assert len(loaded) == 1
        assert loaded[0].title == "New"


class TestComputeNextTodoId:
    def test_returns_1_when_db_missing(self, cfg: ProjConfig) -> None:
        result = compute_next_todo_id(cfg, "nonexistent")
        assert result == 1

    def test_returns_1_when_tables_empty(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        result = compute_next_todo_id(cfg, "myproject")
        assert result == 1

    def test_simple_ids(self, cfg: ProjConfig) -> None:
        todos = [make_todo("1"), make_todo("2"), make_todo("3")]
        save_todos(cfg, "myproject", todos)
        result = compute_next_todo_id(cfg, "myproject")
        assert result == 4

    def test_compound_ids(self, cfg: ProjConfig) -> None:
        todos = [make_todo("475"), make_todo("475.6"), make_todo("3.2.1")]
        save_todos(cfg, "myproject", todos)
        result = compute_next_todo_id(cfg, "myproject")
        assert result == 476

    def test_includes_archive_todos(self, cfg: ProjConfig) -> None:
        save_todos(cfg, "myproject", [make_todo("1")])
        archived = [make_todo("10", status="done")]
        save_archived_todos_append(cfg, "myproject", archived)
        result = compute_next_todo_id(cfg, "myproject")
        assert result == 11


class TestSaveArchivedTodosAppend:
    def test_appends_without_overwriting(self, cfg: ProjConfig) -> None:
        first_batch = [make_todo("1", "First")]
        save_archived_todos_append(cfg, "myproject", first_batch)
        second_batch = [make_todo("2", "Second")]
        save_archived_todos_append(cfg, "myproject", second_batch)
        loaded = load_archived_todos(cfg, "myproject")
        assert len(loaded) == 2
        titles = {t.title for t in loaded}
        assert titles == {"First", "Second"}

    def test_empty_list_noop(self, cfg: ProjConfig) -> None:
        save_archived_todos_append(cfg, "myproject", [])
        loaded = load_archived_todos(cfg, "myproject")
        assert loaded == []


class TestLoadArchivedTodos:
    def test_returns_empty_when_no_archive(self, cfg: ProjConfig) -> None:
        ensure_db(cfg, "myproject")
        result = load_archived_todos(cfg, "myproject")
        assert result == []

    def test_returns_empty_when_db_missing(self, cfg: ProjConfig) -> None:
        result = load_archived_todos(cfg, "nonexistent")
        assert result == []
