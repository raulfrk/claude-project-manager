"""Tests for server.lib.enums."""

from server.lib.enums import TERMINAL_STATUSES, Priority, TodoStatus


class TestTodoStatus:
    def test_values_are_strings(self):
        assert TodoStatus.PENDING == "pending"
        assert TodoStatus.IN_PROGRESS == "in_progress"
        assert TodoStatus.DONE == "done"

    def test_string_comparison(self):
        assert TodoStatus.DONE == "done"
        assert TodoStatus.PENDING == "pending"

    def test_iteration(self):
        values = list(TodoStatus)
        assert len(values) == 3


class TestPriority:
    def test_values_are_strings(self):
        assert Priority.LOW == "low"
        assert Priority.MEDIUM == "medium"
        assert Priority.HIGH == "high"

    def test_iteration(self):
        assert len(list(Priority)) == 3


class TestTerminalStatuses:
    def test_contains_done(self):
        assert "done" in TERMINAL_STATUSES

    def test_contains_cancelled(self):
        assert "cancelled" in TERMINAL_STATUSES

    def test_pending_not_terminal(self):
        assert "pending" not in TERMINAL_STATUSES

    def test_is_frozenset(self):
        assert isinstance(TERMINAL_STATUSES, frozenset)
