"""Tests for server.lib.ids."""

from dataclasses import dataclass

from server.lib.ids import next_todo_id


@dataclass
class FakeMeta:
    next_todo_id: int = 1


@dataclass
class FakeTodo:
    id: str = "5"
    next_child_id: int = 1


class TestNextTodoId:
    def test_root_id_increments(self):
        meta = FakeMeta(next_todo_id=1)
        assert next_todo_id(meta) == "1"
        assert meta.next_todo_id == 2
        assert next_todo_id(meta) == "2"
        assert meta.next_todo_id == 3

    def test_child_id_uses_parent(self):
        meta = FakeMeta(next_todo_id=10)
        parent = FakeTodo(id="5", next_child_id=1)
        assert next_todo_id(meta, parent) == "5.1"
        assert parent.next_child_id == 2
        assert next_todo_id(meta, parent) == "5.2"
        assert parent.next_child_id == 3

    def test_child_id_does_not_increment_meta(self):
        meta = FakeMeta(next_todo_id=10)
        parent = FakeTodo(id="3", next_child_id=1)
        next_todo_id(meta, parent)
        assert meta.next_todo_id == 10

    def test_root_id_does_not_increment_parent(self):
        meta = FakeMeta(next_todo_id=1)
        next_todo_id(meta)

    def test_nested_parent_id(self):
        meta = FakeMeta(next_todo_id=100)
        parent = FakeTodo(id="3.2", next_child_id=5)
        assert next_todo_id(meta, parent) == "3.2.5"
