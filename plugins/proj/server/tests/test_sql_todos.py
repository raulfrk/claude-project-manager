"""Unit tests for sql_todos CRUD module."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from server.lib.db import ensure_db
from server.lib.models import ProjConfig, Todo, TodoGit, TrelloSyncState
from server.lib.sql_todos import (
    _row_to_todo,
    _safe_json_loads,
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

    def test_non_numeric_ids_do_not_collide(self, cfg: ProjConfig) -> None:
        """Non-numeric IDs (e.g. 'abc') must not be treated as 0, causing collisions."""
        # Insert a valid numeric todo with id "5" and a non-numeric one.
        # Without the fix, CAST('abc' AS INTEGER) = 0, so MAX = 5, next = 6.
        # The bug would be if 'abc' caused next_id to drop to 1 (max=0).
        todos = [make_todo("5"), make_todo("abc")]
        save_todos(cfg, "myproject", todos)
        result = compute_next_todo_id(cfg, "myproject")
        # Must be 6 (based on numeric id "5"), not 1 (ignoring "abc" as 0 and miscomputing)
        assert result == 6

    def test_only_non_numeric_ids_returns_1(self, cfg: ProjConfig) -> None:
        """If all IDs are non-numeric, return 1 (no collision risk)."""
        todos = [make_todo("abc"), make_todo("xyz")]
        save_todos(cfg, "myproject", todos)
        result = compute_next_todo_id(cfg, "myproject")
        assert result == 1


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


class TestSafeJsonLoads:
    def test_valid_json_returns_parsed(self) -> None:
        assert _safe_json_loads('["a", "b"]', []) == ["a", "b"]

    def test_none_returns_default(self) -> None:
        assert _safe_json_loads(None, []) == []

    def test_empty_string_returns_default(self) -> None:
        assert _safe_json_loads("", []) == []

    def test_malformed_json_returns_default(self) -> None:
        assert _safe_json_loads("{bad json}", []) == []

    def test_malformed_json_returns_list_default(self) -> None:
        sentinel: list[object] = ["sentinel"]
        assert _safe_json_loads("{bad json}", sentinel) is sentinel


class TestRowToTodoCorruptJson:
    def _make_row(self, overrides: dict) -> sqlite3.Row:  # type: ignore[type-arg]
        defaults: dict[str, object] = {
            "id": "1",
            "title": "Test",
            "status": "pending",
            "priority": "medium",
            "created": "2026-01-01",
            "updated": None,
            "parent": None,
            "children": "[]",
            "next_child_id": None,
            "tags": "[]",
            "git_branch": None,
            "git_commits": "[]",
            "blocks": "[]",
            "blocked_by": "[]",
            "notes": None,
            "has_requirements": 0,
            "has_research": 0,
            "todoist_task_id": None,
            "todoist_desc_synced": None,
            "trello_card_id": None,
            "trello_checklist_id": None,
            "trello_checklist_item_id": None,
            "jira_issue_key": None,
            "jira_comment_ids": "[]",
            "due_date": None,
            "trello_sync_state": None,
        }
        defaults.update(overrides)
        row = MagicMock(spec=sqlite3.Row)
        row.__getitem__ = lambda self_, key: defaults[key]
        return row

    def test_corrupt_children_returns_empty_list(self) -> None:
        row = self._make_row({"children": "{not valid json"})
        todo = _row_to_todo(row)
        assert todo.children == []

    def test_corrupt_tags_returns_empty_list(self) -> None:
        row = self._make_row({"tags": "!!!"})
        todo = _row_to_todo(row)
        assert todo.tags == []

    def test_corrupt_git_commits_returns_empty_list(self) -> None:
        row = self._make_row({"git_commits": "not-json"})
        todo = _row_to_todo(row)
        assert todo.git.commits == []

    def test_corrupt_blocks_returns_empty_list(self) -> None:
        row = self._make_row({"blocks": "["})
        todo = _row_to_todo(row)
        assert todo.blocks == []

    def test_corrupt_blocked_by_returns_empty_list(self) -> None:
        row = self._make_row({"blocked_by": "["})
        todo = _row_to_todo(row)
        assert todo.blocked_by == []

    def test_corrupt_jira_comment_ids_returns_empty_list(self) -> None:
        row = self._make_row({"jira_comment_ids": "bad"})
        todo = _row_to_todo(row)
        assert todo.jira_synced_comment_ids == []

    def test_multiple_corrupt_fields_returns_all_defaults(self) -> None:
        row = self._make_row(
            {
                "children": "bad",
                "tags": "bad",
                "git_commits": "bad",
                "blocks": "bad",
                "blocked_by": "bad",
                "jira_comment_ids": "bad",
            }
        )
        todo = _row_to_todo(row)
        assert todo.children == []
        assert todo.tags == []
        assert todo.git.commits == []
        assert todo.blocks == []
        assert todo.blocked_by == []
        assert todo.jira_synced_comment_ids == []
