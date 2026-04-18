"""Tests for server.lib.ids."""

from server.lib.ids import next_todo_id
from server.lib.models import ProjectMeta, Todo


def _meta(n: int = 1) -> ProjectMeta:
    return ProjectMeta(name="demo", next_todo_id=n)


def test_root_id_from_meta_counter() -> None:
    meta = _meta(5)
    assert next_todo_id(meta) == "5"
    assert meta.next_todo_id == 6


def test_child_id_from_empty_siblings() -> None:
    parent = Todo(id="3", title="P", tags=[])
    meta = _meta()
    # First child: no existing siblings under group:3
    assert next_todo_id(meta, parent=parent, siblings=[]) == "3.1"


def test_child_id_increments_past_existing_siblings() -> None:
    parent = Todo(id="3", title="P")
    siblings = [
        Todo(id="3.1", title="C1", tags=["group:3"]),
        Todo(id="3.2", title="C2", tags=["group:3"]),
    ]
    meta = _meta()
    assert next_todo_id(meta, parent=parent, siblings=siblings) == "3.3"


def test_child_id_handles_out_of_order_siblings() -> None:
    parent = Todo(id="5", title="P")
    siblings = [
        Todo(id="5.3", title="C3", tags=["group:5"]),
        Todo(id="5.1", title="C1", tags=["group:5"]),
    ]
    meta = _meta()
    # Max seen child index is 3 → next is 4
    assert next_todo_id(meta, parent=parent, siblings=siblings) == "5.4"


def test_child_id_handles_nested_parent_id() -> None:
    parent = Todo(id="3.2", title="P")
    siblings = [Todo(id="3.2.1", title="C1", tags=["group:3.2"])]
    meta = _meta()
    assert next_todo_id(meta, parent=parent, siblings=siblings) == "3.2.2"
