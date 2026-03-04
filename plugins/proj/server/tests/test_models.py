"""Tests for data models — serialization and round-trips."""

from __future__ import annotations

import pytest

from server.lib.models import Todo, TodoistSync


class TestTodoistSyncModel:
    def test_from_dict_without_mcp_server_uses_default(self) -> None:
        result = TodoistSync.from_dict({"enabled": True, "auto_sync": False})

        assert result.mcp_server == "claude_ai_Todoist"
        assert result.enabled is True
        assert result.auto_sync is False

    def test_from_dict_with_mcp_server_preserves_value(self) -> None:
        result = TodoistSync.from_dict(
            {"enabled": True, "auto_sync": True, "mcp_server": "sentry"}
        )

        assert result.mcp_server == "sentry"

    def test_to_dict_includes_mcp_server(self) -> None:
        ts = TodoistSync(enabled=True, auto_sync=True, mcp_server="custom")

        d = ts.to_dict()

        assert "mcp_server" in d
        assert d["mcp_server"] == "custom"

    def test_roundtrip_with_custom_mcp_server(self) -> None:
        original = TodoistSync(enabled=False, auto_sync=True, mcp_server="my_server")

        result = TodoistSync.from_dict(original.to_dict())

        assert result.mcp_server == "my_server"
        assert result.enabled == original.enabled
        assert result.auto_sync == original.auto_sync

    def test_default_mcp_server_is_claude_ai_todoist(self) -> None:
        ts = TodoistSync()

        assert ts.mcp_server == "claude_ai_Todoist"


class TestTodoDueDateModel:
    """Tests for Todo.due_date round-trips and backward-compat deserialization."""

    def _make_minimal_todo(self, **kwargs: object) -> Todo:
        return Todo(id="1", title="Task", created="2026-01-01", updated="2026-01-01", **kwargs)  # type: ignore[arg-type]

    def test_due_date_defaults_to_none(self) -> None:
        todo = self._make_minimal_todo()

        assert todo.due_date is None

    def test_due_date_iso_string_roundtrip(self) -> None:
        todo = self._make_minimal_todo(due_date="2026-06-01")

        d = todo.to_dict()
        restored = Todo.from_dict(d)

        assert restored.due_date == "2026-06-01"

    def test_due_date_natural_language_string_roundtrip(self) -> None:
        """Natural language strings are stored as-is (no parsing)."""
        todo = self._make_minimal_todo(due_date="next Friday")

        d = todo.to_dict()
        restored = Todo.from_dict(d)

        assert restored.due_date == "next Friday"

    def test_to_dict_includes_due_date_key(self) -> None:
        todo = self._make_minimal_todo(due_date="2026-12-31")

        d = todo.to_dict()

        assert "due_date" in d
        assert d["due_date"] == "2026-12-31"

    def test_to_dict_due_date_none_serializes_as_none(self) -> None:
        todo = self._make_minimal_todo()

        d = todo.to_dict()

        assert "due_date" in d
        assert d["due_date"] is None

    def test_from_dict_old_yaml_without_due_date_gives_none(self) -> None:
        """Deserializing old YAML that has no due_date key yields None."""
        old_data: dict[str, object] = {
            "id": "1",
            "title": "Legacy task",
            "status": "pending",
            "priority": "medium",
            "created": "2025-01-01",
            "updated": "2025-01-01",
        }

        todo = Todo.from_dict(old_data)

        assert todo.due_date is None

    def test_from_dict_due_date_non_string_ignored(self) -> None:
        """A non-string due_date value (e.g. accidental int) deserializes as None."""
        data: dict[str, object] = {
            "id": "1",
            "title": "Task",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "due_date": 20260601,  # bad type — should be treated as None
        }

        todo = Todo.from_dict(data)

        assert todo.due_date is None
